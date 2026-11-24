from django.test import TestCase
from django.urls import reverse

from .models import Author, Book, Genre


def make_book(title="Test Book", **kwargs):
    defaults = {"publication_year": 2000, "total_copies": 2}
    defaults.update(kwargs)
    return Book.objects.create(title=title, **defaults)


class BookModelTests(TestCase):
    def test_available_copies_with_no_reservations(self):
        book = make_book(total_copies=3)
        self.assertEqual(book.available_copies, 3)
        self.assertTrue(book.is_available)

    def test_zero_copies_means_unavailable(self):
        book = make_book(total_copies=0)
        self.assertFalse(book.is_available)

    def test_multiple_books_without_isbn_are_allowed(self):
        make_book("A")
        make_book("B")  # both have isbn=None, must not clash

    def test_soft_delete_and_restore(self):
        book = make_book()
        book.soft_delete()
        self.assertFalse(Book.objects.active().filter(pk=book.pk).exists())
        book.restore()
        self.assertTrue(Book.objects.active().filter(pk=book.pk).exists())


class BookViewTests(TestCase):
    def test_list_is_paginated(self):
        for i in range(13):
            make_book(f"Book {i:02d}")
        response = self.client.get(reverse("books:list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["books"]), 12)
        response = self.client.get(reverse("books:list"), {"page": 2})
        self.assertEqual(len(response.context["books"]), 1)

    def test_soft_deleted_book_is_hidden(self):
        book = make_book("Hidden Book")
        book.soft_delete()
        response = self.client.get(reverse("books:list"))
        self.assertNotContains(response, "Hidden Book")
        response = self.client.get(book.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_detail_page_shows_availability(self):
        book = make_book("Visible Book", total_copies=0)
        response = self.client.get(book.get_absolute_url())
        self.assertContains(response, "Unavailable")

class BookFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tolkien = Author.objects.create(name="J. R. R. Tolkien")
        cls.asimov = Author.objects.create(name="Isaac Asimov")
        cls.fantasy = Genre.objects.create(name="Fantasy")
        cls.scifi = Genre.objects.create(name="Science Fiction")

        cls.hobbit = make_book("The Hobbit", publication_year=1937, total_copies=2)
        cls.hobbit.authors.add(cls.tolkien)
        cls.hobbit.genres.add(cls.fantasy)

        cls.foundation = make_book(
            "Foundation",
            publication_year=1951,
            total_copies=0,
            summary="A galactic empire declines.",
        )
        cls.foundation.authors.add(cls.asimov)
        cls.foundation.genres.add(cls.scifi)

    def titles(self, **params):
        response = self.client.get(reverse("books:list"), params)
        self.assertEqual(response.status_code, 200)
        return [book.title for book in response.context["books"]]

    def test_no_filters_returns_all_books(self):
        self.assertEqual(self.titles(), ["Foundation", "The Hobbit"])

    def test_filter_by_genre(self):
        self.assertEqual(self.titles(genre=self.fantasy.pk), ["The Hobbit"])

    def test_filter_by_author(self):
        self.assertEqual(self.titles(author=self.asimov.pk), ["Foundation"])

    def test_filter_by_year_range(self):
        self.assertEqual(self.titles(year_from=1940, year_to=1960), ["Foundation"])

    def test_filter_by_availability(self):
        self.assertEqual(self.titles(availability="available"), ["The Hobbit"])
        self.assertEqual(self.titles(availability="unavailable"), ["Foundation"])

    def test_search_by_title(self):
        self.assertEqual(self.titles(q="hobbit"), ["The Hobbit"])

    def test_search_by_partial_title(self):
        self.assertEqual(self.titles(q="hob"), ["The Hobbit"])

    def test_search_by_author_name(self):
        self.assertEqual(self.titles(q="asimov"), ["Foundation"])

    def test_search_in_summary(self):
        self.assertEqual(self.titles(q="galactic"), ["Foundation"])

    def test_sort_by_newest_published(self):
        self.assertEqual(
            self.titles(sort="-publication_year"), ["Foundation", "The Hobbit"]
        )

    def test_invalid_year_does_not_crash(self):
        self.assertEqual(self.titles(year_from="abc"), ["Foundation", "The Hobbit"])

    def test_soft_deleted_books_stay_hidden_when_filtering(self):
        self.hobbit.soft_delete()
        self.assertEqual(self.titles(genre=self.fantasy.pk), [])

    def test_pagination_keeps_filters(self):
        for i in range(13):
            book = make_book(f"Fantasy Book {i:02d}")
            book.genres.add(self.fantasy)
        response = self.client.get(reverse("books:list"), {"genre": self.fantasy.pk})
        self.assertContains(response, f"page=2&amp;genre={self.fantasy.pk}")