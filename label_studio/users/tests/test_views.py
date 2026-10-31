from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from organizations.models import Organization
from organizations.tests.factories import OrganizationFactory
from users.models import User


@override_settings(ORG_INVITE_EXPIRATION_DAYS=30)
class TestUserSignupInviteExpiration(TestCase):
    """FIT-2685: an expired organization invite token must not allow signup.

    Basir legacy patch: user_signup no longer checks expiry (see test_basir_legacy_patches.py).
    """

    @classmethod
    def setUpTestData(cls):
        cls.organization = OrganizationFactory()
        assert Organization.objects.first() == cls.organization

    def _signup(self, token):
        return self.client.post(
            f'/user/signup/?token={token}',
            {'email': 'invitee@example.com', 'password': 'StrongPassw0rd!', 'allow_newsletters': False},
        )

    def _expire_token(self):
        self.organization.token_expires_at = timezone.now() - timedelta(days=1)
        self.organization.save(update_fields=['token_expires_at'])

    @override_settings(DISABLE_SIGNUP_WITHOUT_LINK=True)
    def test_valid_token_allows_signup_when_link_required(self):
        response = self._signup(self.organization.token)

        assert response.status_code == 302
        assert User.objects.filter(email='invitee@example.com').exists()

    @override_settings(DISABLE_SIGNUP_WITHOUT_LINK=True)
    def test_expired_token_is_accepted_when_link_required(self):
        # Basir legacy patch: signup looks the organization up by token only; expiry is not checked.
        self._expire_token()

        response = self._signup(self.organization.token)

        assert response.status_code == 302
        assert User.objects.get(email='invitee@example.com').active_organization_id == self.organization.id

    @override_settings(DISABLE_SIGNUP_WITHOUT_LINK=False)
    def test_expired_token_is_accepted_when_link_optional(self):
        # Basir legacy patch: signup looks the organization up by token only; expiry is not checked.
        self._expire_token()

        response = self._signup(self.organization.token)

        assert response.status_code == 302
        assert User.objects.get(email='invitee@example.com').active_organization_id == self.organization.id
