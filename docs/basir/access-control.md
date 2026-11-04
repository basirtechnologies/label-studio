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

1. Give the projects their access groups (Project settings → General → Access groups, the `access_groups` field of
   `POST/PATCH /api/projects/`, or `basir_merge_organizations` in DW-907 part 2).
2. Make the account behind the Label Server's API token an LS admin, and at least one person:

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
