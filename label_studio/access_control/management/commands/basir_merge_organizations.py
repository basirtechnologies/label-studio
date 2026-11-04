"""Basir DW-907: merge organizations into one (one-time data migration).

    python manage.py basir_merge_organizations --target-org 5 \\
        --map 7=ls-sightence-male 3=ls-sightence-female 5=ls-mail-scanner [--owners-admin] [--dry-run]

Moves everything that references each mapped source organization to the target organization in one transaction
(found through Django model meta), gives the projects and members their access groups, makes the source members
members of the target and switches their active organization. Never deletes or renumbers anything; source
organizations stay, empty. A second run changes nothing. See access_control/merge.py for the rules.
"""

from access_control.merge import MergeError, apply_plan, build_plan, counts_report, format_report
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from organizations.models import Organization


def parse_mapping(values):
    mapping = {}
    for value in values:
        org_id, sep, groups = value.partition('=')
        if not sep or not org_id.strip().isdigit():
            raise CommandError(f'--map expects <org_id>=<group>[,<group>], got {value!r}')
        names = [name.strip() for name in groups.split(',') if name.strip()]
        if not names:
            raise CommandError(f'--map {value!r}: no access group')
        mapping.setdefault(int(org_id), []).extend(names)
    return mapping


class Command(BaseCommand):
    help = 'Merge organizations into one and give their projects and members access groups (Basir DW-907)'

    def add_arguments(self, parser):
        parser.add_argument('--target-org', type=int, required=True, help='ID of the organization everything moves to')
        parser.add_argument(
            '--map',
            nargs='+',
            required=True,
            metavar='ORG_ID=GROUP[,GROUP]',
            help='Access groups per organization; include the target to give its own projects/members groups',
        )
        parser.add_argument(
            '--owners-admin',
            action='store_true',
            help='Give the users who created the mapped organizations the LS role admin',
        )
        parser.add_argument('--dry-run', action='store_true', help='Print what would change and change nothing')

    def handle(self, *args, **options):
        mapping = parse_mapping(options['map'])
        try:
            plan = build_plan(options['target_org'], mapping, owners_admin=options['owners_admin'])
        except MergeError as e:
            raise CommandError(str(e))

        org_ids = [plan.target.id] + [org.id for org in plan.sources]
        titles = dict(Organization.objects.filter(id__in=org_ids).values_list('id', 'title'))
        before = counts_report(org_ids)
        self.stdout.write(f'Target organization {plan.target.id} {plan.target.title!r}')
        self.stdout.write('Before:\n' + format_report(before, titles))
        self._print_plan(plan, titles)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run: nothing was changed.'))
            return
        if not plan.has_changes:
            self.stdout.write(self.style.SUCCESS('Nothing to change: the organizations are already merged.'))
            return

        with transaction.atomic():
            apply_plan(plan)
            after = counts_report(org_ids)
            self.stdout.write('After:\n' + format_report(after, titles))
            self._check_totals(before, after)  # raises, and so rolls the merge back, on any difference
        self.stdout.write(self.style.SUCCESS('Merge done.'))

    def _print_plan(self, plan, titles):
        w = self.stdout.write
        w('Plan:')
        for org in plan.sources:
            moving = {label: count for label, count in plan.moves[org.id].items() if count}
            w(
                f'  organization {org.id} {titles.get(org.id, "")!r} -> {plan.target.id}, groups {",".join(plan.mapping[org.id])}'
            )
            if moving:
                for label, count in moving.items():
                    w(f'    move {count} {label}')
            else:
                w('    nothing to move')
        for user, source_id, restored in plan.memberships_added:
            w(
                f'  {"restore" if restored else "add"} membership of {user.email} (from {source_id}) in {plan.target.id}'
            )
        for user in plan.active_switched:
            w(f'  active organization of {user.email} -> {plan.target.id}')
        for user, old, new in plan.roles_set:
            w(f'  LS role of {user.email}: {old or "none"} -> {new}')
        for user, names in plan.user_groups_added:
            w(f'  groups of {user.email}: + {",".join(names)}')
        for project_id, names in plan.project_groups_added:
            w(f'  groups of project {project_id}: + {",".join(names)}')
        for setting in plan.jwt_enabled:
            w(f'  target organization: {setting} = true (a source organization had it, its tokens must keep working)')
        if not plan.has_changes:
            w('  no changes')

    def _check_totals(self, before, after):
        def totals(report):
            projects = {
                pid: (p['tasks'], p['annotations']) for data in report.values() for pid, p in data['projects'].items()
            }
            return projects, sum(d['webhooks'] for d in report.values()), sum(d['storages'] for d in report.values())

        if totals(before) != totals(after):
            raise CommandError('Totals changed during the merge; nothing was changed (rolled back)')
        self.stdout.write(
            'Totals check: every project keeps its ID, tasks and annotations; webhooks and storages kept.'
        )
