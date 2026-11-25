from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("", views.MyReservationsView.as_view(), name="mine"),
    path("reserve/<int:book_id>/", views.ReserveBookView.as_view(), name="reserve"),
    path("<int:pk>/cancel/", views.CancelReservationView.as_view(), name="cancel"),
    path("<int:pk>/renew/", views.RenewReservationView.as_view(), name="renew"),
    path(
        "waitlist/join/<int:book_id>/",
        views.JoinWaitlistView.as_view(),
        name="waitlist_join",
    ),
    path(
        "waitlist/<int:pk>/leave/",
        views.LeaveWaitlistView.as_view(),
        name="waitlist_leave",
    ),
]