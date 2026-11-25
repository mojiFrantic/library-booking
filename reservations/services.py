from datetime import timedelta
from dashboard.activity import log_activity
from dashboard.models import ActivityLog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from books.models import Book
from . import fines, waitlist
from .errors import ReservationError
from .models import Reservation, WaitlistEntry

Status = Reservation.Status

__all__ = [
    "ReservationError",
    "reserve_book",
    "cancel_reservation",
    "check_out",
    "check_in",
    "renew_reservation",
    "expire_stale_pickups",
    "run_maintenance",
]


def _get_locked(reservation_id, user=None):
    queryset = Reservation.objects.select_for_update()
    if user is not None:
        queryset = queryset.filter(user=user)
    try:
        return queryset.get(pk=reservation_id)
    except Reservation.DoesNotExist:
        raise ReservationError("Reservation not found.") from None


@transaction.atomic
def reserve_book(user, book_id):
    User = get_user_model()
    # Lock the user row so two simultaneous requests cannot bypass the
    # per-user limit, then lock the book row so two users cannot take
    # the last copy at the same time. Always lock in this order.
    user = User.objects.select_for_update().get(pk=user.pk)
    try:
        book = Book.objects.active().select_for_update().get(pk=book_id)
    except Book.DoesNotExist:
        raise ReservationError("This book is not in the catalog.") from None

    now = timezone.now()

    # Release copies held by pickups that have already timed out
    Reservation.objects.filter(
        book=book, status=Status.PENDING, pickup_deadline__lte=now
    ).update(status=Status.EXPIRED, updated_at=now)

    # Expire lapsed claims and offer free copies to the people in line
    # before counting, so newcomers cannot jump ahead of the queue.
    waitlist.promote_locked(book, now)

    if fines.fine_summary(user).is_blocked:
        raise ReservationError(fines.BLOCKED_MESSAGE)

    active = Reservation.objects.active()

    if active.filter(user=user, book=book).exists():
        raise ReservationError("You already have an active reservation for this book.")

    if active.filter(user=user).count() >= settings.MAX_ACTIVE_RESERVATIONS:
        raise ReservationError(
            f"You can have at most {settings.MAX_ACTIVE_RESERVATIONS} "
            "active reservations."
        )

    # A copy held for this very user does not count against them
    own_hold = WaitlistEntry.objects.holding().filter(user=user, book=book).first()
    taken = (
        active.filter(book=book).count()
        + WaitlistEntry.objects.holding().filter(book=book).exclude(user=user).count()
    )
    if taken >= book.total_copies:
        raise ReservationError("No copies of this book are available right now.")

    reservation = Reservation.objects.create(
        user=user,
        book=book,
        pickup_deadline=now + timedelta(hours=settings.RESERVATION_PICKUP_HOURS),
    )
    if own_hold is not None:
        own_hold.status = WaitlistEntry.Status.FULFILLED
        own_hold.save(update_fields=["status", "updated_at"])
    return reservation


@transaction.atomic
def cancel_reservation(reservation_id, user):
    reservation = _get_locked(reservation_id, user=user)
    if not reservation.can_cancel:
        raise ReservationError(
            "Only reservations that are waiting for pickup can be cancelled."
        )
    reservation.status = Status.CANCELLED
    reservation.save(update_fields=["status", "updated_at"])
    waitlist.promote_waitlist(reservation.book_id)
    return reservation


@transaction.atomic
def check_out(reservation_id, actor=None):
    """Staff action: the customer picked up the book."""
    reservation = _get_locked(reservation_id)
    if reservation.status != Status.PENDING:
        raise ReservationError("Only reservations waiting for pickup can be checked out.")
    if reservation.is_pickup_expired:
        raise ReservationError("The pickup window for this reservation has expired.")
    reservation.status = Status.CHECKED_OUT
    reservation.checked_out_at = timezone.now()
    reservation.due_date = timezone.localdate() + timedelta(
        days=settings.LOAN_PERIOD_DAYS
    )
    reservation.save(
        update_fields=["status", "checked_out_at", "due_date", "updated_at"]
    )
    if actor is not None:
        log_activity(
            actor,
            ActivityLog.Action.CHECKED_OUT,
            reservation,
            details=f"Due {reservation.due_date:%b %d, %Y}",
        )
    return reservation


@transaction.atomic
def check_in(reservation_id, actor=None):
    """Staff action: the customer returned the book."""
    reservation = _get_locked(reservation_id)
    if reservation.status != Status.CHECKED_OUT:
        raise ReservationError("Only checked-out books can be returned.")
    reservation.status = Status.RETURNED
    reservation.returned_at = timezone.now()
    reservation.save(update_fields=["status", "returned_at", "updated_at"])

    fine = fines.create_fine_for_return(reservation)
    waitlist.promote_waitlist(reservation.book_id)
    if actor is not None:
        details = (
            f"Late fine recorded: {fine.amount} ({fine.days_overdue} days overdue)"
            if fine
            else ""
        )
        log_activity(actor, ActivityLog.Action.RETURNED, reservation, details=details)
    return reservation

@transaction.atomic
def renew_reservation(reservation_id, user):
    reservation = _get_locked(reservation_id, user=user)
    if reservation.status != Status.CHECKED_OUT:
        raise ReservationError("Only checked-out books can be renewed.")
    if reservation.is_overdue:
        raise ReservationError("Overdue books cannot be renewed. Please return it.")
    if reservation.renewal_count >= settings.MAX_RENEWALS:
        raise ReservationError("This loan has reached the maximum number of renewals.")
    if WaitlistEntry.objects.open().filter(book_id=reservation.book_id).exists():
        raise ReservationError(
            "Other readers are waiting for this book, so it cannot be renewed."
        )
    reservation.due_date += timedelta(days=settings.RENEWAL_DAYS)
    reservation.renewal_count += 1
    reservation.save(update_fields=["due_date", "renewal_count", "updated_at"])
    return reservation


def expire_stale_pickups():
    """Mark timed-out pending reservations as expired. Returns the count."""
    now = timezone.now()
    return Reservation.objects.filter(
        status=Status.PENDING, pickup_deadline__lte=now
    ).update(status=Status.EXPIRED, updated_at=now)


def run_maintenance():
    """Periodic job. Returns (expired_pickups, expired_claims, promoted)."""
    pickups = expire_stale_pickups()
    claims, promoted = waitlist.process_waitlist()
    return pickups, claims, promoted