"""Basir DW-907: merge organizations into one (one-time data migration, see basir_merge_organizations).

Everything that points at a source organization moves to the target organization in one transaction; nothing is
deleted and no ID changes. Rows are found through Django's model meta, not a hard-coded list:

- every many-to-one (ForeignKey) to Organization moves (projects, webhooks, labels, export formats, ML rows, ...);
- one-to-one rows are per-organization settings (JWT settings, session policy) and stay with their organization;
- memberships (OrganizationMember) and User.active_organization are handled as memberships;
- plain integer ``organization_id`` copies (FSM state history) follow, so the history of a moved project stays
  visible; ``core.DeletedRow`` keeps its value (it is a backup of deleted rows, not live data).

Access groups: moved projects get their source organization's groups, projects of the target organization that have
no group yet get the target's groups. Members of a mapped source organization get its groups (and the LS role
labeler unless they have a role); members of the target organization that belong to no mapped source organization
get the target's groups. This keeps a second run a no-op: after the merge the source members are also target
members, and must not get the target's groups.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from access_control.models import AccessGroup, LSRole, UserAccess
from access_control.services import get_or_create_groups, normalize_group_names
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from organizations.models import Organization, OrganizationMember
from projects.models import Project
from tasks.models import Annotation, Task
from users.models import User

logger = logging.getLogger(__name__)

# integer organization_id copies that must keep their value
KEEP_DENORMALIZED = {'core.DeletedRow'}


class MergeError(Exception):
    pass


@dataclass
class MergePlan:
    target: Organization
    sources: list  # Organization, without the target
    mapping: dict  # org id -> [group names]
    owners_admin: bool = False
    moves: dict = field(default_factory=dict)  # source id -> {label: count}
    memberships_added: list = field(default_factory=list)  # (user, source id, restored)
    active_switched: list = field(default_factory=list)  # user
    roles_set: list = field(default_factory=list)  # (user, old role, new role)
    user_groups_added: list = field(default_factory=list)  # (user, [names])
    project_groups_added: list = field(default_factory=list)  # (project id, [names])
    jwt_enabled: list = field(default_factory=list)  # setting names enabled on the target

    @property
    def has_changes(self):
        return any(
            [
                any(count for counts in self.moves.values() for count in counts.values()),
                self.memberships_added,
                self.active_switched,
                self.roles_set,
                self.user_groups_added,
                self.project_groups_added,
                self.jwt_enabled,
            ]
        )


def organization_foreign_keys():
    """(model, field) for every ForeignKey to Organization that moves with the merge."""
    result = []
    for rel in Organization._meta.related_objects:
        if not rel.one_to_many:  # reverse side of a ForeignKey
            continue  # one-to-one: per-organization settings rows; many-to-many: memberships
        model = rel.related_model._meta.concrete_model
        if model in (OrganizationMember, User):
            continue  # memberships and active_organization, handled below
        if not model._meta.managed:
            continue
        result.append((model, rel.field))
    return sorted(result, key=lambda item: (item[0]._meta.label, item[1].name))


def denormalized_organization_fields():
    """(model, field) for plain integer organization_id columns (not ForeignKeys) that follow the merge."""
    result = []
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed or model._meta.label in KEEP_DENORMALIZED:
            continue
        for model_field in model._meta.concrete_fields:
            if model_field.is_relation or model_field.attname != 'organization_id':
                continue
            result.append((model, model_field))
    return sorted(result, key=lambda item: item[0]._meta.label)


def _label(model, model_field):
    name = model._meta.label
    return name if model_field.name == 'organization' else f'{name}.{model_field.name}'


def _unique_groups(model, model_field):
    groups = [tuple(names) for names in model._meta.unique_together]
    for constraint in model._meta.constraints:
        if getattr(constraint, 'fields', None) and getattr(constraint, 'condition', None) is None:
            groups.append(tuple(constraint.fields))
    return [group for group in groups if model_field.name in group and len(group) > 1]


def _check_unique_conflicts(plan):
    """Rows that would collide with a unique constraint once they share the target organization."""
    conflicts = []
    org_ids = [plan.target.id] + [org.id for org in plan.sources]
    for model, model_field in organization_foreign_keys():
        for group in _unique_groups(model, model_field):
            others = [name for name in group if name != model_field.name]
            seen = {}
            for org_id in org_ids:
                rows = model._base_manager.filter(**{model_field.attname: org_id}).values_list('pk', *others)
                for pk, *values in rows:
                    key = tuple(values)
                    if key in seen and seen[key][0] != org_id:
                        conflicts.append(
                            f'{model._meta.label} {dict(zip(others, values))}: row {pk} (organization {org_id}) '
                            f'and row {seen[key][1]} (organization {seen[key][0]})'
                        )
                    seen.setdefault(key, (org_id, pk))
    return conflicts


def _active_members(org_id):
    return User.objects.filter(om_through__organization_id=org_id, om_through__deleted_at__isnull=True).distinct()


def build_plan(target_id: int, mapping: dict, owners_admin: bool = False) -> MergePlan:
    target = Organization.objects.filter(id=target_id).first()
    if target is None:
        raise MergeError(f'Target organization {target_id} does not exist')
    mapping = {int(org_id): normalize_group_names(names) for org_id, names in mapping.items()}
    for org_id, names in mapping.items():
        if not names:
            raise MergeError(f'No access group given for organization {org_id}')
    sources = list(Organization.objects.filter(id__in=[org_id for org_id in mapping if org_id != target.id]))
    missing = set(mapping) - {org.id for org in sources} - {target.id}
    if missing:
        raise MergeError(f'Organization(s) not found: {", ".join(map(str, sorted(missing)))}')

    plan = MergePlan(target=target, sources=sorted(sources, key=lambda o: o.id), mapping=mapping)
    plan.owners_admin = owners_admin

    conflicts = _check_unique_conflicts(plan)
    if conflicts:
        raise MergeError(
            'These rows would break a unique constraint in the target organization:\n  ' + '\n  '.join(conflicts)
        )

    source_ids = [org.id for org in plan.sources]
    for org in plan.sources:
        counts = {}
        for model, model_field in organization_foreign_keys() + denormalized_organization_fields():
            counts[_label(model, model_field)] = model._base_manager.filter(**{model_field.attname: org.id}).count()
        plan.moves[org.id] = counts

    # memberships and active organization
    target_members = OrganizationMember.objects.filter(organization=target)
    target_member_state = {m.user_id: m.deleted_at for m in target_members}
    for org in plan.sources:
        for user in _active_members(org.id):
            if user.id not in target_member_state:
                plan.memberships_added.append((user, org.id, False))
                target_member_state[user.id] = None
            elif target_member_state[user.id] is not None:
                plan.memberships_added.append((user, org.id, True))
                target_member_state[user.id] = None
            if user.active_organization_id in (*source_ids, None) and user not in plan.active_switched:
                plan.active_switched.append(user)

    # roles and user groups
    roles = dict(UserAccess.objects.values_list('user_id', 'role'))
    owners = {org.created_by_id for org in [target, *plan.sources] if org.id in mapping and org.created_by_id}
    groups_for_user = defaultdict(list)
    in_mapped_source = set()
    for org in plan.sources:
        for user in _active_members(org.id):
            in_mapped_source.add(user.id)
            groups_for_user[user].extend(mapping[org.id])
    if target.id in mapping:
        for user in _active_members(target.id):
            if user.id not in in_mapped_source:
                groups_for_user[user].extend(mapping[target.id])

    for user, names in sorted(groups_for_user.items(), key=lambda item: item[0].id):
        current_role = roles.get(user.id)
        new_role = current_role
        if owners_admin and user.id in owners:
            new_role = LSRole.ADMIN
        elif current_role is None:
            new_role = LSRole.LABELER
        if new_role != current_role:
            plan.roles_set.append((user, current_role, new_role))
        if new_role == LSRole.ADMIN:
            continue  # admins see everything; their groups stay as they are
        have = set(user.access_groups.values_list('name', flat=True))
        missing_names = [name for name in dict.fromkeys(names) if name not in have]
        if missing_names:
            plan.user_groups_added.append((user, missing_names))

    # project groups
    groups_of = defaultdict(set)
    for project_id, name in AccessGroup.projects.through.objects.values_list('project_id', 'accessgroup__name'):
        groups_of[project_id].add(name)
    for org in plan.sources:
        for project_id in Project.objects.filter(organization_id=org.id).values_list('id', flat=True):
            missing_names = [name for name in mapping[org.id] if name not in groups_of[project_id]]
            if missing_names:
                plan.project_groups_added.append((project_id, missing_names))
    if target.id in mapping:
        for project_id in Project.objects.filter(organization_id=target.id).values_list('id', flat=True):
            if not groups_of[project_id]:
                plan.project_groups_added.append((project_id, list(mapping[target.id])))

    # API tokens: users now active in the target keep working only if the target allows the same token types
    jwt = getattr(target, 'jwt', None)
    if jwt is not None:
        for setting in ('legacy_api_tokens_enabled', 'api_tokens_enabled'):
            if not getattr(jwt, setting) and any(
                getattr(getattr(org, 'jwt', None), setting, False) for org in plan.sources
            ):
                plan.jwt_enabled.append(setting)
    return plan


@transaction.atomic
def apply_plan(plan: MergePlan) -> None:
    target = plan.target
    for org in plan.sources:
        for model, model_field in organization_foreign_keys() + denormalized_organization_fields():
            model._base_manager.filter(**{model_field.attname: org.id}).update(**{model_field.attname: target.id})

    for user, _source_id, restored in plan.memberships_added:
        if restored:
            OrganizationMember.objects.filter(user=user, organization=target).update(deleted_at=None)
        else:
            OrganizationMember.objects.create(user=user, organization=target)
    for user in plan.active_switched:
        User.objects.filter(pk=user.pk).update(active_organization=target)

    for user, _old, new_role in plan.roles_set:
        UserAccess.objects.update_or_create(user=user, defaults={'role': new_role})
    for user, names in plan.user_groups_added:
        user.access_groups.add(*get_or_create_groups(names))
    for project_id, names in plan.project_groups_added:
        project = Project.objects.get(pk=project_id)
        project.access_groups.add(*get_or_create_groups(names))

    if plan.jwt_enabled:
        jwt = target.jwt
        for setting in plan.jwt_enabled:
            setattr(jwt, setting, True)
        jwt.save(update_fields=plan.jwt_enabled)
    logger.info('Merged organizations %s into %s at %s', [o.id for o in plan.sources], target.id, timezone.now())


def counts_report(org_ids) -> dict:
    """Projects (with tasks/annotations), webhooks, storages and members per organization."""
    storage_models = [
        model
        for model in apps.get_models()
        if model._meta.app_label == 'io_storages'
        and model.__name__.endswith('Storage')
        and any(f.name == 'project' and f.is_relation for f in model._meta.concrete_fields)
    ]
    report = {}
    for org_id in org_ids:
        projects = {}
        for project in Project.objects.filter(organization_id=org_id).order_by('id'):
            projects[project.id] = {
                'title': project.title,
                'tasks': Task.objects.filter(project_id=project.id).count(),
                'annotations': Annotation.objects.filter(project_id=project.id).count(),
                'groups': sorted(project.access_groups.values_list('name', flat=True)),
            }
        webhook_model = apps.get_model('webhooks', 'Webhook')
        report[org_id] = {
            'projects': projects,
            'webhooks': webhook_model.objects.filter(organization_id=org_id).count(),
            'storages': sum(m._base_manager.filter(project__organization_id=org_id).count() for m in storage_models),
            'members': _active_members(org_id).count(),
        }
    return report


def format_report(report: dict, titles: Optional[dict] = None) -> str:
    lines = []
    for org_id, data in report.items():
        title = (titles or {}).get(org_id, '')
        lines.append(
            f'  organization {org_id} {title!r}: {len(data["projects"])} projects, {data["webhooks"]} webhooks, '
            f'{data["storages"]} storages, {data["members"]} members'
        )
        for project_id, project in data['projects'].items():
            groups = ','.join(project['groups']) or '-'
            lines.append(
                f'    project {project_id} {project["title"]!r}: {project["tasks"]} tasks, '
                f'{project["annotations"]} annotations, groups {groups}'
            )
    return '\n'.join(lines)
