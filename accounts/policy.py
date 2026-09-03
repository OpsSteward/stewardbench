from django.core.exceptions import PermissionDenied

from .models import User


def require_admin(actor):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Authentication is required.")
    if not actor.is_active or actor.role != User.Role.ADMIN:
        raise PermissionDenied("StewardBench ADMIN role is required.")
