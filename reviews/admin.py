from django.contrib import admin
from django.utils import timezone

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
        if "is_hidden" in form.changed_data:
            obj.moderated_by = request.user
            obj.moderated_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="Hide selected reviews", permissions=["change"])
    def hide_selected(self, request, queryset):
        updated = queryset.filter(is_hidden=False).update(
            is_hidden=True, moderated_by=request.user, moderated_at=timezone.now()
        )
        self.message_user(request, f"{updated} review(s) hidden.")

    @admin.action(description="Unhide selected reviews", permissions=["change"])
    def unhide_selected(self, request, queryset):
        updated = queryset.filter(is_hidden=True).update(
            is_hidden=False, moderated_by=request.user, moderated_at=timezone.now()
        )
        self.message_user(request, f"{updated} review(s) made visible again.")