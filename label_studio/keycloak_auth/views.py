"""Basir DW-908: "Log in with Keycloak" (start and callback of the Authorization Code flow) and logout."""

import time
from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404
from django.urls import reverse
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView, OIDCAuthenticationRequestView


class _EnabledOnly:
    def dispatch(self, request, *args, **kwargs):
        if not settings.OIDC_ENABLED:
            raise Http404('Keycloak login is not enabled')
        return super().dispatch(request, *args, **kwargs)


class KeycloakLoginView(_EnabledOnly, OIDCAuthenticationRequestView):
    """Redirects the browser to Keycloak's login page (OIDC_OP_BASE_URL)."""


class KeycloakCallbackView(_EnabledOnly, OIDCAuthenticationCallbackView):
    """Keycloak redirects here; the token, userinfo and JWKS calls go to OIDC_OP_INTERNAL_BASE_URL."""

    def login_success(self):
        response = super().login_success()
        # what Label Studio's own login stores (InactivitySessionTimeoutMiddleWare logs out sessions without it)
        self.request.session['last_login'] = time.time()
        return response


def keycloak_logout_url(request):
    """Keycloak's end-session URL for a session that logged in with Keycloak, else None (call before logout)."""
    if not settings.OIDC_ENABLED:
        return None
    id_token = request.session.get('oidc_id_token')
    if not id_token:
        return None
    params = {
        'client_id': settings.OIDC_RP_CLIENT_ID,
        'id_token_hint': id_token,
        'post_logout_redirect_uri': request.build_absolute_uri(reverse('user-login')),
    }
    return f'{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(params)}'
