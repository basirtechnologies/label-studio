"""Tests for the Basir legacy patches ported from our previous fork.

1. `label-studio start/init --username X` gives the user its own organization.
2. Signup joins the organization of the invite token (and leaves the default one);
   login and signup do not check CSRF.
3. A webhook that does not answer 201 raises, and the exception reaches the caller.
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
from webhooks.utils import run_webhook_sync

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
        with pytest.raises(Exception) as excinfo:
            run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED, {'data': 'x'})
    assert type(excinfo.value) is Exception
    assert str(excinfo.value) == message


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


@pytest.mark.django_db
def test_rejected_webhook_fails_annotation_submit(configured_project, business_client, webhook):
    # Without Redis, webhooks run synchronously in the request, so the exception reaches the API call.
    task = configured_project.tasks.first()
    payload = {
        'result': [
            {
                'value': {'choices': ['class_A']},
                'id': 'basir1',
                'from_name': 'text_class',
                'to_name': 'text',
                'type': 'choices',
            }
        ],
        'project': configured_project.id,
    }
    annotations_before = task.annotations.count()
    with requests_mock.Mocker(real_http=True) as m:
        # The project's ML backend auto-created a webhook for all actions; let it accept so only ours rejects.
        m.post('http://localhost:8999/webhook', status_code=201, json={})
        m.post(webhook.url, status_code=400, json={'message': 'backend rejected annotation'})
        response = business_client.post(
            f'/api/tasks/{task.id}/annotations?project={configured_project.id}',
            data=json.dumps(payload),
            content_type='application/json',
        )

    # The API's exception handler turns the exception into a 500 with the backend's message.
    assert response.status_code == 500
    assert response.json()['detail'] == 'backend rejected annotation'
    assert any(r.url == webhook.url for r in m.request_history)
    # The webhook runs after the annotation is saved, so the annotation still exists (same as the legacy fork).
    assert task.annotations.count() == annotations_before + 1


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
        with pytest.raises(Exception, match='rejected'):
            run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED)
    assert m.call_count == 2


@pytest.mark.django_db
def test_auto_disable_off_with_zero_threshold(webhook, settings):
    settings.WEBHOOK_MAX_CONSECUTIVE_FAILURES = 0
    with requests_mock.Mocker() as m:
        m.post(webhook.url, status_code=400, json={'message': 'rejected'})
        for _ in range(60):
            with pytest.raises(Exception, match='rejected'):
                run_webhook_sync(webhook, WebhookAction.PROJECT_CREATED)
    webhook.refresh_from_db()
    assert webhook.is_active is True
    assert not webhook.consecutive_failures
