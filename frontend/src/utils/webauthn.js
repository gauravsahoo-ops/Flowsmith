// WebAuthn JSON <-> ArrayBuffer helpers. The server returns base64url strings;
// the browser Credential API requires ArrayBuffers.

export function b64urlToBuffer(value) {
  if (!value) return new Uint8Array(0).buffer
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

export function bufferToB64url(value) {
  if (!value) return ''
  const bytes = new Uint8Array(value)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function prepareCreationOptions(options) {
  const copy = JSON.parse(JSON.stringify(options))
  copy.challenge = b64urlToBuffer(copy.challenge)
  copy.user.id = b64urlToBuffer(copy.user.id)
  copy.excludeCredentials = (copy.excludeCredentials || []).map((credential) => ({
    ...credential,
    id: b64urlToBuffer(credential.id),
  }))
  return copy
}

export function prepareRequestOptions(options) {
  const copy = JSON.parse(JSON.stringify(options))
  copy.challenge = b64urlToBuffer(copy.challenge)
  copy.allowCredentials = (copy.allowCredentials || []).map((credential) => ({
    ...credential,
    id: b64urlToBuffer(credential.id),
  }))
  return copy
}

export function serializeCredential(credential) {
  const response = credential.response || {}
  const payload = {
    id: credential.id,
    rawId: bufferToB64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: typeof credential.getClientExtensionResults === 'function'
      ? credential.getClientExtensionResults()
      : {},
  }
  if (response.attestationObject) {
    payload.response = {
      clientDataJSON: bufferToB64url(response.clientDataJSON),
      attestationObject: bufferToB64url(response.attestationObject),
      transports: typeof response.getTransports === 'function' ? response.getTransports() : [],
    }
  } else {
    payload.response = {
      clientDataJSON: bufferToB64url(response.clientDataJSON),
      authenticatorData: bufferToB64url(response.authenticatorData),
      signature: bufferToB64url(response.signature),
      userHandle: response.userHandle ? bufferToB64url(response.userHandle) : null,
    }
  }
  return payload
}

export function passkeysSupported() {
  return typeof window !== 'undefined' && Boolean(window.PublicKeyCredential)
}
