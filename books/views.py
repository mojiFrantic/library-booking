from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, ListView

from reservations.models import Reservation, WaitlistEntry
from reviews.forms import ReviewForm
from reviews.models import Review

from .filters import BookFilter
from .models import Book, WishlistItem
from .selectors import similar_books

class BookListView(ListView):
    template_name = "books/book_list.html"
    context_object_name = "books"
    paginate_by = 12

    def get_queryset(self):
        queryset = (
            Book.objects.active()
            .with_availability()
            .with_ratings()
            .with_popularity()
            .prefetch_related("authors", "genres")
            .order_by("title")
        )
        self.filterset = BookFilter(self.request.GET, queryset=queryset)
        return self.filterset.qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filterset"] = self.filterset
        # Keep filters when moving between pages
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context


class BookDetailView(DetailView):
    template_name = "books/book_detail.html"
    context_object_name = "book"

    def get_queryset(self):
        return (
            Book.objects.active()
            .with_availability()
            .with_ratings()
            .prefetch_related("authors", "genres")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        book = self.object

        context["reviews"] = Review.objects.filter(
            book=book, is_hidden=False
        ).select_related("user")[:20]
        context["similar_books"] = similar_books(book)
        context["waitlist_length"] = (
            WaitlistEntry.objects.waiting().filter(book=book).count()
        )

        context["user_reservation"] = None
        context["user_waitlist_entry"] = None
        context["user_hold"] = None
        context["my_review"] = None
        context["review_form"] = None
        context["in_wishlist"] = False
        if user.is_authenticated:
            context["user_reservation"] = (
                Reservation.objects.active().filter(user=user, book=book).first()
            )
            entry = WaitlistEntry.objects.open().filter(user=user, book=book).first()
            context["user_waitlist_entry"] = entry
            if entry is not None and entry.status == WaitlistEntry.Status.NOTIFIED:
                context["user_hold"] = entry
            my_review = Review.objects.filter(user=user, book=book).first()
            context["my_review"] = my_review
            context["review_form"] = ReviewForm(instance=my_review)
            context["in_wishlist"] = WishlistItem.objects.filter(
                user=user, book=book
            ).exists()
        return context


class WishlistView(LoginRequiredMixin, ListView):
    template_name = "books/wishlist.html"
    context_object_name = "books"
    paginate_by = 12

    def get_queryset(self):
        added_at = Subquery(
            WishlistItem.objects.filter(
                user=self.request.user, book=OuterRef("pk")
            ).values("added_at")[:1]
        )
        return (
            Book.objects.active()
            .annotate(added_at=added_at)
            .filter(added_at__isnull=False)
            .with_availability()
            .with_ratings()
            .prefetch_related("authors", "genres")
            .order_by("-added_at")
        )


class WishlistToggleView(LoginRequiredMixin, View):
    """Add the book to the wishlist, or remove it if it is already there."""

    http_method_names = ["post"]

    def post(self, request, pk):
        book = get_object_or_404(Book.objects.active(), pk=pk)
        items = WishlistItem.objects.filter(user=request.user, book=book)
        if items.exists():
            items.delete()
            messages.success(request, "Removed from your wishlist.")
        else:
            WishlistItem.objects.get_or_create(user=request.user, book=book)
            messages.success(request, "Added to your wishlist.")

        # Only follow `next` if it points back to this site
        next_url = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            next_url = book.get_absolute_url()
        return redirect(next_url)