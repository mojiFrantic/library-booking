from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reservations.models import Reservation
from reviews.models import Review

from .models import Author, Book, Genre, WishlistItem
from .selectors import similar_books

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

User = get_user_model()


class WishlistTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", password="pass12345")
        self.book = make_book("Wish Me")
        self.url = reverse("books:wishlist_toggle", args=[self.book.pk])

    def test_toggle_requires_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_toggle_adds_then_removes(self):
        self.client.force_login(self.user)
        self.client.post(self.url)
        self.assertEqual(WishlistItem.objects.count(), 1)
        self.client.post(self.url)
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_wishlist_page_lists_only_my_books(self):
        other = User.objects.create_user("sara", password="pass12345")
        WishlistItem.objects.create(user=self.user, book=self.book)
        WishlistItem.objects.create(user=other, book=make_book("Not Mine"))
        self.client.force_login(self.user)
        response = self.client.get(reverse("books:wishlist"))
        self.assertContains(response, "Wish Me")
        self.assertNotContains(response, "Not Mine")

    def test_next_redirect_cannot_leave_the_site(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], self.book.get_absolute_url())


class SimilarBooksTests(TestCase):
    def test_ranking_by_shared_genres_and_authors(self):
        g1, g2 = Genre.objects.create(name="G1"), Genre.objects.create(name="G2")
        a1 = Author.objects.create(name="A1")

        main = make_book("Main")
        main.genres.set([g1, g2])
        main.authors.set([a1])

        both_genres = make_book("Both genres")
        both_genres.genres.set([g1, g2])

        one_genre = make_book("One genre")
        one_genre.genres.set([g1])

        same_author = make_book("Same author")
        same_author.authors.set([a1])

        unrelated = make_book("Unrelated")

        titles = [b.title for b in similar_books(main)]
        # Same author (2) ties with both genres (2); title breaks the tie
        self.assertEqual(titles, ["Both genres", "Same author", "One genre"])
        self.assertNotIn("Unrelated", titles)
        self.assertNotIn("Main", titles)

    def test_book_without_genres_or_authors_has_no_similar_books(self):
        self.assertEqual(similar_books(make_book("Lonely")), [])


class CommunitySortTests(TestCase):
    def titles(self, **params):
        response = self.client.get(reverse("books:list"), params)
        self.assertEqual(response.status_code, 200)
        return [b.title for b in response.context["books"]]

    def test_top_rated_sort_puts_unrated_books_last(self):
        great, okay, unrated = make_book("Great"), make_book("Okay"), make_book("Unrated")
        u1 = User.objects.create_user("u1", password="x")
        Review.objects.create(user=u1, book=great, rating=5)
        Review.objects.create(user=u1, book=okay, rating=3)
        self.assertEqual(self.titles(sort="top_rated"), ["Great", "Okay", "Unrated"])

    def test_popular_sort_uses_borrow_counts(self):
        popular, quiet, never = make_book("Popular"), make_book("Quiet"), make_book("Never")
        deadline = timezone.now() + timedelta(hours=1)
        for i, book in enumerate([popular, popular, quiet]):
            user = User.objects.create_user(f"reader{i}", password="x")
            Reservation.objects.create(
                user=user, book=book,
                status=Reservation.Status.CHECKED_OUT, pickup_deadline=deadline,
            )
        self.assertEqual(self.titles(sort="popular"), ["Popular", "Quiet", "Never"])