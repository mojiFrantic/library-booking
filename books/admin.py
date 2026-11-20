from django.contrib import admin
from django.utils import timezone

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
    readonly_fields = ("deleted_at", "created_at", "updated_at")
    actions = ["soft_delete_selected", "restore_selected"]

    def has_delete_permission(self, request, obj=None):
        # Only superusers can permanently delete. Staff use soft delete.
        return request.user.is_superuser

    @admin.action(description="Soft delete selected books", permissions=["change"])
    def soft_delete_selected(self, request, queryset):
        updated = queryset.update(is_deleted=True, deleted_at=timezone.now())
        self.message_user(request, f"{updated} book(s) soft deleted.")

    @admin.action(description="Restore selected books", permissions=["change"])
    def restore_selected(self, request, queryset):
        updated = queryset.update(is_deleted=False, deleted_at=None)
        self.message_user(request, f"{updated} book(s) restored.")