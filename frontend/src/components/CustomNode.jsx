import React, { memo, useState, useCallback, useRef, useEffect, Fragment } from 'react'
import { Handle, Position } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useUiStore } from '../stores/uiStore'
import { NodeIcon } from './NodeIcons'

const CATEGORY_COLORS = {
  Trigger: '#34c759',
  Communication: '#4f8cff',
  Database: '#bf5af2',
  Transform: '#ffd60a',
  Logic: '#64d2ff',
  AI: '#ff9f0a',
  api: '#4f8cff',
  database: '#bf5af2',
  communication: '#4f8cff',
}

function ContextMenu({ x, y, nodeId, isPinned, onPin, onUnpin, onClose }) {
  const menuRef = useRef(null)
  const deleteNodes = useWorkflowStore((s) => s.deleteNodes)
  const duplicateNodes = useWorkflowStore((s) => s.duplicateNodes)
  const openNodeEditor = useUiStore((s) => s.openNodeEditor)
  const workflowId = useWorkflowStore((s) => s.workflow?.id)
  const loadExecution = useExecutionStore((s) => s.load)
  const [runningStep, setRunningStep] = useState(false)

  useEffect(() => {
    let active = true
    function handlePointer(e) {
      if (!active) return
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose()
      }
    }
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }

    // Delay listener registration by one animation frame so the contextmenu event itself doesn't close it
    const frame = requestAnimationFrame(() => {
      window.addEventListener('pointerdown', handlePointer, true)
      window.addEventListener('mousedown', handlePointer, true)
      window.addEventListener('touchstart', handlePointer, true)
      window.addEventListener('contextmenu', handlePointer, true)
      window.addEventListener('keydown', handleKey, true)
      window.addEventListener('wheel', onClose, { passive: true, capture: true })
    })

    return () => {
      active = false
      cancelAnimationFrame(frame)
      window.removeEventListener('pointerdown', handlePointer, true)
      window.removeEventListener('mousedown', handlePointer, true)
      window.removeEventListener('touchstart', handlePointer, true)
      window.removeEventListener('contextmenu', handlePointer, true)
      window.removeEventListener('keydown', handleKey, true)
      window.removeEventListener('wheel', onClose, { capture: true })
    }
  }, [onClose])

  const handleTestStep = async () => {
    if (!workflowId || runningStep) return
    setRunningStep(true)
    try {
      try { await useWorkflowStore.getState().save() } catch {}
      const { api } = await import('../api')
      const res = await api.runNode(workflowId, nodeId)
      if (res?.execution_id) {
        await loadExecution(res.execution_id)
      }
      onClose()
    } catch (err) {
      alert('Test step failed: ' + err.message)
    } finally {
      setRunningStep(false)
    }
  }

  const handleRunToHere = async () => {
    if (!workflowId || runningStep) return
    setRunningStep(true)
    try {
      try { await useWorkflowStore.getState().save() } catch {}
      const { api } = await import('../api')
      const res = await api.runToNode(workflowId, nodeId)
      if (res?.execution_id) {
        await loadExecution(res.execution_id)
      }
      onClose()
    } catch (err) {
      alert('Run to here failed: ' + err.message)
    } finally {
      setRunningStep(false)
    }
  }

  return (
    <div
      ref={menuRef}
      className="node-context-menu"
      style={{ left: x, top: y }}
      onClick={(e) => e.stopPropagation()}
    >
      <button onClick={() => { openNodeEditor(nodeId); onClose() }}>
        <span className="ctx-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
        </span>
        <span className="ctx-label">Open</span>
        <span className="ctx-shortcut">Enter</span>
      </button>

      <div className="ctx-sep" />

      <button onClick={handleTestStep} disabled={runningStep}>
        <span className="ctx-icon" style={{ color: 'var(--primary, #6366f1)' }}>
          ▶
        </span>
        <span className="ctx-label">{runningStep ? 'Testing…' : 'Test Step (Run Node)'}</span>
      </button>

      <button onClick={handleRunToHere} disabled={runningStep}>
        <span className="ctx-icon" style={{ color: '#10b981' }}>
          ⏩
        </span>
        <span className="ctx-label">Run to Here</span>
      </button>

      {isPinned ? (
        <button onClick={() => { onUnpin(); onClose() }}>
          <span className="ctx-icon">📌</span>
          <span className="ctx-label">Unpin Mock Data</span>
        </button>
      ) : (
        <button onClick={() => { onPin(); onClose() }}>
          <span className="ctx-icon">📌</span>
          <span className="ctx-label">Pin Output Data</span>
        </button>
      )}

      <div className="ctx-sep" />

      <button onClick={() => { duplicateNodes([nodeId]); onClose() }}>
        <span className="ctx-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
        </span>
        <span className="ctx-label">Duplicate</span>
        <span className="ctx-shortcut">Ctrl+D</span>
      </button>
      <div className="ctx-sep" />
      <button className="ctx-danger" onClick={() => { deleteNodes([nodeId]); onClose() }}>
        <span className="ctx-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <line x1="10" y1="11" x2="10" y2="17" />
            <line x1="14" y1="11" x2="14" y2="17" />
          </svg>
        </span>
        <span className="ctx-label">Delete</span>
        <span className="ctx-shortcut">Del</span>
      </button>
    </div>
  )
}

function CustomNode({ id, data, selected }) {
  const meta = useWorkflowStore((s) => s.catalogIndex.get(data.node.type))
  const status = useExecutionStore((s) => s.nodeStatuses[id])
  const preview = useExecutionStore((s) => s.runPreview[id])
  const openNodeEditor = useUiStore((s) => s.openNodeEditor)

  const [ctx, setCtx] = useState(null)
  const nodeRef = useRef(null)

  const settings = data.node.settings || {}
  const params = data.node.parameters || {}
  const label = settings.label || meta?.display_name || data.node.type
  const accent =
    settings.color ||
    CATEGORY_COLORS[meta?.category] ||
    '#5b6472'

  const isLoop = data.node.type === 'loop' || data.node.type === 'loop_over_items'
  const isSwitch = data.node.type === 'switch'
  const inputHandles = meta?.input_handles?.length ? meta.input_handles : ['main']
  const outputHandles = isLoop
    ? ['done', 'loop']
    : isSwitch
    ? (Array.isArray(params.rules) && params.rules.length > 0
        ? [
            ...params.rules.map((r, i) => (r.rename_output && r.output_name ? r.output_name : (r.output || `route_${i}`))),
            ...(params.options?.fallbackOutput ? ['fallback'] : []),
          ]
        : (meta?.output_handles?.length ? meta.output_handles : ['route_0', 'route_1', 'route_2', 'default']))
    : (meta?.output_handles?.length ? meta.output_handles : ['main'])
  const nInputs = inputHandles.length
  const nOutputs = outputHandles.length

  const failed = status === 'failed' || status === 'error'
  const skipped = status === 'skipped'
  const running = status === 'running' || status === 'waiting' || status === 'waiting_approval'
  const showPreview =
    preview &&
    (status === 'success' || status === 'failed' || status === 'skipped' || status === 'error' || running) &&
    (preview.outputCount != null || preview.error || preview.durationMs != null || status === 'skipped')

  // Derive dynamic subtitle (matching node configuration)
  let subtitle = ''
  let fullSubtitle = ''
  const nodeType = data.node.type
  if (nodeType === 'http_request') {
    const m = params.method || 'GET'
    const u = params.url || ''
    fullSubtitle = u ? `${m}: ${u}` : m
    const cleanUrl = u.replace(/^https?:\/\//, '')
    subtitle = cleanUrl ? `${m}: ${cleanUrl.slice(0, 24)}${cleanUrl.length > 24 ? '…' : ''}` : m
  } else if (nodeType === 'salesforce') {
    const op = params.operation || 'query'
    const obj = params.object_name || ''
    subtitle = obj ? `${op}: ${obj}` : op
    fullSubtitle = subtitle
  } else if (nodeType === 'code') {
    subtitle = params.mode === 'runOnceForAllItems' ? 'Run once' : 'Run for each'
  } else if (nodeType === 'schedule') {
    subtitle = params.rule || params.cron || (params.interval ? `Every ${params.interval}` : 'Trigger')
  } else if (nodeType === 'webhook') {
    subtitle = params.httpMethod ? `${params.httpMethod}: /${params.path || ''}` : 'Inbound'
  } else if (nodeType === 'database_query') {
    subtitle = params.operation || 'Query'
  } else if (nodeType === 'set_data') {
    subtitle = 'Set values'
  } else if (nodeType === 'filter') {
    subtitle = 'Filter'
  } else if (nodeType === 'send_email') {
    subtitle = params.toEmail || 'Email'
  } else if (nodeType === 'slack' || nodeType === 'telegram') {
    subtitle = params.channel || 'Message'
  } else if (nodeType === 'gmail') {
    subtitle = params.operation ? `${params.operation}${params.to ? `: ${params.to}` : ''}` : 'Gmail'
  } else if (nodeType === 'google_sheets') {
    subtitle = params.operation ? `${params.operation}${params.sheetName ? `: ${params.sheetName}` : ''}` : 'Sheets'
  } else if (nodeType === 'google_calendar') {
    subtitle = params.operation || 'Calendar'
  } else if (nodeType === 'google_drive') {
    subtitle = params.operation || 'Drive'
  } else if (nodeType === 'hubspot') {
    subtitle = params.resource || params.operation || 'HubSpot'
  } else if (nodeType === 'ai_agent' || nodeType === 'llm' || nodeType === 'agent') {
    subtitle = params.model ? `Model: ${params.model}` : 'AI Model'
  } else if (nodeType === 'subworkflow') {
    subtitle = params.workflow_id ? `Wf: ${params.workflow_id.slice(0, 8)}` : 'Subworkflow'
  } else if (nodeType === 'switch') {
    subtitle = Array.isArray(params.rules) && params.rules.length > 0 ? `${params.rules.length} route(s)` : 'Branch'
  } else if (isLoop) {
    subtitle = params.batch_size ? `Batch: ${params.batch_size}` : 'Loop'
  }
  if (!fullSubtitle) fullSubtitle = subtitle

  const handleContextMenu = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = nodeRef.current?.getBoundingClientRect()
    setCtx({
      x: e.clientX - (rect?.left || 0),
      y: e.clientY - (rect?.top || 0),
    })
  }, [])

  const updateNode = useWorkflowStore((s) => s.updateNode)
  const isPinned = data.node.pinned_data != null

  const handlePin = useCallback(() => {
    const lastResult = preview?.output_items || preview?.items || (preview?.outputCount ? [{ message: "mock output" }] : [{ id: 1, name: "Sample item" }])
    updateNode(id, { pinned_data: lastResult })
  }, [id, preview, updateNode])

  const handleUnpin = useCallback(() => {
    updateNode(id, { pinned_data: null })
  }, [id, updateNode])

  return (
    <div
      ref={nodeRef}
      className={`rf-node rf-node-wrapper cat-${(meta?.category || 'api').toLowerCase().replace(/[^a-z]+/g, '-')} status-${status || 'idle'} ${selected ? 'selected' : ''} ${failed ? 'has-error' : ''} ${running ? 'is-running' : ''}`}
      onClick={(e) => {
        if (e.target.closest('.react-flow__handle')) return
        openNodeEditor(id)
      }}
      onContextMenu={handleContextMenu}
      title={meta?.description}
      style={{ '--node-accent': accent }}
    >
      {/* Modern Square Card */}
      <div className={`rf-node-card ${running ? 'running' : ''} ${failed ? 'error' : ''}`}>
        {inputHandles.map((h, i) => (
          <Handle
            key={`in-${h}`}
            id={h}
            type="target"
            position={Position.Left}
            className="rf-handle rf-handle-left"
            style={nInputs > 1 ? { top: `${((i + 1) / (nInputs + 1)) * 100}%` } : undefined}
          />
        ))}

        {/* Centered Large Vector Icon */}
        <div className="rf-node-icon-wrap">
          <NodeIcon type={data.node.type} icon={settings.icon} size={36} color={accent} />
        </div>

        {/* Status indicator dot */}
        {status && <span className={`status-dot status-${status}`} />}

        {/* Pinned mock data badge */}
        {isPinned && (
          <span className="rf-node-pin-badge" title="Pinned Mock Data Active (live API calls bypassed)">
            📌
          </span>
        )}

        {/* Output Handles with branch labels for multi-outputs like If */}
        {outputHandles.map((h, i) => (
          <Fragment key={`out-frag-${h}`}>
            {nOutputs > 1 && (
              <span
                className={`rf-handle-label rf-handle-${h}`}
                style={{ top: `${((i + 1) / (nOutputs + 1)) * 100}%` }}
              >
                {h}
              </span>
            )}
            <Handle
              id={h}
              type="source"
              position={Position.Right}
              className="rf-handle rf-handle-right"
              style={nOutputs > 1 ? { top: `${((i + 1) / (nOutputs + 1)) * 100}%` } : undefined}
            />
          </Fragment>
        ))}
      </div>

      {/* Label and Subtitle underneath the card */}
      <div className="rf-node-info">
        <div className="rf-node-label" title={label}>{label}</div>
        {subtitle && <div className="rf-node-subtitle" title={fullSubtitle}>{subtitle}</div>}
      </div>

      {/* Execution chips below info */}
      {showPreview && (
        <div className="rf-node-preview">
          {skipped ? (
            <span
              className="preview-chip skip"
              title={preview?.note || 'Skipped: No input data arrived from upstream; step was not executed.'}
            >
              ⊘ Skipped (No input)
            </span>
          ) : preview?.outputCount === 0 && !preview?.error ? (
            <span
              className="preview-chip stopped"
              title="Workflow stopped here: node produced 0 output items (no data to continue downstream)"
            >
              ⏹ Stopped (0 items)
            </span>
          ) : (
            preview?.outputCount != null && !preview?.error && (
              <span className="preview-chip out" title={`Outputs from last run: ${preview.outputCount} item(s)`}>
                ↦ {preview.outputCount}
              </span>
            )
          )}
          {preview.durationMs != null && (
            <span className="preview-chip time">
              {preview.durationMs < 1000
                ? `${Math.round(preview.durationMs)}ms`
                : `${(preview.durationMs / 1000).toFixed(1)}s`}
            </span>
          )}
          {running && !preview.durationMs && <span className="preview-chip time">…</span>}
        </div>
      )}

      {failed && preview?.error && (
        <div className="rf-node-error" title={preview.error}>
          {String(preview.error).slice(0, 90)}
        </div>
      )}

      {ctx && (
        <ContextMenu
          x={ctx.x}
          y={ctx.y}
          nodeId={id}
          isPinned={isPinned}
          onPin={handlePin}
          onUnpin={handleUnpin}
          onClose={() => setCtx(null)}
        />
      )}
    </div>
  )
}

export default memo(CustomNode)
