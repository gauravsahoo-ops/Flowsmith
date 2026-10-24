# WebAuthn / Passkeys

Flowsmith supports WebAuthn passkeys as a second factor alongside TOTP.
Passkeys count as MFA for organization policy and can be used from the login
screen or registered under **Settings → Passkeys**.

## Configuration

```dotenv
WEBAUTHN_ENABLED=true
WEBAUTHN_RP_ID=flowsmith.example.com
WEBAUTHN_RP_NAME=Flowsmith
WEBAUTHN_ORIGIN=https://flowsmith.example.com
WEBAUTHN_REQUIRE_UV=true
WEBAUTHN_TIMEOUT_MS=60000
# Optional hardware attestation policy:
WEBAUTHN_ATTESTATION=none
WEBAUTHN_ATTESTATION_ROOTS_FILE=
WEBAUTHN_ALLOWED_AAGUIDS=
WEBAUTHN_ALLOWED_FORMATS=
```

`WEBAUTHN_RP_ID` is the registrable domain without a scheme. `WEBAUTHN_ORIGIN`
is the exact browser origin. Production startup requires HTTPS and that the
origin host matches the RP ID. Browsers only permit WebAuthn on secure origins
(`https://`, or `localhost` during development).

## Registration

1. `POST /api/auth/webauthn/register/options` with the current password returns
   creation options and a 5-minute purpose-scoped `registration_token`.
2. The browser calls `navigator.credentials.create()`.
3. `POST /api/auth/webauthn/register/complete` verifies attestation, origin,
   challenge, RP ID, user presence, and user verification, then stores the
   credential public key.
4. Credentials can be listed at `GET /api/auth/webauthn` and removed with
   `DELETE /api/auth/webauthn/{id}`.

The registration challenge is single-use. Registration requires the current
password even when an attacker has a valid session.

## Login

For a user with passkeys, the password/LDAP login response includes:

```json
{
  "webauthn_required": true,
  "webauthn_token": "...",
  "webauthn_options": { "...": "..." },
  "webauthn_expires_in": 300
}
```

If the user also has TOTP enabled, `mfa_required`, `challenge_token`, and TOTP
verification remain available as a fallback. The browser calls
`navigator.credentials.get()`, then exchanges the assertion at
`POST /api/auth/webauthn/authenticate/complete` for a normal JWT.

### Conditional UI / passwordless passkey sign-in

`POST /api/auth/webauthn/conditional/options` returns a discoverable-credential
challenge with an empty allow-list. The login page starts a conditional
`navigator.credentials.get({ mediation: "conditional" })` request so passkeys
can appear in browser autofill, and also exposes a "Sign in with a passkey"
button. Completion posts to `/api/auth/webauthn/conditional/complete`; the
server locates the credential by raw ID, verifies user presence/verification,
and issues the normal JWT. The challenge is single-use and the flow still
requires a user-verifying passkey; no password is sent.

Challenges are purpose-scoped JWTs. They are rejected by all normal token
consumers, including WebSockets, file downloads, session renewal, and bearer
authentication. Successful use revokes the challenge JTI.

## Hardware attestation policy

`WEBAUTHN_ATTESTATION` can be `none` (default), `direct`, or `enterprise`.
Non-none policies request attestation during registration and reject
attestation format `none`. `WEBAUTHN_ATTESTATION_ROOTS_FILE` supplies trusted
attestation root certificates; `WEBAUTHN_ALLOWED_FORMATS` and
`WEBAUTHN_ALLOWED_AAGUIDS` add optional allowlists. Production startup refuses
attestation policies without a roots file. Authenticator attestation formats are
platform/vendor-specific; validate the roots and AAGUID list before enabling.

## Security properties

- RP ID, origin, challenge, user presence, and (when enabled) user verification
  are verified by the `webauthn` library.
- Credential public keys and signature counters are stored server-side; private
  keys never reach Flowsmith.
- Registration and authentication require single-use, short-lived challenges.
- Authentication failures are throttled per account/IP.
- Organization MFA policy accepts a passkey as a valid second factor.
- Disabling TOTP is allowed when a passkey remains, and vice versa.
- Credential IDs are unique; duplicate registrations return `409`.

## Limitations

- Passkeys are an additional factor for local password/LDAP accounts; SAML/OIDC
  users remain governed by their IdP.
- Conditional-UI/autofill is best-effort; browsers that do not support
  `PublicKeyCredential.isConditionalMediationAvailable` still get the explicit
  passkey button and password fallback.
- Passkey-only users have no TOTP/recovery-code fallback unless they also enroll
  TOTP; losing every passkey requires an administrator-assisted account reset.
- Cross-device passkey transfers depend on the platform authenticator and its
  backup/sync behavior.
- Passkeys do not replace password knowledge on their own; password + passkey is
  the supported flow.
- Attestation is optional; enabling `direct`/`enterprise` requires operator-
  supplied trust roots and optional format/AAGUID allowlists.
