from django.contrib import admin, messages
from django.utils import timezone

from . import services
from .models import Reservation


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
        return [field.name for field in self.model._meta.fields]

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