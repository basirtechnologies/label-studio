"""DW-895: annotation writes preserve the complete RLE payload and original author."""

import numpy as np
import pytest
from access_control.services import set_user_access
from django.test import override_settings
from label_studio_sdk.converter.brush import decode_rle, mask2rle

from .test_access_control import CLIENTS, MAIL, World, jwt_tokens_on  # noqa: F401

pytestmark = pytest.mark.django_db


def masks(updated=False):
    result = []
    for page, (width, height) in enumerate([(64, 48), (80, 60)]):
        for obj in range(3):
            mask = np.zeros((height, width), dtype=np.uint8)
            mask[5:20, 3 + obj * 18:12 + obj * 18] = 255
            if updated:
                mask[15:30, 3 + obj * 18:12 + obj * 18] = 255
                mask[35:40, 3 + obj * 18:8 + obj * 18] = 255
                mask[8:10, 5 + obj * 18:7 + obj * 18] = 0
            result.append({
                'id': f'mask-{page}-{obj}', 'from_name': 'tag1', 'to_name': 'pages',
                'type': 'brushlabels', 'item_index': page, 'original_width': width,
                'original_height': height, 'image_rotation': 0,
                'value': {'format': 'rle', 'rle': mask2rle(mask), 'brushlabels': ['Object']},
            })
    return result


def assert_pixels(actual, expected):
    assert len(actual) == len(expected)
    for row, source in zip(actual, expected):
        assert row['id'] == source['id']
        assert row['item_index'] == source['item_index']
        assert row['original_width'] == source['original_width']
        assert row['original_height'] == source['original_height']
        assert row['value']['brushlabels'] == source['value']['brushlabels']
        np.testing.assert_array_equal(decode_rle(row['value']['rle']), decode_rle(source['value']['rle']))


@override_settings(BASIR_ACCESS_CONTROL_ENABLED=True)
@pytest.mark.parametrize('auth', CLIENTS)
@pytest.mark.parametrize('method', ['patch', 'put'])
def test_full_mask_pixels_survive_submit_update_and_retrieve(auth, method):
    world = World()
    editor = world.user(role='labeler', groups=[MAIL])
    client = CLIENTS[auth](world.owner)
    set_user_access(world.owner, role='admin')
    task = world.tasks[MAIL]
    original = masks()
    response = client.post(f'/api/tasks/{task.id}/annotations/', {'result': original}, format='json')
    assert response.status_code == 201, response.content
    annotation_id = response.json()['id']
    assert_pixels(response.json()['result'], original)
    client = CLIENTS[auth](editor)
    updated = masks(updated=True)
    response = getattr(client, method)(f'/api/annotations/{annotation_id}/', {'result': updated}, format='json')
    assert response.status_code == 200, response.content
    assert_pixels(response.json()['result'], updated)
    reopened = client.get(f'/api/annotations/{annotation_id}/').json()
    assert_pixels(reopened['result'], updated)
    assert reopened['completed_by'] == world.owner.id
    assert reopened['updated_by'] == editor.id
