// Comprehensive Salesforce REST API stub for E2E suite.
//
// Supports ALL objects: Account, Contact, Lead, Opportunity, Case, Task,
// Custom Object, plus ContentNote (Add Note), Search (SOSL), Get Summary,
// Create or Update (upsert), and Custom API Call.
//
// Operations:
//   POST   /services/oauth2/token                          -> access_token
//   GET    /services/data/{v}/query?q=SOQL                 -> query result
//   GET    /services/data/{v}/search?q=SOSL                -> search result
//   GET    /services/data/{v}/sobjects/{obj}/describe      -> metadata summary
//   GET    /services/data/{v}/sobjects/{obj}/{id}          -> record
//   POST   /services/data/{v}/sobjects/{obj}               -> create
//   PATCH  /services/data/{v}/sobjects/{obj}/{id}          -> update
//   DELETE /services/data/{v}/sobjects/{obj}/{id}          -> delete
//   GET    /services/data/{v}/sobjects/{obj}               -> object metadata

import http from 'node:http';
import crypto from 'node:crypto';

const PORT = 8181;
const INSTANCE_URL = `http://127.0.0.1:${PORT}`;

// In-memory store: id -> record
const records = new Map();
const index = new Map();

function putRecord(rec) {
  records.set(rec.Id, rec);
  const obj = rec.attributes?.type || '';
  const key = (f, v) => `${obj}::${f.toLowerCase()}::${String(v).toLowerCase()}`;
  for (const [f, v] of Object.entries(rec)) {
    if (f === 'Id' || f === 'attributes') continue;
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
      const k = key(f, v);
      if (!index.has(k)) index.set(k, []);
      const list = index.get(k);
      if (!list.includes(rec.Id)) list.push(rec.Id);
    }
  }
}

function newRecordId(obj) {
  const prefixes = {
    Account: '001', Contact: '003', Lead: '00Q', Opportunity: '006',
    Case: '500', Task: '00T', ContentNote: '069', ContentVersion: '068',
    Document: '015', User: '005', Flow: '300', Attachment: '01P',
    'Custom_Object__c': 'a00',
  };
  const p = prefixes[obj] || '0XX';
  return (p + crypto.randomBytes(8).toString('hex').toUpperCase().slice(0, 12)).slice(0, 15);
}

// Seed default records for each object type
const SEED_RECORDS = [
  { Id: '001AA000003TEST', attributes: { type: 'Account' }, Name: 'Acme Corp', Industry: 'Technology', Phone: '555-0100', Upsert_Key__c: 'ACME-001' },
  { Id: '003AA000001TEST', attributes: { type: 'Contact' }, FirstName: 'Jane', LastName: 'Doe', Email: 'jane@example.com' },
  { Id: '00QAA000001TEST', attributes: { type: 'Lead' }, FirstName: 'Ada', LastName: 'Lovelace', Company: 'ACME', Email: 'ada@example.com' },
  { Id: '006AA000001TEST', attributes: { type: 'Opportunity' }, Name: 'Big Deal', StageName: 'Prospecting', CloseDate: '2026-12-31' },
  { Id: '500AA000001TEST', attributes: { type: 'Case' }, Subject: 'Login Issue', Status: 'New', Origin: 'Email' },
  { Id: '00TAA000001TEST', attributes: { type: 'Task' }, Subject: 'Follow up', Status: 'Not Started', Priority: 'Normal' },
  { Id: '015AA000001TEST', attributes: { type: 'Document' }, Name: 'Report.pdf', FolderId: '00lAA000001FOLD', Body: 'base64data' },
  { Id: '005AA000001TEST', attributes: { type: 'User' }, Name: 'Test User', Email: 'testuser@example.com' },
  { Id: '300AA000001TEST', attributes: { type: 'Flow' }, MasterLabel: 'My Flow', Status: 'Active' },
  { Id: 'a00AA000001TEST', attributes: { type: 'Custom_Object__c' }, Name: 'Custom Record', Status__c: 'Active' },
];
SEED_RECORDS.forEach((r) => putRecord(r));

function seed(obj, id, fields) {
  putRecord({ Id: id, attributes: { type: obj }, ...fields });
}

// ── Seed data ──────────────────────────────────────────────────
seed('Account', '001000000000001', { Name: 'Acme Corp', Industry: 'Technology', Phone: '555-0100', Website: 'https://acme.test' });
seed('Contact', '003000000000001', { FirstName: 'Jane', LastName: 'Doe', Email: 'jane.doe@test.com', AccountId: '001000000000001' });
seed('Lead', '00Q000000000001', { Name: 'Ada Lovelace', Email: 'ada.e2e@example.com', Company: 'Original Co', Status: 'New' });
seed('Opportunity', '006000000000001', { Name: 'Big Deal', AccountId: '001000000000001', Amount: 50000, StageName: 'Prospecting', CloseDate: '2026-12-31' });
seed('Case', '500000000000001', { Subject: 'Login issue', Status: 'New', Priority: 'High', AccountId: '001000000000001' });
seed('Task', '00T000000000001', { Subject: 'Follow up call', Status: 'Not Started', Priority: 'Normal', WhoId: '003000000000001' });

function sendJson(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function sendEmpty(res, status) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end();
}

function notFound(res, id) {
  sendJson(res, 404, [{ errorCode: 'NOT_FOUND', message: `The requested resource does not exist (${id})` }]);
}

function collectBody(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (c) => (raw += c));
    req.on('end', () => resolve(raw));
  });
}

function parseSoql(q) {
  const m = /SELECT\s+(.+?)\s+FROM\s+([A-Za-z_]\w*)(?:\s+WHERE\s+(.+?))?(?:\s+ORDER\s+BY\s+\w+(?:\s+ASC|\s+DESC)?)?(?:\s+LIMIT\s+(\d+))?\s*$/i.exec(q.trim());
  if (!m) return null;
  const where = m[3] ? /^\s*(\w+)\s*=\s*'([^']*)'/i.exec(m[3].trim()) : null;
  return {
    fields: m[1].split(',').map((s) => s.trim()),
    object: m[2],
    whereField: where ? where[1] : null,
    whereValue: where ? where[2] : null,
    limit: m[4] ? Number(m[4]) : null,
  };
}

function runQuery(q) {
  const soql = parseSoql(q);
  if (!soql) return null;
  const all = [];
  for (const rec of records.values()) {
    if (rec.attributes.type !== soql.object) continue;
    if (soql.whereField) {
      const actual = rec[soql.whereField];
      const want = soql.whereValue;
      if (actual === undefined) continue;
      if (String(actual).toLowerCase() !== String(want).toLowerCase()) continue;
    }
    all.push(rec);
  }
  const page = soql.limit ? all.slice(0, soql.limit) : all;
  return { totalSize: all.length, done: true, records: page };
}

function runSearch(q) {
  // SOSL: FIND {term} IN ALL FIELDS [RETURNING Object(Id, Field1, Field2)]
  const m = /FIND\s+\{(.+?)\}\s+IN\s+ALL\s+FIELDS(?:\s+RETURNING\s+(\w+)\((.+?)\))?/i.exec(q.trim());
  if (!m) return null;
  const [, term, obj, fieldsStr] = m;
  const fields = fieldsStr ? fieldsStr.split(',').map((s) => s.trim()) : null;
  const all = [];
  for (const rec of records.values()) {
    if (obj && rec.attributes.type !== obj) continue;
    const matches = Object.values(rec).some((v) =>
      typeof v === 'string' && v.toLowerCase().includes(term.toLowerCase())
    );
    if (matches) {
      if (fields) {
        const projection = { Id: rec.Id };
        for (const f of fields) {
          if (f !== 'Id' && rec[f] !== undefined) projection[f] = rec[f];
        }
        all.push(projection);
      } else {
        all.push({ Id: rec.Id, ...Object.fromEntries(Object.entries(rec).filter(([k]) => k !== 'Id' && k !== 'attributes')) });
      }
    }
  }
  return { searchRecords: all };
}

function getSummary(obj) {
  const all = [];
  for (const rec of records.values()) {
    if (rec.attributes.type === obj) all.push(rec);
  }
  return {
    describe: {
      name: obj,
      label: obj,
      createable: true,
      deletable: true,
      queryable: true,
      fields: Object.keys(all[0] || {}).filter((f) => f !== 'Id' && f !== 'attributes').map((f) => ({
        name: f, label: f, type: 'string',
      })),
    },
    records: all,
    totalCount: all.length,
  };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;
  const method = req.method || 'GET';

  // Health check
  if (path === '/health') return sendJson(res, 200, { ok: true });

  // OAuth2 token
  if (method === 'POST' && /^\/services\/oauth2\/token$/.test(path)) {
    return sendJson(res, 200, {
      access_token: 'e2e-access-token',
      instance_url: INSTANCE_URL,
      token_type: 'Bearer',
      issued_at: Date.now(),
    });
  }

  // ── SOSL Search ───────────────────────────────────────────────
  if (method === 'GET' && /^\/services\/data\/[^/]+\/search$/.test(path)) {
    const result = runSearch(url.searchParams.get('q') || '');
    if (!result) return sendJson(res, 400, [{ errorCode: 'MALFORMED_QUERY', message: 'Bad search query' }]);
    return sendJson(res, 200, result);
  }

  // ── SOQL Query ────────────────────────────────────────────────
  if (method === 'GET' && /^\/services\/data\/[^/]+\/query$/.test(path)) {
    const result = runQuery(url.searchParams.get('q') || '');
    if (!result) return sendJson(res, 400, [{ errorCode: 'MALFORMED_QUERY', message: 'Malformed query' }]);
    return sendJson(res, 200, result);
  }

  // ── Object describe (Get Summary) ─────────────────────────────
  const summaryMatch = /^\/services\/data\/[^/]+\/sobjects\/([^/]+)\/describe$/.exec(path);
  if (method === 'GET' && summaryMatch) {
    return sendJson(res, 200, getSummary(summaryMatch[1]));
  }

  // ── SObject CRUD ──────────────────────────────────────────────
  const sobjMatch = /^\/services\/data\/[^/]+\/sobjects\/([^/]+)(?:\/([^/]+))?$/.exec(path);
  if (sobjMatch) {
    const [, obj, recordId] = sobjMatch;

    // GET /sobjects/{obj} — list metadata
    if (!recordId && method === 'GET') {
      return sendJson(res, 200, { sobjects: [{ name: obj, label: obj, createable: true }] });
    }

    // POST /sobjects/{obj} — create
    if (!recordId && method === 'POST') {
      const body = JSON.parse((await collectBody(req)) || '{}');
      const id = newRecordId(obj);
      putRecord({ Id: id, attributes: { type: obj }, ...body });
      return sendJson(res, 201, { id, success: true });
    }

    // GET /sobjects/{obj}/{id} — get record
    if (recordId && method === 'GET') {
      const rec = records.get(recordId);
      return rec ? sendJson(res, 200, rec) : notFound(res, recordId);
    }

    // PATCH /sobjects/{obj}/{id} — update
    if (recordId && method === 'PATCH') {
      const body = JSON.parse((await collectBody(req)) || '{}');
      const rec = records.get(recordId);
      if (!rec) return notFound(res, recordId);
      Object.assign(rec, body);
      return sendEmpty(res, 204);
    }

    // DELETE /sobjects/{obj}/{id} — delete
    if (recordId && method === 'DELETE') {
      if (!records.delete(recordId)) return notFound(res, recordId);
      return sendEmpty(res, 204);
    }
  }

  // ── Upsert ────────────────────────────────────────────────────
  // PATCH /sobjects/{obj}/{extIdField}/{extId} — upsert (create or update)
  const upsertMatch = /^\/services\/data\/[^/]+\/sobjects\/([^/]+)\/([^/]+)\/([^/]+)$/.exec(path);
  if (upsertMatch && method === 'PATCH') {
    const [, obj, extIdField, extId] = upsertMatch;
    const body = JSON.parse((await collectBody(req)) || '{}');
    const extKey = `${obj}:${extIdField}:${extId}`;
    let rec = records.get(extKey);
    if (rec) {
      Object.assign(rec, body);
    } else {
      const id = newRecordId(obj);
      rec = { Id: id, attributes: { type: obj }, [extIdField]: extId, ...body };
      putRecord(rec);
    }
    return sendEmpty(res, 200);
  }

  // ── Custom API Call (generic) ──────────────────────────────────
  // POST /services/data/{v}/custom/api/* — pass-through
  if (/^\/services\/data\/[^/]+\/custom\//.test(path)) {
    const body = JSON.parse((await collectBody(req)) || '{}');
    return sendJson(res, 200, { success: true, endpoint: path, body });
  }

  // ── Generic catch-all (for mapping test /get, /post, etc.) ─────
  const body = JSON.parse((await collectBody(req)) || '{}');
  return sendJson(res, 200, { ok: true, path, method, body });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Salesforce stub listening on ${INSTANCE_URL}`);
});
