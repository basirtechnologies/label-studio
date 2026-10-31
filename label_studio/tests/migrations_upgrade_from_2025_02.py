"""Upgrade check: migrate a database with data from the Feb 2025 schema to the latest migrations.

Run by tests/test_migrations_upgrade.py in a separate process, against an empty database chosen by the
usual settings env vars (DJANGO_DB=sqlite + DATABASE_NAME, or DJANGO_DB=default + POSTGRE_*):

1. migrate forward to the migration state of upstream 1ba6f0207
   ("docs: Warn about bad events for custom scripts (#7098)", 2025-02-17, Label Studio 1.16/1.17),
2. insert data with the historical models of that state: user, organization, project, task, annotation
   and Data Manager views with hiddenColumns, two of them sharing one filter group,
3. run `migrate` to the latest migrations (async migration jobs run inline: there is no Redis),
4. check the data with the current models.

With --cleanup-before-filter-parent, data_manager 0013_cleanup runs before 0013_filter_parent (both orders are
valid for Django).

Exit code 0 means the upgrade worked.
"""

import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
LABEL_STUDIO_DIR = os.path.dirname(TESTS_DIR)
# Python puts this script's folder first on sys.path; tests/ has packages (e.g. jwt_auth) that shadow the apps
sys.path = [p for p in sys.path if os.path.abspath(p or '.') != TESTS_DIR]
sys.path.insert(0, LABEL_STUDIO_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.label_studio')
os.environ.setdefault('SENTRY_DSN', '')
os.environ.setdefault('SENTRY_RATE', '0')
os.environ.setdefault('COLLECT_ANALYTICS', '0')

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402

# Latest migration of each local app at upstream 1ba6f0207 (2025-02-17).
# Apps added later (fsm, session_policy) did not exist yet and stay unmigrated until step 3.
BASELINE_2025_02 = {
    'core': '0001_initial',
    'data_export': '0010_alter_convertedformat_export_type',
    'data_import': '0002_alter_fileupload_file',
    'data_manager': '0012_alter_view_user',
    'io_storages': '0018_alter_azureblobexportstorage_project_and_more',
    'jwt_auth': '0001_initial',
    'labels_manager': '0003_auto_20221213_1612',
    'ml': '0007_auto_20240314_1957',
    'ml_model_providers': '0008_alter_modelproviderconnection_provider',
    'ml_models': '0015_alter_thirdpartymodelversion_provider',
    'organizations': '0006_alter_organizationmember_deleted_at',
    'projects': '0028_auto_20241107_1031',
    'tasks': '0053_annotation_bulk_created',
    'users': '0010_userproducttour',
    'webhooks': '0004_auto_20221221_1101',
}

LABEL_CONFIG = """<View>
  <Text name="text" value="$text"/>
  <Choices name="label" toName="text"><Choice value="pos"/><Choice value="neg"/></Choices>
</View>"""


def migrate_to_baseline():
    targets = list(BASELINE_2025_02.items())
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets, at_end=True).apps


def seed(apps):
    User = apps.get_model('users', 'User')
    Organization = apps.get_model('organizations', 'Organization')
    OrganizationMember = apps.get_model('organizations', 'OrganizationMember')
    Project = apps.get_model('projects', 'Project')
    Task = apps.get_model('tasks', 'Task')
    Annotation = apps.get_model('tasks', 'Annotation')
    View = apps.get_model('data_manager', 'View')
    FilterGroup = apps.get_model('data_manager', 'FilterGroup')
    Filter = apps.get_model('data_manager', 'Filter')

    user = User.objects.create(email='owner@example.com', username='owner', password='!unusable')
    org = Organization.objects.create(title='Basir', created_by=user)
    OrganizationMember.objects.create(user=user, organization=org)
    user.active_organization = org
    user.save(update_fields=['active_organization'])

    project = Project.objects.create(title='Upgrade', organization=org, created_by=user, label_config=LABEL_CONFIG)
    task = Task.objects.create(project=project, data={'text': 'hello'})
    Annotation.objects.create(
        task=task,
        project=project,
        completed_by=user,
        result=[
            {
                'id': 'r1',
                'from_name': 'label',
                'to_name': 'text',
                'type': 'choices',
                'value': {'choices': ['pos']},
            }
        ],
    )

    shared_group = FilterGroup.objects.create(conjunction='and')
    task_filter = Filter.objects.create(
        index=0, column='filter:tasks:id', type='Number', operator='greater', value={'value': 0}
    )
    shared_group.filters.add(task_filter)
    hidden = {'explore': ['tasks:inner_id'], 'labeling': ['tasks:data.text']}
    View.objects.create(
        project=project, user=user, data={'title': 'Shared A', 'hiddenColumns': hidden}, filter_group=shared_group
    )
    View.objects.create(
        project=project,
        user=user,
        data={'title': 'Shared B', 'hiddenColumns': {k: list(v) for k, v in hidden.items()}},
        filter_group=shared_group,
    )
    View.objects.create(project=project, user=user, data={'title': 'Plain'})


def verify():
    from core.models import AsyncMigrationStatus
    from data_manager.models import View
    from projects.models import Project
    from tasks.models import Annotation, Task

    executor = MigrationExecutor(connection)
    unapplied = executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert not unapplied, f'unapplied migrations: {unapplied}'

    assert Project.objects.count() == 1
    assert Task.objects.count() == 1
    assert Annotation.objects.count() == 1

    views = {v.data['title']: v for v in View.objects.all()}
    assert set(views) == {'Shared A', 'Shared B', 'Plain'}, views
    for title in ('Shared A', 'Shared B'):
        hidden = views[title].data['hiddenColumns']
        # data_manager 0018_remove_allow_skip
        assert 'tasks:allow_skip' in hidden['explore'], (title, hidden)
        assert 'tasks:allow_skip' in hidden['labeling'], (title, hidden)
        assert 'tasks:inner_id' in hidden['explore'], (title, hidden)
    assert views['Plain'].is_locked is False  # 0019_view_lock_fields

    # data_manager 0013_cleanup_inconsistent_filtergroup: the shared filter group was split
    group_a, group_b = views['Shared A'].filter_group, views['Shared B'].filter_group
    assert group_a and group_b and group_a.id != group_b.id
    for group in (group_a, group_b):
        filters = list(group.filters.all())
        assert [(f.column, f.operator, f.value) for f in filters] == [('filter:tasks:id', 'greater', {'value': 0})], (
            filters
        )

    for name in (
        '0013_cleanup_inconsistent_filtergroup_20250624_2119',
        'data_manager.migrations.0018_remove_allow_skip',
    ):
        status = AsyncMigrationStatus.objects.get(name=name).status
        assert status == AsyncMigrationStatus.STATUS_FINISHED, (name, status)


def main():
    cleanup_first = '--cleanup-before-filter-parent' in sys.argv
    print(f'Database: {connection.vendor} {connection.settings_dict["NAME"]}')
    apps = migrate_to_baseline()
    print('Migrated to the 2025-02 baseline')
    seed(apps)
    print('Seeded baseline data')
    if cleanup_first:
        # data_manager has two 0013 migrations that both depend only on 0012, so Django may apply them in either
        # order. Force the order where the cleanup runs before Filter.parent exists.
        call_command(
            'migrate', 'data_manager', '0013_cleanup_inconsistent_filtergroup_20250624_2119', interactive=False
        )
        print('Applied 0013_cleanup before 0013_filter_parent')
    call_command('migrate', interactive=False, verbosity=1)
    verify()
    print('UPGRADE OK')


if __name__ == '__main__':
    main()
