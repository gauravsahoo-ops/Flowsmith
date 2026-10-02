import { Link } from 'react-router-dom'
import PageHeader from '../components/shared/PageHeader'

const DOCS = [
  { id: 'workflows', title: 'Workflow basics', desc: 'Visual canvas, nodes, connections, and DAG execution', to: '/workflows' },
  { id: 'expressions', title: 'Expressions & Syntax', desc: 'Use {{ $json }}, {{ $node.* }}, {{ $env.* }}, {{ $cred.* }}', to: '/variables' },
  { id: 'credentials', title: 'Credentials & Auth', desc: 'Encrypted at rest, injected securely as $cred', to: '/credentials' },
  { id: 'triggers', title: 'Triggers', desc: 'Manual triggers, webhook listeners, and cron schedules', to: '/workflows' },
  { id: 'executions', title: 'Executions & Console', desc: 'Timeline, step payload inspection, retry, and trace console', to: '/executions' },
  { id: 'variables', title: 'Variables & Environment', desc: 'Workspace-scoped variables, secret masking, and {{ $env.KEY }}', to: '/variables' },
  { id: 'templates', title: 'Templates Gallery', desc: 'Production-ready starter workflows and team sharing', to: '/templates' },
  { id: 'knowledge', title: 'RAG & Knowledge', desc: 'Vector collections, document chunking, and similarity search', to: '/knowledge' },
  { id: 'approvals', title: 'Human Approvals', desc: 'Pause execution for manual review before high-impact actions', to: '/approvals' },
  { id: 'monitoring', title: 'Monitoring & Health', desc: 'Queue throughput, worker concurrency, and system telemetry', to: '/monitoring' },
]

function renderDocIcon(id) {
  const props = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" }
  switch (id) {
    case 'workflows':
      return <svg {...props}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
    case 'expressions':
      return <svg {...props}><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>
    case 'credentials':
      return <svg {...props}><circle cx="7.5" cy="15.5" r="5.5" /><path d="M21 2l-9.6 9.6" /><path d="M15.5 7.5l3 3L22 7l-3-3" /></svg>
    case 'triggers':
      return <svg {...props}><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
    case 'executions':
      return <svg {...props}><circle cx="12" cy="12" r="10" /><polygon points="10 8 16 12 10 16 10 8" /></svg>
    case 'variables':
      return <svg {...props}><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>
    case 'templates':
      return <svg {...props}><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="9" y1="21" x2="9" y2="9" /></svg>
    case 'knowledge':
      return <svg {...props}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></svg>
    case 'approvals':
      return <svg {...props}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
    case 'monitoring':
      return <svg {...props}><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" /></svg>
    default:
      return null
  }
}

export default function HelpPage() {
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
  const mod = isMac ? '⌘' : 'Ctrl'

  return (
    <div className="page help-page">
      <PageHeader
        title="Help & Documentation"
        description="Documentation, keyboard shortcuts, and developer reference for Flowsmith."
      />

      <section className="help-grid">
        {DOCS.map(d => (
          <Link key={d.title} to={d.to} className="help-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <strong style={{ fontSize: 14, color: '#f8fafc' }}>{d.title}</strong>
              <span style={{ color: '#94a3b8', display: 'flex', alignItems: 'center' }}>{renderDocIcon(d.id)}</span>
            </div>
            <p className="hint" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, color: '#94a3b8' }}>{d.desc}</p>
          </Link>
        ))}
      </section>

      <section className="help-section-card">
        <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>Keyboard Shortcuts</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 260 }}>Shortcut</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">K</kbd>
                  </div>
                </td>
                <td>Global search & command palette</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">Z</kbd>
                    <span style={{ color: '#64748b', margin: '0 4px' }}>/</span>
                    <kbd className="kbd">Shift</kbd> <span>+</span> <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">Z</kbd>
                  </div>
                </td>
                <td>Undo / Redo canvas edits</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">C</kbd>
                    <span style={{ color: '#64748b', margin: '0 2px' }}>/</span>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">V</kbd>
                  </div>
                </td>
                <td>Copy & Paste selected nodes</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">D</kbd>
                  </div>
                </td>
                <td>Duplicate selection in-place</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">A</kbd>
                  </div>
                </td>
                <td>Select all canvas nodes</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">{mod}</kbd> <span>+</span> <kbd className="kbd">0</kbd>
                  </div>
                </td>
                <td>Fit canvas view</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <kbd className="kbd">Delete</kbd> <span style={{ color: '#64748b' }}>or</span> <kbd className="kbd">Backspace</kbd>
                  </div>
                </td>
                <td>Delete selected nodes and connections</td>
              </tr>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ color: '#94a3b8' }}>Drag from sidebar</span>
                  </div>
                </td>
                <td>Add new node to canvas</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="help-section-card">
        <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>Getting Started</h3>
        <ol className="hint" style={{ lineHeight: 1.8, paddingLeft: 20, margin: 0, fontSize: 13.5 }}>
          <li>Navigate to <Link to="/workflows" style={{ color: '#818cf8', fontWeight: 600 }}>Workflows</Link> → click <strong>＋ Create workflow</strong>.</li>
          <li>Drag nodes from the left palette onto the visual canvas and connect them with edges.</li>
          <li>Click any node to open the inspector dialog (Inputs → Parameters → Live outputs).</li>
          <li>Configure credentials in <Link to="/credentials" style={{ color: '#818cf8', fontWeight: 600 }}>Credentials</Link> for external services like Salesforce, Slack, or databases.</li>
          <li>Click <strong>▶ Run</strong> to execute your flow, monitor real-time node outputs, and inspect full traces in <Link to="/executions" style={{ color: '#818cf8', fontWeight: 600 }}>Executions</Link>.</li>
        </ol>
      </section>

      <section className="help-section-card">
        <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>API & Developer Support</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14 }}>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 16px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>Platform Health</div>
            <div><a href="/api/health" target="_blank" rel="noreferrer" style={{ color: '#38bdf8' }}>/api/health</a></div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 16px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>Prometheus Metrics</div>
            <div><code>/metrics</code> (authenticated)</div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 16px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>Cluster Monitoring</div>
            <div><Link to="/monitoring" style={{ color: '#10b981' }}>View Cluster Telemetry →</Link></div>
          </div>
        </div>
      </section>
      <section className="help-section-card">
        <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>About the Developer</h3>
        <p className="hint" style={{ margin: 0, fontSize: 13.5, lineHeight: 1.7 }}>
          Flowsmith was designed, architected, and developed from scratch by <strong>Gaurav</strong> — every layer,
          from the visual canvas and execution engine to OAuth, the credential vault, AI, and deployment, is original work.
        </p>
      </section>
    </div>
  )
}
