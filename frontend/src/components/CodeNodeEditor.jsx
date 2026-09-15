import { useState, useEffect, useRef } from 'react'
import Editor from '@monaco-editor/react'
import ErrorState from './shared/ErrorState'

const MODE_OPTIONS = [
  { value: 'runOnceForAllItems', label: 'Run Once for All Items' },
  { value: 'runOnceForEachItem', label: 'Run Once for Each Item' },
]

const LANGUAGE_OPTIONS = [
  { value: 'javascript', label: 'JavaScript' },
  { value: 'python', label: 'Python (beta)' },
]

export default function CodeNodeEditor({ node, onParamsChange }) {
  const params = node.parameters || {}
  const mode = params.mode || 'runOnceForAllItems'
  const language = params.language || 'javascript'
  const code = params.code || 'for (const item of $input.all()) {\n  item.json.myNewField = 1;\n}\nreturn $input.all();'

  const [localCode, setLocalCode] = useState(code)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState(null)
  const editorRef = useRef(null)
  const paramsRef = useRef(params)
  paramsRef.current = params
  const onParamsChangeRef = useRef(onParamsChange)
  onParamsChangeRef.current = onParamsChange

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
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('mat_token')}` },
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
    if (v === 'python') {
      // Mark Python as available but with warning
      onParamsChange({ ...params, language: v })
    } else {
      onParamsChange({ ...params, language: v })
    }
  }

  function handleEditorMount(editor, monaco) {
    editorRef.current = editor
    // Configure autocomplete for $input
    monaco.languages.registerCompletionItemProvider('javascript', {
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
    monaco.languages.registerCompletionItemProvider('python', {
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
          {LANGUAGE_OPTIONS.map(o => <option key={o.value} value={o.value} disabled={o.value === 'python' && false}>{o.label}{o.value === 'python' ? ' — Python via sandbox (limited)' : ''}</option>)}
        </select>
        {language === 'python' && <span className="hint" style={{ color: 'var(--amber)' }}>Python runs via secure Python sandbox (limited builtins, no FS/network). Prefer JavaScript for full $input support.</span>}
      </label>

      {/* Editor */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', background: '#1e1e1e' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', background: '#252526', borderBottom: '1px solid var(--border)' }}>
          <span style={{ color: '#cccccc', fontSize: 11, fontWeight: 600, textTransform: 'uppercase' }}>Code</span>
          <button type="button" className="ghost small" onClick={handleCheckCode} disabled={validating} style={{ fontSize: 11, padding: '3px 8px' }}>
            {validating ? 'Checking…' : 'Check Code'}
          </button>
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
          <span style={{ fontWeight: 600 }}>✓ VALID</span>
          <span style={{ fontSize: 11 }}>{validation.message}</span>
        </div>
      )}
      {validation && !validation.valid && (
        <ErrorState
          icon="✗"
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
