from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import ExpressionWrapper, F, IntegerField, Value
from django.db.models.functions import Greatest
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


class BookQuerySet(models.QuerySet):
    def active(self):
        """Books that are not soft-deleted."""
        return self.filter(is_deleted=False)

    def with_availability(self):
        """Annotate each book with reserved_count and available_count."""
        return self.annotate(
            # Phase 4 will replace Value(0) with a count of active reservations
            reserved_count=Value(0, output_field=IntegerField()),
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
        # Phase 4 will count active reservations here.
        return 0

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