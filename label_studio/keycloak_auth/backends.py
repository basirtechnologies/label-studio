"""Basir DW-908: Keycloak login and the local-login allow-list."""

import logging

from access_control.models import UserAccess
from access_control.services import set_user_access
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from keycloak_auth.claims import LoginRefused, ls_groups, ls_role, merge_claims
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from organizations.models import Organization, OrganizationMember
from users.models import User

logger = logging.getLogger(__name__)

USE_KEYCLOAK_MESSAGE = 'This account signs in with Keycloak: use “Log in with Keycloak”.'


def local_login_allowed(email) -> bool:
    """While OIDC is on, only allow-listed accounts may use the email/password form."""
    if not settings.OIDC_ENABLED:
        return True
    return bool(email) and email.strip().lower() in settings.LOCAL_LOGIN_ALLOWED_EMAILS


class LocalLoginAllowListBackend(BaseBackend):
    """Placed before ModelBackend: PermissionDenied stops Django from trying the next backends (also /admin/)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = username or kwargs.get(User.USERNAME_FIELD) or kwargs.get('email')
        if password is not None and email and not local_login_allowed(email):
            logger.info('Local login refused (not on LOCAL_LOGIN_ALLOWED_EMAILS): %s', email)
            raise PermissionDenied(USE_KEYCLOAK_MESSAGE)
        return None


def default_organization():
    if settings.BASIR_DEFAULT_ORGANIZATION_ID:
        org = Organization.objects.filter(id=settings.BASIR_DEFAULT_ORGANIZATION_ID).first()
        if org is None:
            raise LoginRefused('Label Studio is misconfigured (BASIR_DEFAULT_ORGANIZATION_ID). Contact an admin.')
        return org
    orgs = list(Organization.objects.order_by('id')[:2])
    if len(orgs) != 1:
        raise LoginRefused(
            'Label Studio is misconfigured (BASIR_DEFAULT_ORGANIZATION_ID is not set). Contact an admin.'
        )
    return orgs[0]


class KeycloakOIDCBackend(OIDCAuthenticationBackend):
    """Authorization Code flow against Keycloak (realm data_service).

    Users are matched by the Keycloak subject (``sub``), never by email: an existing local account with the same
    email is not taken over (those are linked by hand). Role, groups and names are copied on every login.
    """

    def authenticate(self, request, **kwargs):
        if not settings.OIDC_ENABLED:
            return None
        try:
            return super().authenticate(request, **kwargs)
        except LoginRefused as e:
            logger.warning('Keycloak login refused: %s', e)
            if request is not None:
                messages.error(request, str(e))
            return None

    def get_or_create_user(self, access_token, id_token, payload):
        userinfo = self.get_userinfo(access_token, id_token, payload)
        claims = merge_claims(access_token, payload, userinfo)
        return self.user_from_claims(claims)

    @transaction.atomic
    def user_from_claims(self, claims):
        sub = claims.get('sub')
        if not sub:
            raise LoginRefused('Keycloak did not send a user ID (sub).')
        role = ls_role(claims)
        if role is None:
            raise LoginRefused(
                f'Your Keycloak account has no Label Studio role ({settings.OIDC_ROLE_ADMIN} or '
                f'{settings.OIDC_ROLE_LABELER}). Ask an admin for access.'
            )
        groups = ls_groups(claims)
        email = (claims.get('email') or '').strip().lower()

        record = UserAccess.objects.select_related('user').filter(keycloak_sub=sub).first()
        org = default_organization()
        if record is not None:
            user = record.user
            if not user.is_active:
                raise LoginRefused('Your Label Studio account is deactivated. Contact an admin.')
        else:
            if not email:
                raise LoginRefused('Your Keycloak account has no email address. Ask an admin to add one.')
            if User.objects.filter(email__iexact=email).exists():
                raise LoginRefused(
                    f'A Label Studio account with the email {email} already exists and is not linked to Keycloak. '
                    'Ask an admin to link it.'
                )
            user = User.objects.create_user(email=email, username=self._username(claims, email))
            user.set_unusable_password()
            user.save(update_fields=['password'])
            logger.info('Created Label Studio user %s for Keycloak subject %s', user.id, sub)

        membership = OrganizationMember.objects.filter(user=user, organization=org).first()
        if membership is not None and membership.deleted_at is not None:
            raise LoginRefused('You were removed from the Label Studio organization. Contact an admin.')
        if membership is None:
            OrganizationMember.objects.create(user=user, organization=org)

        changed = []
        for field, claim in (('first_name', 'given_name'), ('last_name', 'family_name')):
            value = (claims.get(claim) or '')[: User._meta.get_field(field).max_length]
            if claim in claims and getattr(user, field) != value:
                setattr(user, field, value)
                changed.append(field)
        if user.active_organization_id != org.id:
            user.active_organization = org
            changed.append('active_organization')
        if changed:
            user.save(update_fields=changed)

        try:
            set_user_access(user, role=role, groups=groups, keycloak_sub=sub)
        except ValidationError as e:
            raise LoginRefused(f'Keycloak sent an invalid group name: {"; ".join(e.messages)}')
        return user

    @staticmethod
    def _username(claims, email):
        name = (claims.get('preferred_username') or email.split('@')[0])[: User._meta.get_field('username').max_length]
        return name
