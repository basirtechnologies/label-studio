# Device-based access control (DW-907)

One Label Studio organization for every device. Access between devices comes from **access groups**
(`ls-sightence-male`, `ls-sightence-female`, `ls-mail-scanner`, … — groups are created on first use, the list is not
hard-coded) and an **LS role** per user.

| LS role   | Sees                                                    | Can                                                                 |
|-----------|---------------------------------------------------------|---------------------------------------------------------------------|
| `admin`   | every project of the organization                       | everything                                                          |
| `labeler` | projects that share at least one access group with them | label, submit, update and skip their own work; Data Manager tabs   |
| no role   | projects that share a group with them (none by default) | as a labeler                                                        |

`is_superuser` / `is_staff` give no access while access control is on (they don't bypass the filter, and the
Django admin at `/admin/` is for LS admins only).

## Switch

`BASIR_ACCESS_CONTROL_ENABLED=true` turns it on. Default `false`: Label Studio behaves as upstream.

## Before switching it on

1. Give the projects their access groups: `basir_merge_organizations` (below) does it while merging the
   organizations; otherwise Project settings → General → Access groups, or the `access_groups` field of
   `POST/PATCH /api/projects/`.
2. Create the Label Server's service account (`basir_create_service_account`, below) and make at least one person
   an LS admin:

   ```bash
   python manage.py basir_set_user_access --email admin@example.com --role admin
   ```

3. Give the shared accounts their role and group:

   ```bash
   python manage.py basir_set_user_access --email male@mail.com --role labeler --groups ls-sightence-male
   python manage.py basir_set_user_access --email female@mail.com --role labeler --groups ls-sightence-female
   python manage.py basir_set_user_access --email mail_scanner@mail.com --role labeler --groups ls-mail-scanner
   ```

   `--groups` replaces the user's groups (comma-separated, `""` removes all); `--role none` removes the role.

## While it is on (labelers)

- A project outside the user's groups answers **404** everywhere: project, tasks, annotations, drafts, predictions,
  Data Manager, next task, stats, `/tasks/<id>/resolve/`, `/presign/`, uploaded files — with a session, a legacy
  token or a JWT.
- Admin-only (**403**): create/update/delete projects, labeling config, project settings, import, export, storages,
  webhooks, ML backends, creating/changing/deleting tasks and predictions, changing or deleting other users'
  annotations, organization/member pages, invites, label library changes. The UI hides these entries.

## API

| Endpoint                                   | Who                    | What                                                    |
|--------------------------------------------|------------------------|---------------------------------------------------------|
| `POST/PATCH /api/projects/` `access_groups` | LS admins¹             | list of group names; unknown names create the group     |
| `GET /api/access-control/groups/`          | LS admins (always)     | groups with project and user counts                     |
| `GET /api/access-control/users/`           | LS admins (always)     | users with their role and groups                        |
| `GET/PATCH /api/access-control/users/<id>/` | LS admins (always)    | `{"role": "labeler", "access_groups": ["ls-…"]}`        |

¹ While access control is off everyone can set them, and project responses only carry `access_groups` when asked
for (`?include=access_groups`) or right after setting them, so the responses stay the upstream ones.

## Merging the per-device organizations (DW-907 part 2)

```bash
python manage.py basir_merge_organizations --target-org 5 \
    --map 7=ls-sightence-male 3=ls-sightence-female 5=ls-mail-scanner --dry-run
python manage.py basir_merge_organizations --target-org 5 \
    --map 7=ls-sightence-male 3=ls-sightence-female 5=ls-mail-scanner
```

- Moves every row with a ForeignKey to a mapped source organization (found through Django model meta: projects,
  webhooks, labels, export formats, ML rows, ...) and the FSM history's `organization_id` to the target, in one
  transaction. Per-organization settings (JWT settings, session policy) stay with their organization; the backup
  of deleted rows (`core.DeletedRow`) keeps its value.
- Moved projects get their source organization's groups; target projects without a group get the target's groups.
- Members of a source organization become members of the target and switch their active organization; members
  without a role become labelers with their organization's groups (`--owners-admin` makes the organizations'
  creators LS admins instead). Existing LS admins keep their role.
- If a source organization allowed legacy (or JWT) API tokens and the target didn't, the target now allows them:
  existing tokens keep working.
- Nothing is deleted, no ID changes, source organizations stay (empty). A second run changes nothing.
  `--dry-run` prints the plan. Before/after counts are printed, and the merge rolls back if any total differs.
- Stops before changing anything when two organizations hold rows that would break a unique constraint together
  (e.g. two labels with the same title): rename one, then run again.

## Label Server service account

```bash
python manage.py basir_create_service_account --email label-server@basir.local --organization 5
```

Creates (or updates) a local account without a usable password, LS role admin, member of the organization, and
prints its legacy API token (`Authorization: Token <token>`). Re-running keeps the token; `--rotate-token` replaces
it; `--token-only` prints just the token. Legacy API tokens are switched on for the organization if they were off.
