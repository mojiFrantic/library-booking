import django_filters

from reservations.models import Reservation


class StaffReservationFilter(django_filters.FilterSet):
    user = django_filters.CharFilter(field_name="user__username", lookup_expr="iexact")
    book = django_filters.CharFilter(field_name="book__title", lookup_expr="icontains")

    class Meta:
        model = Reservation
        fields = ["status"]