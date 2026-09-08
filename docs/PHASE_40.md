# Phase 40 — Safe Expression Engine Hardening

## New resolution surface
- **Quoted bracket keys**: `$node["My Node"].json`, `$json['a b']`,
  `data["a-b"]` — any characters allowed inside quotes; bare words too.
- **Multi-bracket paths**: `rows[0]["Cell A"].x` walk correctly.
- **Depth caps**: paths >64 segments refused (no stack blowout).
- **Type-validation pipes**: `| int`, `| float`, `| bool`,
  `| typeof` (typeof null → Python None; typeof distinguishes
  boolean/number/string/array/object/null).
- Null handling contract pinned by tests: missing → visibly unresolved;
  `??` keeps falsy-but-present values (`0`, `""`); explicit `null`
  compares equal to `""`/None as expected.

## Security guarantees (new test file, 20 cases)
1. Source scan: no `eval(`/`exec(`/`__import__(`/`os.system(` anywhere
   in the module.
2. Dunder traversal refused at tokenizer level: `$json.__class__`,
   `$json["__proto__"]`, `a.__globals__` resolve to None/unresolved —
   never to Python internals.
3. Hostile-input battery (16 malformed/hostile expressions) never
   raises out of `resolve()`; each returns None or stays visibly
   unresolved per contract.
4. Secret hygiene: an unresolvable `$cred…` expression does not echo
   other context values (asserted against a planted secret).
5. Deep-payload walks are bounded; no RecursionError.

## Autocomplete endpoint
`GET /api/workflows/{id}/expression-context` → variables ($json,
$node, $execution, $workflow, $now, $cred), node id/type list for the
current workflow, pipe catalog, and workspace env-var KEYS only
(values never leave the vault). Access-checked (404 hides foreign
workflows). Editor dropdown wiring is a UI follow-up.

## Tests (25 new: 20 security + shape/quoting + 2 endpoint)
All existing 66 expression tests unchanged and passing.

## Evidence
Expression suites 94/94 · dual-pass full suite green on rerun (fast
672→673 incl. new tests; timing 123/123) with the two first-run flakes
reproducing-green isolated (documented contention class) · pyright
repo-wide 0 errors.

## Known limitations / follow-ups
- No string-literal function args beyond contains/replace; no date math.
- Editor autocomplete dropdown UI not wired yet (endpoint ready).
