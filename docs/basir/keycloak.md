# Keycloak login for Label Studio (DW-908)

"Log in with Keycloak" uses the OIDC Authorization Code flow (with PKCE) against the realm **`data_service`**, the
realm our MLOps system uses. Keycloak decides who may log in and what they see:

- realm role **`ls-admin`** → LS admin (sees and manages everything),
- realm role **`ls-labeler`** → LS labeler (sees projects sharing an access group with them),
- groups **`ls-…`** (e.g. `ls-sightence-male`) → the user's access groups.

A user with neither role is refused. Changes in Keycloak take effect at the user's next login.
Steps below are for the Keycloak 26 admin console.

## 1. Client

Realm `data_service` → **Clients → Create client**

| Step / field | Value |
|---|---|
| Client type | OpenID Connect |
| Client ID | `label-studio` (→ `OIDC_RP_CLIENT_ID`) |
| Client authentication | **On** (confidential client) |
| Authorization | Off |
| Authentication flow | **Standard flow** on; Direct access grants, Implicit flow, Service accounts, OAuth 2.0 Device, OIDC CIBA: off |
| PKCE Method (Advanced → Advanced settings, or Capability config) | `S256` (Label Studio always sends PKCE) |
| Root URL / Home URL | `https://<ls-host>` |
| Valid redirect URIs | `https://<ls-host>/oidc/callback/` |
| Valid post logout redirect URIs | `https://<ls-host>/user/login/` |
| Web origins | `https://<ls-host>` |

`<ls-host>` is the URL users open Label Studio with (scheme, host and port exactly as in the browser, e.g.
`http://10.0.0.5:8080`). Then **Credentials** tab → copy **Client Secret** (→ `OIDC_RP_CLIENT_SECRET`).

## 2. Realm roles

**Realm roles → Create role**: `ls-admin`, `ls-labeler` (names must match `OIDC_ROLE_ADMIN` / `OIDC_ROLE_LABELER`).

## 3. Groups

**Groups → Create group**: `ls-sightence-male`, `ls-sightence-female`, `ls-mail-scanner` (and later devices; the
`ls-` prefix is `OIDC_GROUP_PREFIX`). Top-level groups are simplest; a nested group like `/devices/ls-x` also works
(the last part of the path is used). Groups without the prefix are ignored by Label Studio.

The same names are the access groups of the projects in Label Studio (Project settings → General → Access groups).

## 4. Mappers (put roles and groups into the tokens)

**Clients → `label-studio` → Client scopes → `label-studio-dedicated` → Add mapper → By configuration**

| Mapper type | Name | Token Claim Name | Settings |
|---|---|---|---|
| **Group Membership** | `groups` | `groups` | Full group path: on or off (both work); Add to ID token **on**, Add to access token **on**, Add to userinfo **on** |
| **User Realm Role** | `realm roles` | `roles` | Multivalued **on**; Add to ID token **on**, Add to access token **on**, Add to userinfo **on** |

Label Studio also reads Keycloak's default `realm_access.roles` claim of the access token, but the explicit `roles`
mapper doesn't depend on the default `roles` client scope. Keep the default client scopes **`email`** and
**`profile`** on the client: Label Studio needs `email` (new users) and copies `given_name` / `family_name`.

## 5. Users

**Users → user → Role mapping → Assign role** (`ls-admin` or `ls-labeler`) and **Groups → Join group**.
Every Keycloak user needs an **email address**.

## 6. Keycloak's hostname

**Simplest (one URL for both):** if the Label Studio container can reach Keycloak at the same URL as the browser,
set only `OIDC_OP_BASE_URL=http://<server-ip>:9090/realms/data_service` and leave `OIDC_OP_INTERNAL_BASE_URL` empty.
This works with `start-dev --http-port=9090` and no `KC_HOSTNAME` (Keycloak then derives its URLs from the request,
which is the same URL for the browser and the container). Check from the container:

```bash
docker compose exec app python3 -c "import urllib.request; print(urllib.request.urlopen('http://<server-ip>:9090/realms/data_service/.well-known/openid-configuration').read()[:200])"
```

Over plain HTTP from a non-private address, the realm's **Require SSL** (Realm settings → General) must be `none`
(the default `external requests` only allows HTTP from private addresses such as 10.x, 172.16–31.x, 192.168.x).

**When the browser and Label Studio reach it differently:**

The browser goes to `OIDC_OP_BASE_URL` (e.g. `http://<public-host>:9090/realms/data_service`); the Label Studio
container calls the token, userinfo and JWKS endpoints at `OIDC_OP_INTERNAL_BASE_URL` (e.g.
`http://keycloak:8080/realms/data_service`). Keycloak must accept both: run it with `KC_HOSTNAME` set to the public
URL (`http://<public-host>:9090`) and `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`.

## 7. Label Studio settings

```env
OIDC_ENABLED=true
OIDC_RP_CLIENT_ID=label-studio
OIDC_RP_CLIENT_SECRET=<client secret from step 1>
OIDC_OP_BASE_URL=http://<public-host>:9090/realms/data_service
OIDC_OP_INTERNAL_BASE_URL=http://keycloak:8080/realms/data_service   # optional; default OIDC_OP_BASE_URL
OIDC_VERIFY_SSL=true                                               # false only for a self-signed test Keycloak
OIDC_ROLE_ADMIN=ls-admin
OIDC_ROLE_LABELER=ls-labeler
OIDC_GROUP_PREFIX=ls-
BASIR_DEFAULT_ORGANIZATION_ID=5                                    # the single organization (after the merge)
LOCAL_LOGIN_ALLOWED_EMAILS=admin@basir.local
BASIR_ACCESS_CONTROL_ENABLED=true                                  # DW-907
```

- `LOCAL_LOGIN_ALLOWED_EMAILS` (comma-separated): the only accounts that may still use the email/password form,
  e.g. the emergency admin. Everyone else is told to use "Log in with Keycloak". Existing email/password sessions
  of other accounts end at their next request. **Any service that logs in through `/user/login/` with a password
  must be on this list** (API tokens are not affected).
- Sign-up is not changed by this (Keycloak users are created on their first Keycloak login).

## How users are matched

- By the Keycloak subject (`sub`), stored on the user. On the first login a new Label Studio user is created in
  `BASIR_DEFAULT_ORGANIZATION_ID` (no password; it only logs in through Keycloak).
- An existing Label Studio account with the same email but no Keycloak link is **not** taken over: the login is
  refused with a message. Link it by hand with the Keycloak user ID (Keycloak: Users → user → ID):

  ```bash
  python manage.py basir_set_user_access --email someone@example.com --keycloak-sub <keycloak-user-id>
  ```

- Every login copies the role, the `ls-` groups (replacing the previous ones) and first/last name.
- Users deactivated in Label Studio or removed from the organization are refused.

## Logout

Logging out of Label Studio ends the Label Studio session and sends the browser to Keycloak's end-session endpoint
(`id_token_hint`, `client_id`, `post_logout_redirect_uri=https://<ls-host>/user/login/`), so the Keycloak session
ends too. Local (allow-listed) logins log out locally only.

## API

Legacy API tokens (`Authorization: Token …`) and JWT API tokens keep working unchanged; the Label Server doesn't log
in. See `docs/basir/access-control.md` for its service account.
