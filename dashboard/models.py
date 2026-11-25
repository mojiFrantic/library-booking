from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    class Action(models.TextChoices):
        BOOK_CREATED = "book_created", "Book created"
        BOOK_UPDATED = "book_updated", "Book updated"
        BOOK_SOFT_DELETED = "book_soft_deleted", "Book soft deleted"
        BOOK_RESTORED = "book_restored", "Book restored"
        BOOK_PURGED = "book_purged", "Book permanently deleted"
        CHECKED_OUT = "checked_out", "Book checked out"
        RETURNED = "returned", "Book returned"
        FINE_PAID = "fine_paid", "Fine marked as paid"
        FINE_WAIVED = "fine_waived", "Fine waived"
        REVIEW_HIDDEN = "review_hidden", "Review hidden"
        REVIEW_UNHIDDEN = "review_unhidden", "Review made visible"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    action = models.CharField(max_length=30, choices=Action.choices, db_index=True)
    object_type = models.CharField(max_length=30)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    # A text snapshot, so the entry stays readable even if the object is deleted
    object_repr = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()}: {self.object_repr}"