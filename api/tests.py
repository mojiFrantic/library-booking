from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from books.models import Author, Book, Genre, WishlistItem
from dashboard.models import ActivityLog
from reservations import services
from reservations.models import Reservation, WaitlistEntry
from reviews.models import Review

User = get_user_model()
PASSWORD = "Str0ng-pass-123"


def make_user(name, role=User.Role.CUSTOMER):
    return User.objects.create_user(
        name, email=f"{name}@example.com", password=PASSWORD, role=role
    )


def make_book(title="Book", copies=2, **kwargs):
    return Book.objects.create(
        title=title, publication_year=2000, total_copies=copies, **kwargs
    )


class BaseApiTest(APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # throttle counters live in the cache


class AuthApiTests(BaseApiTest):
    payload = {
        "username": "newuser",
        "email": "new@example.com",
        "phone": "",
        "password": PASSWORD,
        "password2": PASSWORD,
    }

    def test_register_returns_a_token_and_creates_a_customer(self):
        response = self.client.post(reverse("api:register"), {**self.payload, "role": "admin"})
        self.assertEqual(response.status_code, 201)
        self.assertIn("token", response.data)
        user = User.objects.get(username="newuser")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_staff)

    def test_register_rejects_a_duplicate_email(self):
        make_user("old")
        response = self.client.post(
            reverse("api:register"), {**self.payload, "email": "OLD@example.com"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_register_rejects_mismatched_and_weak_passwords(self):
        url = reverse("api:register")
        mismatch = self.client.post(url, {**self.payload, "password2": "different"})
        self.assertEqual(mismatch.status_code, 400)
        weak = self.client.post(
            url, {**self.payload, "password": "12345678", "password2": "12345678"}
        )
        self.assertEqual(weak.status_code, 400)
        self.assertIn("password", weak.data)

    def test_register_is_throttled(self):
        url = reverse("api:register")
        codes = [self.client.post(url, {}).status_code for _ in range(6)]
        self.assertEqual(codes, [400, 400, 400, 400, 400, 429])

    def test_login_and_token_usage(self):
        make_user("ali")
        url = reverse("api:login")
        bad = self.client.post(url, {"username": "ali", "password": "wrong"})
        self.assertEqual(bad.status_code, 400)

        good = self.client.post(url, {"username": "ali", "password": PASSWORD})
        self.assertEqual(good.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {good.data['token']}")
        me = self.client.get(reverse("api:me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["username"], "ali")
        self.assertFalse(me.data["is_blocked"])

    def test_logout_invalidates_the_token(self):
        make_user("ali")
        token = self.client.post(
            reverse("api:login"), {"username": "ali", "password": PASSWORD}
        ).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.post(reverse("api:logout")).status_code, 204)
        self.assertEqual(self.client.get(reverse("api:me")).status_code, 401)

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("api:me")).status_code, 401)


class BookApiTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.staff = make_user("boss", role=User.Role.STAFF)
        self.customer = make_user("reader")
        self.author = Author.objects.create(name="Tolkien")
        self.genre = Genre.objects.create(name="Fantasy")
        self.book = make_book("The Hobbit")
        self.book.authors.add(self.author)
        self.book.genres.add(self.genre)

    def test_list_is_public_and_paginated(self):
        make_book("Another")
        response = self.client.get(reverse("api:book-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        first = response.data["results"][0]
        for key in ("authors", "available_copies", "is_available", "average_rating"):
            self.assertIn(key, first)

    def test_filters_search_and_sort(self):
        make_book("Unrelated")
        url = reverse("api:book-list")
        self.assertEqual(self.client.get(url, {"genre": self.genre.pk}).data["count"], 1)
        self.assertEqual(self.client.get(url, {"author": self.author.pk}).data["count"], 1)
        self.assertEqual(self.client.get(url, {"q": "hob"}).data["count"], 1)

        Review.objects.create(user=self.customer, book=self.book, rating=5)
        top = self.client.get(url, {"sort": "top_rated"}).data["results"]
        self.assertEqual([b["title"] for b in top], ["The Hobbit", "Unrelated"])

    def test_invalid_filter_value_is_a_400(self):
        response = self.client.get(reverse("api:book-list"), {"year_from": "abc"})
        self.assertEqual(response.status_code, 400)

    def test_detail_and_soft_deleted_books(self):
        url = reverse("api:book-detail", args=[self.book.pk])
        self.assertEqual(self.client.get(url).data["title"], "The Hobbit")
        self.book.soft_delete()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_only_staff_can_create_books(self):
        payload = {
            "title": "New Book",
            "author_ids": [self.author.pk],
            "genre_ids": [self.genre.pk],
            "publication_year": 2001,
            "total_copies": 3,
        }
        url = reverse("api:book-list")
        self.assertEqual(self.client.post(url, payload).status_code, 401)

        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.post(url, payload).status_code, 403)

        self.client.force_authenticate(self.staff)
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["authors"][0]["name"], "Tolkien")
        self.assertEqual(response.data["available_copies"], 3)
        entry = ActivityLog.objects.get(action=ActivityLog.Action.BOOK_CREATED)
        self.assertEqual(entry.actor, self.staff)

    def test_book_validation(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            reverse("api:book-list"),
            {"title": "Future", "author_ids": [self.author.pk], "publication_year": 3000},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("publication_year", response.data)

    def test_staff_can_update_and_soft_delete(self):
        url = reverse("api:book-detail", args=[self.book.pk])
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.delete(url).status_code, 403)

        self.client.force_authenticate(self.staff)
        patched = self.client.patch(url, {"total_copies": 5})
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["total_copies"], 5)
        self.assertTrue(ActivityLog.objects.filter(action="book_updated").exists())

        self.assertEqual(self.client.delete(url).status_code, 204)
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_deleted)
        self.assertTrue(ActivityLog.objects.filter(action="book_soft_deleted").exists())


class CommunityApiTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = make_user("ali")
        self.book = make_book("Shared Book", copies=1)

    def test_reviews_list_hides_hidden_reviews(self):
        Review.objects.create(user=self.user, book=self.book, rating=5, text="Nice")
        Review.objects.create(
            user=make_user("bad"), book=self.book, rating=1, text="Rude", is_hidden=True
        )
        response = self.client.get(reverse("api:book-reviews", args=[self.book.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["text"] for r in response.data["results"]], ["Nice"])

    def test_my_review_create_update_delete(self):
        url = reverse("api:book-my-review", args=[self.book.pk])
        self.assertEqual(self.client.put(url, {"rating": 4}).status_code, 401)

        self.client.force_authenticate(self.user)
        created = self.client.put(url, {"rating": 4, "text": "Good"})
        self.assertEqual(created.status_code, 201)
        updated = self.client.put(url, {"rating": 2})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().rating, 2)

        self.assertEqual(self.client.put(url, {"rating": 9}).status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(Review.objects.count(), 0)

    def test_wishlist_add_list_and_remove(self):
        self.client.force_authenticate(self.user)
        url = reverse("api:book-wishlist", args=[self.book.pk])
        self.assertEqual(self.client.put(url).data, {"in_wishlist": True})
        listing = self.client.get(reverse("api:my-wishlist"))
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_waitlist_join_and_leave(self):
        url = reverse("api:book-waitlist", args=[self.book.pk])
        self.client.force_authenticate(self.user)

        # The only copy is free, so there is nothing to wait for
        self.assertEqual(self.client.post(url).status_code, 400)

        services.reserve_book(make_user("holder"), self.book.pk)
        joined = self.client.post(url)
        self.assertEqual(joined.status_code, 201)
        self.assertEqual(joined.data["position"], 1)
        self.assertEqual(self.client.get(reverse("api:my-waitlist")).data["count"], 1)

        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertFalse(WaitlistEntry.objects.open().exists())


class ReservationApiTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.user = make_user("ali")
        self.book = make_book("Some Book", copies=2)
        self.url = reverse("api:reservation-list")

    def test_reserve_requires_login(self):
        self.assertEqual(self.client.post(self.url, {"book": self.book.pk}).status_code, 401)

    def test_reserve_reduces_availability(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, {"book": self.book.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        detail = self.client.get(reverse("api:book-detail", args=[self.book.pk]))
        self.assertEqual(detail.data["available_copies"], 1)

    def test_business_rules_come_back_as_400_with_detail(self):
        self.client.force_authenticate(self.user)
        self.client.post(self.url, {"book": self.book.pk})
        duplicate = self.client.post(self.url, {"book": self.book.pk})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("detail", duplicate.data)
        self.assertEqual(self.client.post(self.url, {"book": 9999}).status_code, 400)

    def test_list_shows_only_my_reservations(self):
        services.reserve_book(make_user("other"), self.book.pk)
        mine = services.reserve_book(self.user, self.book.pk)
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual([r["id"] for r in response.data["results"]], [mine.pk])

    def test_cancel_and_cannot_touch_someone_elses(self):
        mine = services.reserve_book(self.user, self.book.pk)
        theirs = services.reserve_book(make_user("other"), self.book.pk)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(reverse("api:reservation-cancel", args=[theirs.pk])).status_code, 404)
        response = self.client.post(reverse("api:reservation-cancel", args=[mine.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")

    def test_renew_a_checked_out_loan(self):
        reservation = services.reserve_book(self.user, self.book.pk)
        services.check_out(reservation.pk)
        self.client.force_authenticate(self.user)
        url = reverse("api:reservation-renew", args=[reservation.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 400)  # only one renewal

    @override_settings(FINE_PER_DAY=Decimal("1.00"), FINE_MAX_PER_LOAN=Decimal("30.00"))
    def test_overdue_loan_blocks_new_reservations(self):
        loan = services.reserve_book(self.user, self.book.pk)
        services.check_out(loan.pk)
        Reservation.objects.filter(pk=loan.pk).update(
            due_date=timezone.localdate() - timedelta(days=2)
        )
        self.client.force_authenticate(self.user)
        other = make_book("Other")
        response = self.client.post(self.url, {"book": other.pk})
        self.assertEqual(response.status_code, 400)
        me = self.client.get(reverse("api:me"))
        self.assertTrue(me.data["is_blocked"])


class StaffReservationApiTests(BaseApiTest):
    def setUp(self):
        super().setUp()
        self.staff = make_user("boss", role=User.Role.STAFF)
        self.customer = make_user("reader")
        self.reservation = services.reserve_book(self.customer, make_book("Desk Book").pk)

    def test_only_staff_can_use_the_staff_endpoints(self):
        url = reverse("api:staff-reservation-list")
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(url).data["count"], 1)

    def test_staff_can_filter_by_user_and_status(self):
        self.client.force_authenticate(self.staff)
        url = reverse("api:staff-reservation-list")
        self.assertEqual(self.client.get(url, {"user": "reader"}).data["count"], 1)
        self.assertEqual(self.client.get(url, {"user": "nobody"}).data["count"], 0)
        self.assertEqual(self.client.get(url, {"status": "returned"}).data["count"], 0)

    def test_check_out_and_check_in(self):
        self.client.force_authenticate(self.staff)
        out = self.client.post(
            reverse("api:staff-reservation-check-out", args=[self.reservation.pk])
        )
        self.assertEqual(out.status_code, 200)
        self.assertEqual(out.data["status"], "checked_out")
        self.assertTrue(
            ActivityLog.objects.filter(action="checked_out", actor=self.staff).exists()
        )

        back = self.client.post(
            reverse("api:staff-reservation-check-in", args=[self.reservation.pk])
        )
        self.assertEqual(back.status_code, 200)
        self.assertEqual(back.data["status"], "returned")
        self.assertIsNone(back.data["fine_amount"])

    def test_customer_cannot_check_out(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(
            reverse("api:staff-reservation-check-out", args=[self.reservation.pk])
        )
        self.assertEqual(response.status_code, 403)


class DocsTests(BaseApiTest):
    def test_schema_is_generated(self):
        self.assertEqual(self.client.get(reverse("schema")).status_code, 200)

    def test_swagger_ui_does_not_depend_on_a_cdn(self):
        response = self.client.get(reverse("swagger-ui"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "cdn.jsdelivr.net")