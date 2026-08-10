from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import User


def verification_required(view_func):
    """Redirect unverified/pending/rejected users to the pending-verification page.

    Roles above 'unverified' are only ever reached via admin approval (see
    users/signals.py), so checking role here is equivalent to checking
    verification_status but matches what permission checks elsewhere key off.
    """

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.role == User.Role.UNVERIFIED:
            return redirect('users:pending_verification')
        return view_func(request, *args, **kwargs)

    return wrapper


def role_required(*roles):
    """Restrict a view to specific User.Role values. Superusers always pass."""

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser or request.user.role in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return wrapper

    return decorator
