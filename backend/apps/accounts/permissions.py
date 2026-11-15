"""
Role-based access control (D-006).

Rule of thumb used across the API:
  * every role can READ (GET/HEAD/OPTIONS) once logged in;
  * WRITES need one of the roles listed on the view.

A view picks who may write with ``write_roles`` (whole view) or
``action_roles = {"sign_off": {...}}`` (one specific action). If it says
nothing, only ADMIN and PLANNER may write. That makes "forgot to configure"
fail closed instead of open.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role

DEFAULT_WRITE_ROLES = frozenset({Role.ADMIN, Role.PLANNER})


class RoleBasedPermission(BasePermission):
    message = "Your role is not allowed to perform this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False

        action = getattr(view, "action", None)
        action_roles = getattr(view, "action_roles", {}) or {}
        if action in action_roles:
            return user.role in action_roles[action]

        if request.method in SAFE_METHODS:
            return True

        allowed = getattr(view, "write_roles", DEFAULT_WRITE_ROLES)
        return user.role in allowed


class IsAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.ADMIN)
