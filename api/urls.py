from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter()
router.register("books", views.BookViewSet, basename="book")
router.register("authors", views.AuthorViewSet, basename="author")
router.register("genres", views.GenreViewSet, basename="genre")
router.register("reservations", views.ReservationViewSet, basename="reservation")
router.register(
    "staff/reservations", views.StaffReservationViewSet, basename="staff-reservation"
)

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("wishlist/", views.WishlistListView.as_view(), name="my-wishlist"),
    path("waitlist/", views.WaitlistListView.as_view(), name="my-waitlist"),
    path("fines/", views.FineListView.as_view(), name="my-fines"),
    path("", include(router.urls)),
]