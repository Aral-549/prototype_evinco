"""Permission policy for the forensic API."""
from django.conf import settings
from rest_framework import permissions

from .authentication import configured_keys


class IsAuthenticatedOrUnconfigured(permissions.BasePermission):
    """Require an API key whenever authentication is switched on.

    `REQUIRE_API_KEY` defaults to True. If it is on but no keys are configured, every
    request is refused with an actionable message rather than being waved through --
    a misconfiguration that silently disables authentication is the failure mode worth
    designing against, because it looks identical to working software.
    """

    message = 'A valid API key is required. Send it as the X-API-Key header.'

    def has_permission(self, request, view):
        if not getattr(settings, 'REQUIRE_API_KEY', True):
            return True

        if not configured_keys():
            self.message = (
                'This deployment requires an API key but none is configured. Set '
                'MARSLICK_API_KEYS (comma-separated label:key pairs), or set '
                'REQUIRE_API_KEY=false for an unauthenticated local demo.'
            )
            return False

        return bool(request.user and getattr(request.user, 'is_authenticated', False))
