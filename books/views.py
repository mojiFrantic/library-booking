from django.views.generic import DetailView, ListView

from .models import Book


class BookListView(ListView):
    template_name = "books/book_list.html"
    context_object_name = "books"
    paginate_by = 12

    def get_queryset(self):
        return (
            Book.objects.active()
            .prefetch_related("authors", "genres")
            .order_by("title")
        )


class BookDetailView(DetailView):
    template_name = "books/book_detail.html"
    context_object_name = "book"

    def get_queryset(self):
        return Book.objects.active().prefetch_related("authors", "genres")