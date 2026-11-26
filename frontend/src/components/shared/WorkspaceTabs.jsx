import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../../api'

const TABS = [
  { label: 'Workflows', path: '/workflows' },
  { label: 'Credentials', path: '/credentials' },
  { label: 'Executions', path: '/executions' },
  { label: 'Variables', path: '/variables' },
  { label: 'Data Tables', path: '/data-tables' },
  { label: 'Knowledge', path: '/knowledge' },
]

export default function WorkspaceTabs() {
  const [ragAvailable, setRagAvailable] = useState(null)

  useEffect(() => {
    let alive = true
    api.ragStatus()
      .then((res) => { if (alive) setRagAvailable(Boolean(res?.semantic_available)) })
      .catch(() => { if (alive) setRagAvailable(false) })
    return () => { alive = false }
  }, [])

  // Knowledge is hidden unless real semantic embeddings are installed.
  const tabs = TABS.filter((tab) => tab.path !== '/knowledge' || ragAvailable === true)

  return (
    <div className="workspace-tabs" role="tablist" aria-label="Workspace sections">
      {tabs.map(tab => (
        tab.disabled ? (
          <span key={tab.path} className="workspace-tab disabled" title={tab.title} aria-disabled="true">
            {tab.label} <span className="tab-badge">soon</span>
          </span>
        ) : (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) => `workspace-tab ${isActive ? 'active' : ''}`}
            role="tab"
            aria-selected={undefined}
          >
            {tab.label}
          </NavLink>
        )
      ))}
    </div>
  )
}
