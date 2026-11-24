from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View

from books.models import Book

from .forms import ReviewForm
from .models import Review


def _book_reviews_url(book_id):
    return f"{reverse('books:detail', args=[book_id])}#reviews"


class ReviewSaveView(LoginRequiredMixin, View):
    """Create the user's review of a book, or update it if it exists."""

    http_method_names = ["post"]

    def post(self, request, book_id):
        book = get_object_or_404(Book.objects.active(), pk=book_id)
        existing = Review.objects.filter(user=request.user, book=book).first()
        form = ReviewForm(request.POST, instance=existing)
        if not form.is_valid():
            messages.error(
                request,
                "Could not save your review. Please choose a rating "
                "and keep the comment under 2000 characters.",
            )
            return redirect(_book_reviews_url(book.pk))

        review = form.save(commit=False)
        review.user = request.user
        review.book = book
        try:
            with transaction.atomic():
                review.save()
        except IntegrityError:
            # A double submit created the review a moment ago
            messages.error(request, "Your review was already submitted.")
        else:
            messages.success(request, "Your review has been saved.")
        return redirect(_book_reviews_url(book.pk))


class ReviewDeleteView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, book_id):
        deleted, _ = Review.objects.filter(user=request.user, book_id=book_id).delete()
        if deleted:
            messages.success(request, "Your review has been deleted.")
        return redirect(_book_reviews_url(book_id))