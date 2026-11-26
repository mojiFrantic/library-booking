from rest_framework import status
from rest_framework.exceptions import APIException

from reservations.errors import ReservationError


class BusinessRuleError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request breaks a library rule."
    default_code = "rule_violation"


def run_service(func, *args, **kwargs):
    """Call a reservation service; a broken business rule becomes a 400."""
    try:
        return func(*args, **kwargs)
    except ReservationError as exc:
        raise BusinessRuleError(str(exc)) from None