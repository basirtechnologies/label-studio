"""Basir DW-907: set the LS role and access groups of a (local) account.

    python manage.py basir_set_user_access --email male@mail.com --role labeler --groups ls-sightence-male
    python manage.py basir_set_user_access --email admin@example.com --role admin
    python manage.py basir_set_user_access --email someone@example.com --groups ""     # remove all groups
    python manage.py basir_set_user_access --email someone@example.com --role none     # remove the role

--groups replaces the user's groups (comma-separated); leave it out to keep them. Unknown groups are created.
"""

from access_control.models import LSRole
from access_control.services import UNSET, get_user_access, set_user_access
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from users.models import User


class Command(BaseCommand):
    help = 'Set the LS role (admin/labeler) and access groups of a user (Basir DW-907)'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True, help='Email of the user')
        parser.add_argument('--role', choices=[*LSRole.values, 'none'], help='LS role; "none" removes it')
        parser.add_argument(
            '--groups', help='Comma-separated access groups, replacing the current ones ("" removes all)'
        )

    def handle(self, *args, **options):
        email = options['email'].strip()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f'No user with email {email}')

        role = UNSET
        if options['role'] is not None:
            role = None if options['role'] == 'none' else options['role']
        groups = UNSET
        if options['groups'] is not None:
            groups = [name for name in options['groups'].split(',') if name.strip()]

        if role is UNSET and groups is UNSET:
            current = get_user_access(user)
        else:
            try:
                current = set_user_access(user, role=role, groups=groups)
            except ValidationError as e:
                raise CommandError('; '.join(e.messages))

        self.stdout.write(
            f'{user.email}: role={current["role"] or "none"} '
            f'groups={",".join(current["access_groups"]) or "-"}'
            + (f' keycloak_sub={current["keycloak_sub"]}' if current['keycloak_sub'] else '')
        )
