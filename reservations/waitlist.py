from datetime import timedelta
from functools import partial

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from books.models import Book

from . import fines
from .errors import ReservationError
from .models import Reservation, WaitlistEntry

Status = WaitlistEntry.Status


def free_copies(book):
    """Copies that are neither reserved nor held for someone in the queue."""
    taken = (
        Reservation.objects.active().filter(book=book).count()
        + WaitlistEntry.objects.holding().filter(book=book).count()
    )
    return book.total_copies - taken


def _send_claim_email(entry_id):
    entry = (
        WaitlistEntry.objects.select_related("user", "book").filter(pk=entry_id).first()
    )
    if entry is None or not entry.user.email or entry.claim_deadline is None:
        return
    deadline = timezone.localtime(entry.claim_deadline)
    link = f"{settings.SITE_URL}{entry.book.get_absolute_url()}"
    send_mail(
        subject=f"A copy of '{entry.book.title}' is ready for you",
        message=(
            f"Hello {entry.user.username},\n\n"
            f"A copy of '{entry.book.title}' is now being held for you.\n"
            f"Please reserve it before {deadline:%b %d, %Y %H:%M}, "
            "otherwise it will go to the next person in line.\n\n"
            f"{link}\n"
        ),
        from_email=None,
        recipient_list=[entry.user.email],
        fail_silently=True,
    )


def promote_locked(book, now=None):
    """Expire stale claims, then hold free copies for the people in line.

    `book` must already be locked with select_for_update() inside a
    transaction. Returns the entries that were just notified.
    """
    now = now or timezone.now()
    WaitlistEntry.objects.filter(
        book=book, status=Status.NOTIFIED, claim_deadline__lte=now
    ).update(status=Status.EXPIRED, updated_at=now)

    free = free_copies(book)
    promoted = []
    if free <= 0:
        return promoted

    waiting = (
        WaitlistEntry.objects.waiting()
        .filter(book=book)
        .select_related("user")
        .order_by("created_at", "pk")
    )
    for entry in waiting:
        if free <= 0:
            break
        if fines.fine_summary(entry.user).is_blocked:
            # They keep their place, but cannot take a copy right now
            continue
        entry.status = Status.NOTIFIED
        entry.notified_at = now
        entry.claim_deadline = now + timedelta(hours=settings.WAITLIST_CLAIM_HOURS)
        entry.save(
            update_fields=["status", "notified_at", "claim_deadline", "updated_at"]
        )
        # Send the email only if the whole transaction succeeds
        transaction.on_commit(partial(_send_claim_email, entry.pk))
        promoted.append(entry)
        free -= 1
    return promoted


def promote_waitlist(book_id):
    """Lock the book, then promote. Call inside a transaction."""
    book = Book.objects.active().select_for_update().filter(pk=book_id).first()
    if book is None:
        return []
    return promote_locked(book)


@transaction.atomic
def join_waitlist(user, book_id):
    try:
        book = Book.objects.active().select_for_update().get(pk=book_id)
    except Book.DoesNotExist:
        raise ReservationError("This book is not in the catalog.") from None

    promote_locked(book)

    if fines.fine_summary(user).is_blocked:
        raise ReservationError(fines.BLOCKED_MESSAGE)
    if Reservation.objects.active().filter(user=user, book=book).exists():
        raise ReservationError("You already have an active reservation for this book.")
    if WaitlistEntry.objects.open().filter(user=user, book=book).exists():
        raise ReservationError("You are already on the waitlist for this book.")
    if free_copies(book) > 0:
        raise ReservationError(
            "This book is available right now. You can reserve it instead "
            "of joining the waitlist."
        )
    return WaitlistEntry.objects.create(user=user, book=book)


@transaction.atomic
def leave_waitlist(entry_id, user):
    try:
        entry = WaitlistEntry.objects.select_for_update().get(pk=entry_id, user=user)
    except WaitlistEntry.DoesNotExist:
        raise ReservationError("Waitlist entry not found.") from None
    if entry.status not in (Status.WAITING, Status.NOTIFIED):
        raise ReservationError("You are no longer in this waitlist.")

    had_hold = entry.status == Status.NOTIFIED
    entry.status = Status.CANCELLED
    entry.save(update_fields=["status", "updated_at"])
    if had_hold:
        # Their held copy goes to the next person in line
        promote_waitlist(entry.book_id)
    return entry


def process_waitlist():
    """Maintenance job: expire timed-out claims, then offer free copies.

    Returns (expired_claims, promoted_count).
    """
    now = timezone.now()
    expired = WaitlistEntry.objects.filter(
        status=Status.NOTIFIED, claim_deadline__lte=now
    ).update(status=Status.EXPIRED, updated_at=now)

    book_ids = list(
        WaitlistEntry.objects.waiting()
        .order_by()
        .values_list("book_id", flat=True)
        .distinct()
    )
    promoted = 0
    for book_id in book_ids:
        with transaction.atomic():
            promoted += len(promote_waitlist(book_id))
    return expired, promoted