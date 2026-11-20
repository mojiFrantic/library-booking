from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, TemplateView
from django_ratelimit.decorators import ratelimit

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