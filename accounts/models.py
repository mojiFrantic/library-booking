from django.contrib.auth.models import AbstractUser, Group
from django.db import models

from .constants import STAFF_GROUP_NAME


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STAFF = "staff", "Staff"
        ADMIN = "admin", "Admin"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    phone = models.CharField(max_length=15, blank=True)

    @property
    def is_library_staff(self):
        return self.is_superuser or self.role in (self.Role.STAFF, self.Role.ADMIN)

    def save(self, *args, **kwargs):
        # Staff and Admin roles can enter the admin panel
        if not self.is_superuser:
            self.is_staff = self.role in (self.Role.STAFF, self.Role.ADMIN)
        super().save(*args, **kwargs)
        self._sync_staff_group()

    def _sync_staff_group(self):
        group = Group.objects.filter(name=STAFF_GROUP_NAME).first()
        if group is None:
            return
        if self.role in (self.Role.STAFF, self.Role.ADMIN):
            self.groups.add(group)
        else:
            self.groups.remove(group)

    def __str__(self):
        return self.username