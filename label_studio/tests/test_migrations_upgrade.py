"""Upgrade test: a database with data at the Feb 2025 migration state must migrate to the latest migrations.

Each case runs tests/migrations_upgrade_from_2025_02.py in a separate process against a fresh, empty database
(the pytest-django test database is already fully migrated, so it can't be used for this).

SQLite always runs. Postgres runs when UPGRADE_TEST_POSTGRE_HOST is set (plus optional UPGRADE_TEST_POSTGRE_PORT,
UPGRADE_TEST_POSTGRE_USER, UPGRADE_TEST_POSTGRE_PASSWORD); the test creates and drops its own database there.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name('migrations_upgrade_from_2025_02.py')
ORDERS = {
    'default-order': [],
    'cleanup-before-filter-parent': ['--cleanup-before-filter-parent'],
}


def _run_upgrade(env_overrides, args, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('POSTGRE_', 'DATABASE_NAME'))}
    env.update(env_overrides)
    env['LABEL_STUDIO_BASE_DATA_DIR'] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0 and 'UPGRADE OK' in output, output[-8000:]


@pytest.mark.parametrize('order', list(ORDERS))
def test_upgrade_from_2025_02_sqlite(tmp_path, order):
    _run_upgrade({'DJANGO_DB': 'sqlite', 'DATABASE_NAME': str(tmp_path / 'upgrade.sqlite3')}, ORDERS[order], tmp_path)


@pytest.mark.skipif(not os.environ.get('UPGRADE_TEST_POSTGRE_HOST'), reason='set UPGRADE_TEST_POSTGRE_HOST to run')
@pytest.mark.parametrize('order', list(ORDERS))
def test_upgrade_from_2025_02_postgres(tmp_path, order):
    import psycopg

    conn_kwargs = dict(
        host=os.environ['UPGRADE_TEST_POSTGRE_HOST'],
        port=int(os.environ.get('UPGRADE_TEST_POSTGRE_PORT', '5432')),
        user=os.environ.get('UPGRADE_TEST_POSTGRE_USER', 'postgres'),
        password=os.environ.get('UPGRADE_TEST_POSTGRE_PASSWORD', ''),
    )
    db_name = f'ls_upgrade_{uuid.uuid4().hex[:10]}'
    with psycopg.connect(dbname='postgres', autocommit=True, **conn_kwargs) as admin:
        admin.execute(f'CREATE DATABASE {db_name}')
    try:
        _run_upgrade(
            {
                'DJANGO_DB': 'default',
                'POSTGRE_HOST': conn_kwargs['host'],
                'POSTGRE_PORT': str(conn_kwargs['port']),
                'POSTGRE_USER': conn_kwargs['user'],
                'POSTGRE_PASSWORD': conn_kwargs['password'],
                'POSTGRE_NAME': db_name,
            },
            ORDERS[order],
            tmp_path,
        )
    finally:
        with psycopg.connect(dbname='postgres', autocommit=True, **conn_kwargs) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS {db_name} WITH (FORCE)')
