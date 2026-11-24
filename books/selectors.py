from django.db.models import Count, F, IntegerField, Q, Value

from .models import Book


def similar_books(book, limit=4):
    """Books sharing genres or authors with `book`, best matches first.

    A shared author counts double a shared genre.
    """
    genre_ids = list(book.genres.values_list("pk", flat=True))
    author_ids = list(book.authors.values_list("pk", flat=True))
    if not genre_ids and not author_ids:
        return []

    zero = Value(0, output_field=IntegerField())
    shared_genres = (
        Count("genres", filter=Q(genres__in=genre_ids), distinct=True)
        if genre_ids
        else zero
    )
    shared_authors = (
        Count("authors", filter=Q(authors__in=author_ids), distinct=True)
        if author_ids
        else zero
    )

    # Step 1: rank candidate ids (a light query)
    ranked_ids = list(
        Book.objects.active()
        .exclude(pk=book.pk)
        .annotate(shared_genres=shared_genres, shared_authors=shared_authors)
        .annotate(score=F("shared_genres") + 2 * F("shared_authors"))
        .filter(score__gt=0)
        .order_by("-score", "title")
        .values_list("pk", flat=True)[:limit]
    )

    # Step 2: load full books with availability and rating annotations
    books = {
        b.pk: b
        for b in Book.objects.active()
        .filter(pk__in=ranked_ids)
        .with_availability()
        .with_ratings()
        .prefetch_related("authors", "genres")
    }
    return [books[pk] for pk in ranked_ids if pk in books]