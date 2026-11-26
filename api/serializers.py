from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from books.models import Author, Book, Genre
from reservations.models import Fine, Reservation, WaitlistEntry
from reviews.models import Review

User = get_user_model()


# ---------- Users and authentication ----------


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "phone", "role")
        read_only_fields = fields


class AuthResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = UserSerializer()


class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password2 = serializers.CharField(
        write_only=True, label="Confirm password", style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = ("username", "email", "phone", "password", "password2")

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password2"):
            raise serializers.ValidationError(
                {"password2": "The two passwords do not match."}
            )
        candidate = User(username=attrs["username"], email=attrs["email"])
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from None
        return attrs

    def create(self, validated_data):
        # The role is never accepted from the client: new users are customers
        return User.objects.create_user(**validated_data)


class MeSerializer(serializers.Serializer):
    user = UserSerializer()
    active_loans = serializers.IntegerField()
    wishlist_count = serializers.IntegerField()
    review_count = serializers.IntegerField()
    outstanding_fines = serializers.DecimalField(max_digits=10, decimal_places=2)
    has_overdue_loans = serializers.BooleanField()
    is_blocked = serializers.BooleanField()


# ---------- Books ----------


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = ("id", "name")


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ("id", "name")


class BookSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Book
        fields = ("id", "title")
        read_only_fields = fields


class BookSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=True)
    genres = GenreSerializer(many=True, read_only=True)
    # Write-only: send ids, receive nested objects
    author_ids = serializers.PrimaryKeyRelatedField(
        source="authors",
        queryset=Author.objects.all(),
        many=True,
        write_only=True,
        allow_empty=False,
    )
    genre_ids = serializers.PrimaryKeyRelatedField(
        source="genres",
        queryset=Genre.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )
    available_copies = serializers.SerializerMethodField()
    is_available = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = (
            "id",
            "title",
            "authors",
            "genres",
            "author_ids",
            "genre_ids",
            "summary",
            "publication_year",
            "isbn",
            "cover",
            "total_copies",
            "available_copies",
            "is_available",
            "average_rating",
            "review_count",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_publication_year(self, value):
        if value > date.today().year + 1:
            raise serializers.ValidationError(
                "Publication year is too far in the future."
            )
        return value

    def validate_isbn(self, value):
        # Store "no ISBN" as NULL so several books can leave it empty
        return value or None

    @extend_schema_field(serializers.IntegerField())
    def get_available_copies(self, obj):
        return obj.available_copies

    @extend_schema_field(serializers.BooleanField())
    def get_is_available(self, obj):
        return obj.is_available

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_average_rating(self, obj):
        value = getattr(obj, "average_rating", None)
        return round(float(value), 2) if value is not None else None

    @extend_schema_field(serializers.IntegerField())
    def get_review_count(self, obj):
        return getattr(obj, "review_count", 0)


# ---------- Reviews and wishlist ----------


class ReviewSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.username", read_only=True)
    text = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    class Meta:
        model = Review
        fields = ("id", "user", "rating", "text", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")
        validators = []  # uniqueness is handled by the view (one review per user)


class WishlistStateSerializer(serializers.Serializer):
    in_wishlist = serializers.BooleanField()


# ---------- Reservations, waitlist, fines ----------


class ReservationSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.username", read_only=True)
    book = BookSummarySerializer(read_only=True)
    status_label = serializers.CharField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    can_cancel = serializers.BooleanField(read_only=True)
    can_renew = serializers.BooleanField(read_only=True)
    fine_amount = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = (
            "id",
            "user",
            "book",
            "status",
            "status_label",
            "reserved_at",
            "pickup_deadline",
            "checked_out_at",
            "due_date",
            "returned_at",
            "renewal_count",
            "is_overdue",
            "can_cancel",
            "can_renew",
            "fine_amount",
        )
        read_only_fields = fields

    @extend_schema_field(
        serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)
    )
    def get_fine_amount(self, obj):
        fine = getattr(obj, "fine", None)
        return str(fine.amount) if fine else None


class ReservationCreateSerializer(serializers.Serializer):
    book = serializers.PrimaryKeyRelatedField(queryset=Book.objects.active())


class WaitlistEntrySerializer(serializers.ModelSerializer):
    book = BookSummarySerializer(read_only=True)
    position = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistEntry
        fields = ("id", "book", "status", "position", "claim_deadline", "created_at")
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_position(self, obj):
        return obj.position()


class FineSerializer(serializers.ModelSerializer):
    book = serializers.CharField(source="reservation.book.title", read_only=True)

    class Meta:
        model = Fine
        fields = (
            "id",
            "book",
            "days_overdue",
            "amount",
            "status",
            "created_at",
            "settled_at",
        )
        read_only_fields = fields