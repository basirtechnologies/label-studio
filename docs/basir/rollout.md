# Rollout runbook: one organization, access groups, Keycloak login (DW-906)

For one server (staging first, then production), upgraded from upstream Label Studio 1.17 (1ba6f0207) to this fork.
It covers DW-907 (access groups + organization merge) and DW-908 (Keycloak login). Run it top to bottom; every step
says how to check it. Rollback is at the end.

Commands assume Docker Compose with the app service `app` and the database service `db`; adapt the names. Shortcut
used below:

```bash
LS="docker compose exec app python3 /label-studio/label_studio/manage.py"
```

## 0. Before the window

- Keycloak (realm `data_service`) is configured as in [keycloak.md](keycloak.md): client `label-studio`, realm roles
  `ls-admin` / `ls-labeler`, groups `ls-sightence-male` / `ls-sightence-female` / `ls-mail-scanner`, the two mappers,
  users with roles and groups (and an email). Keep the client secret at hand.
- Decide the emergency admin account(s) (local email/password login) and the Label Server service account email,
  e.g. `label-server@basir.local`.
- The Label Server change is ready: one token for every device and `access_groups` on project creation
  (`sightence_male` → `ls-sightence-male`, `sightence_female` → `ls-sightence-female`, `mail_scanner` →
  `ls-mail-scanner`).
- Note the image tag running now (for the rollback) and the new image tag (`ghcr.io/…:sha-xxxxxxx`).

## 1. Stop writes

1. Pause the Data Warehouse → Label Server flow (no new projects, imports or webhooks during the window).
2. Tell the labelers; stop Label Studio: `docker compose stop app` (and nginx if separate).

## 2. Back up

```bash
mkdir -p backup-$(date +%F)
docker compose exec -T db pg_dump -U postgres -Fc postgres > backup-$(date +%F)/label-studio.dump
tar -czf backup-$(date +%F)/mydata.tar.gz ./mydata          # uploads, export files, media (the data volume)
cp .env docker-compose.yml backup-$(date +%F)/              # current settings and image tag
```

Check: `pg_restore -l backup-*/label-studio.dump | head` lists tables; the archive is not empty.

## 3. Deploy the new image (everything still off)

In `.env` (or the compose file) set the new image tag and, for now:

```env
BASIR_ACCESS_CONTROL_ENABLED=false
OIDC_ENABLED=false
```

```bash
docker compose up -d app
docker compose logs -f app        # "=> Do database migrations..." ... "=> Migrations completed."
```

The migrations run at start (`locked_migrate`); DW-907 only adds the tables of the `access_control` app.
Check: log in as before; projects, tasks and annotations are all there; the Label Server's current tokens still work.

## 4. Look up the organizations

```bash
$LS shell -c "
from organizations.models import Organization
for o in Organization.objects.order_by('id'):
    print(o.id, repr(o.title), 'projects:', o.projects.count(), 'members:', list(o.members.values_list('user__email', flat=True)))
"
```

Example: `Label Studio mail_scanner` = 5, `Label Studio male` = 7, `Label Studio female` = 3 (the empty
`Label Studio *male` is left alone). Use **your** IDs below; the target is the organization everything moves to.

## 5. Merge the organizations (DW-907)

```bash
$LS basir_merge_organizations --target-org 5 --map 7=ls-sightence-male 3=ls-sightence-female 5=ls-mail-scanner --dry-run
```

Read the plan: rows to move per model, memberships, active organizations, roles (shared accounts → `labeler`),
groups per user and per project, token settings. Then:

```bash
$LS basir_merge_organizations --target-org 5 --map 7=ls-sightence-male 3=ls-sightence-female 5=ls-mail-scanner
```

Check: the "Before"/"After" report shows every project with the same ID, tasks and annotations, now in organization
5 with its group; "Totals check" and "Merge done." are printed. Running it again prints "Nothing to change".
(Add `--owners-admin` only if the users who created the organizations should become LS admins.)

## 6. Accounts

```bash
# the Label Server's service account (LS admin, API only); prints its legacy token
$LS basir_create_service_account --email label-server@basir.local --organization 5

# emergency admin(s): LS admin, local login (also put them in LOCAL_LOGIN_ALLOWED_EMAILS)
$LS basir_set_user_access --email admin@basir.local --role admin

# check the shared accounts got their device (the merge did this)
$LS basir_set_user_access --email male@mail.com
$LS basir_set_user_access --email female@mail.com
$LS basir_set_user_access --email mail_scanner@mail.com
```

Give the printed token to the Label Server (it replaces the three per-organization tokens; the old tokens keep
working until you remove them). Existing local accounts that should log in with Keycloak: link them
(`basir_set_user_access --email … --keycloak-sub <Keycloak user ID>`), otherwise their Keycloak login is refused.

## 7. Switch on access control and Keycloak login

In `.env`:

```env
BASIR_ACCESS_CONTROL_ENABLED=true
OIDC_ENABLED=true
OIDC_RP_CLIENT_ID=label-studio
OIDC_RP_CLIENT_SECRET=<client secret>
OIDC_OP_BASE_URL=http://<public-host>:9090/realms/data_service
OIDC_OP_INTERNAL_BASE_URL=http://keycloak:8080/realms/data_service
OIDC_VERIFY_SSL=true
OIDC_ROLE_ADMIN=ls-admin
OIDC_ROLE_LABELER=ls-labeler
OIDC_GROUP_PREFIX=ls-
BASIR_DEFAULT_ORGANIZATION_ID=5
LOCAL_LOGIN_ALLOWED_EMAILS=admin@basir.local
```

```bash
docker compose up -d app
```

## 8. Check ("flag on")

1. Login page shows "Log in with Keycloak"; `male@mail.com` with its password is refused ("use Log in with
   Keycloak"); `admin@basir.local` logs in with its password and sees all projects with their group tags.
2. A Keycloak user with `ls-labeler` + `ls-sightence-male` logs in, sees only the male projects, can label and
   submit; no Create / Settings / Import / Export / Organization entries. Opening a female project's URL gives
   "not found".
3. Same with an `ls-sightence-female` and an `ls-mail-scanner` user; a Keycloak user without an `ls-` role is
   refused with a message.
4. A Keycloak user with `ls-admin` sees everything.
5. Logout returns to Keycloak and back to the login page; logging in again asks Keycloak for the password.
6. Label Server with the new token: `curl -H "Authorization: Token <token>" https://<ls-host>/api/projects/` lists
   every project; creating a project with `"access_groups": ["ls-sightence-male"]` works; S3 storage sync and
   webhooks work.
7. Resume the Data Warehouse → Label Server flow.

## Partial rollback (no data loss)

- Login problem: `OIDC_ENABLED=false` and restart → email/password login for every local account again.
- Access problem: `BASIR_ACCESS_CONTROL_ENABLED=false` and restart → everyone in the organization sees every project
  (the shared accounts too). Use only for a short time: it lifts the privacy boundary.

The merged organization stays merged; only a full rollback undoes it.

## Full rollback (restore the backup + previous image)

Everything written after step 1 is lost (annotations made since then).

```bash
docker compose stop app
# previous image tag and settings
cp backup-YYYY-MM-DD/.env backup-YYYY-MM-DD/docker-compose.yml .
# database: recreate and restore
docker compose exec -T db psql -U postgres -d template1 -c "DROP DATABASE postgres WITH (FORCE);"
docker compose exec -T db psql -U postgres -d template1 -c "CREATE DATABASE postgres;"
docker compose exec -T db pg_restore -U postgres -d postgres --no-owner < backup-YYYY-MM-DD/label-studio.dump
# data volume
mv mydata mydata.failed && tar -xzf backup-YYYY-MM-DD/mydata.tar.gz
docker compose up -d app
```

Check: login with the old accounts, the three organizations with their projects, the Label Server's old tokens.
Then resume the Data Warehouse → Label Server flow with the old configuration.
