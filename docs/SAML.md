# Native SAML 2.0 Web SSO

Flowsmith implements a native SAML 2.0 service provider for browser-based Web
SSO. It validates signed SAML responses/assertions directly; it does not need a
separate SAML gateway or enterprise paywall.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/auth/sso/saml/metadata` | SP metadata for IdP configuration |
| GET | `/api/auth/sso/saml/login` | SP-initiated login; redirects to the IdP |
| POST | `/api/auth/sso/saml/acs` | Assertion Consumer Service |
| POST | `/api/auth/sso/saml/logout` | Bearer-authenticated SP-initiated logout |
| GET/POST | `/api/auth/sso/saml/slo` | IdP-initiated Single Logout endpoint |

The existing provider discovery endpoint (`/api/auth/sso/providers`) lists
`SAML` when it is enabled and metadata is configured.

## Configuration

```bash
SAML_ENABLED=true
SAML_DISPLAY_NAME=SAML 2.0

# Use a public HTTPS metadata URL:
SAML_IDP_METADATA_URL=https://idp.example.com/app/metadata

# Or, for internal/air-gapped IdPs, paste metadata XML:
# SAML_IDP_METADATA_XML=<EntityDescriptor ...>

# Optional trust pins/overrides:
SAML_IDP_ENTITY_ID=https://idp.example.com/app/metadata
SAML_IDP_X509_CERT=          # PEM or base64 DER; normally read from metadata

# Service provider identity:
SAML_SP_ENTITY_ID=https://flowsmith.example.com
SAML_SP_ACS_URL=https://flowsmith.example.com/api/auth/sso/saml/acs

# Optional AuthnRequest signing (cert + key) / assertion decryption (key alone):
SAML_SP_X509_CERT=
SAML_SP_PRIVATE_KEY=

# Just-in-time provisioning:
SAML_JIT_PROVISIONING=true
SAML_DEFAULT_ROLE=member
SAML_ROLE_ATTRIBUTE=role
# Optional group-claim role mapping:
SAML_GROUP_ATTRIBUTE=groups
SAML_GROUP_ROLE_MAP={"platform-admins":"admin"}
SAML_DEFAULT_ORGANIZATION_ID=
SAML_DEFAULT_WORKSPACE_ID=

# Unsolicited (IdP-initiated) responses are opt-in:
SAML_ALLOW_IDP_INITIATED=false
SAML_CLOCK_SKEW_SECONDS=120
SAML_METADATA_CACHE_SECONDS=300
```

`PUBLIC_URL` must be the externally reachable HTTPS origin in production. The
default SP entity ID is `PUBLIC_URL`; the default ACS URL is
`PUBLIC_URL/api/auth/sso/saml/acs`. `SAML_SP_ENTITY_ID` and `SAML_SP_ACS_URL`
override those defaults.

### IdP setup

1. Open `/api/auth/sso/saml/metadata` or configure the ACS URL manually.
2. Set the IdP audience/entity ID to the Flowsmith SP entity ID.
3. Set the ACS URL to the Flowsmith ACS URL.
4. Use `emailAddress` NameID or send a `mail`/`email` attribute.
5. Sign the response or assertion with the certificate published in IdP
   metadata. Unsigned responses are rejected.

Many IdPs use a `role` attribute for role mapping. Only `admin` and `member`
are accepted; `owner` maps to `admin`. The explicit role attribute wins over
group mapping. Existing members can be promoted to admin by either claim;
existing administrators are never demoted by a missing claim.

Group claims can also drive the global role:

```dotenv
SAML_GROUP_ATTRIBUTE=groups
SAML_GROUP_ROLE_MAP={"platform-admins":"admin","employees":"member"}
```

The matching is case-insensitive. Group claims are not yet mapped to SCIM
groups or individual workspace roles.

### SP request signing

If `SAML_SP_X509_CERT` and `SAML_SP_PRIVATE_KEY` are both set, Flowsmith signs
AuthnRequests with RSA-SHA256 and advertises the certificate in SP metadata.
`SAML_SP_PRIVATE_KEY` alone is valid for decrypting encrypted assertions but
does not advertise request-signing capability. A certificate without its
private key is rejected. Generate a key pair with:

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout flowsmith-saml.key -out flowsmith-saml.crt \
  -days 825 -subj "/CN=flowsmith.example.com"
```

Paste the PEM files into `SAML_SP_PRIVATE_KEY` and `SAML_SP_X509_CERT`, or put
the private key in a Kubernetes Secret as shown in the Helm chart README.

## Validation performed

- XML DTD/entity declarations are rejected before parsing.
- The response or assertion must have an enveloped XMLDSig signature.
- Encrypted assertions using RSA-OAEP with AES-GCM or AES-CBC are decrypted
  with `SAML_SP_PRIVATE_KEY` before assertion validation.
- The signing certificate is pinned from IdP metadata or
  `SAML_IDP_X509_CERT`; SHA-1 signature methods are not accepted.
- The IdP issuer matches metadata.
- The response destination and assertion recipient match the configured ACS.
- The assertion audience matches the SP entity ID.
- `InResponseTo` matches the signed SP state for SP-initiated flows.
- `Conditions` and bearer `SubjectConfirmationData` timestamps are checked
  with a configurable clock skew.
- At least one `AuthnStatement` is required.
- Assertion IDs are single-use. Redis is used when available; otherwise the
  process-local cache is used.
- Deactivated users cannot regain access through SAML.

## Account provisioning

When no local account exists and `SAML_JIT_PROVISIONING=true`, Flowsmith
creates one from the verified assertion. The first account in a fresh install
becomes the administrator; subsequent users receive the IdP role or
`SAML_DEFAULT_ROLE`.

Optional default organization/workspace IDs are validated and membership rows
are created, matching the SCIM provisioning behavior. Existing users are
matched by normalized email.

## Single Logout

Flowsmith supports IdP-initiated SLO at `/api/auth/sso/saml/slo`. A signed
`LogoutRequest` invalidates the matched user's existing JWTs by advancing
`tokens_valid_from`, then Flowsmith returns a `LogoutResponse` to the IdP.
SP-initiated logout is available at `POST /api/auth/sso/saml/logout` with a
Bearer token; it invalidates the user's tokens and sends a LogoutRequest to the
IdP's `SingleLogoutService`.

The IdP metadata must advertise an HTTP-POST or HTTP-Redirect
`SingleLogoutService`. Flowsmith advertises its own POST SLO endpoint in SP
metadata. Logout is not a substitute for deactivating a user; SCIM DELETE
remains the deprovisioning path.

## Current limitations

- Encrypted-key algorithms other than RSA-OAEP are rejected.
- SLO messages must carry an XML signature; query-string-only signatures are
  not supported.
- SAML group claims map to the global admin/member role, but not yet to SCIM
  groups or individual workspace roles. SCIM group provisioning is available
  separately.
- IdP metadata must be fetched over public HTTPS because the shared SSRF guard
  blocks private/link-local metadata URLs. Use inline metadata XML for an
  internal IdP.
- Multi-replica deployments should use Redis for assertion replay protection;
  the process-local fallback does not coordinate across replicas.
- Unsolicited IdP-initiated responses are disabled by default and lack a
  browser-bound request state when explicitly enabled.
- SAML POST ACS requires HTTPS in production so the state cookie can use
  `SameSite=None`.

## Verification

The test suite builds real RSA key pairs, signs assertions/responses with
XMLDSig, and covers valid login, response signing, encrypted assertions,
unsigned/wrong-certificate rejection, audience mismatch, expiry, replay,
IdP-initiated opt-in, JIT disabled, role/default scope provisioning, Single
Logout, and signed AuthnRequest generation.
