"""Basir DW-908: the email/password form refuses accounts outside LOCAL_LOGIN_ALLOWED_EMAILS while OIDC is on."""

from django import forms
from keycloak_auth.backends import USE_KEYCLOAK_MESSAGE, local_login_allowed
from users.forms import LoginForm as UpstreamLoginForm


class LoginForm(UpstreamLoginForm):
    def clean(self, *args, **kwargs):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and not local_login_allowed(email):
            raise forms.ValidationError(USE_KEYCLOAK_MESSAGE)
        return super().clean(*args, **kwargs)
