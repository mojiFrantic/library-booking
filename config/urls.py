from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

app_name = "accounts"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("captcha/", include("captcha.urls")),
    path("accounts/", include("accounts.urls")),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
]