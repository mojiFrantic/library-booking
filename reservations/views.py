from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView

from . import services
from .models import Reservation


class MyReservationsView(LoginRequiredMixin, ListView):
    template_name = "reservations/my_reservations.html"
    context_object_name = "reservations"
    paginate_by = 20

    def get_queryset(self):
        return Reservation.objects.filter(user=self.request.user).select_related("book")


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