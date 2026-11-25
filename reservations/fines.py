from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from .models import Fine, Reservation

BLOCKED_MESSAGE = (
    "You cannot reserve books or join waitlists while you have overdue books "
    "or unpaid late fees. Please return overdue books and settle your fines "
    "at the library desk."
)


def calculate_fine(due_date, end_date):
    """Return (days_overdue, amount) for a loan due on `due_date`."""
    days = max((end_date - due_date).days, 0)
    amount = min(settings.FINE_PER_DAY * days, settings.FINE_MAX_PER_LOAN)
    return days, amount


@dataclass(frozen=True)
class FineSummary:
    unpaid_total: Decimal  # fines already recorded and not yet paid
    accrued_total: Decimal  # fines still growing on overdue loans
    overdue_count: int

    @property
    def total(self):
        return self.unpaid_total + self.accrued_total

    @property
    def is_blocked(self):
        return self.total > 0 or self.overdue_count > 0


def fine_summary(user):
    today = timezone.localdate()
    unpaid_total = Fine.objects.filter(
        user=user, status=Fine.Status.UNPAID
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    accrued_total = Decimal("0")
    overdue_count = 0
    overdue_loans = Reservation.objects.filter(
        user=user,
        status=Reservation.Status.CHECKED_OUT,
        due_date__lt=today,
    )
    for loan in overdue_loans:
        _, amount = calculate_fine(loan.due_date, today)
        accrued_total += amount
        overdue_count += 1

    return FineSummary(unpaid_total, accrued_total, overdue_count)


def create_fine_for_return(reservation):
    """Record a fine when a loan is returned late. Returns the Fine or None."""
    returned_on = timezone.localdate(reservation.returned_at)
    days, amount = calculate_fine(reservation.due_date, returned_on)
    if days == 0 or amount <= 0:
        return None
    return Fine.objects.create(
        user_id=reservation.user_id,
        reservation=reservation,
        days_overdue=days,
        amount=amount,
    )