from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from accounts.constants import STAFF_GROUP_NAME
from accounts.models import User

# (app_label, model, actions). Staff cannot hard-delete books.
# Rerun this command whenever new permissions are added in later phases.
STAFF_PERMISSIONS = [
    ("books", "author", ("add", "change", "view")),
    ("books", "genre", ("add", "change", "view")),
    ("books", "book", ("add", "change", "view")),
    ("reservations", "reservation", ("change", "view")),
    ("reviews", "review", ("change", "view")),
]

class Command(BaseCommand):
    help = "Create the 'Library staff' group, assign permissions and sync members."

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name=STAFF_GROUP_NAME)

        permissions = []
        for app_label, model, actions in STAFF_PERMISSIONS:
            for action in actions:
                permissions.append(
                    Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=f"{action}_{model}",
                    )
                )
        group.permissions.set(permissions)

        staff_users = User.objects.filter(
            role__in=[User.Role.STAFF, User.Role.ADMIN]
        )
        group.user_set.add(*staff_users)

        self.stdout.write(
            self.style.SUCCESS(
                f"Group '{STAFF_GROUP_NAME}' ready: "
                f"{len(permissions)} permissions, {staff_users.count()} users."
            )
        )