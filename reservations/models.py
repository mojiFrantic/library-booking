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


class WaitlistQuerySet(models.QuerySet):
    def waiting(self):
        """Entries still waiting for a copy."""
        return self.filter(status=WaitlistEntry.Status.WAITING)

    def holding(self):
        """Entries with an open claim: a copy is being kept for them."""
        return self.filter(
            status=WaitlistEntry.Status.NOTIFIED,
            claim_deadline__gt=timezone.now(),
        )

    def open(self):
        """Entries still in the queue: waiting, or holding a copy."""
        return self.filter(
            Q(status=WaitlistEntry.Status.WAITING)
            | Q(
                status=WaitlistEntry.Status.NOTIFIED,
                claim_deadline__gt=timezone.now(),
            )
        )


class WaitlistEntry(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        NOTIFIED = "notified", "Copy held"
        FULFILLED = "fulfilled", "Reserved"
        CANCELLED = "cancelled", "Left the waitlist"
        EXPIRED = "expired", "Claim expired"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="waitlist_entries",
    )
    book = models.ForeignKey(
        "books.Book",
        on_delete=models.CASCADE,
        related_name="waitlist_entries",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.WAITING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    claim_deadline = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WaitlistQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            # One open place in line per user and book
            models.UniqueConstraint(
                fields=["user", "book"],
                condition=Q(status__in=["waiting", "notified"]),
                name="unique_open_waitlist_entry_per_user_book",
            ),
        ]

    def __str__(self):
        return f"{self.user} waiting for {self.book} ({self.get_status_display()})"

    def position(self):
        """1-based place in line among people still waiting, else None."""
        if self.status != self.Status.WAITING:
            return None
        ahead = (
            WaitlistEntry.objects.waiting()
            .filter(book_id=self.book_id)
            .filter(
                Q(created_at__lt=self.created_at)
                | Q(created_at=self.created_at, pk__lt=self.pk)
            )
            .count()
        )
        return ahead + 1


class Fine(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        WAIVED = "waived", "Waived"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fines",
    )
    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.PROTECT,
        related_name="fine",
    )
    days_overdue = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNPAID,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user}: {self.amount} ({self.get_status_display()})"