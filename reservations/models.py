from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ReservationQuerySet(models.QuerySet):
    def active(self):
        """Reservations that currently hold a copy of a book.

        A pending reservation stops holding a copy as soon as its pickup
        deadline passes, even if no background job has marked it expired yet.
        """
        return self.filter(
            Q(status=Reservation.Status.CHECKED_OUT)
            | Q(status=Reservation.Status.PENDING, pickup_deadline__gt=timezone.now())
        )


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for pickup"
        CHECKED_OUT = "checked_out", "Checked out"
        RETURNED = "returned", "Returned"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    book = models.ForeignKey(
        "books.Book",
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reserved_at = models.DateTimeField(auto_now_add=True)
    pickup_deadline = models.DateTimeField()
    checked_out_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    renewal_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ReservationQuerySet.as_manager()

    class Meta:
        ordering = ["-reserved_at"]
        constraints = [
            # A user can have only one open reservation per book
            models.UniqueConstraint(
                fields=["user", "book"],
                condition=Q(status__in=["pending", "checked_out"]),
                name="unique_open_reservation_per_user_book",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.book} ({self.get_status_display()})"

    @property
    def is_pickup_expired(self):
        return (
            self.status == self.Status.PENDING
            and self.pickup_deadline <= timezone.now()
        )

    @property
    def is_overdue(self):
        return (
            self.status == self.Status.CHECKED_OUT
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )

    @property
    def can_cancel(self):
        return self.status == self.Status.PENDING and not self.is_pickup_expired

    @property
    def can_renew(self):
        return (
            self.status == self.Status.CHECKED_OUT
            and not self.is_overdue
            and self.renewal_count < settings.MAX_RENEWALS
        )

    @property
    def status_label(self):
        if self.is_pickup_expired:
            return "Expired"
        if self.is_overdue:
            return "Overdue"
        return self.get_status_display()