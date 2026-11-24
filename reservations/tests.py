from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from books.models import Book

from . import services
from .models import Reservation

User = get_user_model()


def make_user(name="ali"):
    return User.objects.create_user(name, password="pass12345")


def make_book(title="Book", copies=1):
    return Book.objects.create(title=title, publication_year=2000, total_copies=copies)


def available(book):
    return Book.objects.with_availability().get(pk=book.pk).available_count


class ReserveTests(TestCase):
    def test_reserving_reduces_availability(self):
        user, book = make_user(), make_book(copies=2)
        services.reserve_book(user, book.pk)
        self.assertEqual(available(book), 1)

    def test_cannot_reserve_when_no_copies_left(self):
        book = make_book(copies=1)
        services.reserve_book(make_user("a"), book.pk)
        with self.assertRaises(services.ReservationError):
            services.reserve_book(make_user("b"), book.pk)

    def test_cannot_reserve_same_book_twice(self):
        user, book = make_user(), make_book(copies=3)
        services.reserve_book(user, book.pk)
        with self.assertRaises(services.ReservationError):
            services.reserve_book(user, book.pk)

    @override_settings(MAX_ACTIVE_RESERVATIONS=2)
    def test_per_user_limit(self):
        user = make_user()
        services.reserve_book(user, make_book("A").pk)
        services.reserve_book(user, make_book("B").pk)
        with self.assertRaises(services.ReservationError):
            services.reserve_book(user, make_book("C").pk)

    def test_soft_deleted_book_cannot_be_reserved(self):
        book = make_book()
        book.soft_delete()
        with self.assertRaises(services.ReservationError):
            services.reserve_book(make_user(), book.pk)


class CancelAndExpiryTests(TestCase):
    def test_cancel_releases_the_copy(self):
        user, book = make_user(), make_book()
        reservation = services.reserve_book(user, book.pk)
        services.cancel_reservation(reservation.pk, user)
        self.assertEqual(available(book), 1)

    def test_cannot_cancel_someone_elses_reservation(self):
        book = make_book()
        reservation = services.reserve_book(make_user("a"), book.pk)
        with self.assertRaises(services.ReservationError):
            services.cancel_reservation(reservation.pk, make_user("b"))

    def test_expired_pickup_releases_copy_and_user_can_reserve_again(self):
        user, book = make_user(), make_book()
        reservation = services.reserve_book(user, book.pk)
        Reservation.objects.filter(pk=reservation.pk).update(
            pickup_deadline=timezone.now() - timedelta(minutes=1)
        )
        # No cron job has run, but the copy is already free
        self.assertEqual(available(book), 1)
        # And the same user can reserve the same book again
        services.reserve_book(user, book.pk)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.EXPIRED)

    def test_expire_stale_pickups_command_function(self):
        reservation = services.reserve_book(make_user(), make_book().pk)
        Reservation.objects.filter(pk=reservation.pk).update(
            pickup_deadline=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(services.expire_stale_pickups(), 1)


class LoanTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.book = make_book()
        self.reservation = services.reserve_book(self.user, self.book.pk)

    def test_check_out_sets_due_date_and_keeps_copy_held(self):
        services.check_out(self.reservation.pk)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CHECKED_OUT)
        self.assertIsNotNone(self.reservation.due_date)
        self.assertEqual(available(self.book), 0)

    def test_check_in_releases_the_copy(self):
        services.check_out(self.reservation.pk)
        services.check_in(self.reservation.pk)
        self.assertEqual(available(self.book), 1)

    def test_cannot_check_out_after_pickup_deadline(self):
        Reservation.objects.filter(pk=self.reservation.pk).update(
            pickup_deadline=timezone.now() - timedelta(minutes=1)
        )
        with self.assertRaises(services.ReservationError):
            services.check_out(self.reservation.pk)

    def test_cannot_return_a_book_that_was_not_checked_out(self):
        with self.assertRaises(services.ReservationError):
            services.check_in(self.reservation.pk)

    def test_renew_extends_due_date_once(self):
        services.check_out(self.reservation.pk)
        self.reservation.refresh_from_db()
        old_due = self.reservation.due_date
        services.renew_reservation(self.reservation.pk, self.user)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.due_date, old_due + timedelta(days=14))
        with self.assertRaises(services.ReservationError):
            services.renew_reservation(self.reservation.pk, self.user)

    def test_cannot_renew_overdue_loan(self):
        services.check_out(self.reservation.pk)
        Reservation.objects.filter(pk=self.reservation.pk).update(
            due_date=timezone.localdate() - timedelta(days=1)
        )
        with self.assertRaises(services.ReservationError):
            services.renew_reservation(self.reservation.pk, self.user)


class ReservationViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.book = make_book()

    def test_reserve_requires_login(self):
        response = self.client.post(reverse("reservations:reserve", args=[self.book.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.assertEqual(Reservation.objects.count(), 0)

    def test_reserve_rejects_get(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("reservations:reserve", args=[self.book.pk]))
        self.assertEqual(response.status_code, 405)

    def test_logged_in_user_can_reserve(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("reservations:reserve", args=[self.book.pk]))
        self.assertRedirects(response, reverse("reservations:mine"))
        self.assertEqual(Reservation.objects.filter(user=self.user).count(), 1)

    def test_detail_page_buttons(self):
        url = self.book.get_absolute_url()
        self.assertContains(self.client.get(url), "Log in to reserve")
        self.client.force_login(self.user)
        self.assertContains(self.client.get(url), "Reserve this book")
        services.reserve_book(self.user, self.book.pk)
        self.assertContains(self.client.get(url), "You have reserved this book")