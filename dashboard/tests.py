
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from books.models import Book
from reservations import services
from reservations.models import Fine, Reservation
from reviews.models import Review

from .activity import log_activity
from .models import ActivityLog

User = get_user_model()
Action = ActivityLog.Action


def make_user(name, role=User.Role.CUSTOMER):
    return User.objects.create_user(
        name, email=f"{name}@example.com", password="pass12345", role=role
    )


def make_book(title="Book", copies=2):
    return Book.objects.create(title=title, publication_year=2000, total_copies=copies)


def make_overdue_loan(user, book, days_late=3):
    reservation = services.reserve_book(user, book.pk)
    services.check_out(reservation.pk)
    Reservation.objects.filter(pk=reservation.pk).update(
        due_date=timezone.localdate() - timedelta(days=days_late)
    )
    return reservation


class DashboardAccessTests(TestCase):
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_customer_gets_403(self):
        self.client.force_login(make_user("reader"))
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:activity")).status_code, 403)

    def test_staff_and_admin_roles_can_open_it(self):
        for role in (User.Role.STAFF, User.Role.ADMIN):
            self.client.force_login(make_user(f"user_{role}", role=role))
            self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)


@override_settings(
    FINE_CURRENCY="$",
    FINE_PER_DAY=Decimal("1.00"),
    FINE_MAX_PER_LOAN=Decimal("30.00"),
)
class DashboardContentTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("boss", role=User.Role.STAFF))
        c1, c2, c3 = make_user("c1"), make_user("c2"), make_user("c3")
        make_overdue_loan(c1, make_book("Overdue Book"), days_late=3)
        services.reserve_book(c2, make_book("Pending Book").pk)
        on_time = services.reserve_book(c3, make_book("On Time Book").pk)
        services.check_out(on_time.pk)
        self.response = self.client.get(reverse("dashboard:home"))

    def test_counts(self):
        stats = self.response.context["stats"]
        self.assertEqual(stats["on_loan"], 2)
        self.assertEqual(stats["overdue"], 1)
        self.assertEqual(stats["pending_pickups"], 1)

    def test_books_appear_in_the_tables(self):
        for title in ("Overdue Book", "Pending Book", "On Time Book"):
            self.assertContains(self.response, title)

    def test_overdue_loan_shows_the_growing_fine(self):
        self.assertContains(self.response, "$3.00")

    def test_daily_series_covers_14_days(self):
        series = self.response.context["daily_reservations"]
        self.assertEqual(len(series), 14)
        self.assertEqual(series[-1]["day"], timezone.localdate())
        self.assertEqual(series[-1]["count"], 3)

    def test_most_borrowed_book_comes_first(self):
        popular = make_book("Popular", copies=3)
        for name in ("p1", "p2"):
            reservation = services.reserve_book(make_user(name), popular.pk)
            services.check_out(reservation.pk)
        response = self.client.get(reverse("dashboard:home"))
        top = response.context["popular_books"][0]
        self.assertEqual(top.title, "Popular")
        self.assertEqual(top.borrow_count, 2)


class StaffActionTests(TestCase):
    def setUp(self):
        self.staff = make_user("boss", role=User.Role.STAFF)
        self.customer = make_user("reader")
        self.book = make_book("Some Book")
        self.reservation = services.reserve_book(self.customer, self.book.pk)

    def test_staff_can_check_out_and_it_is_logged(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("dashboard:check_out", args=[self.reservation.pk])
        )
        self.assertRedirects(response, reverse("dashboard:home"))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.CHECKED_OUT)
        entry = ActivityLog.objects.get(action=Action.CHECKED_OUT)
        self.assertEqual(entry.actor, self.staff)

    def test_customer_cannot_check_out(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("dashboard:check_out", args=[self.reservation.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, Reservation.Status.PENDING)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("dashboard:check_out", args=[self.reservation.pk])
        )
        self.assertEqual(response.status_code, 405)

    @override_settings(
        FINE_PER_DAY=Decimal("1.00"), FINE_MAX_PER_LOAN=Decimal("30.00")
    )
    def test_late_return_records_a_fine_and_logs_it(self):
        services.check_out(self.reservation.pk)
        Reservation.objects.filter(pk=self.reservation.pk).update(
            due_date=timezone.localdate() - timedelta(days=2)
        )
        self.client.force_login(self.staff)
        self.client.post(reverse("dashboard:check_in", args=[self.reservation.pk]))
        self.assertTrue(Fine.objects.filter(reservation=self.reservation).exists())
        entry = ActivityLog.objects.get(action=Action.RETURNED)
        self.assertIn("fine", entry.details.lower())
        self.assertEqual(entry.actor, self.staff)


class ActivityLogPageTests(TestCase):
    def setUp(self):
        self.staff = make_user("boss", role=User.Role.STAFF)
        self.client.force_login(self.staff)

    def test_page_lists_entries_and_filters_by_action(self):
        log_activity(self.staff, Action.BOOK_CREATED, make_book("Alpha Title"))
        log_activity(self.staff, Action.BOOK_RESTORED, make_book("Beta Title"))
        url = reverse("dashboard:activity")

        response = self.client.get(url)
        self.assertContains(response, "Alpha Title")
        self.assertContains(response, "Beta Title")

        response = self.client.get(url, {"action": Action.BOOK_RESTORED})
        self.assertContains(response, "Beta Title")
        self.assertNotContains(response, "Alpha Title")

    def test_unknown_action_filter_is_ignored(self):
        log_activity(self.staff, Action.BOOK_CREATED, make_book("Alpha Title"))
        response = self.client.get(reverse("dashboard:activity"), {"action": "nope"})
        self.assertContains(response, "Alpha Title")


class AdminLoggingTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser("root", password="pass12345")
        self.client.force_login(self.boss)

    def test_soft_delete_action_is_logged(self):
        book = make_book("Doomed")
        self.client.post(
            reverse("admin:books_book_changelist"),
            {"action": "soft_delete_selected", "_selected_action": [book.pk]},
        )
        book.refresh_from_db()
        self.assertTrue(book.is_deleted)
        entry = ActivityLog.objects.get(action=Action.BOOK_SOFT_DELETED)
        self.assertEqual(entry.actor, self.boss)

    def test_restore_action_is_logged(self):
        book = make_book("Back again")
        book.soft_delete()
        self.client.post(
            reverse("admin:books_book_changelist"),
            {"action": "restore_selected", "_selected_action": [book.pk]},
        )
        self.assertTrue(ActivityLog.objects.filter(action=Action.BOOK_RESTORED).exists())

    def test_hide_review_action_is_logged(self):
        review = Review.objects.create(
            user=make_user("rev"), book=make_book(), rating=1, text="Rude"
        )
        self.client.post(
            reverse("admin:reviews_review_changelist"),
            {"action": "hide_selected", "_selected_action": [review.pk]},
        )
        review.refresh_from_db()
        self.assertTrue(review.is_hidden)
        self.assertTrue(ActivityLog.objects.filter(action=Action.REVIEW_HIDDEN).exists())

    def test_fine_paid_action_is_logged(self):
        loan = make_overdue_loan(make_user("late"), make_book(), days_late=2)
        services.check_in(loan.pk)
        fine = Fine.objects.get()
        self.client.post(
            reverse("admin:reservations_fine_changelist"),
            {"action": "mark_paid", "_selected_action": [fine.pk]},
        )
        fine.refresh_from_db()
        self.assertEqual(fine.status, Fine.Status.PAID)
        entry = ActivityLog.objects.get(action=Action.FINE_PAID)
        self.assertEqual(entry.actor, self.boss)