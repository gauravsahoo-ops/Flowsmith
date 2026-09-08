import React from 'react'

export function NodeIcon({ type, icon, size = 34, color }) {
  const normalized = (type || '').toLowerCase()

  // 1. HTTP Request (Globe with latitude & longitude curves - exact n8n style)
  if (normalized === 'http_request' || normalized === 'http') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#60a5fa'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="2" y1="12" x2="22" y2="12" />
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
    )
  }

  // 2. If Condition (Branching arrows - exact n8n style)
  if (normalized === 'if_condition' || normalized === 'if') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#34d399'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5.5" x2="21" y2="5.5" />
        <polyline points="17 2 21 5.5 17 9" />
        <path d="M8 5.5v6.5a4 4 0 0 0 4 4h9" />
        <polyline points="17 12.5 21 16 17 19.5" />
      </svg>
    )
  }

  // 3. Loop Over Items / Split in Batches (Horizontal capsule loop with right-facing arrow - exact n8n style)
  if (
    normalized === 'loop_over_items' ||
    normalized === 'loop' ||
    normalized === 'split_in_batches' ||
    (normalized.includes('loop') && !normalized.includes('sub_workflow'))
  ) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#c084fc'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8a4.5 4.5 0 0 1 4 4.5 4.5 4.5 0 0 1-4.5 4.5H6.5A4.5 4.5 0 0 1 2 12.5a4.5 4.5 0 0 1 4.5-4.5h7.5" />
        <polyline points="10.5 5 14 8 10.5 11" />
      </svg>
    )
  }

  // 3b. Split Out (Horizontal one-to-four fork - exact n8n style)
  if (
    normalized === 'split_out' ||
    normalized === 'split' ||
    normalized.includes('split_out')
  ) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#8b5cf6'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="12" x2="8" y2="12" />
        <path d="M8 12c1.5 0 3-2 3-6h10" />
        <line x1="11" y1="10" x2="21" y2="10" />
        <line x1="11" y1="14" x2="21" y2="14" />
        <path d="M8 12c1.5 0 3 2 3 6h10" />
      </svg>
    )
  }

  // 4. Salesforce (Official cloud vector)
  if (normalized.includes('salesforce')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#00a1e0'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9z" />
        {normalized.includes('trigger') && <polygon points="12 8 9 13 13 13 11 17 15 11 11 11" fill={color || '#00a1e0'} stroke="none" />}
      </svg>
    )
  }

  // 5. Code (Laptop / Terminal script)
  if (normalized === 'code') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#fbbf24'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <line x1="2" y1="20" x2="22" y2="20" />
        <polyline points="7 8 10 11 7 14" />
        <line x1="12" y1="14" x2="16" y2="14" />
      </svg>
    )
  }

  // 6. Schedule (Clock / Timer dial)
  if (normalized === 'schedule') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    )
  }

  // 7. Manual Trigger (Play button)
  if (normalized === 'manual_trigger' || normalized === 'manual') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polygon points="10 8 16 12 10 16 10 8" fill={color || '#10b981'} />
      </svg>
    )
  }

  // 8. Webhook (Link / Plug)
  if (normalized === 'webhook') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#3b82f6'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
      </svg>
    )
  }

  // 9. Filter (Three horizontal centered descending lines - exact n8n style)
  if (normalized === 'filter') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5.5" x2="21" y2="5.5" />
        <line x1="6.5" y1="12" x2="17.5" y2="12" />
        <line x1="9.5" y1="18.5" x2="14.5" y2="18.5" />
      </svg>
    )
  }

  // 10. Set / Edit Data (Sliders / Properties)
  if (normalized === 'set_data' || normalized === 'set' || (normalized.includes('set') && !normalized.includes('dataset'))) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f43f5e'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="4" y1="21" x2="4" y2="14" />
        <line x1="4" y1="10" x2="4" y2="3" />
        <line x1="12" y1="21" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12" y2="3" />
        <line x1="20" y1="21" x2="20" y2="16" />
        <line x1="20" y1="12" x2="20" y2="3" />
        <line x1="1" y1="14" x2="7" y2="14" />
        <line x1="9" y1="8" x2="15" y2="8" />
        <line x1="17" y1="16" x2="23" y2="16" />
      </svg>
    )
  }

  // 11. Aggregate (Layers / Stacking blocks)
  if (normalized === 'aggregate') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#8b5cf6'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 2 7 12 12 22 7 12 2" />
        <polyline points="2 17 12 22 22 17" />
        <polyline points="2 12 12 17 22 12" />
      </svg>
    )
  }

  // 12. Database / SQL / Data Table
  if (normalized.includes('db') || normalized.includes('database') || normalized.includes('data_table')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#a855f7'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    )
  }

  // 13. CSV / JSON Transform (File convert arrows)
  if (normalized.includes('csv') || normalized.includes('transform')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#3b82f6'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 3 21 3 21 8" />
        <line x1="4" y1="20" x2="21" y2="3" />
        <polyline points="21 16 21 21 16 21" />
        <line x1="15" y1="15" x2="21" y2="21" />
        <line x1="4" y1="4" x2="9" y2="9" />
      </svg>
    )
  }

  // 14. GraphQL
  if (normalized === 'graphql') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#e10098'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 21 7.5 21 17.5 12 23 3 17.5 3 7.5 12 2" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    )
  }

  // 15. AI / AI Agent / RAG
  if (normalized.startsWith('ai') || normalized.includes('rag')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ec4899'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
      </svg>
    )
  }

  // 16. Send Email / Gmail
  if (normalized.includes('email') || normalized.includes('mail') || normalized === 'gmail') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ea4335'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="16" x="2" y="4" rx="2" />
        <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
      </svg>
    )
  }

  // 17. Slack / Chat / Telegram
  if (normalized === 'slack' || normalized === 'telegram') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    )
  }

  // 18. Human Approval
  if (normalized.includes('approval') || normalized.includes('human')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <polyline points="16 11 18 13 22 9" />
      </svg>
    )
  }

  // 19. Switch (Distributor spine routing into three right arrows - exact n8n style)
  if (normalized === 'switch') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#64d2ff'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5" x2="21" y2="5" />
        <polyline points="17 1.5 21 5 17 8.5" />
        <line x1="8" y1="5" x2="9.5" y2="12" />
        <line x1="9.5" y1="12" x2="21" y2="12" />
        <polyline points="17 8.5 21 12 17 15.5" />
        <path d="M9.5 12v2.5a4 4 0 0 0 4 4.5h7.5" />
        <polyline points="17 15.5 21 19 17 22.5" />
      </svg>
    )
  }

  // 20. Wait / Delay (Hourglass with top & bottom caps - exact n8n style)
  if (normalized === 'wait') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="5" y1="3" x2="19" y2="3" />
        <line x1="5" y1="21" x2="19" y2="21" />
        <path d="M6 3v4l4 5-4 5v4" />
        <path d="M18 3v4l-4 5 4 5v4" />
      </svg>
    )
  }

  // 21. Google Sheets / Sheets
  if (normalized.includes('sheet')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#0f9d58'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="18" height="18" x="3" y="3" rx="2" />
        <line x1="3" y1="9" x2="21" y2="9" />
        <line x1="3" y1="15" x2="21" y2="15" />
        <line x1="9" y1="3" x2="9" y2="21" />
      </svg>
    )
  }

  // 22. Google Calendar / Calendar
  if (normalized.includes('calendar')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#4285f4'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect width="18" height="18" x="3" y="4" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
      </svg>
    )
  }

  // 23. HubSpot
  if (normalized.includes('hubspot')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ff7a59'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="5" />
        <line x1="12" y1="1" x2="12" y2="7" />
        <line x1="12" y1="17" x2="12" y2="23" />
        <line x1="4.22" y1="4.22" x2="8.46" y2="8.46" />
        <line x1="15.54" y1="15.54" x2="19.78" y2="19.78" />
        <line x1="1" y1="12" x2="7" y2="12" />
        <line x1="17" y1="12" x2="23" y2="12" />
      </svg>
    )
  }

  // 24. Merge (Converging streams into single right arrow - exact n8n style)
  if (normalized === 'merge') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#06b6d4'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5.5" x2="21" y2="5.5" />
        <polyline points="17 2 21 5.5 17 9" />
        <path d="M3 16.5h4c3 0 4.5-5 5-11" />
      </svg>
    )
  }

  // 25. Pagination
  if (normalized === 'pagination') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#a855f7'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="14" height="14" x="3" y="3" rx="2" />
        <path d="M7 21h12a2 2 0 0 0 2-2V7" />
      </svg>
    )
  }

  // 26. When executed by Another Workflow (Right bracket with incoming arrow ->] - exact n8n style)
  if (
    normalized === 'execute_workflow_trigger' ||
    normalized === 'sub_workflow_trigger' ||
    normalized === 'when_executed_by_another_workflow' ||
    (normalized.includes('workflow') && normalized.includes('trigger'))
  ) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#cbd5e1'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="12" x2="14" y2="12" />
        <polyline points="9 7 14 12 9 17" />
        <path d="M17 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3" />
      </svg>
    )
  }

  // 27. Execute Sub-workflow (Left bracket / portal with entering/passing arrow - exact n8n style)
  if (normalized.includes('sub_workflow') || normalized === 'execute_sub_workflow') {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#fbbf24'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4" />
        <line x1="7" y1="12" x2="21" y2="12" />
        <polyline points="16 7 21 12 16 17" />
      </svg>
    )
  }

  // 27. Compare Datasets (Two interlocking/overlapping diagonal rings - exact n8n style)
  if (normalized === 'compare_datasets' || normalized.includes('compare')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="9" cy="9" r="6" />
        <circle cx="15" cy="15" r="6" />
      </svg>
    )
  }

  // 28. Stop and Error (Circle with diagonal prohibition slash - exact n8n style)
  if (normalized === 'stop_and_error' || normalized.includes('stop') || normalized.includes('error')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ef4444'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
      </svg>
    )
  }

  // 27. File / Storage / File I/O
  if (normalized.includes('file')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#94a3b8'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    )
  }

  // If user provided a custom emoji or character that is not a default placeholder
  if (icon && typeof icon === 'string' && icon.trim() && icon !== '🌐' && icon !== '🔌' && icon !== '•') {
    return (
      <span style={{ fontSize: size * 0.78, lineHeight: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
        {icon}
      </span>
    )
  }

  // Fallback: Default node symbol
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#94a3b8'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

export default NodeIcon
