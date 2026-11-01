"""Basir DW-907: admin-only operations and object rules for LS labelers.

Open-source Label Studio declares a ``permission_required`` on its API views but never enforces it. With
``BASIR_ACCESS_CONTROL_ENABLED`` on, ``LSRolePermission`` (a default DRF permission class) enforces the admin-only
ones for users whose LS role is not ``admin``. With the flag off it allows everything, as upstream.

Django's ``User.has_perm`` returns True for every superuser, so the role check never goes through it: our shared
accounts are superusers and must still be filtered.
"""

import logging

from access_control import access
from core.permissions import all_permissions
from django.contrib import admin
from rest_framework.permissions import SAFE_METHODS, BasePermission

logger = logging.getLogger(__name__)

# Permissions that only LS admins hold while access control is on. Everything else (view projects/tasks,
# annotate, drafts, Data Manager tabs, own profile and token) stays available to labelers, limited to their
# projects by access.restrict_projects / Project.has_permission.
ADMIN_ONLY_PERMISSIONS = frozenset(
    [
        all_permissions.organizations_create,
        all_permissions.organizations_change,
        all_permissions.organizations_delete,
        all_permissions.organizations_invite,
        all_permissions.projects_create,
        all_permissions.projects_change,  # project settings, labeling config, import, export, ML backends
        all_permissions.projects_delete,
        all_permissions.projects_reset_cache,
        all_permissions.tasks_create,
        all_permissions.tasks_change,
        all_permissions.tasks_delete,
        all_permissions.views_reset,
        all_permissions.labels_create,
        all_permissions.labels_change,
        all_permissions.labels_delete,
        all_permissions.models_create,
        all_permissions.models_view,
        all_permissions.models_change,
        all_permissions.models_delete,
        all_permissions.model_provider_connection_create,
        all_permissions.model_provider_connection_view,
        all_permissions.model_provider_connection_change,
        all_permissions.model_provider_connection_delete,
        all_permissions.webhooks_view,
        all_permissions.webhooks_change,
        all_permissions.storages_view,
        all_permissions.storages_change,
        all_permissions.storages_sync,
    ]
)

# Views that are admin-only although their declared permission is a "view" one.
ADMIN_ONLY_VIEWS = frozenset(
    [
        # organization / member pages and invites
        'organizations.api.OrganizationListAPI',
        'organizations.api.OrganizationAPI',
        'organizations.api.OrganizationMemberListAPI',
        'organizations.api.OrganizationMemberDetailAPI',
        'organizations.api.OrganizationInviteAPI',
        'organizations.api.OrganizationResetTokenAPI',
        # import / export
        'data_import.api.FileUploadListAPI',
        'data_import.api.FileUploadAPI',
        'data_export.api.ExportFormatsListAPI',
    ]
)

# Views where labelers may read (limited to their projects) but not create, change or delete.
ADMIN_ONLY_WRITE_VIEWS = frozenset(['tasks.api.PredictionAPI'])

# Data Manager actions with these permissions are admin-only: the above plus predictions.any
# ("Retrieve predictions", "Delete predictions").
ADMIN_ONLY_ACTION_PERMISSIONS = ADMIN_ONLY_PERMISSIONS | {all_permissions.predictions_any}

# (view, method) pairs labelers keep although the declared permission is admin-only.
# GET /api/users/ is declared organizations.change upstream, but the Data Manager loads it for every user
# (annotator names in the task table).
LABELER_ALLOWED = frozenset([('users.api.UserAPI', 'GET')])

DENIED_MESSAGE = 'Only LS admins can do this.'


def _view_path(view) -> str:
    cls = view if isinstance(view, type) else type(view)
    return f'{cls.__module__}.{cls.__name__}'


def get_required_permission(view, method):
    """The permission a view declares for a method (str, ViewClassPermission or get_permission_required())."""
    if hasattr(view, 'get_permission_required'):
        try:
            required = view.get_permission_required()
        except Exception:  # invalid entity names etc. are the view's business
            return None
    else:
        required = getattr(view, 'permission_required', None)
    if required is None or isinstance(required, str):
        return required
    return getattr(required, method, None)


def is_admin_only(view, method) -> bool:
    path = _view_path(view)
    if (path, method) in LABELER_ALLOWED:
        return False
    if path in ADMIN_ONLY_VIEWS:
        return True
    if path in ADMIN_ONLY_WRITE_VIEWS and method not in SAFE_METHODS:
        return True
    return get_required_permission(view, method) in ADMIN_ONLY_PERMISSIONS


def _requested_project_ids(request) -> list:
    values = [request.query_params.get('project')]
    if request.method not in SAFE_METHODS:
        try:
            data = request.data
        except Exception:  # unparsable bodies are the view's business
            data = None
        if hasattr(data, 'get'):
            values.append(data.get('project'))
    ids = []
    for value in values:
        if isinstance(value, dict):
            value = value.get('id')
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


class LSRolePermission(BasePermission):
    """Admin-only views for labelers, and labelers may only change their own annotations and profile."""

    message = DENIED_MESSAGE

    def has_permission(self, request, view):
        if not access.is_enabled() or not access.is_restricted(request.user):
            return True
        if request.method == 'OPTIONS':
            return True
        if is_admin_only(view, request.method):
            self.message = DENIED_MESSAGE
            return False
        # A request naming a project outside the user's groups (?project=, or "project" in the body) answers 404
        for project_id in _requested_project_ids(request):
            access.check_project_access(request.user, project_id)
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or not access.is_restricted(request.user):
            return True

        from tasks.models import Annotation
        from users.models import User

        if isinstance(obj, Annotation) and obj.completed_by_id != request.user.id:
            self.message = 'Labelers can only change or delete their own annotations.'
            return False
        if isinstance(obj, User) and obj.id != request.user.id:
            self.message = 'Labelers can only change their own account.'
            return False
        return True


def check_action_permission(user, action, project):
    """Data Manager actions (settings.DATA_MANAGER_CHECK_ACTION_PERMISSION): admin-only ones are hidden for labelers."""
    from data_manager.actions import check_action_permission as upstream_check

    if not upstream_check(user, action, project):
        return False
    if not access.is_restricted(user):
        return True
    permissions = action.get('permission')
    if not isinstance(permissions, list):
        permissions = [permissions]
    return not any(permission in ADMIN_ONLY_ACTION_PERMISSIONS for permission in permissions)


def _admin_site_has_permission(original):
    def has_permission(request):
        # Django admin lists every row of every model: LS admins only, whatever is_superuser says
        if access.is_restricted(request.user) and getattr(request.user, 'is_authenticated', False):
            return False
        return original(request)

    has_permission._basir_wrapped = True
    return has_permission


def install():
    """Called once from AccessControlConfig.ready()."""
    if not getattr(admin.site.has_permission, '_basir_wrapped', False):
        admin.site.has_permission = _admin_site_has_permission(admin.site.has_permission)
