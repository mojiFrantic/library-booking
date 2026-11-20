from django.contrib.auth.mixins import UserPassesTestMixin


class StaffRequiredMixin(UserPassesTestMixin):
    """Allow only library staff (Staff, Admin, superuser)."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_library_staff