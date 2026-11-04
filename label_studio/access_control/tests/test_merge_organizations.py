"""Basir DW-907 part 2: merging the per-device organizations into one, and the Label Server service account.

The setup mirrors production: one organization per device, each created by its shared (superuser) account, plus
the leftover empty organization.
"""

import io
from unittest import mock

import pytest
from access_control.merge import build_plan, denormalized_organization_fields, organization_foreign_keys
from access_control.models import UserAccess
from access_control.services import set_user_access
from core.feature_flags import flag_set
from django.core.management import CommandError, call_command
from django.test import override_settings
from io_storages.s3.models import S3ExportStorage, S3ImportStorage
from jwt_auth.models import JWTSettings
from labels_manager.models import Label
from organizations.models import Organization, OrganizationMember
from projects.models import Project
from projects.tests.factories import ProjectFactory
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from tasks.models import Annotation, Task
from tasks.tests.factories import AnnotationFactory, TaskFactory
from users.models import User
from webhooks.models import Webhook

pytestmark = pytest.mark.django_db
JWT_FLAG = 'fflag__feature_develop__prompts__dia_1829_jwt_token_auth'
MALE, FEMALE, MAIL = 'ls-sightence-male', 'ls-sightence-female', 'ls-mail-scanner'


@pytest.fixture(autouse=True)
def jwt_tokens_on():
    real_flag_set = flag_set

    def fake_flag_set(name, *args, **kwargs):
        return True if name == JWT_FLAG else real_flag_set(name, *args, **kwargs)

    with mock.patch('core.feature_flags.flag_set', wraps=fake_flag_set):
        yield


def make_org(title, email):
    owner = User.objects.create_user(email=email, password='x', username=email.split('@')[0], is_superuser=True)
    org = Organization.create_organization(created_by=owner, title=title)
    owner.active_organization = org
    owner.save(update_fields=['active_organization'])
    org.jwt.legacy_api_tokens_enabled = True
    org.jwt.save()
    return org, owner


def fill(org, owner, name, projects=1):
    for i in range(projects):
        project = ProjectFactory(organization=org, created_by=owner, title=f'{name} scans {i}')
        for _ in range(2):
            task = TaskFactory(project=project)
            AnnotationFactory(task=task, completed_by=owner, result=[])
        Webhook.objects.create(organization=org, project=project, url=f'http://label-server/{name}/{i}')
        S3ImportStorage.objects.create(project=project, bucket=f'{name}-scans')
        S3ExportStorage.objects.create(project=project, bucket=f'{name}-export')
    Label.objects.create(organization=org, created_by=owner, title=f'{name} label', value={'choices': [name]})


class Production:
    def __init__(self):
        self.male, self.male_user = make_org('Label Studio male', 'male@mail.com')
        self.female, self.female_user = make_org('Label Studio female', 'female@mail.com')
        self.mail, self.mail_user = make_org('Label Studio mail_scanner', 'mail_scanner@mail.com')
        self.leftover, _ = make_org('Label Studio *male', 'leftover@mail.com')
        fill(self.male, self.male_user, 'male', projects=2)
        fill(self.female, self.female_user, 'female')
        fill(self.mail, self.mail_user, 'mail')

    def map_args(self):
        return ['--map', f'{self.male.id}={MALE}', f'{self.female.id}={FEMALE}', f'{self.mail.id}={MAIL}']

    def merge(self, *extra):
        out = io.StringIO()
        call_command(
            'basir_merge_organizations', '--target-org', str(self.mail.id), *self.map_args(), *extra, stdout=out
        )
        return out.getvalue()


@pytest.fixture
def prod():
    return Production()


def snapshot():
    """Everything the merge may touch, by ID."""
    return {
        'projects': sorted(Project.objects.values_list('id', 'organization_id')),
        'tasks': sorted(Task.objects.values_list('id', 'project_id')),
        'annotations': sorted(Annotation.objects.values_list('id', 'task_id', 'completed_by_id')),
        'webhooks': sorted(Webhook.objects.values_list('id', 'organization_id', 'project_id')),
        'imports': sorted(S3ImportStorage.objects.values_list('id', 'project_id')),
        'exports': sorted(S3ExportStorage.objects.values_list('id', 'project_id')),
        'labels': sorted(Label.objects.values_list('id', 'organization_id')),
        'members': sorted(OrganizationMember.objects.values_list('id', 'user_id', 'organization_id', 'deleted_at')),
        'active': sorted(User.objects.values_list('id', 'active_organization_id')),
        'orgs': sorted(Organization.objects.values_list('id', 'title')),
        'jwt': sorted(JWTSettings.objects.values_list('organization_id', 'legacy_api_tokens_enabled')),
        'roles': sorted(UserAccess.objects.values_list('user_id', 'role')),
        'project_groups': sorted(Project.access_groups.through.objects.values_list('project_id', 'accessgroup__name')),
        'user_groups': sorted(User.access_groups.through.objects.values_list('user_id', 'accessgroup__name')),
        'tokens': sorted(Token.objects.values_list('key', 'user_id')),
    }


def test_finds_organization_rows_through_model_meta():
    moving = {model._meta.label for model, _ in organization_foreign_keys()}
    assert {'projects.Project', 'webhooks.Webhook', 'labels_manager.Label', 'data_export.ConvertedFormat'} <= moving
    assert {'ml_models.ModelInterface', 'ml_model_providers.ModelProviderConnection'} <= moving
    # per-organization settings and memberships don't move as rows
    assert not moving & {
        'jwt_auth.JWTSettings',
        'session_policy.SessionTimeoutPolicy',
        'organizations.OrganizationMember',
        'users.User',
    }
    copies = {model._meta.label for model, _ in denormalized_organization_fields()}
    assert {'fsm.ProjectState', 'fsm.TaskState', 'fsm.AnnotationState'} <= copies
    assert 'core.DeletedRow' not in copies


def test_merge_moves_everything_and_keeps_every_id(prod):
    before = snapshot()
    output = prod.merge()
    after = snapshot()
    target = prod.mail.id

    # same rows, same IDs; only the organization changed
    assert [pid for pid, _ in after['projects']] == [pid for pid, _ in before['projects']]
    assert {org for _, org in after['projects']} == {target}
    for key in ('tasks', 'annotations', 'imports', 'exports', 'tokens'):
        assert after[key] == before[key], key
    assert [(i, p) for i, _, p in after['webhooks']] == [(i, p) for i, _, p in before['webhooks']]
    assert {org for _, org, _ in after['webhooks']} == {target}
    assert {org for _, org in after['labels']} == {target}
    # organizations, their settings and the old memberships stay
    assert after['orgs'] == before['orgs']
    assert after['jwt'] == before['jwt']
    assert set(before['members']) <= set(after['members'])

    # access groups follow the device
    groups = {p.title: sorted(p.access_groups.values_list('name', flat=True)) for p in Project.objects.all()}
    assert groups == {
        'male scans 0': [MALE],
        'male scans 1': [MALE],
        'female scans 0': [FEMALE],
        'mail scans 0': [MAIL],
    }
    # the shared accounts: members of the target, active there, labelers with their device's group
    for user, group in ((prod.male_user, MALE), (prod.female_user, FEMALE), (prod.mail_user, MAIL)):
        user.refresh_from_db()
        assert user.active_organization_id == target
        assert OrganizationMember.objects.filter(user=user, organization_id=target, deleted_at__isnull=True).exists()
        assert UserAccess.objects.get(user=user).role == 'labeler'
        assert list(user.access_groups.values_list('name', flat=True)) == [group]
    # the leftover organization was not mapped: untouched
    assert Organization.objects.get(id=prod.leftover.id).projects.count() == 0
    assert 'Merge done.' in output and 'Totals check' in output


def test_merge_report_lists_before_and_after(prod):
    output = prod.merge()
    before, after = output.split('After:')
    assert f'organization {prod.male.id}' in before and "'male scans 0': 2 tasks, 2 annotations" in before
    assert f'organization {prod.mail.id}' in after and '4 projects, 4 webhooks, 8 storages, 3 members' in after
    assert f'organization {prod.male.id} ' in after and '0 projects, 0 webhooks, 0 storages' in after


def test_fsm_history_follows_the_moved_projects(prod):
    from fsm.state_models import ProjectState

    states = list(ProjectState.objects.filter(project__organization=prod.male).values_list('id', flat=True))
    prod.merge()
    if states:  # FSM state is written when the FSM flag is on (pytest default)
        assert set(ProjectState.objects.filter(id__in=states).values_list('organization_id', flat=True)) == {
            prod.mail.id
        }


@override_settings(BASIR_ACCESS_CONTROL_ENABLED=True)
def test_after_the_merge_each_shared_account_sees_only_its_old_projects(prod):
    old = {
        user: set(Project.objects.filter(organization=org).values_list('id', flat=True))
        for user, org in ((prod.male_user, prod.male), (prod.female_user, prod.female), (prod.mail_user, prod.mail))
    }
    prod.merge()

    for user, project_ids in old.items():
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.get_or_create(user=user)[0].key}')
        response = client.get('/api/projects/')
        assert response.status_code == 200, response.content  # the legacy token still works after the move
        assert {p['id'] for p in response.json()['results']} == project_ids
        other = Project.objects.exclude(id__in=project_ids).first()
        assert client.get(f'/api/projects/{other.id}/').status_code == 404


def test_dry_run_changes_nothing(prod):
    before = snapshot()
    output = prod.merge('--dry-run')
    assert snapshot() == before
    assert 'Dry run: nothing was changed.' in output
    assert (
        'move 2 projects.Project' in output
        and 'groups of project' in output
        and 'LS role of male@mail.com: none -> labeler' in output
    )


def test_second_run_changes_nothing(prod):
    prod.merge()
    after_first = snapshot()
    output = prod.merge()
    assert snapshot() == after_first
    assert 'Nothing to change' in output
    assert not build_plan(
        prod.mail.id, {prod.male.id: [MALE], prod.female.id: [FEMALE], prod.mail.id: [MAIL]}
    ).has_changes


def test_owners_admin_and_existing_admins(prod):
    emergency = User.objects.create_user(email='emergency@basir.local', password='x', username='emergency')
    OrganizationMember.objects.create(user=emergency, organization=prod.male)
    set_user_access(emergency, role='admin')

    prod.merge('--owners-admin')

    assert UserAccess.objects.get(user=prod.male_user).role == 'admin'  # created "Label Studio male"
    assert UserAccess.objects.get(user=emergency).role == 'admin'  # never downgraded
    assert not emergency.access_groups.exists()


def test_legacy_tokens_keep_working_when_the_target_had_them_off(prod):
    prod.mail.jwt.legacy_api_tokens_enabled = False
    prod.mail.jwt.save()
    token, _ = Token.objects.get_or_create(user=prod.male_user)

    output = prod.merge()

    assert 'legacy_api_tokens_enabled = true' in output
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    assert client.get('/api/projects/').status_code == 200


def test_unique_conflict_stops_before_changing_anything(prod):
    Label.objects.filter(organization=prod.female).update(title='male label')  # same title as the male label
    before = snapshot()
    with pytest.raises(CommandError, match='unique constraint'):
        prod.merge()
    assert snapshot() == before


def test_bad_arguments(prod):
    with pytest.raises(CommandError, match='expects'):
        call_command('basir_merge_organizations', '--target-org', str(prod.mail.id), '--map', 'male=ls-x')
    with pytest.raises(CommandError, match='not found'):
        call_command('basir_merge_organizations', '--target-org', str(prod.mail.id), '--map', '99999=ls-x')
    with pytest.raises(CommandError, match='does not exist'):
        call_command('basir_merge_organizations', '--target-org', '99999', '--map', f'{prod.male.id}=ls-x')


# --- Label Server service account ---------------------------------------------------------------------------------


@override_settings(BASIR_ACCESS_CONTROL_ENABLED=True)
def test_service_account_is_an_ls_admin_with_a_working_token(prod):
    prod.mail.jwt.legacy_api_tokens_enabled = False
    prod.mail.jwt.save()
    out = io.StringIO()
    call_command(
        'basir_create_service_account',
        '--email',
        'Label-Server@basir.local',
        '--organization',
        str(prod.mail.id),
        stdout=out,
    )
    output = out.getvalue()
    user = User.objects.get(email='label-server@basir.local')
    token = Token.objects.get(user=user).key

    assert f'Legacy API token: {token}' in output and 'legacy API tokens switched on' in output
    assert not user.has_usable_password() and not user.is_superuser
    assert UserAccess.objects.get(user=user).role == 'admin'
    assert user.active_organization_id == prod.mail.id
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
    response = client.post(
        '/api/projects/', {'title': 'From the Label Server', 'access_groups': [MALE]}, format='json'
    )
    assert response.status_code == 201, response.content
    assert response.json()['access_groups'] == [MALE]

    # re-run keeps the token; --rotate-token replaces it
    out = io.StringIO()
    call_command(
        'basir_create_service_account',
        '--email',
        'label-server@basir.local',
        '--organization',
        str(prod.mail.id),
        '--token-only',
        stdout=out,
    )
    assert out.getvalue().strip() == token
    out = io.StringIO()
    call_command(
        'basir_create_service_account',
        '--email',
        'label-server@basir.local',
        '--organization',
        str(prod.mail.id),
        '--rotate-token',
        '--token-only',
        stdout=out,
    )
    assert out.getvalue().strip() != token
    assert User.objects.filter(email='label-server@basir.local').count() == 1
