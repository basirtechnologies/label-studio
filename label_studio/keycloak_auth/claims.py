"""Basir DW-908: what Label Studio takes from a Keycloak login (roles, groups, names)."""

from typing import Optional

import jwt
from django.conf import settings


class LoginRefused(Exception):
    """A Keycloak login Label Studio does not accept; the message is shown on the login page."""


def decode_unverified(token: Optional[str]) -> dict:
    """Claims of a token received directly from Keycloak's token endpoint (server to server, client secret)."""
    if not token:
        return {}
    try:
        return jwt.decode(token, options={'verify_signature': False})
    except jwt.PyJWTError:
        return {}


def merge_claims(access_token: Optional[str], id_token_payload: dict, userinfo: dict) -> dict:
    """userinfo wins over the (verified) ID token, which wins over the access token.

    Keycloak puts realm roles in the access token (``realm_access.roles``) by default; the "groups" mapper can add
    ``groups`` to any of the three. Lists of roles and groups are joined, not replaced.
    """
    sources = [decode_unverified(access_token), id_token_payload or {}, userinfo or {}]
    claims = {}
    for source in sources:
        claims.update(source)
    claims['_roles'] = sorted({role for source in sources for role in _roles_of(source)})
    claims['_groups'] = sorted({group for source in sources for group in (source.get('groups') or [])})
    return claims


def _roles_of(source: dict) -> list:
    roles = list((source.get('realm_access') or {}).get('roles') or [])
    top_level = source.get('roles')
    if isinstance(top_level, list):
        roles.extend(top_level)
    return [role for role in roles if isinstance(role, str)]


def ls_role(claims: dict) -> Optional[str]:
    """'admin', 'labeler' or None, from the realm roles (admin wins when the user has both)."""
    roles = set(claims.get('_roles') or [])
    if settings.OIDC_ROLE_ADMIN in roles:
        return 'admin'
    if settings.OIDC_ROLE_LABELER in roles:
        return 'labeler'
    return None


def ls_groups(claims: dict) -> list:
    """Keycloak groups starting with the prefix; paths like "/ls-sightence-male" become "ls-sightence-male"."""
    prefix = settings.OIDC_GROUP_PREFIX
    names = set()
    for group in claims.get('_groups') or []:
        if not isinstance(group, str):
            continue
        name = group.rstrip('/').rsplit('/', 1)[-1]
        if name.startswith(prefix):
            names.add(name)
    return sorted(names)
