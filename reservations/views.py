from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView

from . import fines, services, waitlist
from .models import Fine, Reservation, WaitlistEntry


class MyReservationsView(LoginRequiredMixin, ListView):
    template_name = "reservations/my_reservations.html"
    context_object_name = "reservations"
    paginate_by = 20

    def get_queryset(self):
        return Reservation.objects.filter(user=self.request.user).select_related("book")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["waitlist_entries"] = (
            WaitlistEntry.objects.open().filter(user=user).select_related("book")
        )
        context["fine_summary"] = fines.fine_summary(user)
        context["unpaid_fines"] = Fine.objects.filter(
            user=user, status=Fine.Status.UNPAID
        ).select_related("reservation__book")
        context["fine_currency"] = settings.FINE_CURRENCY
        return context


class ReserveBookView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, book_id):
        try:
            services.reserve_book(request.user, book_id)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
            return redirect("books:detail", pk=book_id)
        messages.success(
            request,
            "Book reserved. Please pick it up within "
            f"{settings.RESERVATION_PICKUP_HOURS} hours.",
        )
        return redirect("reservations:mine")


class CancelReservationView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        try:
            services.cancel_reservation(pk, request.user)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Reservation cancelled.")
        return redirect("reservations:mine")


class RenewReservationView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        try:
            reservation = services.renew_reservation(pk, request.user)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request, f"Loan renewed. New due date: {reservation.due_date:%b %d, %Y}."
            )
        return redirect("reservations:mine")


class JoinWaitlistView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, book_id):
        try:
            waitlist.join_waitlist(request.user, book_id)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                "You have joined the waitlist. We will email you when a copy "
                "is held for you.",
            )
            if not request.user.email:
                messages.warning(
                    request,
                    "Your account has no email address, so we cannot notify "
                    "you. Please check this site regularly.",
                )
        return redirect("books:detail", pk=book_id)


class LeaveWaitlistView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        try:
            waitlist.leave_waitlist(pk, request.user)
        except services.ReservationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "You have left the waitlist.")
        return redirect(request.POST.get("next") or "reservations:mine")