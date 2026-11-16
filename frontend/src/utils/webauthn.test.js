import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  b64urlToBuffer,
  bufferToB64url,
  passkeysSupported,
  prepareCreationOptions,
  prepareRequestOptions,
  serializeCredential,
} from './webauthn'

const toBytes = (buffer) => Array.from(new Uint8Array(buffer))

describe('webauthn helpers', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('round-trips base64url values', () => {
    const buffer = b64urlToBuffer('aGVsbG8')
    expect(bufferToB64url(buffer)).toBe('aGVsbG8')
    expect(toBytes(buffer)).toEqual(Array.from(new TextEncoder().encode('hello')))
  })

  it('handles empty base64url values', () => {
    expect(toBytes(b64urlToBuffer(''))).toEqual([])
    expect(bufferToB64url(null)).toBe('')
  })

  it('prepares creation options as ArrayBuffers', () => {
    const options = prepareCreationOptions({
      challenge: 'Y2hhbGxlbmdl',
      user: { id: 'dXNlcg', name: 'user@example.com' },
      excludeCredentials: [{ id: 'Y3JlZA', type: 'public-key' }],
    })
    expect(toBytes(options.challenge)).toEqual(Array.from(new TextEncoder().encode('challenge')))
    expect(toBytes(options.user.id)).toEqual(Array.from(new TextEncoder().encode('user')))
    expect(toBytes(options.excludeCredentials[0].id)).toEqual(
      Array.from(new TextEncoder().encode('cred')),
    )
  })

  it('prepares request options as ArrayBuffers', () => {
    const options = prepareRequestOptions({
      challenge: 'Y2hhbGxlbmdl',
      allowCredentials: [{ id: 'Y3JlZA', type: 'public-key' }],
    })
    expect(toBytes(options.challenge)).toEqual(Array.from(new TextEncoder().encode('challenge')))
    expect(toBytes(options.allowCredentials[0].id)).toEqual(
      Array.from(new TextEncoder().encode('cred')),
    )
  })

  it('serializes an attestation credential', () => {
    const payload = serializeCredential({
      id: 'cred-id',
      rawId: new TextEncoder().encode('raw').buffer,
      type: 'public-key',
      getClientExtensionResults: () => ({ credProps: { rk: true } }),
      response: {
        clientDataJSON: new TextEncoder().encode('client').buffer,
        attestationObject: new TextEncoder().encode('attest').buffer,
        getTransports: () => ['internal'],
      },
    })
    expect(payload.id).toBe('cred-id')
    expect(payload.type).toBe('public-key')
    expect(payload.clientExtensionResults).toEqual({ credProps: { rk: true } })
    expect(payload.response.clientDataJSON).toBe(bufferToB64url(new TextEncoder().encode('client')))
    expect(payload.response.attestationObject).toBe(
      bufferToB64url(new TextEncoder().encode('attest')),
    )
    expect(payload.response.transports).toEqual(['internal'])
  })

  it('serializes an assertion credential with a user handle', () => {
    const payload = serializeCredential({
      id: 'cred-id',
      rawId: new TextEncoder().encode('raw').buffer,
      type: 'public-key',
      response: {
        clientDataJSON: new TextEncoder().encode('client').buffer,
        authenticatorData: new TextEncoder().encode('auth').buffer,
        signature: new TextEncoder().encode('sig').buffer,
        userHandle: new TextEncoder().encode('user').buffer,
      },
    })
    expect(payload.response.authenticatorData).toBe(
      bufferToB64url(new TextEncoder().encode('auth')),
    )
    expect(payload.response.signature).toBe(bufferToB64url(new TextEncoder().encode('sig')))
    expect(payload.response.userHandle).toBe(bufferToB64url(new TextEncoder().encode('user')))
    expect(payload.clientExtensionResults).toEqual({})
  })

  it('detects passkey support only in a browser context', () => {
    expect(passkeysSupported()).toBe(false)
    vi.stubGlobal('window', { PublicKeyCredential: function PublicKeyCredential() {} })
    expect(passkeysSupported()).toBe(true)
  })
})
