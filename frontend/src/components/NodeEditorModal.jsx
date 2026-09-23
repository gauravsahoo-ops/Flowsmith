// NodeEditorModal: centered node editor with three-panel layout.
// Left: INPUT — upstream data (JSON/Table/Schema)
// Center: PARAMETERS — node configuration form (JsonForm)
// Right: OUTPUT — execution results (JSON/Table/Schema)
// Header: node icon + name, connector, operation, Execute/Save/Close buttons.

import React, { useEffect, useMemo, useState, useCallback, useRef, Suspense, lazy, isValidElement } from 'react'
import { createPortal } from 'react-dom'
import { useWorkflowStore } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useUiStore } from '../stores/uiStore'
import { useCredentialStore } from '../stores/credentialStore'
import { api } from '../api'
import JsonForm from './JsonForm'
import OutputPanel from './OutputPanel'
import InputPanel from './InputPanel'
import Button from './shared/Button'
import Tabs from './shared/Tabs'
import Status from './shared/Status'
import ErrorState from './shared/ErrorState'
import { NodeIcon } from './NodeIcons'
import ExpressionHelper from './ExpressionHelper'
import NodeAutoRepair from './NodeAutoRepair'

const SalesforceNodeEditor = lazy(() => import('./SalesforceNodeEditor'))
const ScheduleTriggerEditor = lazy(() => import('./ScheduleTriggerEditor'))
const WebhookNodeEditor = lazy(() => import('./WebhookNodeEditor'))
const HttpRequestNodeEditor = lazy(() => import('./HttpRequestNodeEditor'))
const CodeNodeEditor = lazy(() => import('./CodeNodeEditor'))
const IfConditionEditor = lazy(() => import('./IfConditionEditor'))
const FilterNodeEditor = lazy(() => import('./FilterNodeEditor'))
const SplitNodeEditor = lazy(() => import('./SplitNodeEditor'))
const CompareDatasetsEditor = lazy(() => import('./CompareDatasetsEditor'))
const StopAndErrorNodeEditor = lazy(() => import('./StopAndErrorNodeEditor'))
const SwitchNodeEditor = lazy(() => import('./SwitchNodeEditor'))
const WaitNodeEditor = lazy(() => import('./WaitNodeEditor'))
const ExecuteWorkflowNodeEditor = lazy(() => import('./ExecuteWorkflowNodeEditor'))
const ExecuteWorkflowTriggerEditor = lazy(() => import('./ExecuteWorkflowTriggerEditor'))
const TokenManagerNodeEditor = lazy(() => import('./TokenManagerNodeEditor'))
const TokenFetchNodeEditor = lazy(() => import('./TokenFetchNodeEditor'))
const TokenStoreNodeEditor = lazy(() => import('./TokenStoreNodeEditor'))
const DataTableDiscovery = lazy(() => import('./DataTableDiscovery'))
import {
  IDEMPOTENCY_LABEL,
  IDEMPOTENCY_HINT,
  NODE_COLORS,
} from '../utils/nodeConstants'
import { CollapsibleSection, OpSafetyHint } from './shared/CollapsibleSection'

export default function NodeEditorModal() {
  const nodeEditorOpen = useUiStore((s) => s.nodeEditorOpen)
  const activeTab = useUiStore((s) => s.nodeEditorTab)
  const setNodeEditorTab = useUiStore((s) => s.setNodeEditorTab)
  const close = useUiStore((s) => s.closeNodeEditor)
  const selectedId = useUiStore((s) => s.selectedNodeId)
  const [settingsTab, setSettingsTab] = useState(false)

  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const catalog = useWorkflowStore((s) => s.catalog)
  const workflow = useWorkflowStore((s) => s.workflow)
  const versions = useWorkflowStore((s) => s.versions)
  const updateNode = useWorkflowStore((s) => s.updateNode)
  const deleteNodes = useWorkflowStore((s) => s.deleteNodes)
  const duplicateNodes = useWorkflowStore((s) => s.duplicateNodes)
  const credentials = useCredentialStore((s) => s.credentials)
  const credentialTypes = useCredentialStore((s) => s.types)

  const executionId = useExecutionStore((s) => s.executionId)
  const trace = useExecutionStore((s) => s.trace)
  const results = useExecutionStore((s) => s.results)
  const nodeStatuses = useExecutionStore((s) => s.nodeStatuses)
  const runPreview = useExecutionStore((s) => s.runPreview)

  const [mapping, setMapping] = useState([])
  const [_upstreamData, setUpstreamData] = useState(null)
  const [outputData, setOutputData] = useState(null)
  const [executing, setExecuting] = useState(false)
  const [execError, setExecError] = useState(null)
  const [showAutoRepair, setShowAutoRepair] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [closing, setClosing] = useState(false)
  const [visible, setVisible] = useState(false)
  const modalRef = useRef(null)
  const previousFocusRef = useRef(null)
  const prevParamsRef = useRef(null)
  const prevNodeIdRef = useRef(null)

  const flowNode = nodes.find((n) => n.id === selectedId)
  const node = flowNode?.data?.node
  const meta = useMemo(
    () => (node ? catalog.find((n) => n.type === node.type) : null),
    [catalog, node],
  )
  const schema = meta?.parameters_schema
  const credTypes = meta?.credential_types || []

  const incomingEdges = useMemo(() => edges?.filter((e) => e.target === selectedId) || [], [edges, selectedId])
  const upstreamNode = useMemo(() => {
    if (incomingEdges.length === 0) return null
    const sourceId = incomingEdges[0].source
    return nodes.find((n) => n.id === sourceId) || null
  }, [incomingEdges, nodes])

  useEffect(() => {
    setConfirmDelete(false)
    setShowAutoRepair(false)
  }, [selectedId])

  // Animate open/close
  useEffect(() => {
    if (nodeEditorOpen) {
      previousFocusRef.current = document.activeElement
      setVisible(true)
      setClosing(false)
      requestAnimationFrame(() => {
        modalRef.current?.focus()
      })
    } else if (visible) {
      setClosing(true)
      const t = setTimeout(() => {
        setVisible(false)
        setClosing(false)
        previousFocusRef.current?.focus()
      }, 200)
      return () => clearTimeout(t)
    }
  }, [nodeEditorOpen, visible])

  // Load upstream fields
  useEffect(() => {
    setMapping([])
    setUpstreamData(null)
    setOutputData(null)
    setExecError(null)
    if (!workflow?.id || !selectedId || !nodeEditorOpen) return
    let alive = true
    api
      .upstreamFields(workflow.id, selectedId)
      .then((data) => {
        if (!alive) return
        setMapping(data.fields || [])
      })
      .catch(() => {})
    return () => { alive = false }
  }, [workflow?.id, selectedId, nodeEditorOpen])

  // Load upstream data from the most recent execution trace
  useEffect(() => {
    if (!nodeEditorOpen || !selectedId) {
      setUpstreamData(null)
      setOutputData(null)
      return
    }
    const step = trace.find((s) => s.node_id === selectedId)
    const fullOutput = (results?.outputs && results.outputs[selectedId]) || null
    if (step || fullOutput) {
      setUpstreamData(step?.inputs || null)
      setOutputData(fullOutput || step?.outputs || null)
    } else {
      if (upstreamNode) {
        const upStep = trace.find((s) => s.node_id === upstreamNode.id)
        const upFull = (results?.outputs && results.outputs[upstreamNode.id]) || null
        setUpstreamData(upFull || upStep?.outputs || null)
      } else {
        setUpstreamData(null)
      }
      setOutputData(null)
    }
  }, [nodeEditorOpen, selectedId, trace, results, upstreamNode])

  // Invalidate stale output when Resource/Object/Operation/SOQL changes — prevents showing old Account data for Recruitment__c
  useEffect(() => {
    if (!nodeEditorOpen || !node) return
    const key = JSON.stringify({ r: node.parameters?.resource, o: node.parameters?.object_name, op: node.parameters?.operation, q: node.parameters?.soql })
    if (prevNodeIdRef.current !== selectedId) {
      prevNodeIdRef.current = selectedId
      prevParamsRef.current = key
      return
    }
    if (prevParamsRef.current !== key) {
      prevParamsRef.current = key
      // Params changed on this node — old output is stale, clear it
      setOutputData(null)
      setExecError(null)
    }
  }, [node?.parameters?.resource, node?.parameters?.object_name, node?.parameters?.operation, node?.parameters?.soql, nodeEditorOpen, node, selectedId])

  const status = nodeStatuses[selectedId]
  const preview = runPreview[selectedId]
  const rawError = execError || preview?.error || (status === 'failed' || status === 'error' ? (preview?.note || 'Execution failed') : null)
  const effectiveError = typeof rawError === 'object' && rawError !== null && !isValidElement(rawError)
    ? (rawError.message || (rawError.code ? `${rawError.code}: ${JSON.stringify(rawError.details || rawError)}` : JSON.stringify(rawError)))
    : rawError
  const operation = node?.parameters?.operation
  const connectorName = meta?.display_name || node?.type || 'Node'

  async function previewExpression(expression) {
    return api.previewExpression(workflow.id, { expression, node_id: selectedId })
  }

  const handleClose = useCallback(() => {
    if (closing) return
    setClosing(true)
    setTimeout(() => {
      close()
      setVisible(false)
      setClosing(false)
      previousFocusRef.current?.focus()
    }, 200)
  }, [closing, close])

  // Focus trap
  useEffect(() => {
    if (!visible || closing) return
    function onKeyDown(e) {
      if (e.key === 'Escape') {
        handleClose()
        return
      }
      if (e.key === 'Tab') {
        const modal = modalRef.current
        if (!modal) return
        const focusable = modal.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
        if (focusable.length === 0) return
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [visible, closing, handleClose])

  // Execute single step — always use current workflow params (save first), never retry success
  const handleExecuteStep = useCallback(async () => {
    if (!workflow?.id || !selectedId) return
    setExecuting(true)
    setExecError(null)
    // Clear stale output immediately — prevents showing old Account data while Recruitment__c runs
    setOutputData(null)
    try {
      // Ensure latest Resource/Object/Operation/SOQL is saved before execution
      try { await useWorkflowStore.getState().save() } catch {}
      let result
      // Only retry if previous execution actually failed this node; otherwise start fresh runNode
      const isFailed = status === 'failed' || status === 'error'
      if (executionId && isFailed) {
        result = await api.retry(executionId, selectedId)
      } else {
        result = await api.runNode(workflow.id, selectedId)
      }
      if (result?.execution_id) {
        await useExecutionStore.getState().load(result.execution_id)
      }
    } catch (err) {
      setExecError(err.message)
    } finally {
      setExecuting(false)
    }
  }, [workflow?.id, selectedId, executionId, status])

  // Execute all nodes up to this one
  const handleExecutePrevious = useCallback(async () => {
    if (!workflow?.id || !selectedId) return
    setExecuting(true)
    setExecError(null)
    try {
      const result = await api.runToNode(workflow.id, selectedId)
      if (result?.execution_id) {
        await useExecutionStore.getState().load(result.execution_id)
      }
    } catch (err) {
      setExecError(err.message)
    } finally {
      setExecuting(false)
    }
  }, [workflow?.id, selectedId])

  if (!visible && !nodeEditorOpen) return null
  if (!flowNode || !node) return null

  function setSetting(key, value) {
    updateNode(node.id, { settings: { ...(node.settings || {}), [key]: value } })
  }

  function setCredential(type, id) {
    const creds = { ...(node.credentials || {}) }
    if (id) creds[type] = id
    else delete creds[type]
    updateNode(node.id, { credentials: creds })
  }

  function handleParamsChange(newParams) {
    updateNode(node.id, { parameters: newParams })
  }

  if (typeof document === 'undefined') return null

  return createPortal(
    <div
      className={`node-editor-overlay ${closing ? 'closing' : ''}`}
      onClick={handleClose}
    >
      <div
        className={`node-editor-modal ${closing ? 'closing' : ''}`}
        onClick={(e) => e.stopPropagation()}
        ref={modalRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`Edit ${connectorName}`}
      >
        {/* Header */}
        <header className="nem-header">
          <div className="nem-title">
            <span className="nem-icon">
              <NodeIcon type={node.type} icon={node.settings?.icon || meta?.icon} size={26} />
            </span>
            <div className="nem-title-text">
              <div className="nem-title-row">
                <h2>{node.settings?.label || node.name || meta?.display_name || node.type}</h2>
                <span className="nem-node-id-badge">{node.id}</span>
              </div>
              <span className="nem-connector-meta">
                {node.settings?.label && meta?.display_name && (
                  <span className="nem-connector-type" style={{ color: '#a5b4fc', marginRight: 4 }}>
                    {meta.display_name}
                  </span>
                )}
                {meta?.category && <span className="nem-category">{meta.category}</span>}
                {operation && <span className="nem-operation">{operation}</span>}
              </span>
            </div>
            {status && (
              <div className="nem-title-status">
                {preview?.durationMs != null && (
                  <span className="nem-duration">
                    {preview.durationMs < 1000
                      ? `${Math.round(preview.durationMs)}ms`
                      : `${(preview.durationMs / 1000).toFixed(1)}s`}
                  </span>
                )}
                <Status status={status} live />
              </div>
            )}
          </div>
          <div className="nem-actions">
            <Button
              variant="ghost"
              onClick={handleExecutePrevious}
              disabled={executing}
              title="Execute all nodes up to this one"
            >
              {executing ? '…' : '▶'} Previous
            </Button>
            <Button
              variant="primary"
              onClick={handleExecuteStep}
              disabled={executing}
              title="Execute this node only"
            >
              {executing ? '…' : '▶'} Execute Step
            </Button>
            <Button variant="ghost" className="nem-close" onClick={handleClose} title="Close (Esc)">
              ✕
            </Button>
          </div>
        </header>

        {/* Responsive Panel Navigation Bar (< 1150px) */}
        <nav className="nem-panel-nav" role="tablist" aria-label="Editor Panels">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'input'}
            className={`nem-panel-nav-btn ${activeTab === 'input' ? 'active' : ''}`}
            onClick={() => setNodeEditorTab('input')}
          >
            <span className="nem-panel-nav-dot" />
            Input
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'parameters'}
            className={`nem-panel-nav-btn ${activeTab === 'parameters' ? 'active' : ''}`}
            onClick={() => setNodeEditorTab('parameters')}
          >
            <span className="nem-panel-nav-dot" />
            Parameters
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'output'}
            className={`nem-panel-nav-btn ${activeTab === 'output' ? 'active' : ''}`}
            onClick={() => setNodeEditorTab('output')}
          >
            <span className="nem-panel-nav-dot" />
            Output
            {outputData && <span className="nem-panel-nav-badge">Data</span>}
          </button>
        </nav>

        {effectiveError && !showAutoRepair && (
          <ErrorState
            icon="⚠️"
            title="Execution failed"
            description={effectiveError}
            action={
              <Button
                variant="primary"
                onClick={() => setShowAutoRepair(true)}
                style={{
                  background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #d946ef 100%)',
                  border: 'none',
                  color: '#fff',
                }}
              >
                ⚡ Flowsmith AI Self-Healing Diagnostic
              </Button>
            }
          />
        )}

        {showAutoRepair && effectiveError && (
          <NodeAutoRepair
            workflowId={workflow.id}
            node={node}
            errorMessage={effectiveError}
            onClose={() => setShowAutoRepair(false)}
            onApplyFix={async (suggestedParams, retest) => {
              updateNode(node.id, { parameters: suggestedParams })
              setShowAutoRepair(false)
              setExecError(null)
              try {
                await useWorkflowStore.getState().save()
              } catch (e) {
                console.error('Failed to save repaired workflow', e)
              }
              if (retest) {
                setTimeout(() => {
                  handleExecuteStep()
                }, 100)
              }
            }}
          />
        )}

        {status === 'skipped' && (
          <div className="nem-stop-notice nem-stop-skipped">
            <span className="nem-stop-icon">⊘</span>
            <div className="nem-stop-content">
              <strong>Step Skipped: No Input Data Arrived</strong>
              <p>{preview?.note || 'This node was skipped because no data arrived from upstream node(s). The workflow stopped before this point.'}</p>
            </div>
          </div>
        )}

        {status === 'success' && preview?.outputCount === 0 && (
          <div className="nem-stop-notice nem-stop-zero">
            <span className="nem-stop-icon">⏹</span>
            <div className="nem-stop-content">
              <strong>Workflow Stopped Here: 0 Output Items</strong>
              <p>This node executed successfully but produced 0 output items. Connected downstream nodes were not executed because there was no data to continue.</p>
            </div>
          </div>
        )}

        {/* Three-panel body */}
        <div className="nem-body">
          {/* INPUT panel — multi-node upstream tree */}
          <div className={`nem-panel nem-input ${activeTab === 'input' ? 'mobile-active' : ''}`}>
            <InputPanel
              currentNodeId={selectedId}
              nodes={nodes}
              edges={edges}
              catalog={catalog}
              trace={trace}
              results={results}
              runPreview={runPreview}
              executing={executing}
              onExecutePrevious={handleExecutePrevious}
            />
          </div>

          {/* PARAMETERS / SETTINGS panel */}
          <div className={`nem-panel nem-params ${activeTab === 'parameters' ? 'mobile-active' : ''}`}>
            <div className="nem-panel-head">
              <h3>{settingsTab ? 'Settings' : 'Parameters'}</h3>
              <Tabs
                className="nem-panel-tabs"
                ariaLabel="Node configuration sections"
                value={settingsTab ? 'settings' : 'parameters'}
                onChange={(id) => setSettingsTab(id === 'settings')}
                tabs={[
                  { id: 'parameters', label: 'Parameters' },
                  { id: 'settings', label: 'Settings' },
                ]}
              />
            </div>
            <div className="nem-panel-body">
              {!settingsTab ? (
                <>
                  {meta?.idempotency && (
                    <p className={`hint idempotency idem-${meta.idempotency}`} title={IDEMPOTENCY_HINT[meta.idempotency]}>
                      {IDEMPOTENCY_LABEL[meta.idempotency] || meta.idempotency}
                    </p>
                  )}
                  {node.type === 'salesforce' && meta?.operations && (
                    <OpSafetyHint operation={operation} operations={meta.operations} />
                  )}

                  <Suspense fallback={<div className="panel-loading" style={{ padding: '24px', textAlign: 'center', opacity: 0.7 }}><p className="hint">Loading editor…</p></div>}>
                  {node.type === 'salesforce' ? (
                    <SalesforceNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      credentials={credentials}
                      onCredentialChange={setCredential}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'code' ? (
                    <CodeNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'if_condition' ? (
                    <IfConditionEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'filter' ? (
                    <FilterNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      onSettingsChange={setSetting}
                      mapping={mapping}
                      onPreview={previewExpression}
                      tab="parameters"
                    />
                  ) : node.type === 'schedule' ? (
                    <ScheduleTriggerEditor node={node} onParamsChange={handleParamsChange} />
                  ) : node.type === 'webhook' ? (
                    <WebhookNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      workflowId={workflow?.id}
                    />
                  ) : node.type === 'http_request' ? (
                    <HttpRequestNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                      credentials={credentials}
                      credentialTypes={credentialTypes}
                      onCredentialChange={setCredential}
                    />
                  ) : (node.type === 'split' || node.type === 'item_lists') ? (
                    <SplitNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'compare_datasets' ? (
                    <CompareDatasetsEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'stop_and_error' ? (
                    <StopAndErrorNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'switch' ? (
                    <SwitchNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : node.type === 'wait' ? (
                    <WaitNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : (node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') ? (
                    <ExecuteWorkflowNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : (node.type === 'execute_workflow_trigger' || node.type === 'sub_workflow_trigger') ? (
                    <ExecuteWorkflowTriggerEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                    />
                  ) : (node.type === 'token_manager') ? (
                    <TokenManagerNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : (node.type === 'token_fetch' || node.type === 'auth_fetch') ? (
                    <TokenFetchNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : (node.type === 'token_store' || node.type === 'auth_store') ? (
                    <TokenStoreNodeEditor
                      node={node}
                      onParamsChange={handleParamsChange}
                      mapping={mapping}
                      onPreview={previewExpression}
                    />
                  ) : (
                    <>
                      {node.type === 'data_table' && (
                        <DataTableDiscovery node={node} onParamsChange={handleParamsChange} />
                      )}
                      {schema ? (
                        // Hide internal schema name for schedule (now has dedicated editor)
                        <JsonForm
                          schema={schema}
                          value={node.parameters || {}}
                          onChange={handleParamsChange}
                          mapping={mapping}
                          onPreview={previewExpression}
                        />
                      ) : (
                        <div className="nem-empty">
                          <div className="nem-empty-icon">⚙️</div>
                          <p className="hint">No parameters defined for this node.</p>
                        </div>
                      )}
                    </>
                  )}
                  </Suspense>

                  {node.type === 'webhook' && (
                    <CollapsibleSection title="Webhook URL" defaultOpen={true}>
                      <input
                        readOnly
                        className="nem-webhook-url"
                        value={`${window.location.origin}/api/webhooks/${node.parameters?.path || ''}`}
                        onFocus={(e) => e.target.select()}
                      />
                    </CollapsibleSection>
                  )}

                  <> 
                      <CollapsibleSection title="Appearance" defaultOpen={false}>
                        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                          <label style={{ width: 80 }}>
                            Icon
                            <input
                              value={node.settings?.icon || ''}
                              placeholder={meta?.icon || '🌐'}
                              maxLength={6}
                              onChange={(e) => setSetting('icon', e.target.value)}
                              style={{ textAlign: 'center', fontSize: 18 }}
                              title="Custom icon or emoji for this node"
                            />
                          </label>
                          <label style={{ flex: 1 }}>
                            Custom label
                            <input
                              value={node.settings?.label || ''}
                              placeholder={meta?.display_name || node.type}
                              onChange={(e) => setSetting('label', e.target.value)}
                            />
                          </label>
                        </div>
                        <label>
                          Colour
                          <select
                            value={node.settings?.color || ''}
                            onChange={(e) => setSetting('color', e.target.value)}
                          >
                            {NODE_COLORS.map((c) => (
                              <option key={c.value} value={c.value}>{c.label}</option>
                            ))}
                          </select>
                        </label>
                      </CollapsibleSection>

                      <CollapsibleSection title="Credential" defaultOpen={false} badge={credTypes.length || ''}>
                        {credTypes.length === 0 ? (
                          <p className="hint">This node needs no credentials.</p>
                        ) : (
                          <>
                            {credTypes.map((type) => {
                              const options = credentials.filter((c) => c.type === type)
                              const value = node.credentials?.[type] || ''
                              const isConnStrType = ['database','postgres','mysql','redis','mongodb'].includes(type)
                              const selectedName = options.find(o => o.id === value)?.name || ''
                              return (
                                <div key={type} style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                                  <label>
                                    {type} {isConnStrType && <span className="hint" style={{ fontWeight: 400 }}>(connection string)</span>}
                                    <select value={value} onChange={(e) => setCredential(type, e.target.value)}>
                                      <option value="">None</option>
                                      {options.map((c) => (
                                        <option key={c.id} value={c.id}>{c.name}</option>
                                      ))}
                                    </select>
                                  </label>
                                  {isConnStrType && value && (
                                    <button type="button" className="ghost small" style={{ alignSelf: 'flex-start', color: 'var(--red)', fontSize: 11 }} onClick={async () => {
                                      if (!window.confirm(`Delete connection string “${selectedName}”? This will remove the credential permanently.`)) return
                                      try { await useCredentialStore.getState().remove(value); setCredential(type, '') } catch (e) { alert(e.message) }
                                    }} title="Delete connection string">🗑 Delete connection string</button>
                                  )}
                                </div>
                              )
                            })}
                            {credentials.length === 0 && (
                              <p className="hint">No credentials stored yet — open Credentials in the sidebar.</p>
                            )}
                          </>
                        )}
                      </CollapsibleSection>

                      <CollapsibleSection title="AI assist" defaultOpen={false}>
                        <AiConfigAssist node={node} updateNode={updateNode} />
                      </CollapsibleSection>
                    </>

                  <div className="panel-actions">
                    <button className="ghost" onClick={() => duplicateNodes([node.id])} title="Duplicate this node (Ctrl+D)">
                      Duplicate
                    </button>
                    {!confirmDelete ? (
                      <button className="danger" onClick={() => setConfirmDelete(true)} title="Delete this node">
                        Delete
                      </button>
                    ) : (
                      <div className="nem-confirm-delete">
                        <span className="hint">Delete this node?</span>
                        <button className="danger" onClick={() => { deleteNodes([node.id]); handleClose() }}>
                          Confirm
                        </button>
                        <button className="ghost" onClick={() => setConfirmDelete(false)}>
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <CollapsibleSection title="General" defaultOpen={true}>
                    <label className="check">
                      <input type="checkbox" checked={Boolean(node.settings?.alwaysOutputData)} onChange={e => setSetting('alwaysOutputData', e.target.checked)} />
                      Always Output Data
                    </label>
                    <p className="hint">If no items, still output an empty item.</p>
                    <label className="check">
                      <input type="checkbox" checked={Boolean(node.settings?.executeOnce)} onChange={e => setSetting('executeOnce', e.target.checked)} />
                      Execute Once
                    </label>
                    <p className="hint">Only execute once per workflow run.</p>
                  </CollapsibleSection>
                  <CollapsibleSection title="Retry" defaultOpen={true}>
                    <label className="check">
                      <input type="checkbox" checked={Boolean(node.settings?.retryOnFail)} onChange={e => setSetting('retryOnFail', e.target.checked)} />
                      Retry On Fail
                    </label>
                    {node.settings?.retryOnFail && (
                      <>
                        <label>
                          Max Tries
                          <input type="number" min={1} max={10} value={node.settings?.maxTries ?? 3} onChange={e => setSetting('maxTries', Number(e.target.value))} />
                        </label>
                        <label>
                          Wait Between Tries (ms)
                          <input type="number" min={0} value={node.settings?.waitBetweenTries ?? 1000} onChange={e => setSetting('waitBetweenTries', Number(e.target.value))} />
                        </label>
                      </>
                    )}
                  </CollapsibleSection>
                  <CollapsibleSection title="On Error" defaultOpen={true}>
                    <select value={node.settings?.onError || 'stop'} onChange={e => setSetting('onError', e.target.value)}>
                      <option value="stop">Stop Workflow</option>
                      <option value="continue">Continue</option>
                      <option value="continueWithError">Continue using error output</option>
                    </select>
                    <p className="hint">
                      {node.settings?.onError === 'stop' && 'Stop execution on error.'}
                      {node.settings?.onError === 'continue' && 'Ignore error and continue.'}
                      {node.settings?.onError === 'continueWithError' && 'Continue and output error data.'}
                    </p>
                  </CollapsibleSection>
                  <CollapsibleSection title="Execution" defaultOpen={false}>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={Boolean(node.settings?.continue_on_error)}
                        onChange={(e) => setSetting('continue_on_error', e.target.checked)}
                      />
                      Continue on error
                    </label>
                    <label>
                      Timeout (seconds)
                      <input
                        type="number"
                        min={0}
                        value={node.settings?.timeout_seconds ?? 0}
                        onChange={(e) => setSetting('timeout_seconds', Number(e.target.value))}
                      />
                    </label>
                    <label>
                      Retries (extra attempts after a transient failure)
                      <input
                        type="number"
                        min={0}
                        max={10}
                        value={node.settings?.retry_max_attempts ?? 0}
                        onChange={(e) => setSetting('retry_max_attempts', Number(e.target.value) || 0)}
                      />
                    </label>
                    <label>
                      Retry backoff (seconds, doubles each attempt)
                      <input
                        type="number"
                        min={0}
                        value={node.settings?.retry_backoff_seconds ?? 2}
                        onChange={(e) => setSetting('retry_backoff_seconds', Number(e.target.value) || 0)}
                      />
                    </label>
                    {Number(node.settings?.retry_max_attempts ?? 0) > 0 && meta?.idempotency && (
                      <p className={`hint ${meta.idempotency === 'idempotent' ? '' : 'retry-risky'}`}>
                        {meta.idempotency === 'idempotent' &&
                          'Retries are safe: this node is idempotent. Only transient errors (network, timeouts) retry — never invalid params or credentials.'}
                        {meta.idempotency === 'conditionally_idempotent' &&
                          'Retries only duplicate side effects for non-read-only runs (POST/PATCH, INSERT/UPDATE/DELETE).'}
                        {meta.idempotency === 'non_idempotent' &&
                          'This node is not idempotent — retries may duplicate side effects (emails sent, model calls billed, rows written).'}
                      </p>
                    )}
                  </CollapsibleSection>
                  <p className="hint">Only settings mapped to the execution engine are persisted.</p>
                </>
              )}
            </div>
          </div>

          {/* OUTPUT panel — execution results */}
          <div className={`nem-panel nem-output ${activeTab === 'output' ? 'mobile-active' : ''}`}>
            <OutputPanel
              data={outputData}
              status={status}
              executing={executing}
              error={
                execError ||
                ((status === 'error' || status === 'failed')
                  ? (() => {
                      const stepErr = trace.find((s) => s.node_id === selectedId)?.error
                      if (stepErr) {
                        return typeof stepErr === 'object' ? (stepErr.message || JSON.stringify(stepErr)) : String(stepErr)
                      }
                      if (preview?.error) {
                        return typeof preview.error === 'object' ? (preview.error.message || JSON.stringify(preview.error)) : String(preview.error)
                      }
                      return preview?.note || 'Execution failed'
                    })()
                  : null)
              }
              nodeId={selectedId}
              nodeLabel={node?.settings?.label || node?.name || node?.data?.label || meta?.display_name || node?.type}
              onExecuteStep={handleExecuteStep}
            />
          </div>
        </div>

        {/* Footer */}
        <footer className="nem-footer">
          {workflow && (
            <span className="nem-version">Version: {workflow.version || '—'}</span>
          )}
          {versions && versions.length > 1 && (
            <span className="nem-versions">
              {versions.slice(0, 3).map((v) => v.version).join(' · ')}
              {versions.length > 3 && ` +${versions.length - 3}`}
            </span>
          )}
          <div className="nem-footer-right">
            <ExpressionHelper workflowId={workflow?.id} nodeId={selectedId} />
          </div>
        </footer>
      </div>
    </div>,
    document.body
  )
}

// AI Config Assist
function AiConfigAssist({ node, updateNode }) {
  const [intent, setIntent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [suggestion, setSuggestion] = useState(null)
  const [applying, setApplying] = useState(false)

  async function suggest() {
    if (!intent.trim() || busy) return
    setBusy(true)
    setError(null)
    setSuggestion(null)
    try {
      const operation = node.parameters?.operation || null
      const data = await api.suggestNodeConfig({
        node_type: node.type,
        operation,
        intent: intent.trim(),
      })
      setSuggestion({
        text: JSON.stringify(data.parameters ?? {}, null, 2),
        ok: Boolean(data.ok),
        issues: data.issues || [],
        explanation: data.explanation || '',
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function apply() {
    if (!suggestion) return
    let parsed
    try {
      parsed = JSON.parse(suggestion.text)
    } catch (err) {
      setError(`Invalid JSON: ${err.message}`)
      return
    }
    setApplying(true)
    try {
      updateNode(node.id, { parameters: parsed })
      setSuggestion(null)
      setIntent('')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="ai-assist">
      <label>
        What should this node do?
        <textarea
          rows={2}
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          placeholder="e.g. search for the lead by email and return its id"
        />
      </label>
      <button className="ghost" disabled={busy || !intent.trim()} onClick={suggest}>
        {busy ? 'Thinking…' : 'Suggest parameters'}
      </button>
      {error && <p className="banner-inline err">{error}</p>}
      {suggestion && (
        <div className="ai-suggestion">
          <span className={`gen-verdict ${suggestion.ok ? 'ok' : 'err'}`}>
            {suggestion.ok ? 'validated' : 'has issues'}
          </span>
          {suggestion.explanation && <p className="hint">{suggestion.explanation}</p>}
          {suggestion.issues.map((i, idx) => (
            <p key={idx} className={`banner-inline ${i.severity === 'error' ? 'err' : 'info'}`}>
              {i.code}: {i.message}
            </p>
          ))}
          <textarea
            className="ai-json"
            rows={8}
            spellCheck="false"
            value={suggestion.text}
            onChange={(e) => setSuggestion({ ...suggestion, text: e.target.value })}
          />
          <p className="hint">Edit freely — applying is a normal edit; save the workflow to persist.</p>
          <div className="ai-actions">
            <button className="primary" disabled={applying} onClick={apply}>Apply</button>
            <button className="ghost" onClick={() => setSuggestion(null)}>Discard</button>
          </div>
        </div>
      )}
    </div>
  )
}
