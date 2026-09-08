import { NavLink } from 'react-router-dom'

const TABS = [
  { label: 'Workflows', path: '/workflows' },
  { label: 'Credentials', path: '/credentials' },
  { label: 'Executions', path: '/executions' },
  { label: 'Variables', path: '/variables' },
  { label: 'Data Tables', path: '/data-tables' },
  { label: 'Knowledge', path: '/knowledge' },
]

export default function WorkspaceTabs() {
  return (
    <div className="workspace-tabs" role="tablist" aria-label="Workspace sections">
      {TABS.map(tab => (
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
