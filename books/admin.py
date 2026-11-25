from django.contrib import admin

from dashboard.activity import log_activity
from dashboard.models import ActivityLog

from .models import Author, Book, Genre


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "publication_year",
        "total_copies",
        "available_copies",
        "is_deleted",
    )
    list_filter = ("is_deleted", "genres", "publication_year")
    search_fields = ("title", "isbn", "authors__name")
    filter_horizontal = ("authors", "genres")
    readonly_fields = ("is_deleted", "deleted_at", "created_at", "updated_at")
    actions = ["soft_delete_selected", "restore_selected"]

    def has_delete_permission(self, request, obj=None):
        # Only superusers can permanently delete. Staff use soft delete.
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            log_activity(request.user, ActivityLog.Action.BOOK_CREATED, obj)
        elif form.changed_data:
            log_activity(
                request.user,
                ActivityLog.Action.BOOK_UPDATED,
                obj,
                details="Changed: " + ", ".join(form.changed_data),
            )

    def delete_model(self, request, obj):
        log_activity(request.user, ActivityLog.Action.BOOK_PURGED, obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for book in queryset:
            log_activity(request.user, ActivityLog.Action.BOOK_PURGED, book)
        super().delete_queryset(request, queryset)

    @admin.action(description="Soft delete selected books", permissions=["change"])
    def soft_delete_selected(self, request, queryset):
        count = 0
        for book in queryset.filter(is_deleted=False):
            book.soft_delete()
            log_activity(request.user, ActivityLog.Action.BOOK_SOFT_DELETED, book)
            count += 1
        self.message_user(request, f"{count} book(s) soft deleted.")

    @admin.action(description="Restore selected books", permissions=["change"])
    def restore_selected(self, request, queryset):
        count = 0
        for book in queryset.filter(is_deleted=True):
            book.restore()
            log_activity(request.user, ActivityLog.Action.BOOK_RESTORED, book)
            count += 1
        self.message_user(request, f"{count} book(s) restored.")