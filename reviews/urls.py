from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("book/<int:book_id>/save/", views.ReviewSaveView.as_view(), name="save"),
    path("book/<int:book_id>/delete/", views.ReviewDeleteView.as_view(), name="delete"),
]