from django.contrib.auth.models import AbstractUser
from django.db import models


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

    def __str__(self):
        return self.username