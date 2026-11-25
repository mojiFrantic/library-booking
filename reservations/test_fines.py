from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from books.models import Book

from . import fines, services
from .models import Fine, Reservation

User = get_user_model()


def make_user(name):
    return User.objects.create_user(
        name, email=f"{name}@example.com", password="pass12345"
    )


def make_book(title="Book", copies=2):
    return Book.objects.create(title=title, publication_year=2000, total_copies=copies)


@override_settings(FINE_PER_DAY=Decimal("2.00"), FINE_MAX_PER_LOAN=Decimal("30.00"))
class FineTests(TestCase):
    def setUp(self):
        self.user = make_user("ali")

    def late_loan(self, book, days_late):
        reservation = services.reserve_book(self.user, book.pk)
        services.check_out(reservation.pk)
        Reservation.objects.filter(pk=reservation.pk).update(
            due_date=timezone.localdate() - timedelta(days=days_late)
        )
        return reservation

    def test_late_return_creates_a_fine(self):
        loan = self.late_loan(make_book("A"), 3)
        services.check_in(loan.pk)
        fine = Fine.objects.get()
        self.assertEqual(fine.user, self.user)
        self.assertEqual(fine.days_overdue, 3)
        self.assertEqual(fine.amount, Decimal("6.00"))
        self.assertEqual(fine.status, Fine.Status.UNPAID)

    def test_fine_is_capped_per_loan(self):
        loan = self.late_loan(make_book("A"), 100)
        services.check_in(loan.pk)
        self.assertEqual(Fine.objects.get().amount, Decimal("30.00"))

    def test_on_time_return_creates_no_fine(self):
        reservation = services.reserve_book(self.user, make_book("A").pk)
        services.check_out(reservation.pk)
        services.check_in(reservation.pk)
        self.assertEqual(Fine.objects.count(), 0)

    def test_overdue_loan_blocks_new_reservations(self):
        self.late_loan(make_book("A"), 2)
        with self.assertRaises(services.ReservationError):
            services.reserve_book(self.user, make_book("B").pk)

    def test_unpaid_fine_blocks_reservations_until_paid(self):
        loan = self.late_loan(make_book("A"), 2)
        services.check_in(loan.pk)
        other = make_book("B")
        with self.assertRaises(services.ReservationError):
            services.reserve_book(self.user, other.pk)
        Fine.objects.update(status=Fine.Status.PAID)
        services.reserve_book(self.user, other.pk)

    def test_summary_for_a_growing_fine(self):
        self.late_loan(make_book("A"), 2)
        summary = fines.fine_summary(self.user)
        self.assertEqual(summary.accrued_total, Decimal("4.00"))
        self.assertEqual(summary.unpaid_total, Decimal("0"))
        self.assertEqual(summary.overdue_count, 1)
        self.assertTrue(summary.is_blocked)

    def test_user_without_loans_is_not_blocked(self):
        self.assertFalse(fines.fine_summary(self.user).is_blocked)

    def test_my_reservations_page_warns_about_fines(self):
        loan = self.late_loan(make_book("A"), 2)
        services.check_in(loan.pk)
        self.client.force_login(self.user)
        response = self.client.get(reverse("reservations:mine"))
        self.assertContains(response, "outstanding late fees")

    def test_staff_can_mark_a_fine_as_paid_in_admin(self):
        loan = self.late_loan(make_book("A"), 2)
        services.check_in(loan.pk)
        fine = Fine.objects.get()
        boss = User.objects.create_superuser("boss", password="pass12345")
        self.client.force_login(boss)
        self.client.post(
            reverse("admin:reservations_fine_changelist"),
            {"action": "mark_paid", "_selected_action": [fine.pk]},
        )
        fine.refresh_from_db()
        self.assertEqual(fine.status, Fine.Status.PAID)
        self.assertEqual(fine.settled_by, boss)