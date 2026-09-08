// Phase 13 workflow-debugger helpers (pure, unit-tested).
//
// Everything here works off the execution payload the API returns:
//   { status, trace:[{node_id,node_type,status,started_at,duration_ms,
//     inputs,outputs,error,note,attempts,retries}], results:{outputs},
//     node_statuses, trigger_data, ... }

export const MASK = "\u2022".repeat(8);

const SENSITIVE_MARKERS = [
  "password", "passwd", "secret", "token", "api_key", "apikey",
  "authorization", "auth", "cookie", "credential", "private_key",
  "access_key", "session", "signature",
];

export function sensitiveKey(key) {
  const lowered = String(key).toLowerCase().replace(/-/g, "_");
  return SENSITIVE_MARKERS.some((m) => lowered.includes(m));
}

/** Client-side defence-in-depth mirror of the backend redactor. */
export function maskJson(value, depth = 0) {
  if (depth > 12) return value;
  if (Array.isArray(value)) return value.map((v) => maskJson(v, depth + 1));
  if (value && typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] =
        v && typeof v === "object"
          ? maskJson(v, depth + 1)
          : typeof v === "string" && sensitiveKey(k)
            ? MASK
            : v;
    }
    return out;
  }
  return value;
}

/**
 * Timeline spans: position each step on [0..100]% of the run window.
 * Returns [] when there is nothing to place.
 */
export function computeSpans(steps) {
  const withStart = (steps || []).filter(
    (s) => s && s.started_at && !Number.isNaN(Date.parse(s.started_at)),
  );
  if (!withStart.length) return [];
  let t0 = Infinity;
  let t1 = -Infinity;
  for (const s of withStart) {
    const start = Date.parse(s.started_at);
    const end = start + Math.max(s.duration_ms || 0, 0);
    if (start < t0) t0 = start;
    if (end > t1) t1 = end;
  }
  const total = Math.max(t1 - t0, 1);
  return withStart
    .map((s) => {
      const start = Date.parse(s.started_at);
      const duration = Math.max(s.duration_ms || 0, 0);
      return {
        step: s,
        startMs: start - t0,
        endMs: start - t0 + duration,
        leftPct: ((start - t0) / total) * 100,
        widthPct: Math.max((duration / total) * 100, 0.75),
      };
    })
    .sort((a, b) => a.startMs - b.startMs || b.widthPct - a.widthPct);
}

export function totalSpanMs(spans) {
  if (!spans.length) return 0;
  return spans[spans.length - 1].endMs;
}

/**
 * Branches taken by a routing node (if_condition / switch): derived from
 * the persisted outputs keyed by handle — 'true'/'false', 'route_0..' +
 * 'default'. Non-routing nodes return [].
 */
const ROUTING_HANDLE_RE = /^(true|false|default|route_\d+)$/;

export function deriveBranches(step, outputsByNode) {
  const byHandle = outputsByNode?.[step?.node_id];
  if (!byHandle || typeof byHandle !== "object") return [];
  const handles = Object.keys(byHandle).filter(
    (h) => ROUTING_HANDLE_RE.test(h) && Array.isArray(byHandle[h]),
  );
  if (!handles.length) return [];
  return handles.map((h) => ({
    handle: h,
    items: byHandle[h].length,
    taken: byHandle[h].length > 0,
  }));
}

/**
 * API status code from well-known output shapes:
 * HTTP Request emits {status, headers, body}; paginated variants emit
 * {status, items}. Returns null when the step is not an API call.
 */
export function extractApiStatus(outputs) {
  const main = outputs?.main;
  if (!Array.isArray(main) || !main.length) return null;
  const first = main[0];
  if (first && typeof first === "object") {
    if (typeof first.status === "number" && ("body" in first || "items" in first)) {
      return first.status;
    }
  }
  return null;
}

/** Connector id from the engine's note text ("Via connector 'stripe'."). */
export function connectorIdFromNote(note) {
  if (typeof note !== "string") return null;
  const m = note.match(/Via connector '([^']+)'/);
  return m ? m[1] : null;
}

/**
 * Retry-safety classification for the "retry node" affordance.
 * safe    = declared idempotent / conditionally idempotent
 * caution = non-idempotent or unknown — UI asks for confirmation.
 */
export function retrySafety(catalogEntry, nodeType) {
  void nodeType;
  if (!catalogEntry) return "caution";
  const idem = catalogEntry.idempotency;
  if (idem === "idempotent" || idem === "conditionally_idempotent") {
    return "safe";
  }
  if (catalogEntry.operations && Object.keys(catalogEntry.operations).length) {
    // Connector nodes: every advertised op must be retry-safe.
    const all = Object.values(catalogEntry.operations).every(
      (op) => op.idempotency === "idempotent" || op.idempotency === "conditionally_idempotent",
    );
    return all ? "safe" : "caution";
  }
  return idem === "non_idempotent" ? "caution" : "caution";
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`).join(",")}}`;
}

export function outputsEqual(a, b) {
  return stableStringify(a ?? null) === stableStringify(b ?? null);
}

/**
 * Compare two executions of the same workflow, keyed by node id.
 * Rows carry both sides so the UI renders one aligned table.
 */
export function diffExecutions(base, cmp) {
  const baseById = new Map((base?.trace || []).map((s) => [s.node_id, s]));
  const cmpById = new Map((cmp?.trace || []).map((s) => [s.node_id, s]));
  const ids = [...new Set([...baseById.keys(), ...cmpById.keys()])];

  const baseStatuses = base?.node_statuses || {};
  const cmpStatuses = cmp?.node_statuses || {};
  const baseOutputs = base?.results?.outputs || {};
  const cmpOutputs = cmp?.results?.outputs || {};

  return ids.map((nodeId) => {
    const bs = baseById.get(nodeId);
    const cs = cmpById.get(nodeId);
    const baseDuration = bs?.duration_ms ?? null;
    const cmpDuration = cs?.duration_ms ?? null;
    const delta =
      baseDuration != null && cmpDuration != null ? cmpDuration - baseDuration : null;
    const baseOut = JSON.stringify(baseOutputs[nodeId] ?? null);
    const cmpOut = JSON.stringify(cmpOutputs[nodeId] ?? null);
    return {
      nodeId,
      inBoth: Boolean(bs && cs),
      baseStatus: baseStatuses[nodeId] || bs?.status || (bs ? "success" : "absent"),
      cmpStatus: cmpStatuses[nodeId] || cs?.status || (cs ? "success" : "absent"),
      baseDuration,
      cmpDuration,
      durationDelta: delta,
      outputsChanged: baseOut !== cmpOut,
      baseRetries: bs?.retries || 0,
      cmpRetries: cs?.retries || 0,
    };
  });
}
