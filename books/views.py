from django.views.generic import DetailView, ListView

from .filters import BookFilter
from .models import Book


class BookListView(ListView):
    template_name = "books/book_list.html"
    context_object_name = "books"
    paginate_by = 12

    def get_queryset(self):
        queryset = (
            Book.objects.active()
            .with_availability()
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
            .prefetch_related("authors", "genres")
        )