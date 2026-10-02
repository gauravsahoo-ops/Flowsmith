import { useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { startNodeDrag } from '../utils/drag'
import { NodeIcon } from './NodeIcons'
import './SubWorkflowBrowser.css'

export default function SubWorkflowBrowser({ onClose }) {
  const [search, setSearch] = useState('')
  const [triggersOpen, setTriggersOpen] = useState(true)
  const [actionsOpen, setActionsOpen] = useState(true)

  const addNode = useWorkflowStore((s) => s.addNode)
  const openEditor = useUiStore((s) => s.openEditor)

  function handleAdd(type) {
    const id = addNode(type)
    if (id) {
      openEditor(id)
    }
    onClose?.()
  }

  const q = search.trim().toLowerCase()

  const showTrigger = !q || 'when executed by another workflow'.includes(q) || 'sub-workflow'.includes(q) || 'trigger'.includes(q)
  const showAction = !q || 'execute a sub-workflow'.includes(q) || 'sub-workflow'.includes(q) || 'action'.includes(q)

  return (
    <div className="subwf-browser">
      <div className="subwf-browser-header">
        <button className="ghost" onClick={onClose} aria-label="Back">←</button>
        <span className="subwf-browser-title">Execute Sub-workflow</span>
        <span className="subwf-browser-icon">
          <NodeIcon type="sub_workflow" size={16} />
        </span>
      </div>

      <div className="subwf-browser-search">
        <span className="subwf-search-icon"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></span>
        <input
          autoFocus
          placeholder="Search actions & triggers..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') setSearch('') }}
          aria-label="Search Sub-workflow"
        />
        {search && (
          <button className="ghost small" onClick={() => setSearch("")} aria-label="Clear search" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        )}
      </div>

      <div className="subwf-browser-content">
        {/* Triggers Section */}
        {showTrigger && (
          <div className="subwf-section">
            <button
              type="button"
              className="subwf-section-head"
              onClick={() => setTriggersOpen((v) => !v)}
              aria-expanded={triggersOpen}
            >
              <span>Triggers (1)</span>
              <span className="subwf-caret">{triggersOpen ? '▾' : '▸'}</span>
            </button>

            {triggersOpen && (
              <div className="subwf-section-body">
                <div
                  className="subwf-card"
                  draggable
                  onDragStart={(e) => startNodeDrag(e, 'execute_workflow_trigger')}
                  onClick={() => handleAdd('execute_workflow_trigger')}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleAdd('execute_workflow_trigger') }}
                >
                  <div className="subwf-card-icon-wrap">
                    <span className="subwf-input-arrow">→]</span>
                  </div>
                  <div className="subwf-card-content">
                    <div className="subwf-card-title">When executed by Another Workflow</div>
                    <div className="subwf-card-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></div>
                    <div className="subwf-card-desc">
                      Starts the workflow when called by an Execute Sub-workflow node in another workflow.
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Actions Section */}
        {showAction && (
          <div className="subwf-section">
            <button
              type="button"
              className="subwf-section-head"
              onClick={() => setActionsOpen((v) => !v)}
              aria-expanded={actionsOpen}
            >
              <span>Actions (1)</span>
              <span className="subwf-caret">{actionsOpen ? '▾' : '▸'}</span>
            </button>

            {actionsOpen && (
              <div className="subwf-section-body">
                <div
                  className="subwf-card"
                  draggable
                  onDragStart={(e) => startNodeDrag(e, 'sub_workflow')}
                  onClick={() => handleAdd('sub_workflow')}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleAdd('sub_workflow') }}
                >
                  <div className="subwf-card-icon-wrap">
                    <NodeIcon type="sub_workflow" size={18} />
                  </div>
                  <div className="subwf-card-content">
                    <div className="subwf-card-title">Execute a Sub-workflow</div>
                    <div className="subwf-card-desc">
                      Call another workflow from this workflow and receive its output items.
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {!showTrigger && !showAction && (
          <div className="hint" style={{ padding: '16px', textAlign: 'center' }}>
            No actions or triggers match “{search}”.
          </div>
        )}
      </div>
    </div>
  )
}
