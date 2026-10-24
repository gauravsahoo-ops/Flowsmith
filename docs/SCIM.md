# SCIM 2.0 User and Group Provisioning

Flowsmith implements SCIM 2.0 user and group lifecycle provisioning at
`/scim/v2`. This lets Okta, Microsoft Entra ID, OneLogin, and other SCIM
clients create, update, deactivate, and query users, and synchronize group
membership without sharing a Flowsmith admin JWT.

## Configuration

```bash
SCIM_ENABLED=true
SCIM_BEARER_TOKEN=<long random token, at least 32 characters>

# Optional defaults for newly provisioned users:
SCIM_DEFAULT_ORGANIZATION_ID=org_xxx
SCIM_DEFAULT_WORKSPACE_ID=ws_xxx

# SCIM groups become private workspaces inside this organization:
SCIM_GROUP_ORGANIZATION_ID=org_xxx
# Optional: defaults to the first active administrator if omitted:
SCIM_GROUP_OWNER_EMAIL=admin@example.com
```

Generate the token with a password manager or:

```bash
openssl rand -hex 32
```

The token is a **dedicated provisioning credential**. Do not reuse
`JWT_SECRET`, an admin password, or a user API key. Rotate it by updating the
environment and restarting the app.

In the Helm chart:

```yaml
scim:
  enabled: true
  bearerToken: "<long random token>"
  defaultOrganizationId: "org_xxx"
  defaultWorkspaceId: "ws_xxx"
  groupOrganizationId: "org_xxx"
  groupOwnerEmail: "admin@example.com"
```

## Authentication

Every request must send:

```http
Authorization: Bearer <SCIM_BEARER_TOKEN>
```

Requests without a valid token return `401`. When SCIM is disabled, the
endpoint returns `404` rather than advertising an unusable surface.

## Supported endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/scim/v2/ServiceProviderConfig` | Capability discovery |
| GET | `/scim/v2/ResourceTypes` | Advertised resource types |
| GET | `/scim/v2/Schemas` | User and Group schemas |
| GET | `/scim/v2/Users` | List/filter users |
| POST | `/scim/v2/Users` | Create a user |
| GET | `/scim/v2/Users/{id}` | Read a user |
| PUT | `/scim/v2/Users/{id}` | Replace supported attributes |
| PATCH | `/scim/v2/Users/{id}` | Patch `active`, `userName`, `roles` |
| DELETE | `/scim/v2/Users/{id}` | Deactivate a user (soft delete) |
| GET | `/scim/v2/Groups` | List/filter groups |
| POST | `/scim/v2/Groups` | Create a group and its workspace |
| GET | `/scim/v2/Groups/{id}` | Read a group and members |
| PUT | `/scim/v2/Groups/{id}` | Replace group attributes and members |
| PATCH | `/scim/v2/Groups/{id}` | Patch `displayName`, `externalId`, `members` |
| DELETE | `/scim/v2/Groups/{id}` | Deactivate a group; preserve its workspace |

`GET /Users` supports `startIndex`, `count`, and these filters:

- `userName eq "ada@example.com"`
- `emails.value eq "ada@example.com"`
- `active eq true`
- `id eq "42"`

`GET /Groups` supports the same pagination plus:

- `displayName eq "Engineering"`
- `externalId eq "idp-engineering"`
- `id eq "grp_..."`

Unsupported filters return a SCIM error (`400`).

## Users

Supported attributes:

- `userName` (required, must be an email address; Flowsmith uses it as the login identity)
- `active`
- `roles` (`admin` or `member`)
- `emails` (first value is used when `userName` is absent)
- `name`, `displayName`, and `externalId` are accepted during provisioning but are not persisted in the current schema
- `groups` is returned read-only from SCIM group memberships

New users are assigned the configured default organization/workspace, if any,
and receive matching membership rows. Without defaults they are created
without organization/workspace scope.

## Groups

A SCIM group is materialized as a **private Flowsmith workspace** inside
`SCIM_GROUP_ORGANIZATION_ID` (or `SCIM_DEFAULT_ORGANIZATION_ID`). The group
`displayName` becomes the workspace name. The configured group owner becomes
the workspace creator/admin; if `SCIM_GROUP_OWNER_EMAIL` is omitted, the first
active administrator is used.

Direct user members must already exist as Flowsmith users, normally because
SCIM provisioned them first; child group members must be existing groups in the
same organization. Adding a user member creates a workspace membership
with `permission=edit`; removing the member removes that workspace membership.
If a workspace membership existed manually before SCIM added the user, SCIM
leaves its existing permission unchanged and does not revoke it when the group
membership is removed. This prevents an IdP group sync from silently removing
or downgrading access granted by a local administrator.

Group members may be users or child groups. A child group is referenced with
`"type": "Group"`; its users inherit the parent group's workspace and optional
organization-role access. Nested groups must belong to the same organization,
cycles are rejected, and changes to a child group are re-materialized into all
active parent groups. Group resources include child references with
`type: Group`; user resources include inherited parent group memberships.

Group `PUT` replaces the member set. Group `PATCH` accepts common IdP forms:

```json
{"op": "add", "path": "members", "value": [{"value": "42"}]}
{"op": "remove", "path": "members[value eq \"42\"]"}
{"op": "replace", "path": "displayName", "value": "Platform"}
```

When a group is deleted, Flowsmith:
- removes the SCIM-managed workspace memberships,
- marks the SCIM group inactive,
- keeps the workspace and its workflows intact,
- renames the workspace and group with a `[deleted ...]` suffix so the name can
  be reused by a later SCIM group.

This is intentionally a soft delete. Flowsmith never destroys workflow content
because an IdP deleted a group.

### Organization role mapping

A group can optionally grant an organization-wide role through the Flowsmith
group extension:

```json
{
  "schemas": [
    "urn:ietf:params:scim:schemas:core:2.0:Group",
    "urn:flowsmith:params:scim:schemas:extension:group:2.0:Group"
  ],
  "displayName": "Engineering",
  "urn:flowsmith:params:scim:schemas:extension:group:2.0:Group": {
    "organizationRole": "member",
    "organizationPermission": "view"
  }
}
```

`organizationRole` accepts `admin` or `member`; `organizationPermission`
accepts `view`, `edit`, or `admin`. When set, group members receive an
`OrganizationMember` row in the group organization. If the membership already
existed manually, its role and permission are left unchanged and are preserved
when the group member is removed. SCIM-created organization memberships are
updated when the group extension changes and revoked when the group membership
or group is removed.

## Current limitations

- Nested group references are supported, but cross-organization nesting is
  rejected.
- Organization-role mapping is explicit opt-in per group; it does not infer
  roles from group names.
- SCIM bulk operations and sorting are not supported.
- Password synchronization is not supported. Deactivated users are blocked;
  reactivated users keep their existing password or SSO login.
- Name fields are accepted but not stored because the current `users` schema
  stores email, role, active state, and scope only.
- SAML group-to-role synchronization is not implemented; SAML user JIT
  provisioning is separate from SCIM group synchronization.

These limitations are explicit so an IdP administrator can enable user and
group provisioning without assuming capabilities that do not exist.
