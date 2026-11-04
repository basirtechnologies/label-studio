"""Basir DW-908: email/password sessions of accounts outside LOCAL_LOGIN_ALLOWED_EMAILS end once OIDC is on."""

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import BACKEND_SESSION_KEY
from keycloak_auth.backends import local_login_allowed

KEYCLOAK_BACKEND = 'keycloak_auth.backends.KeycloakOIDCBackend'


class LocalSessionAllowListMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.OIDC_ENABLED:
            user = getattr(request, 'user', None)
            session = getattr(request, 'session', None)
            if (
                user is not None
                and user.is_authenticated
                and session is not None
                and session.get(BACKEND_SESSION_KEY)  # session logins only, API tokens are not affected
                and session.get(BACKEND_SESSION_KEY) != KEYCLOAK_BACKEND
                and not local_login_allowed(user.email)
            ):
                auth.logout(request)
        return self.get_response(request)
