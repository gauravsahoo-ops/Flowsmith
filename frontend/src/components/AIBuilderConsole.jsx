import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const BUILDER_MODES = [
  { id: 'build', label: 'Build', desc: 'Create a new workflow from requirements' },
  { id: 'modify', label: 'Modify', desc: 'Surgically add or update an existing workflow' },
  { id: 'repair', label: 'Repair', desc: 'Diagnose and fix an execution error with diff' },
]

const STARTER_PROMPTS = [
  {
    mode: 'build',
    label: 'Salesforce Lead Enrichment',
    prompt: 'When a new Salesforce lead arrives, enrich with company data, score with AI, update Salesforce, and notify Teams.',
  },
  {
    mode: 'build',
    label: 'Stripe Payment Alert',
    prompt: 'When a stripe webhook arrives, check if event type is payment_intent.succeeded, then send slack notification.',
  },
  {
    mode: 'modify',
    label: 'Add Exponential Retries',
    prompt: 'Retry transient failures on remote API operations 3 times with exponential backoff.',
  },
  {
    mode: 'repair',
    label: 'Rate Limit Auto-Recovery',
    prompt: 'This workflow failed because Salesforce returned a 429 rate-limit error. Fix it with safe backoff.',
  },
]

export default function AIBuilderConsole({ statusInfo, selectedCredentialId, onSelectCredential }) {
  const navigate = useNavigate()

  // Console State
  const [mode, setMode] = useState('build')
  const [prompt, setPrompt] = useState('')
  const [modelMode, setModelMode] = useState('auto') // 'auto' | specific
  const [selectedProvider, setSelectedProvider] = useState('auto')
  const [selectedModel, setSelectedModel] = useState('auto')
  const [modelSearch, setModelSearch] = useState('')
  const [availableProviders, setAvailableProviders] = useState([])
  const [loadingProviders, setLoadingProviders] = useState(false)

  // Execution & Pipeline State
  const [processing, setProcessing] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [error, setError] = useState(null)
  const [intent, setIntent] = useState(null)
  const [clarifications, setClarifications] = useState([])
  const [clarificationAnswers, setClarificationAnswers] = useState({})
  const [capabilities, setCapabilities] = useState(null)

  // Generated Artifacts
  const [blueprint, setBlueprint] = useState(null)
  const [validationReport, setValidationReport] = useState(null)
  const [simulationResult, setSimulationResult] = useState(null)
  const [repairProposal, setRepairProposal] = useState(null)
  const [modificationDiff, setModificationDiff] = useState(null)
  const [activeCenterTab, setActiveCenterTab] = useState('plan') // 'plan' | 'blueprint' | 'diff' | 'json'

  const [importing, setImporting] = useState(false)
  const [simulating, setSimulating] = useState(false)
  const [showSimTrace, setShowSimTrace] = useState(false)
  const [expandedSimNode, setExpandedSimNode] = useState(null)

  // Load providers for model selection
  useEffect(() => {
    setLoadingProviders(true)
    api.aiStatus()
      .then((res) => {
        if (res?.credentials) {
          setAvailableProviders(res.credentials)
        }
      })
      .catch(() => {})
      .finally(() => setLoadingProviders(false))
  }, [])

  // Auto-search capabilities as user types prompt
  useEffect(() => {
    const trimmed = prompt.trim()
    if (trimmed.length > 5) {
      const timer = setTimeout(() => {
        api.getAiCapabilities(trimmed, 6)
          .then((res) => setCapabilities(res))
          .catch(() => {})
      }, 400)
      return () => clearTimeout(timer)
    }
  }, [prompt])

  // Primary Action: Understand & Synthesize
  const handleSynthesize = async (customPrompt) => {
    const textToRun = (customPrompt || prompt).trim()
    if (!textToRun || processing) return

    setProcessing(true)
    setError(null)
    setCurrentStep(1) // Intent Extraction

    try {
      // 1. Extract Structured Intent & Missing Clarifications
      const intentRes = await api.extractIntent({
        prompt: textToRun,
        mode: mode,
        credential_id: selectedCredentialId,
        answers: clarificationAnswers,
      })
      setIntent(intentRes)
      if (intentRes?.missing_info && intentRes.missing_info.length > 0) {
        setClarifications(intentRes.missing_info)
      }

      setCurrentStep(2) // Capability Discovery & IR Compilation

      if (mode === 'repair') {
        // Repair Pipeline
        const repRes = await api.repairWorkflow({
          workflow: blueprint?.workflow || {},
          error_message: textToRun,
          credential_id: selectedCredentialId,
        })
        setRepairProposal(repRes)
        setBlueprint({ workflow: repRes.repaired_workflow })
        setSimulationResult(repRes.simulation_result)
        setActiveCenterTab('diff')
      } else if (mode === 'modify' && blueprint?.workflow) {
        // Modify Pipeline
        const modRes = await api.modifyWorkflow({
          workflow: blueprint.workflow,
          instruction: textToRun,
          credential_id: selectedCredentialId,
        })
        setModificationDiff(modRes)
        setBlueprint({ workflow: modRes.modified_workflow })
        setActiveCenterTab('diff')
      } else {
        // Build Pipeline: Generate Full Verified Workflow
        setCurrentStep(3) // Code Synthesis
        const genRes = await api.generateWorkflow(textToRun, {
          credentialId: selectedCredentialId,
        })

        if (!genRes?.workflow) {
          throw new Error('Model did not return a valid workflow structure.')
        }

        setBlueprint(genRes)
        setCurrentStep(4) // 6-Stage Validation Pipeline

        const valRes = await api.validatePipeline(genRes.workflow, selectedCredentialId)
        setValidationReport(valRes)

        // Run non-destructive simulation preview
        const simRes = await api.simulateWorkflow(genRes.workflow, null, selectedCredentialId)
        setSimulationResult(simRes)
        setActiveCenterTab('plan')
      }

      setCurrentStep(5) // Complete
    } catch (err) {
      setError(err?.message || 'Failed to complete workflow synthesis pipeline.')
    } finally {
      setProcessing(false)
    }
  }

  // Trigger safe mock simulation
  const handleRunSimulation = async () => {
    if (!blueprint?.workflow || simulating) return
    setSimulating(true)
    setError(null)
    try {
      const res = await api.simulateWorkflow(blueprint.workflow, null, selectedCredentialId)
      setSimulationResult(res)
      setShowSimTrace(true)
    } catch (err) {
      setError(`Simulation error: ${err.message}`)
    } finally {
      setSimulating(false)
    }
  }

  // Open in Canvas
  const handleOpenInCanvas = async () => {
    if (!blueprint?.workflow || importing) return
    setImporting(true)
    setError(null)
    try {
      const imported = await api.importWorkflow(blueprint.workflow)
      navigate(`/workflows/${imported.id}`)
    } catch (err) {
      setError(`Failed to import to canvas: ${err.message}`)
      setImporting(false)
    }
  }

  return (
    <div className="ai-builder-console" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', width: '100%' }}>
      {/* Top Controls Bar: Modes & Model Router */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
          padding: '0.85rem 1.25rem',
          background: 'var(--card-bg, #18181b)',
          border: '1px solid var(--border-color, #27272a)',
          borderRadius: '12px',
        }}
      >
        {/* Mode Selector */}
        <div style={{ display: 'flex', gap: '0.4rem', background: '#09090b', padding: '3px', borderRadius: '8px', border: '1px solid #27272a' }}>
          {BUILDER_MODES.map((m) => (
            <button
              key={m.id}
              className={mode === m.id ? 'primary' : 'ghost'}
              onClick={() => { setMode(m.id); setError(null); }}
              style={{
                fontSize: '12.5px',
                padding: '5px 12px',
                borderRadius: '6px',
                fontWeight: mode === m.id ? 600 : 400,
              }}
              title={m.desc}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* Model Router */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <span style={{ fontSize: '12px', color: 'var(--text-muted, #94a3b8)' }}>Model Router:</span>
          <select
            value={modelMode}
            onChange={(e) => setModelMode(e.target.value)}
            style={{
              padding: '5px 10px',
              borderRadius: '6px',
              background: '#09090b',
              border: '1px solid #3f3f46',
              color: '#f8fafc',
              fontSize: '12px',
            }}
          >
            <option value="auto">Auto (Task-Based Optimal Routing)</option>
            {availableProviders.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || c.id} ({c.provider || 'llm'})
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="banner-inline err" style={{ padding: '0.75rem 1rem', borderRadius: '8px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <span>{error}</span>
        </div>
      )}

      {/* 3-COLUMN PRODUCTION WORKFLOW ENGINE LAYOUT */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(320px, 1fr) minmax(360px, 1.4fr) minmax(280px, 0.95fr)',
          gap: '1.25rem',
          alignItems: 'stretch',
        }}
      >
        {/* LEFT COLUMN: Conversation / Requirements / Intent */}
        <div
          style={{
            padding: '1.25rem',
            background: 'var(--card-bg, #18181b)',
            border: '1px solid var(--border-color, #27272a)',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
          }}
        >
          <div>
            <h4 style={{ margin: '0 0 0.25rem', fontSize: '14px', fontWeight: 600 }}>
              {mode === 'build' ? 'Natural Language Requirements' : (mode === 'modify' ? 'Modification Request' : 'Execution Failure Diagnosis')}
            </h4>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted, #94a3b8)', lineHeight: 1.4 }}>
              {mode === 'build'
                ? 'Describe your business automation outcome. Flowsmith will extract intent, resolve schemas, and compile a verified DAG.'
                : (mode === 'modify' ? 'Specify the exact nodes or routing rules you want to add, update, or replace.' : 'Paste the error message or describe what failed. AI will propose a surgical diff repair.')}
            </p>
          </div>

          <div style={{ position: 'relative' }}>
            <textarea
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                mode === 'build'
                  ? 'e.g. Every morning check Salesforce for new leads, enrich with company data, score with AI, update Salesforce, and notify Teams channel...'
                  : (mode === 'modify' ? 'e.g. Add a Slack notification when lead score is over 80, with 3 exponential retries...' : 'e.g. Salesforce returned 429 Too Many Requests. Add retry policy and rate limit handling...')
              }
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '0.75rem',
                borderRadius: '8px',
                background: '#09090b',
                border: '1px solid #3f3f46',
                color: '#f8fafc',
                fontSize: '13px',
                lineHeight: 1.5,
                resize: 'vertical',
                outline: 'none',
              }}
            />
          </div>

          {/* Action Button */}
          <button
            className="primary"
            onClick={() => handleSynthesize()}
            disabled={processing || !prompt.trim()}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '0.5rem',
              padding: '0.65rem 1rem',
              fontWeight: 600,
              fontSize: '13.5px',
            }}
          >
            {processing ? (
              <>
                <span
                  style={{
                    width: 14,
                    height: 14,
                    border: '2px solid rgba(255,255,255,0.3)',
                    borderTopColor: '#fff',
                    borderRadius: '50%',
                    display: 'inline-block',
                    animation: 'spin 0.8s linear infinite',
                  }}
                />
                Synthesizing Pipeline...
              </>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="16 18 22 12 16 6" />
                  <polyline points="8 6 2 12 8 18" />
                </svg>
                {mode === 'build' ? 'Synthesize & Validate Workflow' : (mode === 'modify' ? 'Apply Modification Diff' : 'Generate Repair Proposal')}
              </>
            )}
          </button>

          {/* Clarification Questions Card */}
          {clarifications.length > 0 && (
            <div
              style={{
                padding: '0.85rem',
                background: 'rgba(99, 102, 241, 0.08)',
                border: '1px solid rgba(99, 102, 241, 0.3)',
                borderRadius: '8px',
              }}
            >
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#818cf8', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="16" x2="12" y2="12" />
                  <line x1="12" y1="8" x2="12.01" y2="8" />
                </svg>
                <span>Clarification Required</span>
              </div>
              {clarifications.map((q) => (
                <div key={q.id} style={{ marginBottom: '0.6rem' }}>
                  <div style={{ fontSize: '12px', marginBottom: '0.3rem' }}>{q.question}</div>
                  {q.options && q.options.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                      {q.options.map((opt) => (
                        <button
                          key={opt}
                          className="ghost small"
                          onClick={() => {
                            setClarificationAnswers({ ...clarificationAnswers, [q.parameter_key]: opt })
                            setPrompt(`${prompt} (${q.parameter_key}: ${opt})`)
                          }}
                          style={{ fontSize: '11px', padding: '2px 8px' }}
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Quick Starter Templates */}
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted, #94a3b8)', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Example Templates
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {STARTER_PROMPTS.filter((s) => s.mode === mode).map((s, idx) => (
                <button
                  key={idx}
                  className="ghost small"
                  onClick={() => {
                    setPrompt(s.prompt)
                    handleSynthesize(s.prompt)
                  }}
                  style={{
                    textAlign: 'left',
                    padding: '6px 10px',
                    fontSize: '12px',
                    borderRadius: '6px',
                    background: 'rgba(255,255,255,0.03)',
                  }}
                >
                  <div style={{ fontWeight: 500, color: '#f8fafc' }}>{s.label}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted, #94a3b8)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {s.prompt}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* CENTER COLUMN: Workflow Plan & Generated Graph Structure */}
        <div
          style={{
            padding: '1.25rem',
            background: 'var(--card-bg, #18181b)',
            border: '1px solid var(--border-color, #27272a)',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
          }}
        >
          {/* Header Tabs */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #27272a', paddingBottom: '0.6rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                className={activeCenterTab === 'plan' ? 'primary small' : 'ghost small'}
                onClick={() => setActiveCenterTab('plan')}
                style={{ fontSize: '12px', padding: '4px 10px' }}
              >
                Plan & Sequence
              </button>
              <button
                className={activeCenterTab === 'blueprint' ? 'primary small' : 'ghost small'}
                onClick={() => setActiveCenterTab('blueprint')}
                style={{ fontSize: '12px', padding: '4px 10px' }}
              >
                Blueprint Nodes ({blueprint?.workflow?.nodes?.length || 0})
              </button>
              {(repairProposal || modificationDiff) && (
                <button
                  className={activeCenterTab === 'diff' ? 'primary small' : 'ghost small'}
                  onClick={() => setActiveCenterTab('diff')}
                  style={{ fontSize: '12px', padding: '4px 10px' }}
                >
                  Diff Changes
                </button>
              )}
            </div>

            {blueprint?.workflow && (
              <button
                className="primary small"
                onClick={handleOpenInCanvas}
                disabled={importing}
                style={{ fontSize: '12px', padding: '4px 12px' }}
              >
                {importing ? 'Importing...' : 'Open in Canvas ↗'}
              </button>
            )}
          </div>

          {/* Tab Content */}
          {activeCenterTab === 'plan' && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
              {intent?.summary && (
                <div style={{ padding: '0.75rem', background: '#09090b', borderRadius: '8px', border: '1px solid #27272a', fontSize: '12.5px', color: '#cbd5e1' }}>
                  <strong>Synthesis Plan:</strong> {intent.summary}
                </div>
              )}

              {/* Node Sequence Pipeline */}
              {blueprint?.workflow?.nodes ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted, #94a3b8)', textTransform: 'uppercase' }}>
                    Compiled Execution Pipeline
                  </div>
                  {blueprint.workflow.nodes.map((n, idx) => (
                    <div
                      key={n.id || idx}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        padding: '0.75rem',
                        background: '#09090b',
                        border: '1px solid #27272a',
                        borderRadius: '8px',
                      }}
                    >
                      <div
                        style={{
                          width: '26px',
                          height: '26px',
                          borderRadius: '50%',
                          background: 'rgba(99, 102, 241, 0.15)',
                          color: '#818cf8',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '11px',
                          fontWeight: 700,
                          flexShrink: 0,
                        }}
                      >
                        {idx + 1}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{ fontWeight: 600, fontSize: '13px', color: '#f8fafc' }}>
                            {n.name || n.type}
                          </span>
                          <span style={{ fontSize: '10.5px', padding: '1px 6px', background: '#1e293b', borderRadius: '4px', color: '#94a3b8' }}>
                            {n.type}
                          </span>
                        </div>
                        {n.parameters?.operation && (
                          <div style={{ fontSize: '11.5px', color: '#38bdf8', marginTop: '2px' }}>
                            Operation: {n.parameters.operation}
                          </div>
                        )}
                      </div>
                      {n.settings?.retry && (
                        <span style={{ fontSize: '10.5px', color: '#f59e0b', background: 'rgba(245, 158, 11, 0.1)', padding: '2px 6px', borderRadius: '4px' }}>
                          Retry: {n.settings.retry.max_attempts || n.settings.retry}x
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 220, color: 'var(--text-muted, #94a3b8)', fontSize: '13px' }}>
                  Describe requirements and click "Synthesize" to generate the workflow plan.
                </div>
              )}
            </div>
          )}

          {activeCenterTab === 'blueprint' && (
            <div style={{ flex: 1, overflowY: 'auto', maxHeight: 420 }}>
              <pre style={{ margin: 0, padding: '0.75rem', background: '#09090b', borderRadius: '8px', fontSize: '11.5px', color: '#a5f3fc', lineHeight: 1.4, fontFamily: 'monospace' }}>
                {JSON.stringify(blueprint?.workflow, null, 2)}
              </pre>
            </div>
          )}

          {activeCenterTab === 'diff' && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
              {repairProposal && (
                <div style={{ padding: '0.75rem', background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '8px' }}>
                  <div style={{ fontSize: '12.5px', fontWeight: 600, color: '#34d399', marginBottom: '4px' }}>
                    ✓ Root Cause: {repairProposal.root_cause}
                  </div>
                  <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                    {repairProposal.rationale}
                  </div>
                </div>
              )}
              {modificationDiff && (
                <div style={{ padding: '0.75rem', background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.3)', borderRadius: '8px', fontSize: '12.5px', color: '#cbd5e1' }}>
                  {modificationDiff.summary}
                </div>
              )}
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Context / Capabilities / Credentials / Validation */}
        <div
          style={{
            padding: '1.25rem',
            background: 'var(--card-bg, #18181b)',
            border: '1px solid var(--border-color, #27272a)',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            gap: '1.2rem',
          }}
        >
          {/* 1. Grounded Connectors */}
          <div>
            <div style={{ fontSize: '12px', fontWeight: 600, color: '#f8fafc', marginBottom: '0.4rem', display: 'flex', justifyContent: 'space-between' }}>
              <span>Grounded Connectors</span>
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>Live Catalog</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
              {capabilities?.connectors && capabilities.connectors.length > 0 ? (
                capabilities.connectors.map((c) => (
                  <span
                    key={c.connector_id}
                    style={{
                      fontSize: '11px',
                      padding: '3px 8px',
                      background: '#09090b',
                      border: '1px solid #3f3f46',
                      borderRadius: '6px',
                      color: '#e2e8f0',
                    }}
                  >
                    {c.display_name} ✓
                  </span>
                ))
              ) : (
                <span style={{ fontSize: '12px', color: 'var(--text-muted, #94a3b8)' }}>
                  Grounded across 65+ connectors
                </span>
              )}
            </div>
          </div>

          {/* 2. 6-Stage Validation Status */}
          <div style={{ borderTop: '1px solid #27272a', paddingTop: '0.8rem' }}>
            <div style={{ fontSize: '12px', fontWeight: 600, color: '#f8fafc', marginBottom: '0.5rem' }}>
              6-Stage Validation Pipeline
            </div>
            {validationReport ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11.5px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>1. Structural DAG</span>
                  <span style={{ color: validationReport.structural_ok ? '#10b981' : '#ef4444' }}>{validationReport.structural_ok ? '✓ Pass' : '✗ Issue'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>2. Connector Schema</span>
                  <span style={{ color: validationReport.connector_ok ? '#10b981' : '#ef4444' }}>{validationReport.connector_ok ? '✓ Pass' : '✗ Issue'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>3. Expression & Data</span>
                  <span style={{ color: validationReport.data_ok ? '#10b981' : '#ef4444' }}>{validationReport.data_ok ? '✓ Pass' : '✗ Issue'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>4. Credential Availability</span>
                  <span style={{ color: validationReport.credential_ok ? '#10b981' : '#f59e0b' }}>{validationReport.credential_ok ? '✓ Ready' : '⚠ Action'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>5. Runtime Policies</span>
                  <span style={{ color: validationReport.runtime_ok ? '#10b981' : '#ef4444' }}>{validationReport.runtime_ok ? '✓ Pass' : '✗ Issue'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>6. Security & Secret Guard</span>
                  <span style={{ color: validationReport.security_ok ? '#10b981' : '#ef4444' }}>{validationReport.security_ok ? '✓ Secure' : '✗ Unsafe'}</span>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted, #94a3b8)' }}>
                Validation will run automatically when workflow is generated.
              </div>
            )}
          </div>

          {/* 3. Non-Destructive Simulation Runner */}
          <div style={{ borderTop: '1px solid #27272a', paddingTop: '0.8rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#f8fafc' }}>Simulation Runner</span>
              {blueprint?.workflow && (
                <button
                  className="ghost small"
                  onClick={handleRunSimulation}
                  disabled={simulating}
                  style={{
                    fontSize: '11px',
                    padding: '3px 9px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    opacity: simulating ? 0.7 : 1,
                    cursor: simulating ? 'wait' : 'pointer',
                  }}
                >
                  {simulating ? '⏳ Simulating...' : '▶ Run Mock'}
                </button>
              )}
            </div>

            {simulating ? (
              <div
                style={{
                  padding: '0.65rem',
                  background: '#09090b',
                  borderRadius: '8px',
                  border: '1px solid #3b82f6',
                  fontSize: '11.5px',
                  color: '#60a5fa',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <span className="smith-send-spinner" style={{ width: 12, height: 12, borderWidth: 2, borderTopColor: '#60a5fa' }} />
                <span>Simulating topological execution across DAG...</span>
              </div>
            ) : simulationResult ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <div
                  style={{
                    padding: '0.65rem',
                    background: '#09090b',
                    borderRadius: '8px',
                    border: `1px solid ${simulationResult.success ? '#059669' : (simulationResult.total_steps > 0 ? '#d97706' : '#dc2626')}`,
                    fontSize: '11.5px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span
                      style={{
                        color: simulationResult.success ? '#10b981' : (simulationResult.total_steps > 0 ? '#f59e0b' : '#ef4444'),
                        fontWeight: 600,
                      }}
                    >
                      {simulationResult.success
                        ? '✓ Simulation Passed'
                        : (simulationResult.total_steps > 0 ? '⚠ Dry-Run Completed (Notices)' : '✗ Simulation Failed')}
                    </span>
                    <span style={{ color: '#94a3b8', fontSize: '10.5px' }}>
                      {simulationResult.estimated_latency_ms}ms estimated
                    </span>
                  </div>

                  <div style={{ color: '#cbd5e1', fontSize: '11px', marginBottom: '6px' }}>
                    {simulationResult.summary || `${simulationResult.total_steps} steps simulated.`}
                  </div>

                  {simulationResult.trace && simulationResult.trace.length > 0 && (
                    <button
                      className="ghost small"
                      onClick={() => setShowSimTrace((prev) => !prev)}
                      style={{ fontSize: '10.5px', padding: '2px 6px', color: '#60a5fa', border: 'none', background: 'none' }}
                    >
                      {showSimTrace ? '▲ Hide Step Trace' : `▼ View Step Trace (${simulationResult.trace.length})`}
                    </button>
                  )}
                </div>

                {/* Step-by-Step Simulation Trace Drawer */}
                {showSimTrace && simulationResult.trace && simulationResult.trace.length > 0 && (
                  <div
                    style={{
                      maxHeight: '260px',
                      overflowY: 'auto',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.4rem',
                      background: '#09090b',
                      padding: '0.5rem',
                      borderRadius: '8px',
                      border: '1px solid #27272a',
                    }}
                  >
                    {simulationResult.trace.map((step, idx) => {
                      const isExpanded = expandedSimNode === step.node_id
                      return (
                        <div
                          key={step.node_id || idx}
                          style={{
                            background: '#18181b',
                            border: '1px solid #27272a',
                            borderRadius: '6px',
                            padding: '0.4rem 0.6rem',
                            fontSize: '11px',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span style={{ color: '#60a5fa', fontWeight: 700 }}>#{idx + 1}</span>
                              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{step.node_name}</span>
                              <span
                                style={{
                                  fontSize: '9.5px',
                                  padding: '1px 4px',
                                  borderRadius: '4px',
                                  background: '#27272a',
                                  color: '#94a3b8',
                                }}
                              >
                                {step.node_type}
                              </span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span style={{ color: '#94a3b8', fontSize: '10px' }}>{step.latency_ms}ms</span>
                              <span
                                style={{
                                  color: step.status === 'success' ? '#10b981' : '#f59e0b',
                                  fontWeight: 600,
                                  fontSize: '10px',
                                }}
                              >
                                {step.status === 'success' ? '✓' : '⚠'}
                              </span>
                            </div>
                          </div>

                          {step.notes && step.notes.length > 0 && (
                            <div style={{ marginTop: '3px', color: '#94a3b8', fontSize: '10px' }}>
                              {step.notes.map((n, i) => (
                                <div key={i}>• {n}</div>
                              ))}
                            </div>
                          )}

                          <button
                            onClick={() => setExpandedSimNode(isExpanded ? null : step.node_id)}
                            style={{
                              marginTop: '4px',
                              background: 'none',
                              border: 'none',
                              color: '#60a5fa',
                              fontSize: '10px',
                              cursor: 'pointer',
                              padding: 0,
                            }}
                          >
                            {isExpanded ? '▴ Hide Sample Data' : '▾ View Sample Output'}
                          </button>

                          {isExpanded && step.output_sample && (
                            <pre
                              style={{
                                marginTop: '4px',
                                padding: '4px 6px',
                                background: '#09090b',
                                borderRadius: '4px',
                                fontSize: '9.5px',
                                color: '#e2e8f0',
                                overflowX: 'auto',
                                maxHeight: '120px',
                              }}
                            >
                              {JSON.stringify(step.output_sample, null, 2)}
                            </pre>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted, #94a3b8)' }}>
                Simulates execution with synthetic items without making external mutations.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
