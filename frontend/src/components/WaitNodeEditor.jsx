import { useState, useRef, useEffect } from 'react'
import MappingField from './MappingField'
import './WaitNodeEditor.css'

const RESUME_MODES = [
  {
    id: 'timeInterval',
    title: 'After Time Interval',
    desc: 'Waits for a certain amount of time',
  },
  {
    id: 'specificTime',
    title: 'At Specified Time',
    desc: 'Waits until a specific date and time to continue',
  },
  {
    id: 'webhook',
    title: 'On Webhook Call',
    desc: 'Waits for a webhook call before continuing',
  },
  {
    id: 'form',
    title: 'On Form Submitted',
    desc: 'Waits for a form submission before continuing',
  },
]

const WAIT_UNITS = [
  { id: 'seconds', label: 'Seconds' },
  { id: 'minutes', label: 'Minutes' },
  { id: 'hours', label: 'Hours' },
  { id: 'days', label: 'Days' },
]

export default function WaitNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const rawResume = params.resume || (params.mode === 'until' ? 'specificTime' : 'timeInterval')
  const resume = RESUME_MODES.some((m) => m.id === rawResume) ? rawResume : 'timeInterval'

  const amount = params.amount ?? params.seconds ?? '5.00'
  const unit = params.unit || 'seconds'
  const dateTime = params.date_time ?? params.dateTime ?? params.until ?? ''
  const webhookSuffix = params.webhook_suffix ?? params.webhookSuffix ?? ''

  // UI Dropdown states
  const [resumeMenuOpen, setResumeMenuOpen] = useState(false)
  const [unitMenuOpen, setUnitMenuOpen] = useState(false)
  const [copiedUrl, setCopiedUrl] = useState(false)

  const resumeRef = useRef(null)
  const unitRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(e) {
      if (resumeRef.current && !resumeRef.current.contains(e.target)) {
        setResumeMenuOpen(false)
      }
      if (unitRef.current && !unitRef.current.contains(e.target)) {
        setUnitMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function updateField(key, val) {
    onParamsChange({
      ...params,
      [key]: val,
      ...(key === 'amount' ? { seconds: Number(val) || 0 } : {}),
      ...(key === 'date_time' ? { until: val, dateTime: val } : {}),
      ...(key === 'resume' ? { mode: val === 'specificTime' ? 'until' : 'delay' } : {}),
    })
  }

  const selectedResume = RESUME_MODES.find((m) => m.id === resume) || RESUME_MODES[0]
  const selectedUnit = WAIT_UNITS.find((u) => u.id === unit) || WAIT_UNITS[0]

  const webhookUrl = `${window.location.origin}/api/webhooks/wait/${node.id}${webhookSuffix ? `/${webhookSuffix}` : ''}`
  const formUrl = `${window.location.origin}/form/${node.id}`

  function copyToClipboard(text) {
    navigator.clipboard?.writeText(text)
    setCopiedUrl(true)
    setTimeout(() => setCopiedUrl(false), 2000)
  }

  return (
    <div className="wait-editor">
      {/* 1. Resume Select Card */}
      <div className="wait-field-group" ref={resumeRef}>
        <div className="wait-field-header">
          <label className="wait-field-label">Resume</label>
          <span
            className="wait-help-icon"
            title="Select the condition upon which execution should resume."
          >
            ?
          </span>
        </div>

        <div className="wait-select-wrap">
          <button
            type="button"
            className={`wait-select-btn ${resumeMenuOpen ? 'open' : ''}`}
            onClick={() => setResumeMenuOpen(!resumeMenuOpen)}
          >
            <div className="wait-select-value">
              <span className="wait-select-title">{selectedResume.title}</span>
              <span className="wait-select-desc">{selectedResume.desc}</span>
            </div>
            <span className="wait-select-arrow">{resumeMenuOpen ? '▴' : '▾'}</span>
          </button>

          {resumeMenuOpen && (
            <div className="wait-select-dropdown">
              {RESUME_MODES.map((m) => {
                const isSelected = m.id === resume
                return (
                  <button
                    key={m.id}
                    type="button"
                    className={`wait-select-item ${isSelected ? 'active' : ''}`}
                    onClick={() => {
                      updateField('resume', m.id)
                      setResumeMenuOpen(false)
                    }}
                  >
                    <div className="wait-select-item-content">
                      <span className="wait-select-item-title">{m.title}</span>
                      <span className="wait-select-item-desc">{m.desc}</span>
                    </div>
                    {isSelected && <span className="wait-select-check">✓</span>}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 2. After Time Interval Controls */}
      {resume === 'timeInterval' && (
        <>
          {/* Wait Amount */}
          <div className="wait-field-group">
            <MappingField
              schema={{
                title: 'Wait Amount',
                description: 'The number of time units to wait before resuming execution',
              }}
              value={String(amount)}
              onChange={(v) => updateField('amount', v)}
              placeholder="5.00"
              path="amount"
              mapping={mapping}
              onPreview={onPreview}
            />
          </div>

          {/* Wait Unit */}
          <div className="wait-field-group" ref={unitRef}>
            <div className="wait-field-header">
              <label className="wait-field-label">Wait Unit</label>
              <span
                className="wait-help-icon"
                title="Unit of time for the wait duration."
              >
                ?
              </span>
            </div>

            <div className="wait-select-wrap">
              <button
                type="button"
                className={`wait-select-btn ${unitMenuOpen ? 'open' : ''}`}
                onClick={() => setUnitMenuOpen(!unitMenuOpen)}
              >
                <span className="wait-select-title">{selectedUnit.label}</span>
                <span className="wait-select-arrow">{unitMenuOpen ? '▴' : '▾'}</span>
              </button>

              {unitMenuOpen && (
                <div className="wait-select-dropdown">
                  {WAIT_UNITS.map((u) => {
                    const isSelected = u.id === unit
                    return (
                      <button
                        key={u.id}
                        type="button"
                        className={`wait-select-item ${isSelected ? 'active' : ''}`}
                        onClick={() => {
                          updateField('unit', u.id)
                          setUnitMenuOpen(false)
                        }}
                      >
                        <span className="wait-select-item-title">{u.label}</span>
                        {isSelected && <span className="wait-select-check">✓</span>}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* 3. At Specified Time Controls */}
      {resume === 'specificTime' && (
        <div className="wait-field-group">
          <MappingField
            schema={{
              title: 'Date and Time',
              description: 'Exact ISO-8601 UTC timestamp or expression (e.g. 2026-09-09T14:30:00Z)',
            }}
            value={dateTime}
            onChange={(v) => updateField('date_time', v)}
            placeholder="YYYY-MM-DDTHH:mm:ssZ"
            path="date_time"
            mapping={mapping}
            onPreview={onPreview}
          />
          <span className="wait-field-hint">
            The execution will pause and resume automatically when this date and time arrives.
          </span>
        </div>
      )}

      {/* 4. On Webhook Call Controls */}
      {resume === 'webhook' && (
        <div className="wait-field-group">
          <label className="wait-field-label">Resume Webhook URL</label>
          <div className="wait-copy-input-wrap">
            <input
              type="text"
              readOnly
              className="wait-text-input"
              value={webhookUrl}
              onFocus={(e) => e.target.select()}
            />
            <button
              type="button"
              className="wait-copy-btn"
              onClick={() => copyToClipboard(webhookUrl)}
            >
              {copiedUrl ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <span className="wait-field-hint">
            When this URL receives a POST or GET request, this execution immediately resumes.
          </span>
        </div>
      )}

      {/* 5. On Form Submitted Controls */}
      {resume === 'form' && (
        <div className="wait-field-group">
          <label className="wait-field-label">Form URL</label>
          <div className="wait-copy-input-wrap">
            <input
              type="text"
              readOnly
              className="wait-text-input"
              value={formUrl}
              onFocus={(e) => e.target.select()}
            />
            <button
              type="button"
              className="wait-copy-btn"
              onClick={() => copyToClipboard(formUrl)}
            >
              {copiedUrl ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <span className="wait-field-hint">
            Execution pauses until the user completes and submits the form at this URL.
          </span>
        </div>
      )}

      {/* Tip Banner */}
      <div className="wait-tip-banner">
        <strong>Tip:</strong> Use <code>{'{{$json.field}}'}</code> for expressions. When execution reaches this node, it pauses until the resume condition is satisfied.
      </div>
    </div>
  )
}
