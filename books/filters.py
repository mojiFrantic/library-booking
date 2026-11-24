import django_filters
from django import forms
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q, F

from .models import Author, Book, Genre

SORT_CHOICES = [
    ("title", "Title (A–Z)"),
    ("-title", "Title (Z–A)"),
    ("-publication_year", "Newest published"),
    ("publication_year", "Oldest published"),
    ("-created_at", "Recently added"),
    ("popular", "Most popular"),
    ("top_rated", "Top rated"),
    ("relevance", "Best match"),
]

AVAILABILITY_CHOICES = [
    ("available", "Available"),
    ("unavailable", "Unavailable"),
]


class BookFilter(django_filters.FilterSet):
    # Declaration order matters: q must run before sort.
    q = django_filters.CharFilter(method="filter_search", label="Search")
    author = django_filters.ModelChoiceFilter(
        field_name="authors",
        queryset=Author.objects.all(),
        empty_label="All authors",
        label="Author",
    )
    genre = django_filters.ModelChoiceFilter(
        field_name="genres",
        queryset=Genre.objects.all(),
        empty_label="All genres",
        label="Genre",
    )
    year_from = django_filters.NumberFilter(
        field_name="publication_year", lookup_expr="gte", label="From year"
    )
    year_to = django_filters.NumberFilter(
        field_name="publication_year", lookup_expr="lte", label="To year"
    )
    availability = django_filters.ChoiceFilter(
        choices=AVAILABILITY_CHOICES,
        method="filter_availability",
        empty_label="Any availability",
        label="Availability",
    )
    sort = django_filters.ChoiceFilter(
        choices=SORT_CHOICES,
        method="filter_sort",
        empty_label=None,
        label="Sort by",
    )

    class Meta:
        model = Book
        fields: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.form.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.setdefault("class", css)
        self.form.fields["q"].widget.attrs["placeholder"] = "Title, author or keyword"
        self.form.fields["year_from"].widget.attrs["placeholder"] = "e.g. 1990"
        self.form.fields["year_to"].widget.attrs["placeholder"] = "e.g. 2024"

    def filter_search(self, queryset, name, value):
        value = value.strip()
        if not value:
            return queryset
        # "simple" config: no language-specific stemming, works for any language.
        vector = SearchVector("title", weight="A", config="simple") + SearchVector(
            "summary", weight="C", config="simple"
        )
        query = SearchQuery(value, search_type="websearch", config="simple")
        return (
            queryset.annotate(search_rank=SearchRank(vector, query))
            .filter(
                Q(search_rank__gt=0)
                | Q(title__icontains=value)
                | Q(authors__name__icontains=value)
            )
            .distinct()
            .order_by("-search_rank", "title")
        )

    def filter_availability(self, queryset, name, value):
        if value == "available":
            return queryset.filter(available_count__gt=0)
        if value == "unavailable":
            return queryset.filter(available_count=0)
        return queryset

    def filter_sort(self, queryset, name, value):
        if value == "relevance":
            if "search_rank" in queryset.query.annotations:
                return queryset.order_by("-search_rank", "title")
            return queryset.order_by("title")
        if value == "popular":
            return queryset.order_by("-borrow_count", "title")
        if value == "top_rated":
            return queryset.order_by(
                F("average_rating").desc(nulls_last=True), "-review_count", "title"
            )
        return queryset.order_by(value, "title")