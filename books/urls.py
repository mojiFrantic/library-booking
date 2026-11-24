from django.urls import path

from .views import (
    BookDetailView,
    BookListView,
    WishlistToggleView,
    WishlistView,
)

app_name = "books"

urlpatterns = [
    path("", BookListView.as_view(), name="list"),
    path("wishlist/", WishlistView.as_view(), name="wishlist"),
    path("<int:pk>/", BookDetailView.as_view(), name="detail"),
    path("<int:pk>/wishlist/", WishlistToggleView.as_view(), name="wishlist_toggle"),
]