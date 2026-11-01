"""Tests for the Basir legacy patches ported from our previous fork.

1. `label-studio start/init --username X` gives the user its own organization.
2. Signup joins the organization of the invite token (and leaves the default one);
   login and signup do not check CSRF.
3. A webhook that does not answer 201 raises WebhookRejected (HTTP 400); a rejected annotation create/update is
   rolled back.
"""

import json

import pytest
import requests
import requests_mock
from django.test import Client
from organizations.models import Organization, OrganizationMember
from server import _create_user
from users.models import User
from webhooks.models import Webhook, WebhookAction
from webhooks.utils import WebhookRejected, run_webhook_sync

from label_studio.core.argparser import parse_input_args

# ---------------------------------------------------------------- 1. _create_user


def _cli_args(email):
    return parse_input_args(['init', 'test', '--username', email, '--password', '12345678'])


def _make_default_org():
    owner = User.objects.create_user(email='owner@example.com', password='12345678')
    return Organization.create_organization(created_by=owner, title='Label Studio')


@pytest.mark.django_db
def test_create_user_gets_own_organization():
    default_org = _make_default_org()

    user = _create_user(_cli_args('alice@example.com'), {})

    user.refresh_from_db()
    own_org = user.active_organization
    assert own_org is not None
    assert own_org.id != default_org.id
    assert own_org.title == 'Label Studio alice'
    assert own_org.created_by_id == user.id
    assert own_org.has_user(user)
    assert not default_org.has_user(user)
    assert list(OrganizationMember.objects.filter(user=user).values_list('organization_id', flat=True)) == [own_org.id]


@pytest.mark.django_db
def test_create_user_on_empty_database():
    # No organization yet: the user's own org is also the first one; remove_user + add_user must leave it a member.
    user = _create_user(_cli_args('bob@example.com'), {})

    user.refresh_from_db()
    assert Organization.objects.count() == 1
    org = user.active_organization
    assert org.title == 'Label Studio bob'
    assert org.created_by_id == user.id
    assert org.has_user(user)


@pytest.mark.django_db(transaction=True)
def test_create_user_is_idempotent_on_restart():
    # transaction=True: the second call goes through _create_user's `except IntegrityError` for the existing
    # user, which would break pytest's wrapping transaction (it is fine in production autocommit mode).
    # The app container runs `label-studio init` on every start, so _create_user runs again for an existing user.
    _make_default_org()
    first = _create_user(_cli_args('carol@example.com'), {})
    first.refresh_from_db()
    org_id = first.active_organization_id
    org_count = Organization.objects.count()

    again = _create_user(_cli_args('carol@example.com'), {})

    again.refresh_from_db()
    assert again.id == first.id
    assert again.active_organization_id == org_id
    assert Organization.objects.count() == org_count
    assert list(OrganizationMember.objects.filter(user=again).values_list('organization_id', flat=True)) == [org_id]


# ---------------------------------------------------------------- 2. signup / login


def _second_org():
    owner = User.objects.create_user(email='team-b-owner@example.com', password='12345678')
    return Organization.create_organization(created_by=owner, title='Team B')


@pytest.mark.django_db
def test_signup_with_token_joins_token_org_and_leaves_default(business_client, client):
    default_org = Organization.objects.first()
    team_b = _second_org()
    assert default_org.id != team_b.id

    response = client.post(
        f'/user/signup/?token={team_b.token}', data={'email': 'new@example.com', 'password': 'test_password'}
    )

    assert response.status_code == 302
    user = User.objects.get(email='new@example.com')
    assert user.active_organization_id == team_b.id
    assert team_b.has_user(user)
    assert not default_org.has_user(user)


@pytest.mark.django_db
def test_signup_with_default_org_token_stays_in_default_org(business_client, client):
    default_org = Organization.objects.first()

    response = client.post(
        f'/user/signup/?token={default_org.token}', data={'email': 'new@example.com', 'password': 'test_password'}
    )

    assert response.status_code == 302
    user = User.objects.get(email='new@example.com')
    assert user.active_organization_id == default_org.id
    assert list(OrganizationMember.objects.filter(user=user).values_list('organization_id', flat=True)) == [
        default_org.id
    ]


@pytest.mark.django_db
def test_signup_with_mixed_case_email_still_joins_token_org(business_client, client):
    # The signup form stores the email lowercased, so the post-signup lookup must use the same normalization.
    team_b = _second_org()

    response = client.post(
        f'/user/signup/?token={team_b.token}', data={'email': ' New.User@Example.com ', 'password': 'test_password'}
    )

    assert response.status_code == 302
    user = User.objects.get(email='new.user@example.com')
    assert user.active_organization_id == team_b.id


@pytest.mark.django_db
@pytest.mark.parametrize('query', ['?token=not-a-real-token', ''])
def test_signup_without_valid_token_fails_on_lookup(business_client, client, query):
    # Legacy behavior: no DISABLE_SIGNUP_WITHOUT_LINK / mismatch checks; Organization.objects.get(token=...) fails.
    with pytest.raises(Organization.DoesNotExist):
        client.post(f'/user/signup/{query}', data={'email': 'new@example.com', 'password': 'test_password'})
    assert not User.objects.filter(email='new@example.com').exists()


@pytest.mark.django_db
def test_first_signup_on_fresh_install_needs_no_token(client):
    # Deviation agreed for the port: with no organization at all, the first user may sign up without a token
    # and gets the first organization (upstream's save_user creates it).
    assert not Organization.objects.exists()

    response = client.post('/user/signup/', data={'email': 'first@example.com', 'password': 'test_password'})

    assert response.status_code == 302
    user = User.objects.get(email='first@example.com')
    assert Organization.objects.count() == 1
    org = Organization.objects.get()
    assert org.created_by_id == user.id
    assert user.active_organization_id == org.id
    assert org.has_user(user)

    # Once an organization exists, the legacy rule applies again: no token, no signup.
    client.logout()
    with pytest.raises(Organization.DoesNotExist):
        client.post('/user/signup/', data={'email': 'second@example.com', 'password': 'test_password'})
    assert not User.objects.filter(email='second@example.com').exists()


@pytest.mark.django_db
def test_fresh_install_signup_with_unknown_token_still_fails(client):
    with pytest.raises(Organization.DoesNotExist):
        client.post('/user/signup/?token=nope', data={'email': 'first@example.com', 'password': 'test_password'})
    assert not Organization.objects.exists()


@pytest.mark.django_db
def test_signup_and_login_do_not_check_csrf(business_client):
    team_b = _second_org()
    # enforce_csrf_checks=1 makes core.middleware.DisableCSRF turn CSRF on for views without their own setting.
    csrf_client = Client(enforce_csrf_checks=True)

    # Control: a view that is not exempt is rejected without a CSRF token.
    response = csrf_client.post('/logout?enforce_csrf_checks=1')
    assert response.status_code == 403

    response = csrf_client.post(
        f'/user/signup/?token={team_b.token}&enforce_csrf_checks=1',
        data={'email': 'csrf-signup@example.com', 'password': 'test_password'},
    )
    assert response.status_code == 302

    login_client = Client(enforce_csrf_checks=True)
    response = login_client.post(
        '/user/login/?enforce_csrf_checks=1', data={'email': 'csrf-signup@example.com', 'password': 'test_password'}
    )
    assert response.status_code == 302
    assert '_auth_user_id' in login_client.session


# ---------------------------------------------------------------- 3. strict webhooks


@pytest.fixture
def webhook(configured_project):
    return Webhook.objects.create(
        organization=configured_project.organization, project=None, url='http://127.0.0.1:8000/basir-hook/'
    )


@pytest.mark.django_db
def test_webhook_201_returns_response(webhook):
    with requests_mock.Mocker() as m:
        m.post(webhook.url, status_code=201, json={})
        response = run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED, {'data': 'x'})
    assert response.status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize(
    'status_code, body, message',
    [
        (200, {'message': 'rejected by backend'}, 'rejected by backend'),
        (400, {'message': 'bad annotation'}, 'bad annotation'),
        (500, {}, 'Unknown error'),
    ],
)
def test_webhook_non_201_raises(webhook, status_code, body, message):
    with requests_mock.Mocker() as m:
        m.post(webhook.url, status_code=status_code, json=body)
        with pytest.raises(WebhookRejected) as excinfo:
            run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED, {'data': 'x'})
    assert excinfo.value.status_code == 400
    assert str(excinfo.value.detail) == message


@pytest.mark.django_db
def test_webhook_non_201_without_json_body_is_swallowed(webhook):
    # Legacy behavior: response.json() raises requests' JSONDecodeError, a RequestException, which was caught.
    with requests_mock.Mocker() as m:
        m.post(webhook.url, status_code=502, text='<html>Bad Gateway</html>')
        assert run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED) is None


@pytest.mark.django_db
def test_webhook_connection_error_is_swallowed(webhook):
    with requests_mock.Mocker() as m:
        m.post(webhook.url, exc=requests.exceptions.ConnectTimeout)
        assert run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED) is None


# ---------------------------------------------------------------- 3b. rejected annotations are rolled back

ML_BACKEND_WEBHOOK = 'http://localhost:8999/webhook'  # auto-created for configured_project's ML backend
LABEL_SERVER_URL = 'http://127.0.0.1:8000/label-server/'


@pytest.fixture
def label_server(configured_project):
    """Our Label Server: a project webhook for ANNOTATION_CREATED / ANNOTATION_UPDATED."""
    hook = Webhook.objects.create(
        organization=configured_project.organization,
        project=configured_project,
        url=LABEL_SERVER_URL,
        send_for_all_actions=False,
    )
    WebhookAction.objects.create(webhook=hook, action=WebhookAction.ANNOTATION_CREATED)
    WebhookAction.objects.create(webhook=hook, action=WebhookAction.ANNOTATION_UPDATED)
    return hook


def _result(choice):
    return [
        {
            'value': {'choices': [choice]},
            'id': 'basir1',
            'from_name': 'text_class',
            'to_name': 'text',
            'type': 'choices',
        }
    ]


def _post_annotation(client, project, task, choice='class_A', **extra):
    return client.post(
        f'/api/tasks/{task.id}/annotations/?project={project.id}',
        data=json.dumps({'result': _result(choice), 'project': project.id, **extra}),
        content_type='application/json',
    )


def _label_server_mock(m, **response):
    m.post(ML_BACKEND_WEBHOOK, status_code=201, json={})  # the ML backend's webhook accepts
    m.post(LABEL_SERVER_URL, **response)


def _task_state(task):
    task.refresh_from_db()
    summary = task.project.summary
    summary.refresh_from_db()
    return {
        'annotations': list(task.annotations.values_list('id', 'result')),
        'is_labeled': task.is_labeled,
        'total_annotations': task.total_annotations,
        'cancelled_annotations': task.cancelled_annotations,
        'summary_created_annotations': dict(summary.created_annotations or {}),
        'summary_created_labels': dict(summary.created_labels or {}),
    }


@pytest.mark.django_db
def test_rejected_annotation_create_is_rolled_back(configured_project, business_client, label_server):
    from tasks.models import AnnotationDraft

    task = configured_project.tasks.first()
    draft = AnnotationDraft.objects.create(task=task, user=business_client.user, result=_result('class_A'))
    before = _task_state(task)

    with requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, status_code=400, json={'message': 'wrong object'})
        response = _post_annotation(business_client, configured_project, task, draft_id=draft.id)

    assert response.status_code == 400, response.content
    assert response.json()['detail'] == 'wrong object'
    assert any(r.url == LABEL_SERVER_URL for r in m.request_history)
    # nothing from the request survives: no annotation row; counters, summary and the draft unchanged
    assert _task_state(task) == before
    assert not task.annotations.exists()
    assert AnnotationDraft.objects.filter(id=draft.id).exists()

    # retrying with the same rejection still leaves no annotation (no duplicates)
    with requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, status_code=400, json={'message': 'wrong object'})
        assert _post_annotation(business_client, configured_project, task).status_code == 400
    assert not task.annotations.exists()


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['patch', 'put'])
def test_rejected_annotation_update_is_rolled_back(configured_project, business_client, label_server, method):
    task = configured_project.tasks.first()
    with requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, status_code=201, json={})
        created = _post_annotation(business_client, configured_project, task, choice='class_A')
    assert created.status_code == 201, created.content
    annotation_id = created.json()['id']
    before = _task_state(task)

    with requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, status_code=400, json={'message': 'wrong object'})
        response = getattr(business_client, method)(
            f'/api/annotations/{annotation_id}/',
            data=json.dumps({'result': _result('class_B')}),
            content_type='application/json',
        )

    assert response.status_code == 400, response.content
    assert response.json()['detail'] == 'wrong object'
    assert _task_state(task) == before  # result still class_A; counters and summary unchanged


@pytest.mark.django_db
def test_accepted_annotation_is_saved(configured_project, business_client, label_server):
    task = configured_project.tasks.first()
    with requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, status_code=201, json={})
        response = _post_annotation(business_client, configured_project, task, choice='class_A')
        assert response.status_code == 201, response.content
        annotation_id = response.json()['id']
        patched = business_client.patch(
            f'/api/annotations/{annotation_id}/',
            data=json.dumps({'result': _result('class_B')}),
            content_type='application/json',
        )
    assert patched.status_code == 200, patched.content
    task.refresh_from_db()
    assert task.is_labeled and task.total_annotations == 1
    assert task.annotations.get().result[0]['value']['choices'] == ['class_B']
    sent = [r.json() for r in m.request_history if r.url == LABEL_SERVER_URL]
    assert [p['action'] for p in sent] == [WebhookAction.ANNOTATION_CREATED, WebhookAction.ANNOTATION_UPDATED]
    assert sent[0]['annotation']['id'] == annotation_id  # the receiver gets the full annotation in the payload


@pytest.mark.django_db
def test_unreachable_webhook_still_saves_annotation(configured_project, business_client, label_server):
    task = configured_project.tasks.first()
    with requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, exc=requests.exceptions.ConnectTimeout)
        response = _post_annotation(business_client, configured_project, task)
    assert response.status_code == 201, response.content
    assert task.annotations.count() == 1


@pytest.mark.django_db
def test_webhook_rejection_is_not_sent_to_sentry(configured_project, business_client, label_server):
    from unittest import mock

    task = configured_project.tasks.first()
    with mock.patch('core.utils.common.logger') as handler_logger, requests_mock.Mocker(real_http=True) as m:
        _label_server_mock(m, status_code=400, json={'message': 'wrong object'})
        assert _post_annotation(business_client, configured_project, task).status_code == 400
    extras = [call.kwargs.get('extra', {}) for call in handler_logger.error.call_args_list]
    assert extras and all(extra.get('sentry_skip') is True for extra in extras)


# ---------------------------------------------------------------- deployment: internal webhook host

BASIR_WEBHOOK_URL = 'http://apis.basir:5050/webhook'


@pytest.fixture
def apis_basir_resolves_to_docker_ip(monkeypatch):
    # In our stack apis.basir is a Docker-network hostname with a private address.
    import socket

    real = socket.gethostbyname
    monkeypatch.setattr(socket, 'gethostbyname', lambda host: '172.18.0.5' if host == 'apis.basir' else real(host))


@pytest.mark.django_db
def test_internal_webhook_blocked_while_ssrf_protection_on(
    configured_project, business_client, settings, apis_basir_resolves_to_docker_ip
):
    settings.SSRF_PROTECTION_ENABLED = True

    response = business_client.post(
        '/api/webhooks/',
        data=json.dumps({'url': BASIR_WEBHOOK_URL, 'project': configured_project.id}),
        content_type='application/json',
    )
    # SsrfBlockedUrlError is answered with 403
    assert response.status_code == 403, response.content
    assert not Webhook.objects.filter(url=BASIR_WEBHOOK_URL).exists()

    webhook = Webhook.objects.create(organization=configured_project.organization, url=BASIR_WEBHOOK_URL)
    with requests_mock.Mocker() as m:
        m.post(BASIR_WEBHOOK_URL, status_code=400, json={'message': 'rejected'})
        # blocked before sending: logged and swallowed, so nothing is raised and nothing is sent
        assert run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED) is None
    assert m.call_count == 0


@pytest.mark.django_db
def test_internal_webhook_works_with_ssrf_protection_off(
    configured_project, business_client, settings, apis_basir_resolves_to_docker_ip
):
    settings.SSRF_PROTECTION_ENABLED = False

    response = business_client.post(
        '/api/webhooks/',
        data=json.dumps({'url': BASIR_WEBHOOK_URL, 'project': configured_project.id}),
        content_type='application/json',
    )
    assert response.status_code == 201, response.content
    webhook = Webhook.objects.get(id=response.json()['id'])

    with requests_mock.Mocker() as m:
        m.post(BASIR_WEBHOOK_URL, status_code=201, json={})
        assert run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED).status_code == 201
        m.post(BASIR_WEBHOOK_URL, status_code=400, json={'message': 'rejected'})
        with pytest.raises(WebhookRejected, match='rejected'):
            run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED)
    assert m.call_count == 2


@pytest.mark.django_db
def test_auto_disable_off_with_zero_threshold(webhook, settings):
    settings.WEBHOOK_MAX_CONSECUTIVE_FAILURES = 0
    with requests_mock.Mocker() as m:
        m.post(webhook.url, status_code=400, json={'message': 'rejected'})
        for _ in range(60):
            with pytest.raises(WebhookRejected, match='rejected'):
                run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED)
    webhook.refresh_from_db()
    assert webhook.is_active is True
    assert not webhook.consecutive_failures
