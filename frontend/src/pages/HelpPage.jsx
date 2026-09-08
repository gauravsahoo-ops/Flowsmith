import { Link } from 'react-router-dom'
import PageHeader from '../components/shared/PageHeader'

const DOCS = [
  { title: 'Workflow basics', desc: 'Visual canvas, nodes, connections, and DAG execution', to: '/workflows', icon: '⚡' },
  { title: 'Expressions & Syntax', desc: 'Use {{ $json }}, {{ $node.* }}, {{ $env.* }}, {{ $cred.* }}', to: '/variables', icon: '🧩' },
  { title: 'Credentials & Auth', desc: 'Encrypted at rest, injected securely as $cred', to: '/credentials', icon: '🔑' },
  { title: 'Triggers', desc: 'Manual triggers, webhook listeners, and cron schedules', to: '/workflows', icon: '⏰' },
  { title: 'Executions & Console', desc: 'Timeline, step payload inspection, retry, and trace console', to: '/executions', icon: '🕘' },
  { title: 'Variables & Environment', desc: 'Workspace-scoped variables, secret masking, and {{ $env.KEY }}', to: '/variables', icon: '🌍' },
  { title: 'Templates Gallery', desc: 'Production-ready starter workflows and team sharing', to: '/templates', icon: '📋' },
  { title: 'RAG & Knowledge', desc: 'Vector collections, document chunking, and similarity search', to: '/knowledge', icon: '📚' },
  { title: 'Human Approvals', desc: 'Pause execution for manual review before high-impact actions', to: '/approvals', icon: '✅' },
  { title: 'Monitoring & Health', desc: 'Queue throughput, worker concurrency, and system telemetry', to: '/monitoring', icon: '📊' },
]

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
              <span style={{ fontSize: 16 }}>{d.icon}</span>
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
    </div>
  )
}
