from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("captcha/", include("captcha.urls")),
    path("accounts/", include("accounts.urls")),
    path("books/", include("books.urls")),
    path("", RedirectView.as_view(pattern_name="books:list"), name="home"),
    path("reservations/", include("reservations.urls")),
    path("reviews/", include("reviews.urls")),
    path("staff/", include("dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)