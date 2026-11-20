from django.test import TestCase
from django.urls import reverse
from .models import User
from django.core.management import call_command
from django.contrib.auth.models import Group
from .constants import STAFF_GROUP_NAME


class AuthTests(TestCase):
    def test_register_creates_customer_even_if_role_is_posted(self):
        data = {
            "username": "ali",
            "email": "ali@example.com",
            "phone": "",
            "password1": "S3cretPass!xy",
            "password2": "S3cretPass!xy",
            "captcha_0": "x",
            "captcha_1": "passed",
            "role": "admin",  # attempt to escalate privileges
        }
        response = self.client.post(reverse("accounts:register"), data)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="ali")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_staff)

    def test_staff_role_sets_is_staff(self):
        user = User.objects.create_user("sara", password="x", role=User.Role.STAFF)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_library_staff)

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)

class StaffGroupTests(TestCase):
    def setUp(self):
        call_command("setup_roles")

    def test_staff_user_joins_group_and_gets_book_permissions(self):
        user = User.objects.create_user("sara", password="x", role=User.Role.STAFF)
        self.assertTrue(user.groups.filter(name=STAFF_GROUP_NAME).exists())
        self.assertTrue(user.has_perm("books.add_book"))
        self.assertTrue(user.has_perm("books.change_book"))
        self.assertFalse(user.has_perm("books.delete_book"))

    def test_customer_is_not_in_staff_group(self):
        user = User.objects.create_user("omid", password="x")
        self.assertFalse(user.groups.filter(name=STAFF_GROUP_NAME).exists())
        self.assertFalse(user.has_perm("books.add_book"))