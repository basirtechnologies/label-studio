"""Basir DW-907: the Label Server's service account.

    python manage.py basir_create_service_account --email label-server@basir.local --organization 5
    python manage.py basir_create_service_account --email label-server@basir.local --organization 5 --rotate-token

Creates (or updates) a local account with the LS role admin, adds it to the organization, makes it its active
organization and prints its legacy API token (``Authorization: Token <token>``). The account has no usable password:
it can't log in to the UI, it only calls the API. Safe to re-run: it keeps the same token unless --rotate-token.
Legacy API tokens are switched on for the organization if they were off (otherwise the token is refused).
"""

from access_control.models import LSRole
from access_control.services import set_user_access
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from organizations.models import Organization, OrganizationMember
from rest_framework.authtoken.models import Token
from users.models import User


class Command(BaseCommand):
    help = "Create the Label Server's service account (LS admin) and print its legacy API token (Basir DW-907)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--email', required=True, help='Email of the service account, e.g. label-server@basir.local'
        )
        parser.add_argument('--organization', type=int, required=True, help='ID of the organization')
        parser.add_argument('--name', default='Label Server', help='First name shown in the UI')
        parser.add_argument(
            '--rotate-token', action='store_true', help='Replace the token (the old one stops working)'
        )
        parser.add_argument('--token-only', action='store_true', help='Print only the token (for scripts)')

    @transaction.atomic
    def handle(self, *args, **options):
        org = Organization.objects.filter(id=options['organization']).first()
        if org is None:
            raise CommandError(f'Organization {options["organization"]} does not exist')
        email = options['email'].strip().lower()

        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User.objects.create_user(email=email, username=email.split('@')[0], first_name=options['name'])
            user.set_unusable_password()
            user.save(update_fields=['password'])
        elif not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])

        membership = OrganizationMember.objects.filter(user=user, organization=org).first()
        if membership is None:
            OrganizationMember.objects.create(user=user, organization=org)
        elif membership.deleted_at is not None:
            OrganizationMember.objects.filter(pk=membership.pk).update(deleted_at=None)
        if user.active_organization_id != org.id:
            User.objects.filter(pk=user.pk).update(active_organization=org)

        set_user_access(user, role=LSRole.ADMIN)

        notes = []
        jwt = getattr(org, 'jwt', None)
        if jwt is not None and not jwt.legacy_api_tokens_enabled:
            jwt.legacy_api_tokens_enabled = True
            jwt.save(update_fields=['legacy_api_tokens_enabled'])
            notes.append(f'legacy API tokens switched on for organization {org.id}')

        if options['rotate_token']:
            Token.objects.filter(user=user).delete()
            notes.append('token rotated: the previous token no longer works')
        token, _ = Token.objects.get_or_create(user=user)

        if options['token_only']:
            self.stdout.write(token.key)
            return
        self.stdout.write(
            f'{"Created" if created else "Updated"} service account {user.email} (id {user.id}): '
            f'LS role admin, member of organization {org.id} {org.title!r}'
        )
        for note in notes:
            self.stdout.write(f'  {note}')
        self.stdout.write(f'Legacy API token: {token.key}')
        self.stdout.write(f'Use it as: Authorization: Token {token.key}')
