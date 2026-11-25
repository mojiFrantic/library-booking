from django.contrib import admin, messages
from django.utils import timezone

from . import services
from .models import Fine, Reservation, WaitlistEntry


def _all_field_names(model):
    return [field.name for field in model._meta.fields]


class OverdueFilter(admin.SimpleListFilter):
    title = "overdue"
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return [("yes", "Overdue loans")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                status=Reservation.Status.CHECKED_OUT,
                due_date__lt=timezone.localdate(),
            )
        return queryset


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "user",
        "status",
        "reserved_at",
        "pickup_deadline",
        "due_date",
        "overdue",
    )
    list_filter = ("status", OverdueFilter)
    search_fields = ("book__title", "user__username", "user__email")
    list_select_related = ("book", "user")
    actions = ["mark_checked_out", "mark_returned"]

    def get_readonly_fields(self, request, obj=None):
        return _all_field_names(self.model)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Reservation history is never deleted
        return False

    @admin.display(boolean=True, description="Overdue")
    def overdue(self, obj):
        return obj.is_overdue

    def _run(self, request, queryset, service, success_text):
        done = 0
        for reservation in queryset:
            try:
                service(reservation.pk)
                done += 1
            except services.ReservationError as exc:
                self.message_user(
                    request, f"{reservation}: {exc}", level=messages.WARNING
                )
        if done:
            self.message_user(request, f"{done} reservation(s) {success_text}.")

    @admin.action(
        description="Mark selected as checked out (picked up)",
        permissions=["change"],
    )
    def mark_checked_out(self, request, queryset):
        self._run(request, queryset, services.check_out, "checked out")

    @admin.action(
        description="Mark selected as returned",
        permissions=["change"],
    )
    def mark_returned(self, request, queryset):
        self._run(request, queryset, services.check_in, "marked as returned")


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("book", "user", "status", "created_at", "claim_deadline")
    list_filter = ("status",)
    search_fields = ("book__title", "user__username", "user__email")
    list_select_related = ("book", "user")

    def get_readonly_fields(self, request, obj=None):
        return _all_field_names(self.model)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Fine)
class FineAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "book_title",
        "days_overdue",
        "amount",
        "status",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "reservation__book__title")
    list_select_related = ("user", "reservation__book")
    actions = ["mark_paid", "waive_selected"]

    def get_readonly_fields(self, request, obj=None):
        return _all_field_names(self.model)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Book")
    def book_title(self, obj):
        return obj.reservation.book.title

    def _settle(self, request, queryset, status, text):
        updated = queryset.filter(status=Fine.Status.UNPAID).update(
            status=status,
            settled_at=timezone.now(),
            settled_by=request.user,
        )
        self.message_user(request, f"{updated} fine(s) {text}.")

    @admin.action(description="Mark selected fines as paid", permissions=["change"])
    def mark_paid(self, request, queryset):
        self._settle(request, queryset, Fine.Status.PAID, "marked as paid")

    @admin.action(description="Waive selected fines", permissions=["change"])
    def waive_selected(self, request, queryset):
        self._settle(request, queryset, Fine.Status.WAIVED, "waived")