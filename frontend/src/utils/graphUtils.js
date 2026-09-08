// Graph helpers for the editor: cycle prevention and reachability.
// Pure functions so they unit-test without React or the stores.

export function edgeKey(e) {
  return `${e.source}|${e.sourceHandle ?? 'main'}|${e.target}|${e.targetHandle ?? 'main'}`;
}

/**
 * Would adding source->target introduce a cycle?
 * True when target can already reach source (or source === target):
 * the new wire closes a loop back into an ancestor.
 */
export function wouldCreateCycle(edges, source, target) {
  if (!source || !target) return false;
  if (source === target) return true;
  // Walk upstream (predecessors) from SOURCE searching for TARGET.
  const incoming = new Map();
  for (const e of edges) {
    if (!incoming.has(e.target)) incoming.set(e.target, []);
    incoming.get(e.target).push(e.source);
  }
  const stack = [source];
  const seen = new Set();
  while (stack.length) {
    const current = stack.pop();
    if (current === target) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    for (const prev of incoming.get(current) || []) stack.push(prev);
  }
  return false;
}

/** Nodes reachable from `start` following edges downstream (excludes start). */
export function descendants(edges, start) {
  const out = new Set();
  const adjacency = new Map();
  for (const e of edges) {
    if (!adjacency.has(e.source)) adjacency.set(e.source, []);
    adjacency.get(e.source).push(e.target);
  }
  const stack = [...(adjacency.get(start) || [])];
  while (stack.length) {
    const id = stack.pop();
    if (out.has(id)) continue;
    out.add(id);
    for (const next of adjacency.get(id) || []) stack.push(next);
  }
  return out;
}

/** Nodes reachable from `start` walking upstream predecessors (in reverse topological order). */
export function ancestors(edges, start) {
  const out = [];
  const seen = new Set();
  const incoming = new Map();
  for (const e of edges) {
    if (!incoming.has(e.target)) incoming.set(e.target, []);
    incoming.get(e.target).push(e.source);
  }
  const queue = [...(incoming.get(start) || [])];
  while (queue.length) {
    const id = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(id);
    for (const prev of incoming.get(id) || []) queue.push(prev);
  }
  return out;
}

/**
 * Validate an existing graph: returns { ok, problems[] } with human
 * readable messages. Used by the canvas status strip.
 */
export function validateGraph(nodes, edges) {
  const problems = [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const seenEdges = new Set();
  let cycles = 0;
  for (const e of edges) {
    const key = edgeKey(e);
    if (seenEdges.has(key)) {
      problems.push(`Duplicate connection ${e.source} → ${e.target}`);
      continue;
    }
    seenEdges.add(key);
    if (!byId.has(e.source)) problems.push(`Connection from missing node “${e.source}”`);
    if (!byId.has(e.target)) problems.push(`Connection to missing node “${e.target}”`);
    // Allow loop-back for Loop-family targets (visual continuation, not a true DAG cycle)
    const targetNode = byId.get(e.target)
    const isLoopCycle = targetNode && ['loop', 'split', 'loop_over_items', 'loop_while'].includes(targetNode.data?.node?.type || targetNode.type)
    if (!isLoopCycle && wouldCreateCycle(edges.filter((x) => x !== e), e.source, e.target)) cycles += 1;
  }
  if (cycles > 0) problems.push(`${cycles} cycle${cycles > 1 ? 's' : ''} — runs will loop forever unless a condition breaks them`);
  const orphans = nodes.filter(
    (n) => !edges.some((e) => e.source === n.id || e.target === n.id),
  );
  for (const o of orphans) {
    const label = o.data?.node?.type || o.id;
    problems.push(`“${label}” (${o.id}) is not connected to anything`);
  }
  return { ok: problems.length === 0, problems };
}
