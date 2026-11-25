from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, TemplateView
from django_ratelimit.decorators import ratelimit
from django.conf import settings
from reservations import fines
from reservations.models import Reservation
from .forms import LoginForm, RegisterForm


@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=True), name="dispatch"
)
class RegisterView(CreateView):
    form_class = RegisterForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect(self.success_url)


@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=True), name="dispatch"
)
class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        reservations = Reservation.objects.filter(user=user).select_related("book")
        context["active_loans"] = reservations.filter(
            status=Reservation.Status.CHECKED_OUT
        )
        context["recent_reservations"] = reservations[:5]
        context["wishlist_count"] = user.wishlist_items.count()
        context["review_count"] = user.reviews.count()
        context["fine_summary"] = fines.fine_summary(user)
        context["fine_currency"] = settings.FINE_CURRENCY
        return context