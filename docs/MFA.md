# Multi-Factor Authentication (TOTP)

Flowsmith supports optional TOTP multi-factor authentication for local
password accounts. Users enroll an authenticator app from **Settings → Multi-Factor
Authentication**, and receive ten single-use recovery codes when enrollment
completes.

## Behavior

1. `POST /api/auth/mfa/setup` (authenticated, current password required) generates
   a base32 secret and returns its `otpauth://` URI.
2. `POST /api/auth/mfa/enable` (authenticated, current password + current TOTP
   code) enables MFA and returns ten recovery codes. The codes are shown once.
3. A successful password login for an MFA-enabled account returns:

   ```json
   {
     "mfa_required": true,
     "challenge_token": "...",
     "expires_in": 300
   }
   ```

   No bearer token is issued at this stage.
4. `POST /api/auth/mfa/verify` exchanges the challenge token plus a TOTP code or
   an unused recovery code for a normal bearer token.
5. `POST /api/auth/mfa/disable` (authenticated, current password + TOTP/recovery
   code) removes MFA.

## Organization-wide requirement

Organization founders can enable **Require MFA** in Settings → Organizations.
A registered WebAuthn/passkey also satisfies the policy. For users who belong
to that organization and have neither TOTP nor a passkey, password/LDAP login
returns:

```json
{
  "mfa_enrollment_required": true,
  "enrollment_token": "...",
  "expires_in": 600,
  "issuer": "Flowsmith"
}
```

The login screen then shows the TOTP secret and a code field. Completing
`POST /api/auth/mfa/enroll/complete` enables MFA, returns the normal login
token, and displays ten recovery codes once. `enrollment_token` is a
purpose-scoped JWT and cannot be used as a bearer token.

Enabling the policy invalidates existing bearer tokens for organization members
who have not enrolled in TOTP, so their next request requires a fresh
password/LDAP login and forced enrollment. SAML/OIDC users remain governed by
their identity provider's MFA, and machine API keys are exempt as service
credentials. Disabling TOTP while the policy is active causes the next login to
require enrollment again.

## Security properties

- TOTP secrets are encrypted at rest with the same Fernet key used for connector
  credentials (`CREDENTIALS_ENCRYPTION_KEY`).
- Recovery codes are stored only as SHA-256 hashes and are removed on use.
- Accepted TOTP counters are persisted per user; replaying an already-used
  6-digit code is rejected.
- Challenge tokens are signed JWTs with `purpose=mfa` and a 5-minute lifetime.
  They are rejected by every normal token consumer, including bearer auth,
  WebSocket handshakes, file downloads, and session renewal.
- MFA setup, enable, disable, and login challenges require the current password
  (the challenge itself is issued only after a valid password).
- Failed MFA exchanges use the existing per-account/IP failure throttle.
- Deactivated users cannot complete an MFA challenge.

## Limitations

- MFA is optional by default; organizations can opt into a policy.
- While an organization policy is active, members cannot disable their own
  MFA; an organization founder must change the policy first.
- SAML/OIDC users are expected to perform MFA at their identity provider.
  Local TOTP enrollment for SAML/OIDC JIT accounts requires the user to set a
  local password first; password and LDAP users can use forced enrollment.
- WebAuthn/passkeys are supported as an alternative second factor; see
  [`WEBAUTHN.md`](WEBAUTHN.md).
- Recovery-code regeneration is not exposed yet; disable and re-enable MFA to
  issue a fresh set.
- Push notifications and hardware security-key attestation policy are not
  implemented. WebAuthn/passkeys are supported separately; see
  [`WEBAUTHN.md`](WEBAUTHN.md).

## Configuration

No new environment variables are required. The TOTP issuer label is
`Flowsmith`; codes use SHA-1, six digits, and a 30-second period for broad
authenticator compatibility.
