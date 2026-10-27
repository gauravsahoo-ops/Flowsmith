import manifest from '../generated/brandLogos.json'

const LOGOS = manifest.logos || {}
const BY_NAME = manifest.byName || {}

const EXTRA_ALIASES = {
  aws_s3: 's3',
  aws_s3_trigger: 's3',
  google_workspace_admin: 'g_suite_admin',
  google_cloud_platform: 'google_cloud_natural_language',
  microsoft_365: 'microsoft',
  microsoft_dynamics_365: 'dynamics_crm',
  microsoft_teams_api: 'microsoft_teams',
  outlook365: 'microsoft_outlook',
  send_grid: 'sendgrid',
  twilio_sendgrid: 'sendgrid',
  whatsapp_business: 'whatsapp',
  whatsapp_business_cloud: 'whatsapp',
  x_twitter: 'twitter',
}

function compact(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/\+/g, 'plus')
    .replace(/[^a-z0-9]/g, '')
}

function spaced(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function keyVariants(value) {
  const raw = String(value || '').trim()
  if (!raw) return []
  const normalized = raw
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/\+/g, 'plus')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  const variants = new Set([normalized])
  const base = normalized.replace(/_(trigger|node|connector|api)$/, '')
  if (base) variants.add(base)
  const compactKey = compact(normalized)
  if (EXTRA_ALIASES[normalized]) variants.add(EXTRA_ALIASES[normalized])
  if (EXTRA_ALIASES[base]) variants.add(EXTRA_ALIASES[base])
  for (const [alias, target] of Object.entries(EXTRA_ALIASES)) {
    if (compact(alias) === compactKey && target) variants.add(target)
  }
  return [...variants]
}

function lookup(value) {
  const raw = String(value || '').trim()
  if (!raw) return null
  for (const key of keyVariants(raw)) {
    if (LOGOS[key]) return { key, entry: LOGOS[key] }
  }
  const byName = BY_NAME[spaced(raw)]
  if (byName && LOGOS[byName]) return { key: byName, entry: LOGOS[byName] }
  return null
}

export function getBrandLogo({ type, name, icon } = {}) {
  return lookup(type) || lookup(name) || lookup(icon) || null
}

export function hasBrandLogo(props) {
  return Boolean(getBrandLogo(props))
}
