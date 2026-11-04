"""Basir DW-907: change access groups and LS roles (API, management commands, Keycloak login in DW-908)."""

from typing import Iterable

from access_control import access
from access_control.models import AccessGroup, LSRole, UserAccess, access_group_name_validator
from django.core.exceptions import ValidationError
from django.db import transaction

UNSET = object()


def normalize_group_names(names: Iterable[str]) -> list:
    """Strip, drop empties and duplicates (keeping order), validate. Raises ValidationError."""
    result = []
    for raw in names or []:
        if not isinstance(raw, str):
            raise ValidationError(f'Access group names must be strings, got {raw!r}')
        name = raw.strip()
        if not name or name in result:
            continue
        access_group_name_validator(name)
        if len(name) > AccessGroup._meta.get_field('name').max_length:
            raise ValidationError(f'Access group name is too long: {name}')
        result.append(name)
    return result


def get_or_create_groups(names: Iterable[str]) -> list:
    """Access groups by name, created on first use (the list of devices is not hard-coded)."""
    names = normalize_group_names(names)
    existing = {group.name: group for group in AccessGroup.objects.filter(name__in=names)}
    groups = []
    for name in names:
        group = existing.get(name)
        if group is None:
            group, _ = AccessGroup.objects.get_or_create(name=name)
        groups.append(group)
    return groups


def project_group_names(project) -> list:
    return sorted(group.name for group in project.access_groups.all())


@transaction.atomic
def set_project_groups(project, names: Iterable[str]) -> list:
    groups = get_or_create_groups(names)
    project.access_groups.set(groups)
    return [group.name for group in groups]


@transaction.atomic
def add_project_groups(project, names: Iterable[str]) -> list:
    groups = get_or_create_groups(names)
    project.access_groups.add(*groups)
    return project_group_names(project)


def get_user_access(user) -> dict:
    record = UserAccess.objects.filter(user_id=user.id).first()
    return {
        'role': record.role if record else None,
        'access_groups': access.get_group_names(user),
        'keycloak_sub': record.keycloak_sub if record else None,
    }


@transaction.atomic
def set_user_access(user, role=UNSET, groups=UNSET, keycloak_sub=UNSET) -> dict:
    """Set the LS role ('admin', 'labeler' or None), the access groups (replaces them) and/or the Keycloak subject."""
    if role is not UNSET and role not in (None, *LSRole.values):
        raise ValidationError(f'Unknown LS role: {role!r} (use one of {", ".join(LSRole.values)})')

    if role is not UNSET or keycloak_sub is not UNSET:
        record, _ = UserAccess.objects.get_or_create(user=user)
        changed = []
        if role is not UNSET and record.role != role:
            record.role = role
            changed.append('role')
        if keycloak_sub is not UNSET and record.keycloak_sub != (keycloak_sub or None):
            record.keycloak_sub = keycloak_sub or None
            changed.append('keycloak_sub')
        if changed:
            record.save(update_fields=[*changed, 'updated_at'])

    if groups is not UNSET:
        user.access_groups.set(get_or_create_groups(groups))

    access.clear_cache(user)
    return get_user_access(user)
