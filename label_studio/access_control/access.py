"""Basir DW-907: the one place that decides which projects a user may see.

With ``BASIR_ACCESS_CONTROL_ENABLED`` off (the default) every function here is a no-op and Label Studio behaves
exactly as upstream. With it on, a user whose LS role is not ``admin`` only sees projects that share at least one
access group with them. ``is_superuser`` and ``is_staff`` play no part: access comes only from the LS role and groups.

Use:
- ``restrict_projects(queryset, user)`` for querysets of projects or of objects linked to a project,
- ``check_project_access(user, project)`` for one project (raises Http404, so a hidden project answers 404),
- ``is_restricted(user)`` for admin-only operations.
"""

from typing import Optional, Union

from django.conf import settings
from django.db.models import Model, QuerySet
from django.http import Http404

_CACHE_ATTR = '_ls_access_cache'
ROLE_ADMIN = 'admin'  # access_control.models.LSRole.ADMIN (models can't be imported at settings time)
ROLE_LABELER = 'labeler'


def is_enabled() -> bool:
    return bool(getattr(settings, 'BASIR_ACCESS_CONTROL_ENABLED', False))


def _cache(user) -> dict:
    cache = user.__dict__.get(_CACHE_ATTR)
    if cache is None:
        cache = user.__dict__[_CACHE_ATTR] = {}
    return cache


def clear_cache(user) -> None:
    """Forget the cached role/groups of this user object (after changing them in the same request)."""
    if user is not None:
        user.__dict__.pop(_CACHE_ATTR, None)


def _is_authenticated(user) -> bool:
    return bool(user is not None and getattr(user, 'is_authenticated', False) and getattr(user, 'id', None))


def get_role(user) -> Optional[str]:
    """LS role of the user: 'admin', 'labeler' or None (no role set)."""
    if not _is_authenticated(user):
        return None
    cache = _cache(user)
    if 'role' not in cache:
        from access_control.models import UserAccess

        cache['role'] = UserAccess.objects.filter(user_id=user.id).values_list('role', flat=True).first()
    return cache['role']


def get_group_ids(user) -> list:
    if not _is_authenticated(user):
        return []
    cache = _cache(user)
    if 'group_ids' not in cache:
        from access_control.models import AccessGroup

        cache['group_ids'] = list(
            AccessGroup.users.through.objects.filter(user_id=user.id).values_list('accessgroup_id', flat=True)
        )
    return cache['group_ids']


def get_group_names(user) -> list:
    if not _is_authenticated(user):
        return []
    from access_control.models import AccessGroup

    return list(AccessGroup.objects.filter(users__id=user.id).order_by('name').values_list('name', flat=True))


def is_ls_admin(user) -> bool:
    return get_role(user) == ROLE_ADMIN


def is_restricted(user) -> bool:
    """True when access control is on and the user is not an LS admin (labeler, no role, or anonymous)."""
    return is_enabled() and not is_ls_admin(user)


def accessible_project_ids(user) -> QuerySet:
    """Subquery with the IDs of the projects sharing at least one access group with the user."""
    from access_control.models import AccessGroup

    return (
        AccessGroup.projects.through.objects.filter(accessgroup_id__in=get_group_ids(user))
        .values('project_id')
        .distinct()
    )


def restrict_projects(queryset: QuerySet, user, project_field: Optional[str] = None) -> QuerySet:
    """Limit a queryset to the projects the user may see.

    :param queryset: projects (``project_field=None``) or objects linked to a project
    :param project_field: lookup path from the queryset's model to the project, e.g. 'project' or 'task__project'
    """
    if not is_restricted(user):
        return queryset
    if not get_group_ids(user):
        return queryset.none()
    lookup = f'{project_field}__in' if project_field else 'pk__in'
    return queryset.filter(**{lookup: accessible_project_ids(user)})


def can_access_project(user, project: Union[Model, int, None]) -> bool:
    if not is_restricted(user):
        return True
    project_id = getattr(project, 'pk', project)
    if project_id is None:
        return False
    group_ids = get_group_ids(user)
    if not group_ids:
        return False
    per_project = _cache(user).setdefault('projects', {})
    if project_id not in per_project:
        from access_control.models import AccessGroup

        per_project[project_id] = AccessGroup.projects.through.objects.filter(
            project_id=project_id, accessgroup_id__in=group_ids
        ).exists()
    return per_project[project_id]


def check_project_access(user, project) -> None:
    """Raise Http404 when the project is outside the user's groups: hidden projects must look like missing ones."""
    if not can_access_project(user, project):
        raise Http404('Project not found')


def access_groups_requested(request) -> bool:
    """True when the request asks for the access_groups field (?include=... or ?fields=...)."""
    params = getattr(request, 'query_params', None) or getattr(request, 'GET', {})
    getlist = getattr(params, 'getlist', None)
    values = getlist('include') + getlist('fields') if getlist else []
    return any('access_groups' in value.split(',') for value in values)


def shows_access_groups(request, sparse_fields=None) -> bool:
    """Whether a project list response carries access_groups (same rule as ProjectSerializer)."""
    if request is None or is_restricted(request.user):
        return False
    if sparse_fields is not None:
        return 'access_groups' in sparse_fields
    return is_enabled() or access_groups_requested(request)
