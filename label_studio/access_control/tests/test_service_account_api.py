"""Basir DW-907: the Label Server's service account (LS admin, not a superuser) with access control on.

Runs through every call the Label Server makes with its legacy token. S3 is mocked with moto; the ML backend's
health and setup calls are mocked (there is no ML backend in the tests).
"""

import io
from types import SimpleNamespace
from unittest import mock

import boto3
import pytest
from django.core.management import call_command
from django.test import override_settings
from io_storages.s3.models import S3ImportStorage
from moto import mock_s3
from organizations.models import Organization
from projects.models import Project
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from tasks.models import Task
from users.models import User
from webhooks.models import Webhook

pytestmark = pytest.mark.django_db
LABEL_CONFIG = (
    '<View><Image name="image" value="$image"/><Choices name="c" toName="image"><Choice value="ok"/></Choices></View>'
)


@pytest.fixture
def s3_bucket(monkeypatch):
    for name in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SECURITY_TOKEN', 'AWS_SESSION_TOKEN'):
        monkeypatch.setenv(name, 'testing')
    with mock_s3():
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='sightence-male-scans')
        for key in ('scans/1.png', 'scans/2.png'):
            s3.put_object(Bucket='sightence-male-scans', Key=key, Body=b'png')
        yield 'sightence-male-scans'


@pytest.fixture
def org():
    owner = User.objects.create_user(email='admin@basir.local', password='x', username='admin')
    org = Organization.create_organization(created_by=owner, title='Label Studio mail_scanner')
    owner.active_organization = org
    owner.save(update_fields=['active_organization'])
    return org


@pytest.fixture
def label_server(org):
    out = io.StringIO()
    call_command(
        'basir_create_service_account',
        '--email',
        'label-server@basir.local',
        '--organization',
        str(org.id),
        '--token-only',
        stdout=out,
    )
    user = User.objects.get(email='label-server@basir.local')
    assert not user.is_superuser and not user.is_staff
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {out.getvalue().strip()}')
    return client, user


ML_OK = SimpleNamespace(is_error=False, status_code=200, error_message=None, response={'model_version': 'v1'})


@override_settings(BASIR_ACCESS_CONTROL_ENABLED=True)
@mock.patch('ml.serializers.validate_upload_url', lambda *args, **kwargs: None)
@mock.patch('ml.models.MLBackend.healthcheck_', return_value=ML_OK)
@mock.patch('ml.models.MLBackend.setup_', return_value=ML_OK)
def test_label_server_calls_with_access_control_on(_setup, _health, org, label_server, s3_bucket):
    client, service_user = label_server
    member = User.objects.create_user(email='male@mail.com', password='x', username='male', is_superuser=True)
    org.add_user(member)

    def ok(response, *codes):
        assert response.status_code in (codes or (200,)), (
            response.request['PATH_INFO'],
            response.status_code,
            response.content[:400],
        )
        return response.json() if response.content else None

    # whoami and org members
    assert ok(client.get('/api/current-user/whoami'))['ls_access']['role'] == 'admin'
    assert ok(client.get(f'/api/users/{member.id}/'))['email'] == 'male@mail.com'
    assert ok(client.get(f'/api/users/{org.created_by_id}/'))['email'] == 'admin@basir.local'

    # projects
    project = ok(
        client.post(
            '/api/projects/',
            {'title': 'Sightence male 2026-11', 'label_config': LABEL_CONFIG, 'access_groups': ['ls-sightence-male']},
            format='json',
        ),
        201,
    )
    pid = project['id']
    assert project['access_groups'] == ['ls-sightence-male']
    assert ok(client.get(f'/api/projects/{pid}/'))['title'] == 'Sightence male 2026-11'
    assert (
        ok(client.patch(f'/api/projects/{pid}/', {'description': 'from DWH'}, format='json'))['description']
        == 'from DWH'
    )

    # tasks
    task = ok(
        client.post(
            '/api/tasks/', {'project': pid, 'data': {'image': 's3://sightence-male-scans/x.png'}}, format='json'
        ),
        201,
    )
    assert ok(client.get(f'/api/tasks/{task["id"]}/'))['data']['image'].endswith('x.png')
    ok(
        client.patch(
            f'/api/tasks/{task["id"]}/', {'data': {'image': 's3://sightence-male-scans/y.png'}}, format='json'
        )
    )
    ok(client.delete(f'/api/tasks/{task["id"]}/'), 204)
    assert not Task.objects.filter(id=task['id']).exists()

    # webhooks
    webhook = ok(
        client.post(
            '/api/webhooks/',
            {
                'project': pid,
                'url': 'http://label-server.example:8000/hooks',
                'send_payload': True,
                'actions': ['ANNOTATION_CREATED'],
            },
            format='json',
        ),
        201,
    )
    assert Webhook.objects.get(id=webhook['id']).organization_id == org.id

    # S3 import storage: create, update, sync
    storage = ok(
        client.post(
            '/api/storages/s3/',
            {'project': pid, 'bucket': s3_bucket, 'prefix': 'scans', 'use_blob_urls': True, 'title': 'male scans'},
            format='json',
        ),
        201,
    )
    sid = storage['id']
    ok(client.patch(f'/api/storages/s3/{sid}', {'title': 'male scans (renamed)', 'project': pid}, format='json'))
    ok(client.post(f'/api/storages/s3/{sid}/sync'), 200)
    assert S3ImportStorage.objects.get(id=sid).title == 'male scans (renamed)'
    assert Task.objects.filter(project_id=pid).count() == 2  # the two scans of the bucket

    # ML backend
    ml = ok(
        client.post(
            '/api/ml/', {'project': pid, 'url': 'http://ml-backend.example:9090', 'title': 'model'}, format='json'
        ),
        201,
    )
    assert ml['url'] == 'http://ml-backend.example:9090'

    # delete the project last
    ok(client.delete(f'/api/projects/{pid}/'), 204)
    assert not Project.objects.filter(id=pid).exists()
    assert Token.objects.filter(user=service_user).exists()
