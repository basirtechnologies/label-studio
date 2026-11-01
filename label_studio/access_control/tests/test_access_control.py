"""Basir DW-907: device-based access control (access groups + LS roles).

Three devices, as in production: Sightence male, Sightence female and Mail Scanner, one project each, in one
organization. Every check runs with a session login and with a legacy API token.
"""

import base64
import time
from unittest import mock

import pytest
from access_control import access
from access_control.models import AccessGroup, UserAccess
from access_control.services import set_project_groups, set_user_access
from core.feature_flags import flag_set
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from jwt_auth.models import LSAPIToken
from organizations.tests.factories import OrganizationFactory
from projects.models import Project
from projects.tests.factories import ProjectFactory
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from tasks.models import Annotation, Task
from tasks.tests.factories import AnnotationDraftFactory, AnnotationFactory, PredictionFactory, TaskFactory
from users.tests.factories import UserFactory

MALE, FEMALE, MAIL = 'ls-sightence-male', 'ls-sightence-female', 'ls-mail-scanner'
LABEL_CONFIG = (
    '<View><Text name="text" value="$text"/><Choices name="c" toName="text"><Choice value="a"/></Choices></View>'
)

pytestmark = pytest.mark.django_db
JWT_FLAG = 'fflag__feature_develop__prompts__dia_1829_jwt_token_auth'


@pytest.fixture(autouse=True)
def jwt_tokens_on():
    """Production has JWT API tokens on (and legacy tokens enabled per organization)."""
    real_flag_set = flag_set

    def fake_flag_set(name, *args, **kwargs):
        return True if name == JWT_FLAG else real_flag_set(name, *args, **kwargs)

    with mock.patch('core.feature_flags.flag_set', wraps=fake_flag_set):
        yield


enabled = override_settings(BASIR_ACCESS_CONTROL_ENABLED=True)


class World:
    """One org with a project per device, each with a task, an annotation, a draft and a prediction."""

    def __init__(self):
        self.org = OrganizationFactory()
        self.org.jwt.legacy_api_tokens_enabled = True
        self.org.jwt.save()
        self.owner = self.org.created_by
        self.projects = {}
        self.tasks = {}
        self.annotations = {}
        self.drafts = {}
        self.predictions = {}
        for group in (MALE, FEMALE, MAIL):
            project = ProjectFactory(organization=self.org, created_by=self.owner, label_config=LABEL_CONFIG)
            set_project_groups(project, [group])
            task = TaskFactory(project=project)
            TaskFactory(project=project)  # not labeled yet: the labeling stream has a next task
            self.projects[group] = project
            self.tasks[group] = task
            self.annotations[group] = AnnotationFactory(task=task, completed_by=self.owner, result=[])
            self.drafts[group] = AnnotationDraftFactory(task=task, user=self.owner)
            self.predictions[group] = PredictionFactory(task=task)

    def user(self, role=None, groups=(), **kwargs):
        user = UserFactory(active_organization=self.org, **kwargs)
        if role or groups:
            set_user_access(user, role=role, groups=list(groups))
        return user


def session_client(user):
    client = APIClient()
    client.force_login(user, backend='django.contrib.auth.backends.ModelBackend')
    session = client.session
    session['last_login'] = time.time()  # what the login view stores (InactivitySessionTimeoutMiddleWare)
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key  # signed-cookie sessions live in the cookie
    return client


def token_client(user):
    client = APIClient()
    token, _ = Token.objects.get_or_create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


def jwt_client(user):
    org = user.active_organization
    org.jwt.api_tokens_enabled = True
    org.jwt.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {LSAPIToken.for_user(user).access_token}')
    return client


CLIENTS = {'session': session_client, 'token': token_client, 'jwt': jwt_client}


@pytest.fixture
def world():
    return World()


def project_ids(response):
    data = response.json()
    items = data['results'] if isinstance(data, dict) else data
    return {item['id'] for item in items}


def scoped_urls(world, group):
    """Project-scoped reads of one device's project."""
    project, task = world.projects[group], world.tasks[group]
    annotation, draft, prediction = world.annotations[group], world.drafts[group], world.predictions[group]
    fileuri = base64.urlsafe_b64encode(b's3://bucket/scan.png').decode()
    return {
        'project detail': f'/api/projects/{project.id}/',
        'project next task': f'/api/projects/{project.id}/next/',
        'project summary': f'/api/projects/{project.id}/summary/',
        'project annotators': f'/api/projects/{project.id}/annotators/',
        'project tasks': f'/api/projects/{project.id}/tasks/',
        'task detail': f'/api/tasks/{task.id}/',
        'task list': f'/api/tasks/?project={project.id}',
        'task annotations': f'/api/tasks/{task.id}/annotations/',
        'task drafts': f'/api/tasks/{task.id}/drafts',
        'annotation detail': f'/api/annotations/{annotation.id}/',
        'draft detail': f'/api/drafts/{draft.id}/',
        'prediction detail': f'/api/predictions/{prediction.id}/',
        'dm views': f'/api/dm/views/?project={project.id}',
        'dm project': f'/api/dm/project/?project={project.id}',
        'dm columns': f'/api/dm/columns/?project={project.id}',
        'dm actions': f'/api/dm/actions/?project={project.id}',
        'dm user options': f'/api/dm/projects/{project.id}/user-options/',
        'ml backends': f'/api/ml/?project={project.id}',
        'task resolve': f'/tasks/{task.id}/resolve/?fileuri={fileuri}',
        'task presign': f'/tasks/{task.id}/presign/?fileuri={fileuri}',
        'project resolve': f'/projects/{project.id}/resolve/?fileuri={fileuri}',
    }


# --- labelers see only their devices ---------------------------------------------------------------------------


@enabled
@pytest.mark.parametrize('auth', CLIENTS)
def test_male_labeler_sees_only_male_projects(world, auth):
    labeler = world.user(role='labeler', groups=[MALE])
    client = CLIENTS[auth](labeler)
    male = world.projects[MALE].id

    assert project_ids(client.get('/api/projects/')) == {male}
    assert project_ids(client.get('/api/projects/counts/')) == {male}
    assert {t['id'] for t in client.get(f'/api/tasks/?project={male}').json()['tasks']} == set(
        world.projects[MALE].tasks.values_list('id', flat=True)
    )
    assert {p['id'] for p in client.get('/api/predictions/').json()} == {world.predictions[MALE].id}

    for name, url in scoped_urls(world, MALE).items():
        response = client.get(url)
        if 'resolve' in name or 'presign' in name:
            # no storage holds the file: the request got past the access check
            assert b'Project not found' not in response.content, name
        else:
            assert response.status_code == 200, (name, response.status_code, response.content[:300])


@enabled
@pytest.mark.parametrize('auth', CLIENTS)
@pytest.mark.parametrize('other', [FEMALE, MAIL])
def test_male_labeler_gets_404_for_other_devices(world, auth, other):
    labeler = world.user(role='labeler', groups=[MALE])
    client = CLIENTS[auth](labeler)

    for name, url in scoped_urls(world, other).items():
        response = client.get(url)
        assert response.status_code == 404, (name, response.status_code, response.content[:300])
        if 'resolve' in name or 'presign' in name:
            assert b'Project not found' in response.content, name  # refused before looking for the file


@enabled
def test_hidden_project_writes_answer_404(world):
    labeler = world.user(role='labeler', groups=[MALE])
    client = session_client(labeler)
    female_task = world.tasks[FEMALE]

    response = client.post(f'/api/tasks/{female_task.id}/annotations/', {'result': []}, format='json')
    assert response.status_code == 404
    response = client.post(f'/api/tasks/{female_task.id}/drafts', {'result': []}, format='json')
    assert response.status_code == 404
    response = client.post('/api/dm/views/', {'project': world.projects[FEMALE].id, 'data': {}}, format='json')
    assert response.status_code == 404
    assert not Annotation.objects.filter(task=female_task, completed_by=labeler).exists()


@enabled
def test_labeler_in_two_groups_sees_both(world):
    labeler = world.user(role='labeler', groups=[MALE, FEMALE])
    client = session_client(labeler)

    assert project_ids(client.get('/api/projects/')) == {world.projects[MALE].id, world.projects[FEMALE].id}
    assert client.get(f'/api/tasks/{world.tasks[FEMALE].id}/').status_code == 200
    assert client.get(f'/api/tasks/{world.tasks[MAIL].id}/').status_code == 404


@enabled
def test_project_in_two_groups_is_seen_by_both(world):
    shared = ProjectFactory(organization=world.org, created_by=world.owner)
    set_project_groups(shared, [MALE, FEMALE])
    male = session_client(world.user(role='labeler', groups=[MALE]))
    female = session_client(world.user(role='labeler', groups=[FEMALE]))

    assert shared.id in project_ids(male.get('/api/projects/'))
    assert shared.id in project_ids(female.get('/api/projects/'))


@enabled
@pytest.mark.parametrize('auth', CLIENTS)
def test_admin_sees_everything(world, auth):
    admin = world.user(role='admin')  # no groups needed
    client = CLIENTS[auth](admin)

    assert project_ids(client.get('/api/projects/')) == {p.id for p in world.projects.values()}
    for group in (MALE, FEMALE, MAIL):
        assert client.get(f'/api/tasks/{world.tasks[group].id}/').status_code == 200


@enabled
@pytest.mark.parametrize('auth', CLIENTS)
def test_superuser_without_admin_role_is_filtered(world, auth):
    shared = world.user(role='labeler', groups=[MALE], is_superuser=True, is_staff=True)
    client = CLIENTS[auth](shared)

    assert project_ids(client.get('/api/projects/')) == {world.projects[MALE].id}
    assert client.get(f'/api/projects/{world.projects[FEMALE].id}/').status_code == 404
    assert client.post('/api/projects/', {'title': 'x'}, format='json').status_code == 403
    # Django admin lists every row of every model
    assert session_client(shared).get('/admin/').status_code == 302
    # the settings dump of /version/ is not for labelers
    assert 'settings' not in session_client(shared).get('/version/').content.decode()


@enabled
def test_user_without_role_or_groups_sees_nothing(world):
    client = session_client(world.user())

    assert project_ids(client.get('/api/projects/')) == set()
    assert client.get(f'/api/projects/{world.projects[MALE].id}/').status_code == 404


# --- admin-only operations -------------------------------------------------------------------------------------


def admin_only_requests(world, labeler):
    male, task = world.projects[MALE], world.tasks[MALE]
    return [
        ('create project', 'post', '/api/projects/', {'title': 'new'}),
        ('update project', 'patch', f'/api/projects/{male.id}/', {'title': 'renamed'}),
        ('update access groups', 'patch', f'/api/projects/{male.id}/', {'access_groups': [MALE, FEMALE]}),
        ('delete project', 'delete', f'/api/projects/{male.id}/', None),
        ('validate labeling config', 'post', f'/api/projects/{male.id}/validate/', {'label_config': LABEL_CONFIG}),
        ('import', 'post', f'/api/projects/{male.id}/import', [{'text': 'x'}]),
        ('file uploads', 'get', f'/api/projects/{male.id}/file-uploads', None),
        ('export', 'get', f'/api/projects/{male.id}/export', None),
        ('export formats', 'get', f'/api/projects/{male.id}/export/formats', None),
        ('export list', 'get', f'/api/projects/{male.id}/exports/', None),
        ('storages', 'get', f'/api/storages/s3/?project={male.id}', None),
        ('create storage', 'post', '/api/storages/s3/', {'project': male.id, 'bucket': 'b'}),
        ('webhooks', 'get', '/api/webhooks/', None),
        ('create webhook', 'post', '/api/webhooks/', {'project': male.id, 'url': 'http://example.com'}),
        ('create ML backend', 'post', '/api/ml/', {'project': male.id, 'url': 'http://example.com'}),
        ('create task', 'post', '/api/tasks/', {'project': male.id, 'data': {'text': 'x'}}),
        ('update task', 'patch', f'/api/tasks/{task.id}/', {'data': {'text': 'y'}}),
        ('delete task', 'delete', f'/api/tasks/{task.id}/', None),
        ('delete project tasks', 'delete', f'/api/projects/{male.id}/tasks/', None),
        (
            'dm delete tasks',
            'post',
            f'/api/dm/actions/?project={male.id}&id=delete_tasks',
            {'selectedItems': {'all': True}},
        ),
        ('create prediction', 'post', '/api/predictions/', {'task': task.id, 'result': []}),
        ('delete prediction', 'delete', f'/api/predictions/{world.predictions[MALE].id}/', None),
        ('delete others annotation', 'delete', f'/api/annotations/{world.annotations[MALE].id}/', None),
        ('update others annotation', 'patch', f'/api/annotations/{world.annotations[MALE].id}/', {'result': []}),
        ('organizations', 'get', '/api/organizations/', None),
        ('organization', 'get', f'/api/organizations/{world.org.id}', None),
        ('members', 'get', f'/api/organizations/{world.org.id}/memberships', None),
        ('invite', 'get', '/api/invite', None),
        ('update other user', 'patch', f'/api/users/{world.owner.id}/', {'first_name': 'x'}),
        ('create label', 'post', '/api/labels/', {'value': {'x': 1}, 'title': 'x', 'from_name': 'c'}),
        ('access groups', 'get', '/api/access-control/groups/', None),
        ('users access', 'get', '/api/access-control/users/', None),
        ('set own role', 'patch', f'/api/access-control/users/{labeler.id}/', {'role': 'admin'}),
    ]


@enabled
@pytest.mark.parametrize('auth', CLIENTS)
def test_admin_only_endpoints_answer_403_to_labelers(world, auth):
    labeler = world.user(role='labeler', groups=[MALE], is_superuser=True)
    client = CLIENTS[auth](labeler)

    for name, method, url, data in admin_only_requests(world, labeler):
        response = getattr(client, method)(url, data, format='json')
        assert response.status_code == 403, (name, response.status_code, response.content[:300])

    assert Project.objects.filter(id=world.projects[MALE].id).exists()
    assert Task.objects.filter(id=world.tasks[MALE].id).exists()
    assert Annotation.objects.filter(id=world.annotations[MALE].id).exists()
    assert set(world.projects[MALE].access_groups.values_list('name', flat=True)) == {MALE}
    assert access.get_role(labeler) == 'labeler'


@enabled
def test_admin_can_use_admin_only_endpoints(world):
    admin = world.user(role='admin')
    client = session_client(admin)
    male = world.projects[MALE]

    assert client.patch(f'/api/projects/{male.id}/', {'title': 'renamed'}, format='json').status_code == 200
    assert client.get('/api/webhooks/').status_code == 200
    assert client.get(f'/api/organizations/{world.org.id}/memberships').status_code == 200
    assert client.get(f'/api/projects/{male.id}/export/formats').status_code == 200
    assert client.delete(f'/api/tasks/{world.tasks[MALE].id}/').status_code == 204


@enabled
def test_labeler_can_label_skip_and_manage_own_work(world):
    labeler = world.user(role='labeler', groups=[MALE])
    client = session_client(labeler)
    task = world.tasks[MALE]

    response = client.post(f'/api/tasks/{task.id}/annotations/', {'result': [], 'lead_time': 1}, format='json')
    assert response.status_code == 201, response.content
    own = response.json()['id']
    response = client.post(
        f'/api/tasks/{task.id}/annotations/', {'result': [], 'was_cancelled': True}, format='json'
    )  # skip
    assert response.status_code == 201, response.content
    assert client.patch(f'/api/annotations/{own}/', {'result': []}, format='json').status_code == 200
    assert client.post(f'/api/tasks/{task.id}/drafts', {'result': []}, format='json').status_code == 201
    assert client.delete(f'/api/annotations/{own}/').status_code == 204
    # Data Manager tabs of their project
    assert (
        client.post('/api/dm/views/', {'project': world.projects[MALE].id, 'data': {}}, format='json').status_code
        == 201
    )
    # own profile
    assert client.patch(f'/api/users/{labeler.id}/', {'first_name': 'Me'}, format='json').status_code == 200


@enabled
def test_data_manager_hides_admin_only_actions_for_labelers(world):
    male = world.projects[MALE]
    labeler_actions = {
        a['id']
        for a in session_client(world.user(role='labeler', groups=[MALE]))
        .get(f'/api/dm/actions/?project={male.id}')
        .json()
    }
    admin_actions = {
        a['id'] for a in session_client(world.user(role='admin')).get(f'/api/dm/actions/?project={male.id}').json()
    }

    for action in (
        'delete_tasks',
        'delete_tasks_annotations',
        'delete_tasks_predictions',
        'retrieve_tasks_predictions',
    ):
        assert action not in labeler_actions
        assert action in admin_actions
    state = session_client(world.user(role='labeler', groups=[MALE])).get(f'/api/dm/project/?project={male.id}').json()
    assert state['can_delete_tasks'] is False


@enabled
def test_whoami_tells_the_ui_the_role(world):
    labeler = world.user(role='labeler', groups=[MALE, FEMALE])
    data = session_client(labeler).get('/api/current-user/whoami').json()

    assert data['ls_access'] == {
        'enabled': True,
        'role': 'labeler',
        'is_admin': False,
        'can_manage': False,
        'access_groups': [FEMALE, MALE],
    }
    assert 'projects.create' not in data['permissions'] and 'projects.view' in data['permissions']
    admin = session_client(world.user(role='admin')).get('/api/current-user/whoami').json()
    assert admin['ls_access']['can_manage'] is True and 'projects.create' in admin['permissions']


# --- access_groups on projects ------------------------------------------------------------------------------------


@enabled
def test_admin_creates_and_updates_project_access_groups(world):
    client = token_client(world.user(role='admin'))

    response = client.post(
        '/api/projects/', {'title': 'Project P', 'access_groups': [MALE, ' ls-new-device ', MALE]}, format='json'
    )
    assert response.status_code == 201, response.content
    assert response.json()['access_groups'] == ['ls-new-device', MALE]
    project_id = response.json()['id']
    assert AccessGroup.objects.filter(name='ls-new-device').exists()  # groups are created on first use

    response = client.patch(f'/api/projects/{project_id}/', {'access_groups': [FEMALE]}, format='json')
    assert response.json()['access_groups'] == [FEMALE]
    assert client.get(f'/api/projects/{project_id}/').json()['access_groups'] == [FEMALE]
    assert client.get('/api/projects/?include=id,access_groups').json()['results'][0]['access_groups']

    response = client.patch(f'/api/projects/{project_id}/', {'access_groups': ['bad name!']}, format='json')
    assert response.status_code == 400


@enabled
def test_labelers_dont_see_project_access_groups(world):
    client = session_client(world.user(role='labeler', groups=[MALE]))
    assert 'access_groups' not in client.get(f'/api/projects/{world.projects[MALE].id}/').json()


# --- user access endpoints and command ----------------------------------------------------------------------------


@enabled
def test_admin_reads_and_sets_user_access(world):
    admin = world.user(role='admin')
    user = world.user()
    client = session_client(admin)

    response = client.patch(
        f'/api/access-control/users/{user.id}/', {'role': 'labeler', 'access_groups': [MAIL]}, format='json'
    )
    assert response.status_code == 200, response.content
    assert response.json()['role'] == 'labeler' and response.json()['access_groups'] == [MAIL]
    assert project_ids(session_client(user).get('/api/projects/')) == {world.projects[MAIL].id}

    users = {u['id']: u for u in client.get('/api/access-control/users/').json()}
    assert users[user.id]['access_groups'] == [MAIL]
    groups = {g['name']: g for g in client.get('/api/access-control/groups/').json()}
    assert groups[MAIL]['project_count'] == 1 and groups[MAIL]['user_count'] == 1


def test_user_access_endpoints_need_the_admin_role_even_with_access_control_off(world):
    user = world.user()
    assert (
        session_client(user)
        .patch(f'/api/access-control/users/{user.id}/', {'role': 'admin'}, format='json')
        .status_code
        == 403
    )
    assert access.get_role(user) is None


def test_basir_set_user_access_command(world, capsys):
    user = world.user(email='male@mail.com', is_superuser=True)

    call_command('basir_set_user_access', '--email', 'male@mail.com', '--role', 'labeler', '--groups', MALE)
    assert capsys.readouterr().out.strip() == f'male@mail.com: role=labeler groups={MALE}'
    assert UserAccess.objects.get(user=user).role == 'labeler'
    assert list(user.access_groups.values_list('name', flat=True)) == [MALE]

    call_command('basir_set_user_access', '--email', 'MALE@mail.com', '--groups', f'{MALE},{FEMALE}')
    assert set(user.access_groups.values_list('name', flat=True)) == {MALE, FEMALE}
    assert UserAccess.objects.get(user=user).role == 'labeler'  # unchanged

    call_command('basir_set_user_access', '--email', 'male@mail.com', '--role', 'none', '--groups', '')
    assert UserAccess.objects.get(user=user).role is None and not user.access_groups.exists()


# --- flag off = upstream behaviour ----------------------------------------------------------------------------------


@pytest.mark.parametrize('auth', CLIENTS)
def test_access_control_off_is_upstream_behaviour(world, auth):
    labeler = world.user(role='labeler', groups=[MALE], is_superuser=True)
    client = CLIENTS[auth](labeler)

    assert project_ids(client.get('/api/projects/')) == {p.id for p in world.projects.values()}
    for group in (FEMALE, MAIL):
        for name, url in scoped_urls(world, group).items():
            response = client.get(url)
            if 'resolve' not in name and 'presign' not in name:
                assert response.status_code == 200, (name, response.status_code)
    assert client.post('/api/projects/', {'title': 'upstream'}, format='json').status_code == 201
    assert client.get('/api/webhooks/').status_code == 200
    assert client.delete(f'/api/annotations/{world.annotations[FEMALE].id}/').status_code == 204
    # the project response is the upstream one unless access_groups is asked for
    assert 'access_groups' not in client.get(f'/api/projects/{world.projects[MALE].id}/').json()
    assert client.get('/api/projects/?include=id,access_groups').json()['results'][0]['access_groups'] is not None
    data = client.get('/api/current-user/whoami').json()
    assert 'projects.create' in data['permissions'] and data['ls_access']['can_manage'] is True


@enabled
def test_label_links_are_limited_to_the_users_projects(world):
    from labels_manager.models import Label, LabelLink

    label = Label.objects.create(
        title='shared', value={'choices': ['a']}, organization=world.org, created_by=world.owner
    )
    for group in (MALE, FEMALE):
        LabelLink.objects.create(label=label, project=world.projects[group], from_name='c')
    client = session_client(world.user(role='labeler', groups=[MALE]))

    response = client.get('/api/label_links/')
    assert response.status_code == 200
    assert {link['project'] for link in response.json()['results']} == {world.projects[MALE].id}
    assert client.get(f'/api/label_links/?project={world.projects[FEMALE].id}').status_code == 404


@enabled
def test_page_tells_the_ui_the_role(world):
    page = session_client(world.user(role='labeler', groups=[MALE])).get('/projects/').content.decode()
    assert '"can_manage": false' in page and '"role": "labeler"' in page
    page = session_client(world.user(role='admin')).get('/projects/').content.decode()
    assert '"can_manage": true' in page
