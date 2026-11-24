from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("", views.MyReservationsView.as_view(), name="mine"),
    path("reserve/<int:book_id>/", views.ReserveBookView.as_view(), name="reserve"),
    path("<int:pk>/cancel/", views.CancelReservationView.as_view(), name="cancel"),
    path("<int:pk>/renew/", views.RenewReservationView.as_view(), name="renew"),
]