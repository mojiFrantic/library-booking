from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsLibraryStaff(BasePermission):
    """Staff, Admin and superusers only."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_library_staff)


class IsLibraryStaffOrReadOnly(BasePermission):
    """Anyone can read; only library staff can change data."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return IsLibraryStaff().has_permission(request, view)