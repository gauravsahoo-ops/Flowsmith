# LDAP Authentication

Flowsmith supports LDAP/Active Directory password authentication as a fallback
to local passwords. When LDAP is enabled, a login identifier that is not an
email address (for example `jdoe` or a `sAMAccountName`) is accepted by the API
and the login form.

## Flow

1. Flowsmith checks the local password first. This preserves bootstrap/admin
   accounts and lets LDAP be enabled without locking out local operators.
2. If no local user/password matches and LDAP is enabled, Flowsmith binds to
   the directory with the configured service account, searches for the user,
   and then binds as that user's DN with the supplied password.
3. On success, Flowsmith links an existing account by email or provisions a new
   account (when `LDAP_JIT_PROVISIONING=true`). The LDAP password is never
   stored.
4. The normal JWT/MFA flow follows. An LDAP user with TOTP MFA enabled still
   receives the `mfa_required` challenge after the directory bind.
5. A deactivated Flowsmith account is never reactivated by LDAP.

## Configuration

```dotenv
LDAP_ENABLED=true
LDAP_SERVER_URL=ldaps://ldap.example.com
# Or: ldap://ldap.example.com with LDAP_START_TLS=true
LDAP_TLS_VERIFY=true
LDAP_CA_CERT_FILE=/etc/flowsmith/ldap-ca.pem
LDAP_BIND_DN=cn=svc-flowsmith,ou=services,dc=example,dc=com
LDAP_BIND_PASSWORD=...
LDAP_USER_SEARCH_BASE=ou=people,dc=example,dc=com
LDAP_USER_SEARCH_FILTER=(uid={username})
LDAP_USER_EMAIL_ATTRIBUTE=mail
LDAP_USER_DISPLAY_ATTRIBUTE=displayName
LDAP_GROUP_SEARCH_BASE=ou=groups,dc=example,dc=com
LDAP_GROUP_SEARCH_FILTER=(member={user_dn})
LDAP_GROUP_ATTRIBUTE=cn
LDAP_GROUP_ROLE_MAP={"platform-admins":"admin"}
# Optional workspace memberships:
LDAP_GROUP_WORKSPACE_MAP={"platform-admins":[{"workspace_id":"ws_xxx","role":"admin","permission":"admin"}]}
LDAP_GROUP_ORG_MAP={"platform-admins":[{"organization_id":"org_xxx","role":"admin","permission":"admin"}]}
LDAP_DEFAULT_ROLE=member
LDAP_SYNC_ENABLED=false
LDAP_SYNC_INTERVAL_SECONDS=900
LDAP_JIT_PROVISIONING=true
LDAP_DEFAULT_ORGANIZATION_ID=
LDAP_DEFAULT_WORKSPACE_ID=
```

`{username}` and `{user_dn}` are required placeholders in the corresponding
filters and are escaped before the search, preventing LDAP filter injection.
Production startup requires `ldaps://` or `LDAP_START_TLS=true` and
`LDAP_TLS_VERIFY=true`.

### Active Directory example

```dotenv
LDAP_USER_SEARCH_FILTER=(sAMAccountName={username})
LDAP_USER_EMAIL_ATTRIBUTE=mail
LDAP_GROUP_SEARCH_FILTER=(member={user_dn})
```

### OpenLDAP example

```dotenv
LDAP_USER_SEARCH_FILTER=(uid={username})
LDAP_GROUP_SEARCH_FILTER=(member={user_dn})
```

## Group-to-role mapping

`LDAP_GROUP_ROLE_MAP` is a JSON object whose keys are group names and whose
values are `admin` or `member`, case-insensitively. Any mapped `admin` group
promotes the user to administrator; otherwise a mapped `member` group (or
`LDAP_DEFAULT_ROLE`) applies. Existing administrators are **not** demoted when
an LDAP group is removed, to prevent an accidental directory change from
locking out the only operator.

`LDAP_GROUP_WORKSPACE_MAP` maps group names to one or more workspace grants.
Each grant may be a workspace ID or an object with `workspace_id`, `role`
(`member`/`admin`), and `permission` (`view`/`edit`/`admin`). Grants are
materialized on login; memberships created by LDAP are tracked separately, so
removing the group revokes only memberships Flowsmith created. A manually
granted workspace membership is never deleted by LDAP group removal.

`LDAP_GROUP_ORG_MAP` does the same for organization memberships. Each grant
may be an organization ID or an object with `organization_id`, `role`, and
`permission`. Organization founders are never removed by group synchronization.

## Background refresh

Set `LDAP_SYNC_ENABLED=true` to start the LDAP refresh daemon in the API
process. Every `LDAP_SYNC_INTERVAL_SECONDS` (minimum 60) it:

1. acquires a PostgreSQL advisory lock so only one API replica runs the sweep;
2. refreshes stored users by LDAP DN using the service account;
3. updates group claims, global admin promotion, workspace access, and
   organization access;
4. never deactivates a Flowsmith account just because the directory lookup
   temporarily fails or the user is absent.

`ldap_dn`, `ldap_groups`, and `ldap_synced_at` are stored on the user for this
purpose. Background sync does not demote administrators.

## Security properties

- The service-account password is used only for search and is never returned.
- The user's LDAP password is used only for a bind and is not persisted.
- LDAP failures fail closed; a directory outage cannot authenticate a user.
- Inactive Flowsmith users cannot authenticate through LDAP.
- JIT-created users receive a random local password hash, never the directory
  password.
- Username search values and user DNs are escaped with `ldap3` filter escaping.
- Production refuses plaintext LDAP.

## Limitations

- LDAP groups map to workspace and organization memberships through
  `LDAP_GROUP_WORKSPACE_MAP` and `LDAP_GROUP_ORG_MAP`; the primary
  `user.organization_id` pointer is not rewritten by group sync.
- Background sync refreshes profiles, groups, workspace memberships, and
  organization memberships; it deliberately does not deactivate accounts when a
  directory lookup fails or a user disappears. Directory-driven deactivation
  still requires an explicit SCIM/admin action.
- Nested LDAP groups are not expanded; the group search filter must return the
  groups that should map to roles.
- Password changes remain local. LDAP password-write-back is not implemented.
- Group searches use a bounded result size (200). Very large directories should
  use a group filter that is specific to the user.
- The automated suite mocks the directory boundary; a real OpenLDAP 1.5 smoke
  test was also run locally (bind, search, group retrieval, bad password, and
  unknown user). CI does not currently provision a live directory.

## Helm and Compose

Helm values under `ldap:` render the non-secret settings into the ConfigMap and
`bindPassword` into the Secret. Both Compose files pass the `LDAP_*` variables
through from `.env`; see `.env.example`.
