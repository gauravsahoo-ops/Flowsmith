// Escape a value for safe interpolation into raw HTML strings
// (e.g. popup.document.write templates). React escapes on its own;
// this is for the few places that build HTML by hand.
const ENTITIES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ENTITIES[ch])
}
