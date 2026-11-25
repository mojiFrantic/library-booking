from django.contrib import admin
from django.utils import timezone

from dashboard.activity import log_activity
from dashboard.models import ActivityLog

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("book", "user", "rating", "short_text", "is_hidden", "created_at")
    list_filter = ("is_hidden", "rating")
    search_fields = ("book__title", "user__username", "text")
    list_select_related = ("book", "user")
    actions = ["hide_selected", "unhide_selected"]

    def get_readonly_fields(self, request, obj=None):
        # Staff can only change the is_hidden flag
        return [f.name for f in self.model._meta.fields if f.name != "is_hidden"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Comment")
    def short_text(self, obj):
        return (obj.text[:60] + "…") if len(obj.text) > 60 else obj.text

    def save_model(self, request, obj, form, change):
        hidden_changed = "is_hidden" in form.changed_data
        if hidden_changed:
            obj.moderated_by = request.user
            obj.moderated_at = timezone.now()
        super().save_model(request, obj, form, change)
        if hidden_changed:
            action = (
                ActivityLog.Action.REVIEW_HIDDEN
                if obj.is_hidden
                else ActivityLog.Action.REVIEW_UNHIDDEN
            )
            log_activity(request.user, action, obj)

    def _set_hidden(self, request, queryset, hidden, action):
        count = 0
        for review in queryset.filter(is_hidden=not hidden).select_related(
            "book", "user"
        ):
            review.is_hidden = hidden
            review.moderated_by = request.user
            review.moderated_at = timezone.now()
            review.save(
                update_fields=["is_hidden", "moderated_by", "moderated_at", "updated_at"]
            )
            log_activity(request.user, action, review)
            count += 1
        return count

    @admin.action(description="Hide selected reviews", permissions=["change"])
    def hide_selected(self, request, queryset):
        count = self._set_hidden(request, queryset, True, ActivityLog.Action.REVIEW_HIDDEN)
        self.message_user(request, f"{count} review(s) hidden.")

    @admin.action(description="Unhide selected reviews", permissions=["change"])
    def unhide_selected(self, request, queryset):
        count = self._set_hidden(
            request, queryset, False, ActivityLog.Action.REVIEW_UNHIDDEN
        )
        self.message_user(request, f"{count} review(s) made visible again.")