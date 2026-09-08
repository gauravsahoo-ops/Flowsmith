import { useState, useMemo } from 'react'

const INTERVAL_OPTIONS = [
  { value: 'seconds', label: 'Seconds', hint: 'Seconds Between Triggers', min: 1, max: 59 },
  { value: 'minutes', label: 'Minutes', hint: 'Minutes Between Triggers', min: 1, max: 59 },
  { value: 'hours', label: 'Hours', hint: 'Hours Between Triggers', min: 1, max: 23 },
  { value: 'days', label: 'Days', hint: 'Days Between Triggers', min: 1, max: 31 },
  { value: 'weeks', label: 'Weeks', hint: 'Weeks Between Triggers', min: 1, max: 52 },
  { value: 'months', label: 'Months', hint: 'Months Between Triggers', min: 1, max: 12 },
  { value: 'cron', label: 'Custom (Cron)', hint: 'Cron Expression', min: 1, max: 59 },
]

const TIMEZONES = ['UTC','America/New_York','America/Chicago','America/Los_Angeles','Europe/London','Europe/Berlin','Asia/Tokyo','Australia/Sydney']

function newRule(interval='minutes', value=5) {
  return { id: Math.random().toString(36).slice(2,10), interval, value, cron: interval==='cron' ? '*/5 * * * *' : undefined, timezone: 'UTC', collapsed: false }
}

function summary(rule) {
  if (rule.interval === 'cron') return `${rule.cron} (${rule.timezone})`
  const opt = INTERVAL_OPTIONS.find(o=>o.value===rule.interval)
  const label = opt ? opt.label.toLowerCase() : rule.interval
  return `Every ${rule.value} ${label}${rule.value>1?'s':''}`
}

export default function ScheduleTriggerEditor({ node, onParamsChange }) {
  const params = node.parameters || {}
  const rules = Array.isArray(params.rules) && params.rules.length ? params.rules : (params.cron ? [{ id: 'legacy', interval: 'cron', cron: params.cron, timezone: params.timezone||'UTC', value: 5 }] : [{ id: 'r1', interval: 'minutes', value: 5, timezone: 'UTC', collapsed: false }])

  const [collapsed, setCollapsed] = useState(() => {
    const m = {}
    rules.forEach((r,i)=> m[r.id] = !!r.collapsed)
    return m
  })

  function updateRules(next) {
    onParamsChange({ ...params, rules: next, cron: undefined, timezone: undefined })
  }

  function addRule() {
    const r = newRule('minutes', 5)
    updateRules([...rules, r])
    setCollapsed(c=> ({...c, [r.id]: false}))
  }

  function removeRule(id) {
    if (rules.length===1) return
    if (!confirm('Remove this trigger rule?')) return
    updateRules(rules.filter(r=> r.id!==id))
  }

  function toggleCollapse(id) {
    setCollapsed(c=> ({...c, [id]: !c[id]}))
    // persist collapsed flag
    updateRules(rules.map(r=> r.id===id ? {...r, collapsed: !collapsed[id]} : r))
  }

  function updateRule(id, patch) {
    const next = rules.map(r=> {
      if (r.id!==id) return r
      let nr = { ...r, ...patch }
      // Interval change: reset stale fields
      if (patch.interval && patch.interval !== r.interval) {
        if (patch.interval === 'cron') {
          nr.cron = r.cron || '*/5 * * * *'
          nr.timezone = r.timezone || 'UTC'
          delete nr.value
        } else {
          const opt = INTERVAL_OPTIONS.find(o=>o.value===patch.interval)
          nr.value = 5
          if (opt && nr.value < opt.min) nr.value = opt.min
          if (opt && nr.value > opt.max) nr.value = opt.max
          delete nr.cron
          // keep timezone but default UTC
          nr.timezone = r.timezone || 'UTC'
        }
      }
      return nr
    })
    updateRules(next)
  }

  return (
    <div className="st-editor">
      <div className="st-info banner-inline info" style={{fontSize:'12px', padding:'8px 10px', marginBottom:'12px'}}>
        This workflow will run on the schedule you define here once you publish it. For testing, you can also trigger it manually by going back to the canvas and clicking 'execute workflow'.
      </div>

      <div className="st-rules-head">
        <h4 style={{margin:0, fontSize:'13px', fontWeight:600}}>Trigger Rules</h4>
        <button type="button" className="ghost small st-add-icon" onClick={addRule} title="Add rule" aria-label="Add rule">+</button>
      </div>

      <div className="st-rules">
        {rules.map((rule, idx)=> {
          const isCollapsed = !!collapsed[rule.id]
          const opt = INTERVAL_OPTIONS.find(o=>o.value===rule.interval) || INTERVAL_OPTIONS[1]
          const isCron = rule.interval==='cron'
          let error = null
          if (!isCron) {
            if (rule.value==null || rule.value==='') error = 'Required'
            else if (rule.value < opt.min || rule.value > opt.max) error = `Must be in range ${opt.min}-${opt.max}`
          } else {
            if (!rule.cron) error = 'Cron required'
          }
          return (
            <div key={rule.id} className="st-rule">
              <button type="button" className="st-rule-head" onClick={()=>toggleCollapse(rule.id)} aria-expanded={!isCollapsed}>
                <span className="st-caret">{isCollapsed?'▸':'▾'}</span>
                <span className="st-rule-title">Trigger Interval {idx+1}</span>
                {isCollapsed && <span className="st-rule-summary">{summary(rule)}</span>}
                {rules.length>1 && (
                  <span className="st-rule-actions" onClick={e=>e.stopPropagation()}>
                    <button type="button" className="ghost small" onClick={()=>removeRule(rule.id)} title="Remove rule" aria-label="Remove rule">×</button>
                  </span>
                )}
              </button>
              {!isCollapsed && (
                <div className="st-rule-body">
                  <label>
                    <span>Trigger Interval <span className="required-badge">*</span></span>
                    <select value={rule.interval} onChange={e=>updateRule(rule.id, {interval: e.target.value})}>
                      {INTERVAL_OPTIONS.map(o=> <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </label>
                  {!isCron ? (
                    <label>
                      <span>{opt.hint} <span className="required-badge">*</span></span>
                      <input type="number" min={opt.min} max={opt.max} value={rule.value??''} onChange={e=>updateRule(rule.id, {value: e.target.value===''? '' : Number(e.target.value)})} />
                      {error && <span className="field-error">{error}</span>}
                    </label>
                  ) : (
                    <>
                      <label>
                        <span>Cron Expression <span className="required-badge">*</span></span>
                        <input type="text" value={rule.cron||''} onChange={e=>updateRule(rule.id, {cron: e.target.value})} placeholder="*/5 * * * *" />
                        {error && <span className="field-error">{error}</span>}
                      </label>
                      <label>
                        <span>Timezone <span className="required-badge">*</span></span>
                        <select value={rule.timezone||'UTC'} onChange={e=>updateRule(rule.id, {timezone: e.target.value})}>
                          {TIMEZONES.map(t=> <option key={t} value={t}>{t}</option>)}
                        </select>
                      </label>
                    </>
                  )}
                  {isCron && (
                    <label>
                      <span>Timezone</span>
                      <select value={rule.timezone||'UTC'} onChange={e=>updateRule(rule.id, {timezone: e.target.value})}>
                        {TIMEZONES.map(t=> <option key={t} value={t}>{t}</option>)}
                      </select>
                    </label>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <button type="button" className="ghost small st-add-rule" onClick={addRule} style={{marginTop:'8px'}}>+ Add Rule</button>
    </div>
  )
}
