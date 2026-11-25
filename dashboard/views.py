from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from accounts.mixins import StaffRequiredMixin
from books.models import Book
from reservations import fines, services
from reservations.models import Fine, Reservation, WaitlistEntry

from .models import ActivityLog

TABLE_LIMIT = 25


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        today = timezone.localdate()
        status = Reservation.Status

        pending = Reservation.objects.filter(
            status=status.PENDING, pickup_deadline__gt=now
        )
        on_loan = Reservation.objects.filter(status=status.CHECKED_OUT)

        inventory = Book.objects.active().aggregate(
            titles=Count("pk"), copies=Sum("total_copies")
        )
        unpaid = Fine.objects.filter(status=Fine.Status.UNPAID).aggregate(
            total=Sum("amount"), count=Count("pk")
        )

        context["stats"] = {
            "titles": inventory["titles"],
            "copies": inventory["copies"] or 0,
            "pending_pickups": pending.count(),
            "on_loan": on_loan.count(),
            "overdue": on_loan.filter(due_date__lt=today).count(),
            "people_waiting": WaitlistEntry.objects.open().count(),
            "unpaid_fines_total": unpaid["total"] or Decimal("0"),
            "unpaid_fines_count": unpaid["count"],
        }

        context["pending_reservations"] = list(
            pending.select_related("user", "book").order_by("pickup_deadline")[
                :TABLE_LIMIT
            ]
        )
        loans = list(
            on_loan.select_related("user", "book").order_by("due_date")[:TABLE_LIMIT]
        )
        for loan in loans:
            loan.days_late, loan.accrued_fine = fines.calculate_fine(
                loan.due_date, today
            )
        context["loans"] = loans
        context["table_limit"] = TABLE_LIMIT

        context["popular_books"] = list(
            Book.objects.active()
            .with_popularity()
            .filter(borrow_count__gt=0)
            .order_by("-borrow_count", "title")[:5]
        )
        context["longest_waitlists"] = list(
            WaitlistEntry.objects.open()
            .order_by()
            .values("book_id", "book__title")
            .annotate(people=Count("pk"))
            .order_by("-people", "book__title")[:5]
        )
        context["daily_reservations"] = self._daily_reservations(today)
        context["recent_activity"] = ActivityLog.objects.select_related("actor")[:10]
        context["fine_currency"] = settings.FINE_CURRENCY
        return context

    @staticmethod
    def _daily_reservations(today):
        """Reservations made per day over the last 14 days, with bar widths."""
        start = today - timedelta(days=13)
        rows = (
            Reservation.objects.filter(reserved_at__date__gte=start)
            .annotate(day=TruncDate("reserved_at"))
            .order_by()
            .values("day")
            .annotate(total=Count("pk"))
        )
        counts = {row["day"]: row["total"] for row in rows}
        peak = max(counts.values(), default=0)
        series = []
        for offset in range(14):
            day = start + timedelta(days=offset)
            count = counts.get(day, 0)
            series.append(
                {
                    "day": day,
                    "count": count,
                    "percent": round(count * 100 / peak) if peak else 0,
                }
            )
        return series


class StaffCheckOutView(StaffRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        try:
            reservation = services.check_out(pk, actor=request.user)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"Checked out to {reservation.user}. "
                f"Due {reservation.due_date:%b %d, %Y}.",
            )
        return redirect("dashboard:home")


class StaffCheckInView(StaffRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        try:
            reservation = services.check_in(pk, actor=request.user)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
        else:
            fine = Fine.objects.filter(reservation=reservation).first()
            if fine:
                messages.warning(
                    request,
                    f"Returned late. A fine of {settings.FINE_CURRENCY}{fine.amount} "
                    f"was recorded for {reservation.user}.",
                )
            else:
                messages.success(request, "Marked as returned.")
        return redirect("dashboard:home")


class ActivityLogView(StaffRequiredMixin, ListView):
    template_name = "dashboard/activity_log.html"
    context_object_name = "entries"
    paginate_by = 25

    def get_queryset(self):
        queryset = ActivityLog.objects.select_related("actor")
        action = self.request.GET.get("action", "")
        if action in ActivityLog.Action.values:
            queryset = queryset.filter(action=action)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action_choices"] = ActivityLog.Action.choices
        context["selected_action"] = self.request.GET.get("action", "")
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context