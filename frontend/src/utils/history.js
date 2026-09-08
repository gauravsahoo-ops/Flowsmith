// Undo/redo history for the editor (pure logic — unit-tested directly).
//
// Snapshots are shallow: {nodes, edges} arrays are copied on push, node
// objects themselves are treated as immutable (the store never mutates
// them in place), so snapshots stay cheap even for large graphs.

export const HISTORY_LIMIT = 100;

/** How long edits with the same coalesce key merge into one undo step. */
const COALESCE_MS = 600;

function snapshot(nodes, edges) {
  return { nodes: nodes.slice(), edges: edges.slice() };
}

/**
 * A tiny undo/redo stack.
 * `push(present, coalesceKey?)` records the current state before a
 * mutation; consecutive pushes sharing a coalesceKey within COALESCE_MS
 * replace the previous entry (so typing a parameter doesn't spam history).
 */
export function createHistory(_initialNodes = [], _initialEdges = []) {
  let past = [];
  let future = [];
  let lastKey = null;
  let lastAt = 0;

  return {
    push(nodes, edges, coalesceKey = null) {
      const now = Date.now();
      const merge =
        coalesceKey !== null &&
        coalesceKey === lastKey &&
        now - lastAt < COALESCE_MS;
      if (!merge) {
        past.push(snapshot(nodes, edges));
        if (past.length > HISTORY_LIMIT) past.shift();
      }
      lastKey = coalesceKey;
      lastAt = now;
      future = [];
    },

    /**
     * Undo from `current`; returns the state to restore or null.
     * The current state is pushed onto the redo stack.
     */
    undo(current) {
      if (!past.length) return null;
      const prev = past.pop();
      future.push(snapshot(current.nodes, current.edges));
      lastKey = null; // a discrete jump breaks any run of merges
      return prev;
    },

    /** Redo after an undo; returns the state to restore or null. */
    redo(current) {
      if (!future.length) return null;
      const next = future.pop();
      past.push(snapshot(current.nodes, current.edges));
      lastKey = null;
      return next;
    },

    /** Any new mutation invalidates the redo branch. */
    clearFuture() {
      future = [];
    },

    canUndo() {
      return past.length > 0;
    },
    canRedo() {
      return future.length > 0;
    },
    reset() {
      past = [];
      future = [];
      lastKey = null;
      lastAt = 0;
    },
  };
}
