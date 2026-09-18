"""API key authentication and the audit trail that goes with it.

The console produces material that accuses ships of pollution. Before this, anyone
who could reach the port could upload evidence into the case file and read every
case in the system. For a tool whose output is meant to be evidentiary, "who
submitted this scene" is not an optional field.

Deliberately an API key rather than user accounts: a coastal authority integrating
this will call it from a ground-segment pipeline, not a browser login form. Keys are
per-caller so the manifest can record WHICH caller ran an analysis, which is the part
that matters for chain of custody.

The key is compared with `secrets.compare_digest` and only its digest is ever stored
in the manifest, so a leaked dossier does not leak the key that produced it.
"""
import hashlib
import secrets

from django.conf import settings
from rest_framework import authentication, exceptions

HEADER = 'HTTP_X_API_KEY'
BEARER_PREFIX = 'Bearer '


def configured_keys() -> dict:
    """{label: key} from settings. Empty means authentication is not configured."""
    return dict(getattr(settings, 'API_KEYS', {}) or {})


def key_label(presented: str):
    """Return the label for a presented key, or None.

    Constant-time comparison against every configured key: a short-circuit on the
    first differing byte would leak key material through timing.
    """
    if not presented:
        return None
    match = None
    for label, key in configured_keys().items():
        if secrets.compare_digest(str(presented), str(key)):
            match = label
    return match


def key_fingerprint(presented: str) -> str:
    """Short digest of a key, safe to record in a manifest."""
    if not presented:
        return 'anonymous'
    return hashlib.sha256(str(presented).encode()).hexdigest()[:16]


def extract_key(request) -> str:
    """Read the key from X-API-Key, or from an Authorization: Bearer header."""
    presented = request.META.get(HEADER, '')
    if presented:
        return presented
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith(BEARER_PREFIX):
        return auth_header[len(BEARER_PREFIX):]
    return ''


class APIKeyUser:
    """A minimal authenticated principal. Not a Django user; nothing here has a profile."""

    is_authenticated = True

    def __init__(self, label, fingerprint):
        self.label = label
        self.fingerprint = fingerprint

    def __str__(self):
        return f'api-key:{self.label}'


class APIKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate a caller by API key.

    When no keys are configured the request is allowed through as anonymous, and
    `IsAuthenticatedOrUnconfigured` is what decides whether that is acceptable. The
    two are split so that an unconfigured deployment fails loudly at the permission
    layer rather than silently authenticating everyone here.
    """

    def authenticate(self, request):
        presented = extract_key(request)
        if not presented:
            return None

        label = key_label(presented)
        if label is None:
            raise exceptions.AuthenticationFailed('Invalid API key.')

        return (APIKeyUser(label, key_fingerprint(presented)), presented)

    def authenticate_header(self, request):
        return 'X-API-Key'
