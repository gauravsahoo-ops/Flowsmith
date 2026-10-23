// CSP nonce bridge: Monaco and several UI libraries create <style> elements
// at runtime. The backend injects a per-response nonce into index.html; stamp
// it onto every dynamically created style element before it is appended.
const nonceMeta = document.querySelector('meta[name="csp-nonce"]')
const cspNonce = nonceMeta?.getAttribute('content') || ''

if (cspNonce) {
  const originalCreateElement = Document.prototype.createElement
  Document.prototype.createElement = function patchedCreateElement(name, options) {
    const element = originalCreateElement.call(this, name, options)
    if (typeof name === 'string' && name.toLowerCase() === 'style') {
      element.nonce = cspNonce
    }
    return element
  }
}
