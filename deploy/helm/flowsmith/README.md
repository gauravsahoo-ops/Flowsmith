# Flowsmith Helm chart

Production-oriented Kubernetes packaging for Flowsmith: the API/UI, external
queue workers, a migration hook, optional bundled PostgreSQL (pgvector) and
Redis, ingress, HPA, and a PodDisruptionBudget.

## Requirements

- Kubernetes 1.27+
- Helm 3.14+
- A default StorageClass (unless you supply PostgreSQL/Redis externally)
- An image containing the Flowsmith backend and built frontend

## Install

Set real secrets on the command line or, preferably, in a private values file:

```bash
helm upgrade --install flowsmith deploy/helm/flowsmith \
  --namespace flowsmith --create-namespace \
  --set secrets.jwtSecret="$(openssl rand -hex 32)" \
  --set secrets.credentialsEncryptionKey="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --set secrets.registrationBootstrapToken="$(openssl rand -hex 24)" \
  --set postgresql.password="$(openssl rand -hex 24)" \
  --set redis.password="$(openssl rand -hex 24)" \
  --set config.publicUrl="https://flowsmith.example.com" \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.hosts[0].host=flowsmith.example.com
```

A pre-install/pre-upgrade Job runs `python -m app.scripts.migrate`. Wait for it
to complete before relying on the app:

```bash
kubectl -n flowsmith rollout status deploy/flowsmith
kubectl -n flowsmith rollout status deploy/flowsmith-worker
```

## External PostgreSQL and Redis

For production HA, disable the bundled single-replica data services and use
managed or operator-managed backends:

```yaml
postgresql:
  enabled: false
redis:
  enabled: false
externalDatabase:
  url: postgresql://flowsmith:REDACTED@postgres.example.internal:5432/flowsmith
externalRedis:
  url: redis://:REDACTED@redis.example.internal:6379/0
```

The PostgreSQL database must have the `vector` extension available (pgvector).
Set `config.queueBackend=db` only for small installations; external workers
require Redis.

## Native SAML 2.0

Native SAML 2.0 Web SSO is disabled by default. Point Flowsmith at your IdP
metadata and, optionally, pin the expected entity ID:

```yaml
saml:
  enabled: true
  idpMetadataUrl: "https://idp.example.com/app/metadata"
  idpEntityId: "https://idp.example.com/app/metadata"
  # For an internal/air-gapped IdP, paste metadata instead:
  # idpMetadataXml: |
  #   <md:EntityDescriptor ...>
  spEntityId: "https://flowsmith.example.com"
  spAcsUrl: "https://flowsmith.example.com/api/auth/sso/saml/acs"
  jitProvisioning: true
  groupAttribute: "groups"
  groupRoleMap: '{"platform-admins": "admin"}'
  defaultOrganizationId: ""
  defaultWorkspaceId: ""
```

The SP metadata endpoint is
`https://flowsmith.example.com/api/auth/sso/saml/metadata`. Configure your IdP
with that metadata, or set the ACS URL and entity ID manually. Optional SP
request signing requires both `saml.spX509Cert` and `saml.spPrivateKey`;
the private key alone enables decryption of encrypted assertions. See
`docs/SAML.md` for validation, JIT, Single Logout, encryption, and current
limitations.

## SCIM 2.0

SCIM user provisioning is disabled by default. Enable it with a dedicated
bearer token and optional defaults for newly created users:

```yaml
scim:
  enabled: true
  bearerToken: "use-a-long-random-token-stored-in-a-secret"
  defaultOrganizationId: "org_xxx"
  defaultWorkspaceId: "ws_xxx"
  groupOrganizationId: "org_xxx"
  groupOwnerEmail: "admin@example.com"
```

The endpoint is `/scim/v2`. Use this token as the SCIM bearer token in your
IdP; it is separate from user JWTs. SCIM groups are mapped to private
workspaces in `groupOrganizationId`; if `groupOwnerEmail` is omitted, the
first active administrator owns them. See `docs/SCIM.md` for the supported
endpoints and current limitations.

## LDAP

LDAP authentication is disabled by default and acts as a fallback after the
local password check. Use LDAPS (or StartTLS) in production:

```yaml
ldap:
  enabled: true
  serverUrl: "ldaps://ldap.example.com"
  bindDn: "cn=svc-flowsmith,ou=services,dc=example,dc=com"
  bindPassword: "stored-in-a-secret"
  userSearchBase: "ou=people,dc=example,dc=com"
  userSearchFilter: "(uid={username})"
  groupSearchBase: "ou=groups,dc=example,dc=com"
  groupSearchFilter: "(member={user_dn})"
  groupRoleMap: '{"platform-admins": "admin"}'
  groupWorkspaceMap: '{"platform-admins": [{"workspace_id": "ws_xxx", "role": "admin", "permission": "admin"}]}'
  groupOrgMap: '{"platform-admins": [{"organization_id": "org_xxx", "role": "admin", "permission": "admin"}]}'
  syncEnabled: true
  syncIntervalSeconds: 900
  jitProvisioning: true
```

Set `bindPassword` through a private values file or an External Secret. The
chart places it in the generated Secret, never the ConfigMap. See
`docs/LDAP.md` for directory-specific filters and limitations.

## WebAuthn/passkeys

Passkeys are disabled by default because the relying-party ID and origin must
match the deployment exactly:

```yaml
webauthn:
  enabled: true
  rpId: "flowsmith.example.com"
  rpName: "Flowsmith"
  origin: "https://flowsmith.example.com"
  requireUv: true
```

Users register passkeys under **Settings → Passkeys**. Passkeys count as MFA
for organization policy and can be used alongside TOTP. Browser support and a
secure HTTPS origin are required.

## External Secret

To keep secrets out of Helm values:

```yaml
secrets:
  create: false
  existingSecret: flowsmith-prod-secrets
```

The referenced Secret must contain:

- `JWT_SECRET`
- `CREDENTIALS_ENCRYPTION_KEY`
- `DATABASE_URL`
- `REDIS_URL` (when Redis is used)
- `POSTGRES_PASSWORD` / `REDIS_PASSWORD` when bundled data services are enabled
- `SCIM_BEARER_TOKEN` when SCIM is enabled
- `SAML_SP_PRIVATE_KEY` when SAML SP request signing is enabled

The chart does not print secret values in `helm get manifest`; they are stored
in the cluster Secret as `stringData` on creation. Use an external secret
manager for production rotation.

## Scaling

The API is stateless apart from the `data` volume. The chart defaults to one
app and one worker replica. To scale:

```bash
kubectl -n flowsmith scale deploy/flowsmith --replicas=3
kubectl -n flowsmith scale deploy/flowsmith-worker --replicas=5
```

Before running multiple app replicas, configure shared S3-compatible object
storage (`config.objectStoreBackend=s3` plus credentials via `extraEnvFrom`)
or a ReadWriteMany data volume. The bundled local object store uses a single
ReadWriteOnce claim.

`autoscaling.enabled=true` adds a CPU-based HPA for the API. For workers, use
KEDA with the Redis queue as the scaling signal; CPU-only HPA does not reflect
queue depth.

## Upgrades

```bash
helm upgrade flowsmith deploy/helm/flowsmith -n flowsmith -f prod-values.yaml
```

The migration Job is recreated on every upgrade. If a migration fails, inspect
the Job logs before retrying; `migrate.backoffLimit` defaults to 5.

## Uninstall

```bash
helm uninstall flowsmith -n flowsmith
```

PersistentVolumeClaims created by the chart are retained by Kubernetes. Delete
them explicitly only after confirming backups:

```bash
kubectl -n flowsmith get pvc
```

## Validation

```bash
helm lint deploy/helm/flowsmith -f deploy/helm/flowsmith/ci/test-values.yaml
helm template flowsmith deploy/helm/flowsmith \
  -n flowsmith -f deploy/helm/flowsmith/ci/test-values.yaml >/tmp/flowsmith.yaml
kubectl apply --dry-run=client -f /tmp/flowsmith.yaml
```

## Scope and limitations

- The bundled PostgreSQL and Redis are single-replica StatefulSets intended
  for evaluation and small self-hosted installs. Use managed/operator-managed
  HA services for production.
- The chart does not install cert-manager, an ingress controller, Prometheus,
  Grafana, or a backup operator.
- The local object store is not suitable for horizontal app scaling; use S3,
  MinIO, or another shared object store.
