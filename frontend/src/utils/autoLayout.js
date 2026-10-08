// Dependency-free layered auto-layout (Sugiyama-lite).
//
// Layers = longest path from any root; within-layer order by barycenter of
// neighbours (two sweeps); positions spread on a fixed grid. Deterministic:
// same graph in, same coordinates out. Pure so it unit-tests without React.

const NODE_W = 172;
const NODE_H = 64;
const GAP_X = 90;
const GAP_Y = 60;

/**
 * Lay out `nodes` (React Flow shape) according to `edges`.
 * direction: "LR" | "TB". Returns a Map id -> {x, y} (absolute).
 * Isolated nodes keep their relative order, laid out in a column.
 */
export function autoLayout(nodes, edges, direction = 'LR') {
  const ids = nodes.map((n) => n.id);
  const idSet = new Set(ids);
  const cleanEdges = edges.filter((e) => idSet.has(e.source) && idSet.has(e.target));

  const outgoing = new Map(ids.map((id) => [id, []]));
  const incoming = new Map(ids.map((id) => [id, []]));
  for (const e of cleanEdges) {
    if (e.source === e.target) continue;
    outgoing.get(e.source).push(e.target);
    incoming.get(e.target).push(e.source);
  }

  // -- layer assignment: longest path from roots -------------------------
  const layer = new Map(ids.map((id) => [id, 0]));
  const indeg = new Map(ids.map((id) => [id, incoming.get(id).length]));

  // Kahn topsort ignoring cycles: when a cycle blocks progress, force the
  // lowest-indegree remaining node into the next layer.
  const queue = ids.filter((id) => indeg.get(id) === 0);
  const placed = new Set();
  let frontier = [...queue];
  let depth = 0;
  while (placed.size < ids.length) {
    const nextFrontier = [];
    for (const id of frontier) {
      if (placed.has(id)) continue;
      placed.add(id);
      layer.set(id, Math.max(layer.get(id), depth));
      for (const next of outgoing.get(id)) {
        indeg.set(next, indeg.get(next) - 1);
        if (indeg.get(next) === 0) nextFrontier.push(next);
      }
    }
    if (nextFrontier.length === 0 && placed.size < ids.length) {
      // Cycle: promote one unplaced node with minimal indegree.
      let best = null;
      let bestDeg = Infinity;
      for (const id of ids) {
        if (placed.has(id)) continue;
        const deg = Math.max(indeg.get(id), 0);
        if (deg < bestDeg) {
          bestDeg = deg;
          best = id;
        }
      }
      frontier = [best];
      depth += 1;
      continue;
    }
    frontier = nextFrontier;
    depth += 1;
  }

  // -- ordering: two barycenter sweeps -----------------------------------
  const layers = new Map();
  for (const id of ids) {
    const l = layer.get(id);
    if (!layers.has(l)) layers.set(l, []);
    layers.get(l).push(id);
  }
  for (const list of layers.values()) list.sort((a, b) => a.localeCompare(b));
  for (let sweep = 0; sweep < 2; sweep += 1) {
    const descending = sweep % 2 === 1;
    const orderedLayers = [...layers.keys()].sort((a, b) => (descending ? b - a : a - b));
    for (const l of orderedLayers) {
      const list = layers.get(l);
      const scored = list.map((id) => {
        const neighbours = descending ? outgoing.get(id) : incoming.get(id);
        const positions = neighbours
          .map((n) => layers.get(layer.get(n))?.indexOf(n))
          .filter((i) => i != null && i >= 0);
        const barycenter = positions.length
          ? positions.reduce((a, b) => a + b, 0) / positions.length
          : list.indexOf(id);
        return { id, barycenter };
      });
      scored.sort((a, b) => a.barycenter - b.barycenter || a.id.localeCompare(b.id));
      layers.set(l, scored.map((s) => s.id));
    }
  }

  // -- coordinates --------------------------------------------------------
  const horizontal = direction === 'LR';
  const sortedDepths = [...layers.keys()].sort((a, b) => a - b);
  const positions = new Map();
  const alongGap = horizontal ? NODE_W + GAP_X : NODE_H + GAP_Y;
  const crossGap = horizontal ? NODE_H + GAP_Y : NODE_W + GAP_X;
  for (const l of sortedDepths) {
    const list = layers.get(l);
    list.forEach((id, i) => {
      const along = l * alongGap;
      const across = i * crossGap;
      positions.set(
        id,
        horizontal
          ? { x: along, y: across }
          : { x: across, y: along },
      );
    });
  }

  // Isolated nodes (no edges at all): park them in their own right column.
  const connected = new Set();
  for (const e of cleanEdges) {
    connected.add(e.source);
    connected.add(e.target);
  }
  const maxDepth = sortedDepths.length ? sortedDepths[sortedDepths.length - 1] + 1 : 0;
  const isolated = ids.filter((id) => !connected.has(id));
  isolated.forEach((id, i) => {
    positions.set(
      id,
      horizontal
        ? { x: (maxDepth + 1) * alongGap, y: i * crossGap }
        : { x: i * alongGap, y: (maxDepth + 1) * alongGap },
    );
  });

  return positions;
}

export const AUTO_LAYOUT_METRICS = { NODE_W, NODE_H, GAP_X, GAP_Y };

/**
 * Smoothly interpolates node positions to targetPositions using requestAnimationFrame.
 * Creates a fluid 60fps glide animation across the canvas instead of an abrupt jump.
 */
export function animateAutoLayout(store, targetPositions, duration = 280, onComplete) {
  if (!store || !targetPositions || targetPositions.size === 0) {
    if (onComplete) onComplete();
    return;
  }
  const currentNodes = store.nodes || [];
  const startPositions = new Map();
  for (const n of currentNodes) {
    if (targetPositions.has(n.id) && n.position) {
      startPositions.set(n.id, { x: n.position.x, y: n.position.y });
    }
  }

  if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
    store.onNodesChange(
      [...targetPositions.entries()].map(([id, position]) => ({
        id,
        type: 'position',
        position,
        dragging: false,
      }))
    );
    if (onComplete) onComplete();
    return;
  }

  const startTime = performance.now();
  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(1, elapsed / duration);
    const ease = 1 - Math.pow(1 - progress, 3);

    const changes = [];
    for (const [id, target] of targetPositions.entries()) {
      const start = startPositions.get(id) || target;
      changes.push({
        id,
        type: 'position',
        position: {
          x: Math.round(start.x + (target.x - start.x) * ease),
          y: Math.round(start.y + (target.y - start.y) * ease),
        },
        dragging: false,
      });
    }
    store.onNodesChange(changes);

    if (progress < 1) {
      requestAnimationFrame(step);
    } else if (onComplete) {
      onComplete();
    }
  }
  requestAnimationFrame(step);
}
