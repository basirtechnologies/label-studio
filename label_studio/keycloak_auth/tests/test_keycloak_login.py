"""Basir DW-908: Keycloak (OIDC) login, with a mocked Keycloak.

The whole browser flow runs through the real views: /oidc/authenticate/ redirects to Keycloak, Keycloak redirects
back to /oidc/callback/ with a code, Label Studio exchanges it (token endpoint), checks the RS256 ID token against
the JWKS endpoint and reads userinfo. The browser-facing and the internal Keycloak URLs differ, as in production.
"""

import json
import time
import uuid
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import requests_mock
from access_control.models import UserAccess
from access_control.services import set_user_access
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.test import Client, override_settings
from organizations.models import Organization, OrganizationMember
from projects.tests.factories import ProjectFactory
from rest_framework.authtoken.models import Token
from users.models import User

pytestmark = pytest.mark.django_db

BROWSER_REALM = 'http://keycloak.example:9090/realms/data_service'
INTERNAL_REALM = 'http://keycloak:8080/realms/data_service'
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = 'test-key'

OIDC = dict(
    OIDC_ENABLED=True,
    OIDC_RP_CLIENT_ID='label-studio',
    OIDC_RP_CLIENT_SECRET='secret',
    OIDC_OP_BASE_URL=BROWSER_REALM,
    OIDC_OP_INTERNAL_BASE_URL=INTERNAL_REALM,
    OIDC_OP_AUTHORIZATION_ENDPOINT=f'{BROWSER_REALM}/protocol/openid-connect/auth',
    OIDC_OP_LOGOUT_ENDPOINT=f'{BROWSER_REALM}/protocol/openid-connect/logout',
    OIDC_OP_TOKEN_ENDPOINT=f'{INTERNAL_REALM}/protocol/openid-connect/token',
    OIDC_OP_USER_ENDPOINT=f'{INTERNAL_REALM}/protocol/openid-connect/userinfo',
    OIDC_OP_JWKS_ENDPOINT=f'{INTERNAL_REALM}/protocol/openid-connect/certs',
    LOCAL_LOGIN_ALLOWED_EMAILS=['admin@basir.local'],
)
oidc_on = override_settings(**OIDC)


@pytest.fixture
def org():
    owner = User.objects.create_user(email='admin@basir.local', password='Local-pass-1', username='admin')
    org = Organization.create_organization(created_by=owner, title='Basir')
    owner.active_organization = org
    owner.save(update_fields=['active_organization'])
    return org


def sign(claims):
    return jwt.encode(claims, KEY, algorithm='RS256', headers={'kid': KID})


class FakeKeycloak:
    """Token, userinfo and JWKS endpoints at the internal URL; remembers what Label Studio asked for."""

    def __init__(self, mocker):
        self.mocker = mocker
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
        jwk.update(kid=KID, alg='RS256', use='sig')
        mocker.get(f'{INTERNAL_REALM}/protocol/openid-connect/certs', json={'keys': [jwk]})

    def user(self, sub=None, email='anna@basir.local', roles=('ls-labeler',), groups=('/ls-sightence-male',), **extra):
        return {
            'sub': sub or str(uuid.uuid4()),
            'email': email,
            'given_name': 'Anna',
            'family_name': 'Berg',
            'preferred_username': 'anna',
            'roles': list(roles),
            'groups': list(groups),
            **extra,
        }

    def login(self, client, user, next_url=None):
        """Run the browser flow; returns the callback response."""
        start = client.get('/oidc/authenticate/' + (f'?next={next_url}' if next_url else ''))
        assert start.status_code == 302
        location = urlparse(start['Location'])
        assert (
            f'{location.scheme}://{location.netloc}{location.path}' == f'{BROWSER_REALM}/protocol/openid-connect/auth'
        )
        query = parse_qs(location.query)
        state, nonce = query['state'][0], query['nonce'][0]

        now = int(time.time())
        id_token = sign(
            {
                'iss': BROWSER_REALM,
                'aud': 'label-studio',
                'sub': user['sub'],
                'email': user['email'],
                'nonce': nonce,
                'iat': now,
                'exp': now + 300,
            }
        )
        access_token = sign(
            {'sub': user['sub'], 'realm_access': {'roles': user['roles'] + ['offline_access']}, 'exp': now + 300}
        )
        userinfo = {k: v for k, v in user.items() if k != 'roles'}
        self.mocker.post(
            f'{INTERNAL_REALM}/protocol/openid-connect/token',
            json={'id_token': id_token, 'access_token': access_token, 'token_type': 'Bearer'},
        )
        self.mocker.get(f'{INTERNAL_REALM}/protocol/openid-connect/userinfo', json=userinfo)
        return client.get('/oidc/callback/', {'code': 'the-code', 'state': state})


@pytest.fixture
def keycloak():
    with requests_mock.Mocker() as mocker:
        yield FakeKeycloak(mocker)


def logged_in_user(client):
    response = client.get('/api/current-user/whoami')
    return response.json() if response.status_code == 200 else None


def login_page_messages(client):
    return client.get('/user/login/').content.decode()


@oidc_on
def test_first_login_creates_the_user_with_role_and_groups(org, keycloak):
    client = Client()
    kc_user = keycloak.user(groups=['/ls-sightence-male', '/ls-mail-scanner', '/other-team', '/parent/ls-nested'])

    response = keycloak.login(client, kc_user)

    assert response.status_code == 302 and response['Location'] == '/'
    user = User.objects.get(email='anna@basir.local')
    assert (user.first_name, user.last_name) == ('Anna', 'Berg')
    assert not user.has_usable_password() and not user.is_superuser
    assert user.active_organization_id == org.id
    assert OrganizationMember.objects.filter(user=user, organization=org).exists()
    access = UserAccess.objects.get(user=user)
    assert (access.role, access.keycloak_sub) == ('labeler', kc_user['sub'])
    assert sorted(user.access_groups.values_list('name', flat=True)) == [
        'ls-mail-scanner',
        'ls-nested',
        'ls-sightence-male',
    ]
    # the token, userinfo and JWKS calls went to the internal Keycloak URL
    assert {r.url.split('/protocol')[0] for r in keycloak.mocker.request_history} == {INTERNAL_REALM}
    # and the session works (Label Studio's session timeout needs last_login)
    assert logged_in_user(client)['email'] == 'anna@basir.local'
    assert logged_in_user(client)['ls_access']['role'] == 'labeler'


@oidc_on
def test_second_login_updates_role_groups_and_names(org, keycloak):
    kc_user = keycloak.user()
    keycloak.login(Client(), kc_user)

    changed = {**kc_user, 'roles': ['ls-admin', 'ls-labeler'], 'groups': ['/ls-sightence-female'], 'given_name': 'Ann'}
    response = keycloak.login(Client(), changed)

    assert response.status_code == 302
    user = User.objects.get(email='anna@basir.local')
    assert User.objects.filter(email='anna@basir.local').count() == 1
    assert UserAccess.objects.get(user=user).role == 'admin'
    assert list(user.access_groups.values_list('name', flat=True)) == ['ls-sightence-female']
    assert user.first_name == 'Ann'


@oidc_on
def test_the_user_is_matched_by_sub_not_by_email(org, keycloak):
    kc_user = keycloak.user()
    keycloak.login(Client(), kc_user)
    keycloak.login(Client(), {**kc_user, 'email': 'anna.berg@basir.local'})  # email changed in Keycloak
    assert User.objects.filter(ls_access__keycloak_sub=kc_user['sub']).count() == 1


@oidc_on
def test_login_without_an_ls_role_is_refused(org, keycloak):
    client = Client()
    response = keycloak.login(client, keycloak.user(roles=['offline_access']))

    assert response.status_code == 302 and response['Location'] == '/user/login/'
    assert not User.objects.filter(email='anna@basir.local').exists()
    assert logged_in_user(client) is None
    assert 'has no Label Studio role (ls-admin or ls-labeler)' in login_page_messages(client)


@oidc_on
def test_an_existing_local_account_is_not_taken_over(org, keycloak):
    local = User.objects.create_user(email='male@mail.com', password='x', username='male')
    client = Client()

    response = keycloak.login(client, keycloak.user(email='Male@Mail.com'))

    assert response['Location'] == '/user/login/'
    assert logged_in_user(client) is None
    assert not UserAccess.objects.filter(user=local, keycloak_sub__isnull=False).exists()
    assert 'already exists and is not linked to Keycloak' in login_page_messages(client)


@oidc_on
def test_a_hand_linked_local_account_logs_in_with_keycloak(org, keycloak):
    local = User.objects.create_user(email='male@mail.com', password='x', username='male')
    kc_user = keycloak.user(email='male@mail.com')
    set_user_access(local, keycloak_sub=kc_user['sub'])

    client = Client()
    keycloak.login(client, kc_user)
    assert logged_in_user(client)['id'] == local.id


@oidc_on
def test_deactivated_or_removed_users_are_refused(org, keycloak):
    kc_user = keycloak.user()
    keycloak.login(Client(), kc_user)
    user = User.objects.get(email='anna@basir.local')

    OrganizationMember.objects.filter(user=user).update(deleted_at='2026-01-01T00:00:00Z')
    client = Client()
    keycloak.login(client, kc_user)
    assert logged_in_user(client) is None and 'removed from the Label Studio organization' in login_page_messages(
        client
    )

    User.objects.filter(pk=user.pk).update(is_active=False)
    client = Client()
    keycloak.login(client, kc_user)
    assert logged_in_user(client) is None


@oidc_on
@override_settings(BASIR_DEFAULT_ORGANIZATION_ID=None)
def test_new_users_join_the_default_organization(org, keycloak):
    other_owner = User.objects.create_user(email='o@x.local', password='x', username='o')
    other = Organization.create_organization(created_by=other_owner, title='Other')

    client = Client()
    keycloak.login(client, keycloak.user())  # two organizations and no BASIR_DEFAULT_ORGANIZATION_ID
    assert logged_in_user(client) is None and 'BASIR_DEFAULT_ORGANIZATION_ID' in login_page_messages(client)

    with override_settings(BASIR_DEFAULT_ORGANIZATION_ID=other.id):
        keycloak.login(Client(), keycloak.user())
    assert User.objects.get(email='anna@basir.local').active_organization_id == other.id


@oidc_on
@override_settings(BASIR_ACCESS_CONTROL_ENABLED=True)
def test_keycloak_groups_drive_access_control(org, keycloak):
    male = ProjectFactory(organization=org, created_by=org.created_by)
    female = ProjectFactory(organization=org, created_by=org.created_by)
    from access_control.services import set_project_groups

    set_project_groups(male, ['ls-sightence-male'])
    set_project_groups(female, ['ls-sightence-female'])
    client = Client()
    keycloak.login(client, keycloak.user(groups=['/ls-sightence-male']))

    assert [p['id'] for p in client.get('/api/projects/').json()['results']] == [male.id]
    assert client.get(f'/api/projects/{female.id}/').status_code == 404


# --- local login allow-list -------------------------------------------------------------------------------------


@oidc_on
def test_local_login_only_for_allow_listed_emails(org):
    User.objects.create_user(email='male@mail.com', password='Local-pass-1', username='male')

    client = Client()
    response = client.post('/user/login/', {'email': 'Admin@basir.local', 'password': 'Local-pass-1'})
    assert response.status_code == 302 and logged_in_user(client)['email'] == 'admin@basir.local'

    client = Client()
    response = client.post('/user/login/', {'email': 'male@mail.com', 'password': 'Local-pass-1'})
    assert response.status_code == 200 and logged_in_user(client) is None
    assert 'use “Log in with Keycloak”' in response.content.decode()

    # the Django admin login goes through the same backends
    client = Client()
    client.post('/admin/login/', {'username': 'male@mail.com', 'password': 'Local-pass-1'})
    assert '_auth_user_id' not in client.session


@oidc_on
def test_existing_local_sessions_outside_the_allow_list_end(org):
    user = User.objects.create_user(email='male@mail.com', password='Local-pass-1', username='male')
    org.add_user(user)
    with override_settings(OIDC_ENABLED=False):
        client = Client()
        client.post('/user/login/', {'email': 'male@mail.com', 'password': 'Local-pass-1'})
        assert logged_in_user(client)['id'] == user.id
    assert logged_in_user(client) is None  # OIDC switched on: the email/password session ends


@oidc_on
def test_login_page_shows_the_keycloak_button(org):
    page = Client().get('/user/login/').content.decode()
    assert 'Log in with Keycloak' in page and '/oidc/authenticate/' in page


# --- logout -----------------------------------------------------------------------------------------------------


@oidc_on
def test_logout_ends_the_keycloak_session(org, keycloak):
    client = Client()
    keycloak.login(client, keycloak.user())
    id_token = client.session['oidc_id_token']

    response = client.get('/logout')

    assert response.status_code == 302
    location = urlparse(response['Location'])
    assert f'{location.scheme}://{location.netloc}{location.path}' == f'{BROWSER_REALM}/protocol/openid-connect/logout'
    query = parse_qs(location.query)
    assert query['client_id'] == ['label-studio'] and query['id_token_hint'] == [id_token]
    assert query['post_logout_redirect_uri'] == ['http://testserver/user/login/']
    assert logged_in_user(client) is None


@oidc_on
def test_local_logout_stays_local(org):
    client = Client()
    client.post('/user/login/', {'email': 'admin@basir.local', 'password': 'Local-pass-1'})
    response = client.get('/logout')
    assert not response['Location'].startswith(BROWSER_REALM)


# --- API tokens and OIDC off ------------------------------------------------------------------------------------


@oidc_on
def test_api_tokens_keep_working(org):
    user = User.objects.create_user(email='label-server@basir.local', username='label-server')
    org.add_user(user)
    user.active_organization = org
    user.save()
    org.jwt.legacy_api_tokens_enabled = True
    org.jwt.save()
    token, _ = Token.objects.get_or_create(user=user)

    client = Client(HTTP_AUTHORIZATION=f'Token {token.key}')
    assert client.get('/api/projects/').status_code == 200


def test_disabled_is_upstream_behaviour(org):
    assert settings.OIDC_ENABLED is False
    assert Client().get('/oidc/authenticate/').status_code == 404
    assert Client().get('/oidc/callback/', {'code': 'x', 'state': 'y'}).status_code == 404
    assert 'Log in with Keycloak' not in Client().get('/user/login/').content.decode()
    # any local account logs in with email and password; logout stays local
    org.add_user(User.objects.create_user(email='male@mail.com', password='Local-pass-1', username='male'))
    client = Client()
    assert client.post('/user/login/', {'email': 'male@mail.com', 'password': 'Local-pass-1'}).status_code == 302
    assert logged_in_user(client)['email'] == 'male@mail.com'
    assert client.get('/logout')['Location'] in ('/', settings.HOSTNAME.rstrip('/') + '/')
