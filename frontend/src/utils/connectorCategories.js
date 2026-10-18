export const CATEGORIES = [
  { id: 'all', label: 'All Integrations' },
  { id: 'crm', label: 'CRM & Sales' },
  { id: 'database', label: 'Databases & Storage' },
  { id: 'communication', label: 'Communication' },
  { id: 'marketing', label: 'Marketing & Content' },
  { id: 'developer', label: 'Developer & DevOps' },
  { id: 'ai', label: 'AI & Knowledge' },
  { id: 'productivity', label: 'Productivity' },
  { id: 'finance', label: 'Finance & Payments' },
]

export const CONNECTOR_CATEGORY_MAP = {
  // CRM & Sales
  salesforce: ['crm'],
  hubspot: ['crm'],
  dynamics_crm: ['crm'],
  freshsales: ['crm'],
  zoho_crm: ['crm'],
  pipedrive: ['crm', 'productivity'],
  activecampaign: ['crm', 'communication', 'marketing'],
  workday: ['crm'],
  zendesk: ['crm', 'communication'],
  intercom: ['crm', 'communication'],
  gong: ['crm'],
  salesloft: ['crm'],
  outreach: ['crm'],
  apollo: ['crm', 'marketing'],
  churnzero: ['crm'],
  totango: ['crm'],
  gainsight: ['crm'],
  leadfeeder: ['crm', 'marketing'],
  clearbit: ['crm', 'marketing'],
  zoominfo: ['crm', 'marketing'],
  // Communication
  slack: ['communication'],
  slack_api: ['communication'],
  discord: ['communication'],
  telegram: ['communication'],
  microsoft_teams: ['communication'],
  twilio: ['communication'],
  whatsapp: ['communication'],
  sendgrid: ['communication', 'marketing'],
  resend: ['communication', 'developer'],
  mailchimp: ['communication', 'marketing'],
  mailgun: ['communication', 'developer'],
  postmark: ['communication', 'developer'],
  brevo: ['communication', 'marketing'],
  loops: ['communication', 'marketing'],
  customerio: ['communication', 'marketing'],
  front: ['communication', 'crm'],
  linear: ['developer', 'productivity'],
  jira: ['developer', 'productivity'],
  asana: ['productivity'],
  trello: ['productivity'],
  clickup: ['productivity'],
  monday: ['productivity'],
  notion: ['productivity', 'ai'],
  coda: ['productivity'],
  airtable: ['database', 'productivity'],
  google_sheets: ['database', 'productivity'],
  google_drive: ['productivity'],
  google_calendar: ['productivity'],
  google_docs: ['productivity'],
  microsoft_excel: ['database', 'productivity'],
  // Databases & Storage
  postgresql: ['database'],
  mysql: ['database'],
  sql_server: ['database'],
  oracle: ['database'],
  sqlite: ['database'],
  mongodb: ['database'],
  redis: ['database'],
  elasticsearch: ['database'],
  supabase: ['database', 'developer'],
  firebase: ['database', 'developer'],
  snowflake: ['database'],
  bigquery: ['database'],
  databricks: ['database'],
  aws_s3: ['database', 'developer'],
  google_cloud_storage: ['database', 'developer'],
  azure_blob: ['database', 'developer'],
  pinot: ['database'],
  clickhouse: ['database'],
  // Developer & DevOps
  github: ['developer'],
  gitlab: ['developer'],
  bitbucket: ['developer'],
  docker: ['developer'],
  kubernetes: ['developer'],
  datadog: ['developer'],
  sentry: ['developer'],
  postman: ['developer'],
  vercel: ['developer'],
  cloudflare: ['developer'],
  pagerduty: ['developer'],
  opsgenie: ['developer'],
  // AI & Knowledge
  openai: ['ai'],
  anthropic: ['ai'],
  gemini: ['ai'],
  cohere: ['ai'],
  mistral: ['ai'],
  groq: ['ai'],
  perplexity: ['ai'],
  replicate: ['ai'],
  pinecone: ['ai', 'database'],
  weaviate: ['ai', 'database'],
  qdrant: ['ai', 'database'],
  chroma: ['ai', 'database'],
  // Finance & Payments
  stripe: ['finance'],
  paypal: ['finance'],
  square: ['finance'],
  braintree: ['finance'],
  paddle: ['finance'],
  chargebee: ['finance'],
  recurly: ['finance'],
  quickbooks: ['finance'],
  xero: ['finance'],
  netsuite: ['finance'],
  sap: ['finance'],
  frankfurter: ['finance'],
  coin_gecko: ['finance'],
}

export function matchesCategory(conn, catId) {
  if (!catId || catId === 'all') return true
  const key = (conn.connector_key || '').toLowerCase()
  const mapped = CONNECTOR_CATEGORY_MAP[key]
  if (mapped && mapped.includes(catId)) return true
  if (key.startsWith('open_meteo') && catId === 'developer') return true

  const cat = (conn.category || '').toLowerCase()
  if (catId === 'crm') return cat.includes('crm') || cat.includes('sale') || cat.includes('lead') || cat.includes('support')
  if (catId === 'database') return cat.includes('data') || cat.includes('storage') || cat.includes('sql') || cat.includes('db')
  if (catId === 'communication') return cat.includes('comm') || cat.includes('message') || cat.includes('mail') || cat.includes('chat') || cat.includes('sms')
  if (catId === 'marketing') return cat.includes('market') || cat.includes('content') || cat.includes('campaign') || cat.includes('seo')
  if (catId === 'developer') return cat.includes('dev') || cat.includes('git') || cat.includes('code') || cat.includes('api') || cat.includes('devops') || cat.includes('infra')
  if (catId === 'ai') return cat.includes('ai') || cat.includes('rag') || cat.includes('llm') || cat.includes('agent')
  if (catId === 'productivity') return cat.includes('prod') || cat.includes('task') || cat.includes('work') || cat.includes('doc') || cat.includes('calendar') || cat.includes('project')
  if (catId === 'finance') return cat.includes('finance') || cat.includes('payment') || cat.includes('billing') || cat.includes('account') || cat.includes('invoice') || cat.includes('money')
  return cat.includes(catId)
}
