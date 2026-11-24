from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from books.models import Book

from .models import Review

User = get_user_model()


def make_user(name="ali"):
    return User.objects.create_user(name, password="pass12345")


def make_book(title="Book"):
    return Book.objects.create(title=title, publication_year=2000, total_copies=2)


def stats(book):
    return Book.objects.with_ratings().get(pk=book.pk)


class ReviewViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.book = make_book()
        self.save_url = reverse("reviews:save", args=[self.book.pk])

    def test_saving_a_review_requires_login(self):
        response = self.client.post(self.save_url, {"rating": 5})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.assertEqual(Review.objects.count(), 0)

    def test_user_can_post_a_review(self):
        self.client.force_login(self.user)
        response = self.client.post(self.save_url, {"rating": 4, "text": "Great"})
        self.assertEqual(response.status_code, 302)
        review = Review.objects.get()
        self.assertEqual((review.user, review.rating, review.text), (self.user, 4, "Great"))

    def test_posting_again_updates_the_same_review(self):
        self.client.force_login(self.user)
        self.client.post(self.save_url, {"rating": 4})
        self.client.post(self.save_url, {"rating": 2, "text": "Changed my mind"})
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().rating, 2)

    def test_invalid_rating_is_rejected(self):
        self.client.force_login(self.user)
        for bad in ("6", "0", "", "abc"):
            self.client.post(self.save_url, {"rating": bad})
        self.assertEqual(Review.objects.count(), 0)

    def test_user_deletes_only_their_own_review(self):
        other = make_user("sara")
        Review.objects.create(user=other, book=self.book, rating=5)
        Review.objects.create(user=self.user, book=self.book, rating=3)
        self.client.force_login(self.user)
        self.client.post(reverse("reviews:delete", args=[self.book.pk]))
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().user, other)

    def test_hidden_review_is_not_shown_on_detail_page(self):
        Review.objects.create(user=self.user, book=self.book, rating=5, text="Visible words")
        Review.objects.create(
            user=make_user("bad"), book=self.book, rating=1,
            text="Rude words", is_hidden=True,
        )
        response = self.client.get(self.book.get_absolute_url())
        self.assertContains(response, "Visible words")
        self.assertNotContains(response, "Rude words")


class RatingTests(TestCase):
    def test_book_without_reviews_has_no_average(self):
        book = stats(make_book())
        self.assertIsNone(book.average_rating)
        self.assertEqual(book.review_count, 0)

    def test_average_ignores_hidden_reviews(self):
        book = make_book()
        Review.objects.create(user=make_user("a"), book=book, rating=5)
        Review.objects.create(user=make_user("b"), book=book, rating=3)
        Review.objects.create(user=make_user("c"), book=book, rating=1, is_hidden=True)
        result = stats(book)
        self.assertAlmostEqual(float(result.average_rating), 4.0)
        self.assertEqual(result.review_count, 2)


class ReviewModerationTests(TestCase):
    def test_staff_can_hide_reviews_from_admin(self):
        admin_user = User.objects.create_superuser("boss", password="pass12345")
        book = make_book()
        review = Review.objects.create(user=make_user(), book=book, rating=1, text="Rude")
        self.client.force_login(admin_user)
        self.client.post(
            reverse("admin:reviews_review_changelist"),
            {"action": "hide_selected", "_selected_action": [review.pk]},
        )
        review.refresh_from_db()
        self.assertTrue(review.is_hidden)
        self.assertEqual(review.moderated_by, admin_user)