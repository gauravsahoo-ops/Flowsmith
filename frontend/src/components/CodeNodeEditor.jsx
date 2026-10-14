import { useState, useEffect, useRef } from 'react'
import Editor, { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/language/typescript/ts.worker?worker'
import ErrorState from './shared/ErrorState'
import { getToken } from '../api'

// Self-host Monaco: bundle the editor and its workers from our own origin
// so the strict CSP (script-src 'self') never falls back to a CDN.
self.MonacoEnvironment = {
  getWorker(_id, label) {
    if (label === 'json') return new jsonWorker()
    if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker()
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker()
    if (label === 'typescript' || label === 'javascript') return new tsWorker()
    return new editorWorker()
  },
}
loader.config({ monaco })

const MODE_OPTIONS = [
  { value: 'runOnceForAllItems', label: 'Run Once for All Items' },
  { value: 'runOnceForEachItem', label: 'Run Once for Each Item' },
]

const LANGUAGE_OPTIONS = [
  { value: 'javascript', label: 'JavaScript' },
  { value: 'python', label: 'Python (sandbox)' },
]

const DEFAULT_CODE = {
  javascript: 'for (const item of $input.all()) {\n  item.json.myNewField = 1;\n}\nreturn $input.all();',
  python: '# Process items and return output\noutput = []\nfor item in items:\n    record = dict(item.get("json", item))\n    record["myNewField"] = 1\n    output.append({"json": record})\nreturn output',
}

const SNIPPETS = {
  javascript: [
    {
      label: 'Group Items by Field',
      code: `// Group items by category or key
const items = $input.all();
const grouped = {};
for (const item of items) {
  const key = item.json.category || 'default';
  if (!grouped[key]) grouped[key] = [];
  grouped[key].push(item.json);
}
return Object.entries(grouped).map(([category, items]) => ({ json: { category, items } }));`,
    },
    {
      label: 'Deduplicate by Unique Key',
      code: `// Deduplicate items matching by email or id
const seen = new Set();
const unique = [];
for (const item of $input.all()) {
  const key = item.json.email || item.json.id;
  if (!seen.has(key)) {
    seen.add(key);
    unique.push(item);
  }
}
return unique;`,
    },
    {
      label: 'Flatten Nested Arrays',
      code: `// Unroll nested arrays into individual output items
const output = [];
for (const item of $input.all()) {
  const records = item.json.records || [item.json];
  for (const r of records) {
    output.push({ json: r });
  }
}
return output;`,
    },
    {
      label: 'Filter Items by Condition',
      code: `// Keep only items that meet criteria
return $input.all().filter(item => {
  return item.json.status === 'active';
});`,
    },
    {
      label: 'Map & Rename Fields',
      code: `// Transform and rename fields cleanly
return $input.all().map(item => ({
  json: {
    id: item.json.id,
    title: item.json.name || item.json.title,
    processedAt: new Date().toISOString()
  }
}));`,
    },
  ],
  python: [
    {
      label: 'Salesforce Contact Ingest & State Normalizer',
      code: `STATE_MAP = {'AL': 'Alabama', 'CA': 'California', 'FL': 'Florida', 'NY': 'New York', 'TX': 'Texas'}
raw = items[0].get('json', items[0]) if items else {}
records = raw.get('records', [])
summary = raw.get('summary', {})
cleaned = []
for r in records:
    c = dict(r)
    c.pop('_row_number', None)
    st = c.get('MailingState', '')
    if st and st.upper() in STATE_MAP:
        c['MailingState'] = STATE_MAP[st.upper()]
    cleaned.append(c)
return [{
    'status': 'SUCCESS',
    'total_csv_records': summary.get('total_parsed', len(records)),
    'valid_unique_contacts': len(cleaned),
    'records': cleaned
}]`,
    },
    {
      label: 'Transform & Add Field',
      code: `# Process each item and add calculated fields
output = []
for item in items:
    record = dict(item.get("json", {}))
    record["processed"] = True
    output.append({"json": record})
return output`,
    },
    {
      label: 'Filter Active Items',
      code: `# Filter items based on criteria
output = [item for item in items if item.get("json", {}).get("status") == "active"]
return output`,
    },
  ],
}

export default function CodeNodeEditor({ node, onParamsChange }) {
  const params = node.parameters || {}
  const mode = params.mode || 'runOnceForAllItems'
  const language = params.language || 'javascript'
  const code = params.code || DEFAULT_CODE[language] || DEFAULT_CODE.javascript

  const [localCode, setLocalCode] = useState(code)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState(null)
  const editorRef = useRef(null)
  const providerDisposablesRef = useRef([])
  const paramsRef = useRef(params)
  paramsRef.current = params
  const onParamsChangeRef = useRef(onParamsChange)
  onParamsChangeRef.current = onParamsChange

  // Dispose monaco completion providers registered on mount — they are
  // process-global and would otherwise accumulate on every editor open.
  useEffect(() => () => {
    providerDisposablesRef.current.forEach((d) => {
      try { d.dispose() } catch { /* already disposed */ }
    })
    providerDisposablesRef.current = []
  }, [])

  useEffect(() => {
    setLocalCode(code)
  }, [code])

  // Debounced onChange to avoid too many saves
  useEffect(() => {
    if (localCode === code) return
    const t = setTimeout(() => {
      onParamsChangeRef.current({ ...paramsRef.current, code: localCode })
    }, 500)
    return () => clearTimeout(t)
  }, [localCode, code])

  async function handleCheckCode() {
    setValidating(true)
    setValidation(null)
    try {
      const res = await fetch('/api/nodes/code/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ code: localCode, language }),
      })
      const j = await res.json()
      if (j.data?.valid) {
        setValidation({ valid: true, message: 'Code is valid' })
      } else {
        setValidation({ valid: false, message: j.data?.message || 'Invalid code', line: j.data?.line, column: j.data?.column })
      }
    } catch (e) {
      setValidation({ valid: false, message: e.message })
    } finally {
      setValidating(false)
    }
  }

  function handleModeChange(v) {
    onParamsChange({ ...params, mode: v })
  }

  function handleLanguageChange(v) {
    let nextCode = localCode
    const prevLang = language
    const prevDefault = DEFAULT_CODE[prevLang]
    const nextDefault = DEFAULT_CODE[v]
    if (nextDefault && (!localCode.trim() || localCode.trim() === prevDefault?.trim())) {
      nextCode = nextDefault
      setLocalCode(nextCode)
    }
    setValidation(null)
    onParamsChange({ ...params, language: v, code: nextCode })
  }

  function handleEditorMount(editor, monaco) {
    editorRef.current = editor
    // Configure autocomplete for $input
    const jsProvider = monaco.languages.registerCompletionItemProvider('javascript', {
      triggerCharacters: ['$', '.'],
      provideCompletionItems: (model, position) => {
        const word = model.getWordUntilPosition(position)
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        }
        // Only suggest if typing $input
        const lineContent = model.getLineContent(position.lineNumber)
        const before = lineContent.substring(0, position.column - 1)
        if (before.endsWith('$input') || before.endsWith('$input.')) {
          const suggestions = [
            {
              label: '$input.all()',
              kind: monaco.languages.CompletionItemKind.Function,
              insertText: '$input.all()',
              detail: 'Returns all input items',
              range,
            },
            {
              label: '$input.item',
              kind: monaco.languages.CompletionItemKind.Variable,
              insertText: '$input.item',
              detail: 'Current item (for Run Once for Each Item)',
              range,
            },
            {
              label: '$input.item.json',
              kind: monaco.languages.CompletionItemKind.Variable,
              insertText: '$input.item.json',
              detail: 'Current item JSON',
              range,
            },
          ]
          return { suggestions }
        }
        if (before.includes('$input')) {
          return {
            suggestions: [
              {
                label: '$input',
                kind: monaco.languages.CompletionItemKind.Variable,
                insertText: '$input',
                detail: '$input API',
                range,
              },
            ],
          }
        }
        return { suggestions: [] }
      },
    })
    // Also for python (simple)
    const pyProvider = monaco.languages.registerCompletionItemProvider('python', {
      triggerCharacters: ['$', '.'],
      provideCompletionItems: (model, position) => {
        const word = model.getWordUntilPosition(position)
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        }
        return {
          suggestions: [
            {
              label: '$input.all()',
              kind: monaco.languages.CompletionItemKind.Function,
              insertText: '$input.all()',
              range,
            },
          ],
        }
      },
    })
    providerDisposablesRef.current.push(jsProvider, pyProvider)
  }

  return (
    <div className="code-editor" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Mode */}
      <label>
        <span>Mode <span className="required-badge">*</span></span>
        <select value={mode} onChange={(e) => handleModeChange(e.target.value)}>
          {MODE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className="hint">
          {mode === 'runOnceForAllItems' ? 'Process all items in one execution (e.g., loop over $input.all()).' : 'Process each item individually (e.g., modify $input.item).'}
        </span>
      </label>

      {/* Language */}
      <label>
        <span>Language</span>
        <select value={language} onChange={(e) => handleLanguageChange(e.target.value)}>
          {LANGUAGE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>
              {o.label}{o.value === 'python' ? ' — Fast for large datasets' : ''}
            </option>
          ))}
        </select>
        {language === 'python' && (
          <span className="hint" style={{ color: 'var(--amber)' }}>
            Python runs via secure sandbox. Fast and memory-efficient — recommended for large datasets (10,000+ records).
          </span>
        )}
      </label>

      {/* Editor */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', background: '#1e1e1e' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', background: '#252526', borderBottom: '1px solid var(--border)' }}>
          <span style={{ color: '#cccccc', fontSize: 11, fontWeight: 600, textTransform: 'uppercase' }}>Code</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <select
              className="small"
              value=""
              onChange={(e) => {
                const s = (SNIPPETS[language] || []).find((item) => item.label === e.target.value)
                if (s) {
                  setLocalCode(s.code)
                  onParamsChange({ ...params, code: s.code })
                }
              }}
              style={{ fontSize: 11, padding: '2px 6px', background: '#18181b', color: '#a5b4fc', border: '1px solid rgba(139, 92, 246, 0.3)', borderRadius: 4 }}
              title="Insert pre-built battle-tested code snippets"
            >
              <option value="" disabled>Snippet Templates…</option>
              {(SNIPPETS[language] || []).map((s) => (
                <option key={s.label} value={s.label}>{s.label}</option>
              ))}
            </select>
            <button type="button" className="ghost small" onClick={handleCheckCode} disabled={validating} style={{ fontSize: 11, padding: '3px 8px' }}>
              {validating ? 'Checking…' : 'Check Code'}
            </button>
          </div>
        </div>
        <Editor
          height="320px"
          language={language === 'python' ? 'python' : 'javascript'}
          value={localCode}
          onChange={(v) => setLocalCode(v || '')}
          onMount={handleEditorMount}
          theme="vs-dark"
          options={{
            minimap: { enabled: false },
            lineNumbers: 'on',
            folding: true,
            bracketPairColorization: { enabled: true },
            autoIndent: 'full',
            formatOnType: true,
            formatOnPaste: true,
            tabSize: 2,
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            automaticLayout: true,
            fontSize: 13,
            fontFamily: 'ui-monospace, "Cascadia Code", Consolas, monospace',
            quickSuggestions: { other: true, comments: false, strings: false },
            suggestOnTriggerCharacters: true,
          }}
        />
      </div>

      {/* Validation */}
      {validation && validation.valid && (
        <div className="banner-inline ok" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>VALID</span>
          <span style={{ fontSize: 11 }}>{validation.message}</span>
        </div>
      )}
      {validation && !validation.valid && (
        <ErrorState
          icon="alert"
          title="Code validation failed"
          description={validation.message}
          details={validation.line ? `Line ${validation.line}${validation.column ? `, Column ${validation.column}` : ''}` : undefined}
        />
      )}

      <span className="hint">
        Use <code>$input.all()</code> for All Items, <code>$input.item</code> for Each Item. Example: <code>for (const item of $input.all()) item.json.x=1; return $input.all();</code>
      </span>

      {/* Autocomplete hint */}
      <div style={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 10px' }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase' }}>Autocomplete</span>
        <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {['$input', '$input.all()', '$input.item', '$input.item.json'].map(s => (
            <code key={s} style={{ background: 'var(--bg)', padding: '2px 6px', borderRadius: 4, fontSize: 10, border: '1px solid var(--border)' }}>{s}</code>
          ))}
        </div>
      </div>
    </div>
  )
}
