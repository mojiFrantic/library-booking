from .models import ActivityLog


def log_activity(actor, action, obj, details=""):
    """Record something a staff member did to `obj`."""
    ActivityLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=obj._meta.model_name,
        object_id=obj.pk,
        object_repr=str(obj)[:255],
        details=details,
    )