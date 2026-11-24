from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import (
    Avg,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    IntegerField,
    OuterRef,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce, Greatest
from django.urls import reverse
from django.utils import timezone


class Author(models.Model):
    name = models.CharField(max_length=200)
    bio = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def _count_by_book(queryset):
    """Subquery expression: how many rows of `queryset` each book has.

    A subquery (not a JOIN) so other joins, like author or genre filters,
    never inflate the numbers.
    """
    return Coalesce(
        Subquery(
            queryset.filter(book=OuterRef("pk"))
            .order_by()
            .values("book")
            .annotate(total=Count("pk"))
            .values("total"),
            output_field=IntegerField(),
        ),
        Value(0),
        output_field=IntegerField(),
    )


class BookQuerySet(models.QuerySet):
    def active(self):
        """Books that are not soft-deleted."""
        return self.filter(is_deleted=False)

    def with_availability(self):
        """Annotate reserved_count and available_count."""
        # Imported here to avoid circular imports at module load time
        from reservations.models import Reservation

        return self.annotate(
            reserved_count=_count_by_book(Reservation.objects.active()),
        ).annotate(
            available_count=Greatest(
                ExpressionWrapper(
                    F("total_copies") - F("reserved_count"),
                    output_field=IntegerField(),
                ),
                Value(0),
                output_field=IntegerField(),
            ),
        )

    def with_ratings(self):
        """Annotate average_rating (None if no reviews) and review_count.

        Hidden reviews are ignored.
        """
        from reviews.models import Review

        visible = Review.objects.filter(is_hidden=False)
        average = Subquery(
            visible.filter(book=OuterRef("pk"))
            .order_by()
            .values("book")
            .annotate(avg=Avg("rating"))
            .values("avg"),
            output_field=FloatField(),
        )
        return self.annotate(
            average_rating=average,
            review_count=_count_by_book(visible),
        )

    def with_popularity(self):
        """Annotate borrow_count: how many times the book was borrowed."""
        from reservations.models import Reservation

        borrowed = Reservation.objects.filter(
            status__in=[
                Reservation.Status.CHECKED_OUT,
                Reservation.Status.RETURNED,
            ]
        )
        return self.annotate(borrow_count=_count_by_book(borrowed))


class Book(models.Model):
    title = models.CharField(max_length=255)
    authors = models.ManyToManyField(Author, related_name="books")
    genres = models.ManyToManyField(Genre, related_name="books", blank=True)
    summary = models.TextField(blank=True)
    publication_year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1000)]
    )
    isbn = models.CharField(
        "ISBN",
        max_length=17,
        unique=True,
        null=True,
        blank=True,
        help_text="Optional. Must be unique if provided.",
    )
    cover = models.ImageField(upload_to="covers/", blank=True)
    total_copies = models.PositiveIntegerField(
        default=1, help_text="Total number of physical copies owned."
    )

    # Soft delete
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("books:detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        if self.publication_year and self.publication_year > date.today().year + 1:
            raise ValidationError(
                {"publication_year": "Publication year is too far in the future."}
            )

    # Availability is always computed, never stored
    def active_reservation_count(self):
        return self.reservations.active().count()

    @property
    def available_copies(self):
        annotated = getattr(self, "available_count", None)
        if annotated is not None:
            return annotated
        return max(self.total_copies - self.active_reservation_count(), 0)

    @property
    def is_available(self):
        return self.available_copies > 0

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class WishlistItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )
    book = models.ForeignKey(
        Book, on_delete=models.CASCADE, related_name="wishlist_items"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "book"], name="unique_wishlist_item"
            ),
        ]

    def __str__(self):
        return f"{self.user} ♥ {self.book}"