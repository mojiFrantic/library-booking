from django.test import TestCase
from django.urls import reverse

from .models import Book


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