from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from books.filters import BookFilter
from books.models import Author, Book, Genre, WishlistItem
from dashboard.activity import log_activity
from dashboard.models import ActivityLog
from reservations import fines, services
from reservations import waitlist as waitlist_service
from reservations.models import Fine, Reservation, WaitlistEntry
from reviews.models import Review

from .exceptions import BusinessRuleError, run_service
from .filters import StaffReservationFilter
from .permissions import IsLibraryStaff, IsLibraryStaffOrReadOnly
from .serializers import (
    AuthorSerializer,
    AuthResponseSerializer,
    BookSerializer,
    FineSerializer,
    GenreSerializer,
    MeSerializer,
    RegisterSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    ReviewSerializer,
    UserSerializer,
    WaitlistEntrySerializer,
    WishlistStateSerializer,
)

User = get_user_model()


def _is_schema_generation(view):
    """True while drf-spectacular inspects a view without a real request."""
    return getattr(view, "swagger_fake_view", False)


# ---------- Authentication ----------


class RegisterView(generics.CreateAPIView):
    """Create a customer account and return an API token."""

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    @extend_schema(responses={201: AuthResponseSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(ObtainAuthToken):
    """Exchange a username and password for an API token."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(responses={200: AuthResponseSerializer})
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    """Delete the caller's API token."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """The caller's profile, activity counts and fine status."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        user = request.user
        summary = fines.fine_summary(user)
        data = {
            "user": user,
            "active_loans": Reservation.objects.filter(
                user=user, status=Reservation.Status.CHECKED_OUT
            ).count(),
            "wishlist_count": user.wishlist_items.count(),
            "review_count": user.reviews.count(),
            "outstanding_fines": summary.total,
            "has_overdue_loans": summary.overdue_count > 0,
            "is_blocked": summary.is_blocked,
        }
        return Response(MeSerializer(data).data)


# ---------- Books ----------


class AuthorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer


class GenreViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Genre.objects.all()
    serializer_class = GenreSerializer
    pagination_class = None


class BookViewSet(viewsets.ModelViewSet):
    """Browse books (public). Library staff can also add, edit and delete them.

    Query parameters for the list: `q`, `author`, `genre`, `year_from`,
    `year_to`, `availability` (available/unavailable) and `sort`
    (title, -title, publication_year, -publication_year, -created_at,
    popular, top_rated, relevance).
    """

    serializer_class = BookSerializer
    permission_classes = [IsLibraryStaffOrReadOnly]
    filterset_class = BookFilter

    def get_queryset(self):
        return (
            Book.objects.active()
            .with_availability()
            .with_ratings()
            .with_popularity()
            .prefetch_related("authors", "genres")
            .order_by("title")
        )

    def _respond(self, instance, status_code):
        # Re-read the book so the response includes availability and rating
        instance = self.get_queryset().get(pk=instance.pk)
        return Response(self.get_serializer(instance).data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return self._respond(serializer.instance, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return self._respond(serializer.instance, status.HTTP_200_OK)

    def perform_create(self, serializer):
        book = serializer.save()
        log_activity(self.request.user, ActivityLog.Action.BOOK_CREATED, book)

    def perform_update(self, serializer):
        book = serializer.save()
        log_activity(
            self.request.user,
            ActivityLog.Action.BOOK_UPDATED,
            book,
            details="Changed: " + ", ".join(sorted(serializer.validated_data)),
        )

    def perform_destroy(self, instance):
        # Staff never hard-delete: the book is hidden but its history stays
        instance.soft_delete()
        log_activity(self.request.user, ActivityLog.Action.BOOK_SOFT_DELETED, instance)

    # ----- reviews -----

    @extend_schema(responses=ReviewSerializer(many=True))
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def reviews(self, request, pk=None):
        """Visible (not hidden) reviews of this book, newest first."""
        book = self.get_object()
        queryset = Review.objects.filter(book=book, is_hidden=False).select_related(
            "user"
        )
        page = self.paginate_queryset(queryset)
        serializer = ReviewSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        methods=["PUT"], request=ReviewSerializer, responses=ReviewSerializer
    )
    @extend_schema(methods=["DELETE"], responses={204: None})
    @action(
        detail=True,
        methods=["put", "delete"],
        url_path="my-review",
        permission_classes=[IsAuthenticated],
    )
    def my_review(self, request, pk=None):
        """Create or update (PUT) or delete (DELETE) your own review."""
        book = self.get_object()
        existing = Review.objects.filter(user=request.user, book=book).first()
        if request.method == "DELETE":
            if existing:
                existing.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = ReviewSerializer(existing, data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save(user=request.user, book=book)
        except IntegrityError:
            raise BusinessRuleError("Your review was already submitted.") from None
        code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        return Response(serializer.data, status=code)

    # ----- wishlist -----

    @extend_schema(
        methods=["PUT"], request=None, responses=WishlistStateSerializer
    )
    @extend_schema(methods=["DELETE"], responses={204: None})
    @action(
        detail=True,
        methods=["put", "delete"],
        url_path="wishlist",
        permission_classes=[IsAuthenticated],
    )
    def wishlist(self, request, pk=None):
        """Add (PUT) or remove (DELETE) this book from your wishlist."""
        book = self.get_object()
        if request.method == "DELETE":
            WishlistItem.objects.filter(user=request.user, book=book).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        WishlistItem.objects.get_or_create(user=request.user, book=book)
        return Response({"in_wishlist": True})

    # ----- waitlist -----

    @extend_schema(
        methods=["POST"], request=None, responses={201: WaitlistEntrySerializer}
    )
    @extend_schema(methods=["DELETE"], responses={204: None})
    @action(
        detail=True,
        methods=["post", "delete"],
        url_path="waitlist",
        permission_classes=[IsAuthenticated],
    )
    def waitlist(self, request, pk=None):
        """Join (POST) or leave (DELETE) the waitlist of a fully booked book."""
        book = self.get_object()
        if request.method == "POST":
            entry = run_service(waitlist_service.join_waitlist, request.user, book.pk)
            return Response(
                WaitlistEntrySerializer(entry).data, status=status.HTTP_201_CREATED
            )
        entry = (
            WaitlistEntry.objects.open().filter(user=request.user, book=book).first()
        )
        if entry is None:
            raise NotFound("You are not on the waitlist for this book.")
        run_service(waitlist_service.leave_waitlist, entry.pk, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- The caller's own lists ----------


class WishlistListView(generics.ListAPIView):
    """Books in your wishlist, most recently added first."""

    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if _is_schema_generation(self):
            return Book.objects.none()
        added_at = Subquery(
            WishlistItem.objects.filter(
                user=self.request.user, book=OuterRef("pk")
            ).values("added_at")[:1]
        )
        return (
            Book.objects.active()
            .annotate(added_at=added_at)
            .filter(added_at__isnull=False)
            .with_availability()
            .with_ratings()
            .prefetch_related("authors", "genres")
            .order_by("-added_at")
        )


class WaitlistListView(generics.ListAPIView):
    """Your open places in waitlists."""

    serializer_class = WaitlistEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if _is_schema_generation(self):
            return WaitlistEntry.objects.none()
        return WaitlistEntry.objects.open().filter(user=self.request.user).select_related(
            "book"
        )


class FineListView(generics.ListAPIView):
    """Your late fines."""

    serializer_class = FineSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status"]

    def get_queryset(self):
        if _is_schema_generation(self):
            return Fine.objects.none()
        return Fine.objects.filter(user=self.request.user).select_related(
            "reservation__book"
        )


# ---------- Reservations ----------


class ReservationViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Your own reservations. Create one by sending the book id."""

    serializer_class = ReservationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status"]

    def get_queryset(self):
        if _is_schema_generation(self):
            return Reservation.objects.none()
        return Reservation.objects.filter(user=self.request.user).select_related(
            "book", "fine"
        )

    @extend_schema(
        request=ReservationCreateSerializer, responses={201: ReservationSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = run_service(
            services.reserve_book, request.user, serializer.validated_data["book"].pk
        )
        return Response(
            ReservationSerializer(reservation).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses=ReservationSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a reservation that is still waiting for pickup."""
        reservation = self.get_object()
        updated = run_service(
            services.cancel_reservation, reservation.pk, request.user
        )
        return Response(ReservationSerializer(updated).data)

    @extend_schema(request=None, responses=ReservationSerializer)
    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        """Extend the due date of a checked-out book."""
        reservation = self.get_object()
        updated = run_service(
            services.renew_reservation, reservation.pk, request.user
        )
        return Response(ReservationSerializer(updated).data)


class StaffReservationViewSet(viewsets.ReadOnlyModelViewSet):
    """All reservations, for library staff. Check books out and in here."""

    serializer_class = ReservationSerializer
    permission_classes = [IsLibraryStaff]
    filterset_class = StaffReservationFilter
    queryset = Reservation.objects.select_related("user", "book", "fine")

    @extend_schema(request=None, responses=ReservationSerializer)
    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, pk=None):
        """The customer picked up the book."""
        reservation = self.get_object()
        updated = run_service(services.check_out, reservation.pk, actor=request.user)
        return Response(self.get_serializer(updated).data)

    @extend_schema(request=None, responses=ReservationSerializer)
    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        """The customer returned the book. A late return records a fine."""
        reservation = self.get_object()
        updated = run_service(services.check_in, reservation.pk, actor=request.user)
        return Response(self.get_serializer(updated).data)