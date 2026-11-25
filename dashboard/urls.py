from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="home"),
    path("activity/", views.ActivityLogView.as_view(), name="activity"),
    path(
        "reservations/<int:pk>/check-out/",
        views.StaffCheckOutView.as_view(),
        name="check_out",
    ),
    path(
        "reservations/<int:pk>/check-in/",
        views.StaffCheckInView.as_view(),
        name="check_in",
    ),
]