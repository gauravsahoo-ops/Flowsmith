#!/usr/bin/env node
/**
 * Stub server for n8n-workflow E2E test.
 * Handles: login, data fetch, search, create, update
 * Port: 8182 (separate from salesforce stub on 8181)
 */
import http from 'node:http';

const PORT = 8182;
const records = new Map();

// Seed some existing records
records.set('rec_001', { Id: 'rec_001', Name: 'Existing Record', Email: 'existing@test.com', Company: 'TestCo' });
records.set('rec_002', { Id: 'rec_002', Name: 'Another Record', Email: 'another@test.com', Company: 'TestCo' });

let nextId = 3;

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function collectBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => resolve(body));
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname;
  const method = req.method;

  // POST /api/login — authentication
  if (method === 'POST' && path === '/api/login') {
    const body = JSON.parse((await collectBody(req)) || '{}');
    if (body.email && body.password) {
      return sendJson(res, 200, { token: 'stub-jwt-token-12345', user: { email: body.email } });
    }
    return sendJson(res, 401, { error: 'Invalid credentials' });
  }

  // GET /api/data — returns a list of items to process
  if (method === 'GET' && path === '/api/data') {
    return sendJson(res, 200, {
      items: [
        { id: 'item_1', name: 'First Item', email: 'first@test.com' },
        { id: 'item_2', name: 'Second Item', email: 'second@test.com' },
        { id: 'item_3', name: 'Third Item', email: 'third@test.com' },
      ],
      total: 3,
    });
  }

  // GET /api/search/:id — check if a custom object exists
  const searchMatch = path.match(/^\/api\/search\/(.+)$/);
  if (method === 'GET' && searchMatch) {
    const searchId = searchMatch[1];
    // Check if any record matches the search
    for (const [, rec] of records) {
      if (rec.Email === searchId || rec.Id === searchId) {
        return sendJson(res, 200, { found: true, record: rec });
      }
    }
    return sendJson(res, 200, { found: false, record: null });
  }

  // POST /api/objects — create a custom object
  if (method === 'POST' && path === '/api/objects') {
    const body = JSON.parse((await collectBody(req)) || '{}');
    const id = `rec_${String(nextId++).padStart(3, '0')}`;
    const rec = { Id: id, ...body };
    records.set(id, rec);
    return sendJson(res, 201, { id, success: true });
  }

  // PATCH /api/objects/:id — update a custom object
  const updateMatch = path.match(/^\/api\/objects\/(.+)$/);
  if (method === 'PATCH' && updateMatch) {
    const updateId = updateMatch[1];
    const rec = records.get(updateId);
    if (!rec) return sendJson(res, 404, { error: 'Not found' });
    const body = JSON.parse((await collectBody(req)) || '{}');
    Object.assign(rec, body);
    return sendJson(res, 200, { id: updateId, success: true });
  }

  // GET /api/health — health check
  if (method === 'GET' && path === '/api/health') {
    return sendJson(res, 200, { status: 'ok' });
  }

  sendJson(res, 404, { error: 'Not found' });
});

server.listen(PORT, () => {
  console.log(`n8n-workflow stub server listening on http://127.0.0.1:${PORT}`);
});

process.on('SIGTERM', () => server.close());
process.on('SIGINT', () => server.close());
