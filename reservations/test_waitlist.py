from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from books.models import Book

from . import services, waitlist
from .models import WaitlistEntry

User = get_user_model()
Status = WaitlistEntry.Status


def make_user(name):
    return User.objects.create_user(
        name, email=f"{name}@example.com", password="pass12345"
    )


def make_book(title="Book", copies=1):
    return Book.objects.create(title=title, publication_year=2000, total_copies=copies)


def available(book):
    return Book.objects.with_availability().get(pk=book.pk).available_count


class QueueSetupMixin:
    """One-copy book reserved by `holder`; `second` and `third` wait in order."""

    def setUp(self):
        self.book = make_book()
        self.holder = make_user("holder")
        self.second = make_user("second")
        self.third = make_user("third")
        self.reservation = services.reserve_book(self.holder, self.book.pk)
        self.entry2 = waitlist.join_waitlist(self.second, self.book.pk)
        self.entry3 = waitlist.join_waitlist(self.third, self.book.pk)

    def refresh(self, *entries):
        for entry in entries:
            entry.refresh_from_db()


class WaitlistTests(QueueSetupMixin, TestCase):
    def test_cannot_join_when_copies_are_free(self):
        free_book = make_book("Free", copies=2)
        with self.assertRaises(services.ReservationError):
            waitlist.join_waitlist(self.holder, free_book.pk)

    def test_queue_positions(self):
        self.assertEqual(self.entry2.position(), 1)
        self.assertEqual(self.entry3.position(), 2)

    def test_cannot_join_twice(self):
        with self.assertRaises(services.ReservationError):
            waitlist.join_waitlist(self.second, self.book.pk)

    def test_user_with_an_active_reservation_cannot_join(self):
        with self.assertRaises(services.ReservationError):
            waitlist.join_waitlist(self.holder, self.book.pk)

    def test_cancel_offers_the_copy_to_the_first_in_line(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.cancel_reservation(self.reservation.pk, self.holder)
        self.refresh(self.entry2, self.entry3)
        self.assertEqual(self.entry2.status, Status.NOTIFIED)
        self.assertIsNotNone(self.entry2.claim_deadline)
        self.assertEqual(self.entry3.status, Status.WAITING)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["second@example.com"])

    def test_held_copy_is_unavailable_to_everyone_else(self):
        services.cancel_reservation(self.reservation.pk, self.holder)
        self.assertEqual(available(self.book), 0)
        with self.assertRaises(services.ReservationError):
            services.reserve_book(make_user("newcomer"), self.book.pk)

    def test_notified_user_can_reserve_the_held_copy(self):
        services.cancel_reservation(self.reservation.pk, self.holder)
        services.reserve_book(self.second, self.book.pk)
        self.refresh(self.entry2)
        self.assertEqual(self.entry2.status, Status.FULFILLED)
        self.assertEqual(available(self.book), 0)

    def test_expired_claim_passes_to_the_next_in_line(self):
        services.cancel_reservation(self.reservation.pk, self.holder)
        WaitlistEntry.objects.filter(pk=self.entry2.pk).update(
            claim_deadline=timezone.now() - timedelta(minutes=1)
        )
        with self.captureOnCommitCallbacks(execute=True):
            expired, promoted = waitlist.process_waitlist()
        self.assertEqual((expired, promoted), (1, 1))
        self.refresh(self.entry2, self.entry3)
        self.assertEqual(self.entry2.status, Status.EXPIRED)
        self.assertEqual(self.entry3.status, Status.NOTIFIED)

    def test_newcomer_cannot_take_a_copy_whose_claim_just_lapsed(self):
        services.cancel_reservation(self.reservation.pk, self.holder)
        WaitlistEntry.objects.filter(pk=self.entry2.pk).update(
            claim_deadline=timezone.now() - timedelta(minutes=1)
        )
        with self.assertRaises(services.ReservationError):
            services.reserve_book(make_user("newcomer"), self.book.pk)

    def test_leaving_with_a_held_copy_offers_it_to_the_next_person(self):
        services.cancel_reservation(self.reservation.pk, self.holder)
        with self.captureOnCommitCallbacks(execute=True):
            waitlist.leave_waitlist(self.entry2.pk, self.second)
        self.refresh(self.entry2, self.entry3)
        self.assertEqual(self.entry2.status, Status.CANCELLED)
        self.assertEqual(self.entry3.status, Status.NOTIFIED)

    def test_returning_a_book_offers_it_to_the_queue(self):
        services.check_out(self.reservation.pk)
        with self.captureOnCommitCallbacks(execute=True):
            services.check_in(self.reservation.pk)
        self.refresh(self.entry2)
        self.assertEqual(self.entry2.status, Status.NOTIFIED)

    def test_cannot_renew_while_someone_is_waiting(self):
        services.check_out(self.reservation.pk)
        with self.assertRaises(services.ReservationError):
            services.renew_reservation(self.reservation.pk, self.holder)


class WaitlistViewTests(QueueSetupMixin, TestCase):
    def test_join_requires_login(self):
        response = self.client.post(
            reverse("reservations:waitlist_join", args=[self.book.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.assertEqual(WaitlistEntry.objects.count(), 2)

    def test_join_view_adds_the_user_to_the_queue(self):
        newcomer = make_user("newcomer")
        self.client.force_login(newcomer)
        response = self.client.post(
            reverse("reservations:waitlist_join", args=[self.book.pk])
        )
        self.assertRedirects(response, self.book.get_absolute_url())
        self.assertTrue(WaitlistEntry.objects.open().filter(user=newcomer).exists())

    def test_detail_page_offers_the_waitlist_for_a_full_book(self):
        self.client.force_login(make_user("newcomer"))
        response = self.client.get(self.book.get_absolute_url())
        self.assertContains(response, "Join the waitlist")

    def test_detail_page_shows_the_position_in_line(self):
        self.client.force_login(self.second)
        response = self.client.get(self.book.get_absolute_url())
        self.assertContains(response, "You are number 1 in the waitlist")

    def test_detail_page_tells_the_notified_user_a_copy_is_held(self):
        services.cancel_reservation(self.reservation.pk, self.holder)
        self.client.force_login(self.second)
        response = self.client.get(self.book.get_absolute_url())
        self.assertContains(response, "A copy is being held for you")