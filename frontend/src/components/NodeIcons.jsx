import React from 'react'

/**
 * High-fidelity, official vector logos and icons for all Flowsmith nodes & connectors.
 * Supports exact brand logos (multi-color / brand palette) for all 45+ enterprise integrations
 * and clean, modern SVG icons for all 57+ flow and logic nodes.
 */
export function NodeIcon({ type, icon, size = 34, color }) {
  const t = (type || '').toLowerCase().trim()
  const ic = (icon || '').toLowerCase().trim()

  // Helper to check match across type, alias, or icon key
  const matches = (...keys) => {
    return keys.some((k) => t === k || t.includes(k) || ic === k || ic.includes(k))
  }

  // =========================================================================
  // 1. THIRD-PARTY CONNECTORS & SERVICE LOGOS (OFFICIAL BRAND MARKS)
  // =========================================================================

  // Slack (Official 4-color Octothorpe)
  if (matches('slack')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52-2.523c0-1.394 1.127-2.524 2.52-2.524h2.524v2.524c0 1.393-1.13 2.523-2.524 2.523z" fill="#E01E5A" />
        <path d="M8.834 15.165a2.528 2.528 0 0 1 2.524 2.524v2.52a2.528 2.528 0 0 1-2.524 2.525c-1.393 0-2.523-1.13-2.523-2.524v-2.52h2.523z" fill="#E01E5A" />
        <path d="M8.834 5.042a2.528 2.528 0 0 1 2.524-2.52c1.393 0 2.523 1.127 2.523 2.52v2.524H8.834V5.042z" fill="#36C5F0" />
        <path d="M8.834 8.834a2.528 2.528 0 0 1-2.523-2.524c0-1.393 1.13-2.524 2.523-2.524h2.524v5.048H8.834z" fill="#36C5F0" />
        <path d="M18.958 8.834a2.528 2.528 0 0 1 2.523 2.524c0 1.393-1.13 2.524-2.523 2.524h-2.524V8.834h2.524z" fill="#2EB67D" />
        <path d="M15.166 8.834a2.528 2.528 0 0 1-2.524-2.524V3.79a2.528 2.528 0 0 1 2.524-2.524c1.393 0 2.524 1.13 2.524 2.524v2.524h-2.524z" fill="#2EB67D" />
        <path d="M15.166 18.958a2.528 2.528 0 0 1-2.524 2.523c-1.393 0-2.524-1.13-2.524-2.523v-2.524h5.048v2.524z" fill="#ECB22E" />
        <path d="M15.166 15.166a2.528 2.528 0 0 1 2.524 2.523c0 1.394-1.13 2.524-2.524 2.524h-2.524v-5.047h2.524z" fill="#ECB22E" />
      </svg>
    )
  }

  // GitHub (Official Octocat Silhouette)
  if (matches('github')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
          fill="#FFFFFF"
        />
      </svg>
    )
  }

  // GitLab (Official Multi-tone Origami Fox)
  if (matches('gitlab')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M22.65 14.39L20.6 8.08c-.14-.42-.72-.42-.86 0L17.7 14.39H6.3L4.26 8.08c-.14-.42-.72-.42-.86 0L1.35 14.39c-.11.35.01.73.3.94l10.02 7.28c.2.15.46.15.66 0l10.02-7.28c.29-.21.41-.59.3-.94z" fill="#E24329" />
        <path d="M1.35 14.39L3.4 8.08c.14-.42.72-.42.86 0l2.04 6.31H1.35z" fill="#FC6D26" />
        <path d="M22.65 14.39L20.6 8.08c-.14-.42-.72-.42-.86 0l-2.04 6.31h4.09z" fill="#FC6D26" />
        <path d="M6.3 14.39l5.7 4.14 5.7-4.14H6.3z" fill="#FCA326" />
      </svg>
    )
  }

  // Bitbucket (Official Blue Bucket)
  if (matches('bitbucket')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M2.5 3.5c-.3 0-.5.2-.6.5l-1.8 14c-.1.3.1.6.4.7l10.8 2.3c.3.1.6 0 .8-.2l10.8-7.3c.3-.2.4-.5.3-.8l-2.7-8.7c-.1-.3-.3-.5-.6-.5H2.5zm8.8 11.2l-3.3-.7 1.2-5.7h5.3l-3.2 6.4z" fill="#2684FF" />
      </svg>
    )
  }

  // Salesforce (Official Cloud with optional Trigger Bolt)
  if (matches('salesforce')) {
    const isTrigger = matches('trigger')
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path
          d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9z"
          fill="#00A1E0"
        />
        {isTrigger ? (
          <polygon points="12 7 8 13 12.5 13 11 18 16 11 12 11" fill="#FFFFFF" />
        ) : (
          <path d="M10.8 9.2a3.8 3.8 0 0 1 5.4 0M8.5 11.5a6.5 6.5 0 0 1 9 0" stroke="#FFFFFF" strokeWidth="1.2" strokeLinecap="round" />
        )}
      </svg>
    )
  }

  // HubSpot (Official Sprocket)
  if (matches('hubspot')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="4.2" fill="#FF7A59" />
        <circle cx="12" cy="3.5" r="2.2" fill="#FF7A59" />
        <circle cx="20.5" cy="12" r="2.2" fill="#FF7A59" />
        <circle cx="12" cy="20.5" r="2.2" fill="#FF7A59" />
        <path d="M12 5.7v2.1M12 16.2v2.1M16.2 12h2.1" stroke="#FF7A59" strokeWidth="2" strokeLinecap="round" />
      </svg>
    )
  }

  // Jira (Official Dual-Diamond Flow)
  if (matches('jira')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M11.53 2c0 2.4-1.97 4.35-4.4 4.35H2.8v4.32h4.33c4.78 0 8.65-3.88 8.65-8.67H11.53z" fill="#0052CC" />
        <path d="M15.8 6.32c0 2.4-1.96 4.35-4.4 4.35H7.07v4.32h4.33c4.78 0 8.65-3.88 8.65-8.67H15.8z" fill="#2684FF" />
        <path d="M20.07 10.65c0 2.4-1.96 4.35-4.4 4.35h-4.33v4.32h4.33c4.78 0 8.65-3.88 8.65-8.67h-4.25z" fill="#0052CC" />
      </svg>
    )
  }

  // Notion (Official 'N' Mark)
  if (matches('notion')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#FFFFFF" />
        <path d="M6 6.5l3.2-.5 8 11.5V6.5L20 6v12l-3.2.5-8-11.5v11L6 18.5v-12z" fill="#000000" />
      </svg>
    )
  }

  // Airtable (Official Tri-Color Block)
  if (matches('airtable')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M11.2 3.2L3.1 7.4c-.6.3-.6 1.2 0 1.5l8.1 4.2c.5.3 1.1.3 1.6 0l8.1-4.2c.6-.3.6-1.2 0-1.5L12.8 3.2c-.5-.3-1.1-.3-1.6 0z" fill="#18BFFF" />
        <path d="M12.8 14.8v6c0 .6.6 1 1.1.8l7-3.7c.6-.3 1-.9 1-1.6V10.4l-9.1 4.4z" fill="#FCB400" />
        <path d="M11.2 14.8L2.1 10.4v5.9c0 .7.4 1.3 1 1.6l7 3.7c.5.2 1.1-.2 1.1-.8v-6z" fill="#ED3137" />
      </svg>
    )
  }

  // Trello (Official Blue Board)
  if (matches('trello')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#0079BF" />
        <rect x="5.5" y="5.5" width="5" height="11" rx="1.5" fill="#FFFFFF" />
        <rect x="13.5" y="5.5" width="5" height="7" rx="1.5" fill="#FFFFFF" />
      </svg>
    )
  }

  // Asana (Official 3 Coral Dots)
  if (matches('asana')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="7.5" r="4.2" fill="#F06A6A" />
        <circle cx="6.5" cy="16.5" r="4.2" fill="#F06A6A" />
        <circle cx="17.5" cy="16.5" r="4.2" fill="#F06A6A" />
      </svg>
    )
  }

  // Linear (Official Diamond Spiral)
  if (matches('linear')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M2.5 17.5L17.5 2.5M6.5 21.5L21.5 6.5M2 12a10 10 0 1 0 20 0 10 10 0 1 0-20 0z" stroke="#5E6AD2" strokeWidth="2.2" strokeLinecap="round" />
      </svg>
    )
  }

  // ClickUp (Official Chevron + Dot)
  if (matches('clickup')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M3.5 16.5l8.5-7 8.5 7" stroke="#7B68EE" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="12" cy="5" r="2.2" fill="#FF00DF" />
      </svg>
    )
  }

  // Monday.com (Official 3-Color Gauge)
  if (matches('monday')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="10" width="4" height="10" rx="2" fill="#FF3D57" />
        <rect x="10" y="6" width="4" height="14" rx="2" fill="#FFCC00" />
        <rect x="17" y="4" width="4" height="16" rx="2" fill="#00C875" />
      </svg>
    )
  }

  // Todoist (Official Red Chevrons)
  if (matches('todoist')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#E44332" />
        <path d="M6 13l4 4 8-8M6 8l4 4 8-8" stroke="#FFFFFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  // Microsoft Teams (Official Purple T-Badge)
  if (matches('msteams', 'teams')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="7" y="4" width="14" height="16" rx="3" fill="#6264A7" />
        <rect x="3" y="7" width="10" height="10" rx="2.5" fill="#464775" />
        <path d="M6.5 10.5h3M8 10.5v4" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="16" cy="8" r="1.8" fill="#8B8CC7" />
        <path d="M13.5 15a2.5 2.5 0 0 1 5 0" stroke="#8B8CC7" strokeWidth="1.6" />
      </svg>
    )
  }

  // Microsoft Outlook (Official Blue Envelope + 'O')
  if (matches('outlook')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="7" y="4" width="14" height="16" rx="2" fill="#0078D4" />
        <path d="M7 6l7 5 7-5" stroke="#FFFFFF" strokeWidth="1.4" fill="none" />
        <rect x="3" y="7" width="9" height="10" rx="2" fill="#106EBE" />
        <circle cx="7.5" cy="12" r="2.5" stroke="#FFFFFF" strokeWidth="1.8" fill="none" />
      </svg>
    )
  }

  // Discord (Official Clyde Game Controller)
  if (matches('discord')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path
          d="M19.3 5.3a15.7 15.7 0 0 0-3.9-1.2.1.1 0 0 0-.1.1 10.9 10.9 0 0 0-.5 1 14.5 14.5 0 0 0-5.6 0 11.5 11.5 0 0 0-.5-1 .1.1 0 0 0-.1-.1 15.6 15.6 0 0 0-3.9 1.2.1.1 0 0 0-.1.1C2.3 8.8 1.7 12.2 2 15.6a.1.1 0 0 0 .1.1 15.8 15.8 0 0 0 4.8 2.4.1.1 0 0 0 .1 0 11.3 11.3 0 0 0 1-1.6.1.1 0 0 0-.1-.1 10.4 10.4 0 0 1-1.5-.7.1.1 0 0 1 0-.2c.1-.1.2-.2.3-.3a11.3 11.3 0 0 0 10.6 0c.1.1.2.2.3.3a.1.1 0 0 1 0 .2 10.2 10.2 0 0 1-1.5.7.1.1 0 0 0-.1.1 11.7 11.7 0 0 0 1 1.6.1.1 0 0 0 .1 0 15.7 15.7 0 0 0 4.8-2.4.1.1 0 0 0 .1-.1c.4-4-.7-7.4-2.7-10.4a.1.1 0 0 0-.1-.1zM8.5 13.5c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5zm7 0c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5z"
          fill="#5865F2"
        />
      </svg>
    )
  }

  // Twilio (Official Red Badge with 4 Dots)
  if (matches('twilio')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#F22F46" />
        <circle cx="9" cy="9" r="2" fill="#FFFFFF" />
        <circle cx="15" cy="9" r="2" fill="#FFFFFF" />
        <circle cx="9" cy="15" r="2" fill="#FFFFFF" />
        <circle cx="15" cy="15" r="2" fill="#FFFFFF" />
      </svg>
    )
  }

  // WhatsApp (Official Green Phone Speech Bubble)
  if (matches('whatsapp')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#25D366" />
        <path
          d="M17.5 14.4c-.3-.1-1.7-.8-2-1-.2-.1-.4-.1-.6.1-.2.3-.7 1-.9 1.1-.2.2-.3.2-.6.1-.3-.1-1.3-.5-2.5-1.5-.9-.8-1.5-1.8-1.7-2.1-.2-.3 0-.5.1-.6.1-.1.3-.4.5-.5.1-.2.2-.3.3-.5.1-.2 0-.4 0-.5-.1-.2-.6-1.5-.8-2.1-.2-.6-.5-.5-.6-.5h-.5c-.2 0-.6.1-.9.4-.3.3-1.1 1.1-1.1 2.6 0 1.6 1.1 3.1 1.3 3.3.2.2 2.2 3.4 5.5 4.7.8.3 1.4.5 1.9.7.8.2 1.5.2 2.1.1.6-.1 1.9-.8 2.2-1.5.3-.8.3-1.4.2-1.6-.1-.2-.3-.3-.6-.4z"
          fill="#FFFFFF"
        />
      </svg>
    )
  }

  // Zoom (Official Blue Video Camera)
  if (matches('zoom')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="5" fill="#2D8CFF" />
        <rect x="5.5" y="7.5" width="8" height="9" rx="1.5" fill="#FFFFFF" />
        <polygon points="14.5 10 18.5 7.5 18.5 16.5 14.5 14" fill="#FFFFFF" />
      </svg>
    )
  }

  // OpenAI (Official Rosette Swirl)
  if (matches('openai')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path
          d="M21.2 9.8a5.5 5.5 0 0 0-.5-4.4 5.6 5.6 0 0 0-5.3-2.7 5.7 5.7 0 0 0-4.1 1.8 5.6 5.6 0 0 0-4.4.5A5.6 5.6 0 0 0 4.2 10a5.6 5.6 0 0 0 .5 4.4 5.6 5.6 0 0 0 5.3 2.7 5.7 5.7 0 0 0 4.1-1.8 5.6 5.6 0 0 0 4.4-.5 5.6 5.6 0 0 0 2.7-5z"
          stroke="#10A37F"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="12" cy="12" r="2.5" fill="#10A37F" />
      </svg>
    )
  }

  // Stripe (Official Bold 'S' Badge)
  if (matches('stripe')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#635BFF" />
        <path
          d="M13.8 8.8c0-.7-.6-1.1-1.6-1.1-1.4 0-2.8.5-3.8 1.1l-.6-2.3c1.3-.6 3-1 4.7-1 3.2 0 5.3 1.6 5.3 4.3 0 4.1-5.7 3.5-5.7 5.3 0 .8.7 1.2 1.8 1.2 1.6 0 3.3-.6 4.3-1.3l.6 2.4c-1.3.7-3.2 1.1-5.1 1.1-3.3 0-5.6-1.6-5.6-4.3 0-4.4 5.7-3.7 5.7-5.4z"
          fill="#FFFFFF"
        />
      </svg>
    )
  }

  // Shopify (Official Green Shopping Bag + 'S')
  if (matches('shopify')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M18.8 5.5l-2.1-.6s-1.4-1.4-2.1-1.4c-.6 0-1.2.3-1.6 1.4L6 6.3c-.6.2-.8.6-.7 1.2l2.4 12.8c.1.7.7 1.2 1.4 1.2h6.5c.7 0 1.3-.5 1.4-1.2l2-13.6c.1-.6-.2-1-.6-1.2z" fill="#95BF47" />
        <path d="M13 3.5c-.5 0-1 .4-1.3 1.2l-.3 1.4 2.8.8.2-1.8c0-.9-.5-1.6-1.4-1.6z" fill="#5E8E3E" />
        <path d="M12.5 11c-.8 0-1.4.5-1.4 1.1 0 1.2 2 1.4 2 2.5 0 .6-.5 1-1.2 1-.9 0-1.8-.4-2.2-.8l-.3 1.3c.6.4 1.6.7 2.4.7 1.6 0 2.6-.9 2.6-2.2 0-1.4-2-1.7-2-2.5 0-.5.4-.8 1-.8.7 0 1.4.3 1.8.6l.4-1.3c-.6-.4-1.3-.6-2.1-.6z" fill="#FFFFFF" />
      </svg>
    )
  }

  // QuickBooks (Official Green 'qb')
  if (matches('quickbooks')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#2CA01C" />
        <path d="M9.5 8a3.5 3.5 0 0 0-3.5 3.5v1A3.5 3.5 0 0 0 9.5 16h1v-2h-1a1.5 1.5 0 0 1-1.5-1.5v-1A1.5 1.5 0 0 1 9.5 10h1V8h-1zm5 0h-1v2h1a1.5 1.5 0 0 1 1.5 1.5v1A1.5 1.5 0 0 1 14.5 14h-1v2h1a3.5 3.5 0 0 0 3.5-3.5v-1A3.5 3.5 0 0 0 14.5 8z" fill="#FFFFFF" />
      </svg>
    )
  }

  // Dropbox (Official 5-Diamond Open Box)
  if (matches('dropbox')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <polygon points="6 3 12 7 6 11 0 7" fill="#0061FF" />
        <polygon points="18 3 24 7 18 11 12 7" fill="#0061FF" />
        <polygon points="6 15 12 19 6 23 0 19" fill="#0061FF" />
        <polygon points="18 15 24 19 18 23 12 19" fill="#0061FF" />
        <polygon points="12 11.5 18 15.5 12 19.5 6 15.5" fill="#0061FF" />
      </svg>
    )
  }

  // Calendly (Official 'C' Circle)
  if (matches('calendly')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#006BFF" />
        <path d="M15.5 8.5A5 5 0 1 0 16 15" stroke="#FFFFFF" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    )
  }

  // Zendesk (Official Geometric Z)
  if (matches('zendesk')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M12 3a9 9 0 0 0-9 9h9V3z" fill="#03363D" />
        <path d="M12 21a9 9 0 0 0 9-9h-9v9z" fill="#03363D" />
        <circle cx="6.5" cy="17.5" r="3.5" fill="#03363D" />
        <circle cx="17.5" cy="6.5" r="3.5" fill="#03363D" />
      </svg>
    )
  }

  // Freshdesk (Official Leaf Clover)
  if (matches('freshdesk')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="5" fill="#1F9A85" />
        <path d="M12 6a4 4 0 0 1 4 4c0 3-4 6-4 6s-4-3-4-6a4 4 0 0 1 4-4z" fill="#FFFFFF" />
        <circle cx="12" cy="10" r="1.5" fill="#1F9A85" />
      </svg>
    )
  }

  // PagerDuty (Official Green 'P')
  if (matches('pagerduty')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#06AC38" />
        <path d="M7 6h5.5a4.5 4.5 0 0 1 0 9H10v3H7V6zm3 6h2.5a1.5 1.5 0 0 0 0-3H10v3z" fill="#FFFFFF" />
      </svg>
    )
  }

  // Mailchimp (Official Freddie Chimp)
  if (matches('mailchimp')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#FFE01B" />
        <path d="M7 11.5c.5-2 2.5-3.5 5-3.5s4.5 1.5 5 3.5" stroke="#000000" strokeWidth="2" strokeLinecap="round" />
        <circle cx="9.5" cy="12" r="1" fill="#000000" />
        <circle cx="14.5" cy="12" r="1" fill="#000000" />
        <path d="M9 15c1 1.5 2 2 3 2s2-.5 3-2" stroke="#000000" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    )
  }

  // Brevo (Official Teal Leaf)
  if (matches('brevo')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#0B996F" />
        <path d="M12 6c3.5 0 6 2.5 6 6 0 3.5-2.5 6-6 6-2 0-4-1-5-2.5l5-3.5-5-3.5C8 7 10 6 12 6z" fill="#FFFFFF" />
      </svg>
    )
  }

  // Pipedrive (Official Green 'P')
  if (matches('pipedrive')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#00AC3E" />
        <path d="M9 7h4a3.5 3.5 0 0 1 0 7h-2v4H9V7zm2 5h2a1.5 1.5 0 0 0 0-3h-2v3z" fill="#FFFFFF" />
      </svg>
    )
  }

  // Google Drive (Official Tri-Color Triangle)
  if (matches('google_drive', 'drive')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M8.2 3.8h7.6l6.2 10.7-3.8 6.5H10.6L8.2 3.8z" fill="#FFBB00" />
        <path d="M15.8 3.8l6.2 10.7-3.8 6.5-6.2-10.7 3.8-6.5z" fill="#4285F4" />
        <path d="M2 14.5l3.8-6.5 7.6 13H5.8L2 14.5z" fill="#0F9D58" />
      </svg>
    )
  }

  // Google Sheets (Official Spreadsheet Mark)
  if (matches('google_sheets', 'sheet')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="2" width="18" height="20" rx="3" fill="#0F9D58" />
        <path d="M15 2l6 6h-6V2z" fill="#87CEAB" />
        <rect x="7" y="10" width="10" height="2" rx="0.5" fill="#FFFFFF" />
        <rect x="7" y="14" width="10" height="2" rx="0.5" fill="#FFFFFF" />
        <line x1="11" y1="10" x2="11" y2="16" stroke="#0F9D58" strokeWidth="1.2" />
      </svg>
    )
  }

  // Google Calendar (Official Calendar Mark)
  if (matches('google_calendar', 'calendar')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="3" width="18" height="18" rx="3" fill="#4285F4" />
        <rect x="3" y="3" width="18" height="6" rx="1" fill="#EA4335" />
        <rect x="6" y="12" width="4" height="4" rx="1" fill="#FFFFFF" />
        <rect x="14" y="12" width="4" height="4" rx="1" fill="#FBBC04" />
      </svg>
    )
  }

  // Google Docs (Official Blue Page)
  if (matches('google_docs', 'docs')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="4" y="2" width="16" height="20" rx="2.5" fill="#4285F4" />
        <path d="M14 2l6 6h-6V2z" fill="#A1C2FA" />
        <rect x="7" y="11" width="10" height="1.8" rx="0.9" fill="#FFFFFF" />
        <rect x="7" y="14.5" width="10" height="1.8" rx="0.9" fill="#FFFFFF" />
        <rect x="7" y="18" width="6" height="1.8" rx="0.9" fill="#FFFFFF" />
      </svg>
    )
  }

  // Gmail (Official Red/White/Blue Envelope)
  if (matches('gmail')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect x="2" y="4" width="20" height="16" rx="3" fill="#FFFFFF" />
        <path d="M2 6l10 7 10-7v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6z" fill="#EA4335" opacity="0.15" />
        <path d="M2 6l10 7 10-7" stroke="#EA4335" strokeWidth="2.2" strokeLinecap="round" />
        <path d="M2 6v12a2 2 0 0 0 2 2h2V11L2 6z" fill="#4285F4" />
        <path d="M22 6v12a2 2 0 0 1-2 2h-2V11l4-5z" fill="#34A853" />
      </svg>
    )
  }

  // PostgreSQL (Official Blue Elephant Silhouette)
  if (matches('postgres', 'postgresql')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#336791" />
        <path
          d="M17.5 12.5c0-3-2.5-5.5-5.5-5.5-2.5 0-4.5 1.5-5.2 3.5-.8 0-1.8.5-1.8 1.5 0 .8.5 1.5 1.5 1.5v3.5h2v-2h2v2h2v-3.5c1.5-.5 3-2 3-4.5z"
          fill="#FFFFFF"
        />
        <circle cx="10" cy="10.5" r="0.9" fill="#336791" />
      </svg>
    )
  }

  // MySQL (Official Dolphin / Blue-Orange)
  if (matches('mysql')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#00758F" />
        <path
          d="M6 14.5c2-4.5 6-7 11.5-6.5-.5 2.5-2 4.5-4 5.5l1.5 3.5c-2.5-.5-4.5-1.5-5.5-3.5-1 1-2 1.5-3.5 1z"
          fill="#F29111"
        />
        <circle cx="15.5" cy="10" r="0.8" fill="#FFFFFF" />
      </svg>
    )
  }

  // MongoDB (Official Green Leaf)
  if (matches('mongodb', 'mongo')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M12 2C12 2 6 8.5 6 13.5c0 3.3 2.7 6 6 6.5V2z" fill="#13AA52" />
        <path d="M12 2c0 0 6 6.5 6 11.5 0 3.3-2.7 6-6 6.5V2z" fill="#00ED64" />
        <path d="M12 18.5v3.5" stroke="#13AA52" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  // Redis (Official Red 3D Database Cube)
  if (matches('redis')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <polygon points="12 2 21 6.5 12 11 3 6.5" fill="#DC382D" />
        <polygon points="3 7.5 12 12 12 21.5 3 17" fill="#A82820" />
        <polygon points="21 7.5 12 12 12 21.5 21 17" fill="#8F221B" />
        <circle cx="12" cy="6.5" r="1.5" fill="#FFFFFF" opacity="0.6" />
      </svg>
    )
  }

  // Supabase (Official Emerald Green Bolt)
  if (matches('supabase')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#1C1C1C" />
        <path d="M12.5 3.5L5.5 13.5h6l-1 7 7-10h-6l1-7z" fill="#3ECF8E" />
      </svg>
    )
  }

  // Resend (Official Modern Fast-Forward Mark)
  if (matches('resend')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#000000" />
        <path d="M6 7.5L14 12L6 16.5V7.5Z" fill="#FFFFFF" />
        <path d="M12 7.5L20 12L12 16.5V7.5Z" fill="#FFFFFF" opacity="0.6" />
      </svg>
    )
  }

  // Pinecone (Official Vector Mesh / Pinecone Icon)
  if (matches('pinecone')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#0A0F1D" />
        <path d="M12 4L18 8V16L12 20L6 16V8L12 4Z" stroke="#00FFE0" strokeWidth="1.5" />
        <circle cx="12" cy="8" r="1.5" fill="#00FFE0" />
        <circle cx="8.5" cy="12" r="1.5" fill="#00FFE0" />
        <circle cx="15.5" cy="12" r="1.5" fill="#00FFE0" />
        <circle cx="12" cy="16" r="1.5" fill="#00FFE0" />
        <line x1="12" y1="8" x2="8.5" y2="12" stroke="#00FFE0" strokeWidth="1.2" />
        <line x1="12" y1="8" x2="15.5" y2="12" stroke="#00FFE0" strokeWidth="1.2" />
        <line x1="8.5" y1="12" x2="12" y2="16" stroke="#00FFE0" strokeWidth="1.2" />
        <line x1="15.5" y1="12" x2="12" y2="16" stroke="#00FFE0" strokeWidth="1.2" />
      </svg>
    )
  }

  // Sentry (Official Stylized S Wireframe Knot)
  if (matches('sentry')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#362D59" />
        <path
          d="M13.1 5.2a6.8 6.8 0 0 0-4.6 2.4c-1.8 2.2-2.1 5.3-.8 7.8l-1.9 3.3c-2.3-3.6-1.8-8.4.9-11.4a10.5 10.5 0 0 1 7.2-3.8l-.8 1.7zm4.2 2.6c2.3 3.6 1.8 8.4-.9 11.4a10.5 10.5 0 0 1-7.2 3.8l.8-1.7a6.8 6.8 0 0 0 4.6-2.4c1.8-2.2 2.1-5.3.8-7.8l1.9-3.3z"
          fill="#FF385C"
        />
        <circle cx="12" cy="12" r="2.2" fill="#FFFFFF" />
      </svg>
    )
  }

  // AWS S3 / Object Store (Official S3 Bucket & Cloud Mark)
  if (matches('s3', 'aws_s3', 'aws', 'object_store', 'minio')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#232F3E" />
        <path d="M6 8.5L12 5L18 8.5V15.5L12 19L6 15.5V8.5Z" stroke="#FF9900" strokeWidth="1.5" fill="#FF9900" fillOpacity="0.2" />
        <path d="M12 5V19M6 8.5L18 15.5M18 8.5L6 15.5" stroke="#FF9900" strokeWidth="1.2" />
      </svg>
    )
  }

  // CoinGecko (Official Green Gecko Face)
  if (matches('coin_gecko', 'coingecko')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#8DC63F" />
        <circle cx="8.5" cy="10" r="2.8" fill="#FFFFFF" />
        <circle cx="15.5" cy="10" r="2.8" fill="#FFFFFF" />
        <circle cx="9" cy="10" r="1.4" fill="#231F20" />
        <circle cx="15" cy="10" r="1.4" fill="#231F20" />
        <path d="M8.5 15.5c2 1.5 5 1.5 7 0" stroke="#231F20" strokeWidth="1.5" strokeLinecap="round" />
        <ellipse cx="12" cy="13.5" rx="1.5" ry="0.8" fill="#FFF200" />
      </svg>
    )
  }

  // Frankfurter / Currency Exchange
  if (matches('frankfurter', 'fx', 'currency')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#003399" />
        <path d="M7 9h6M7 12h4M7 7v10" stroke="#FFCC00" strokeWidth="2" strokeLinecap="round" />
        <path d="M14 15l3-3m0 0l-3-3m3 3h-5" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  // Open-Meteo / Weather (Air Quality, Flood, Marine, Historical Weather)
  if (matches('open_meteo', 'weather', 'climate', 'meteo', 'flood', 'marine', 'air_quality')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="10" cy="9" r="4.5" fill="#FFB300" />
        <path
          d="M7 17a4 4 0 0 1-.2-8 5.5 5.5 0 0 1 10.7-1.5A4.5 4.5 0 0 1 18 17H7z"
          fill="#4285F4"
        />
        <line x1="9" y1="19" x2="8" y2="21" stroke="#38BDF8" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="13" y1="19" x2="12" y2="21" stroke="#38BDF8" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="17" y1="19" x2="16" y2="21" stroke="#38BDF8" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  // Open Notify ISS (Satellite Orbit)
  if (matches('open_notify', 'iss', 'satellite')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#0B132B" />
        <circle cx="12" cy="12" r="5" stroke="#48CAE4" strokeWidth="1.5" strokeDasharray="2 2" />
        <rect x="9.5" y="9.5" width="5" height="5" rx="1" fill="#0077B6" />
        <rect x="5" y="10.5" width="3.5" height="3" fill="#90E0EF" />
        <rect x="15.5" y="10.5" width="3.5" height="3" fill="#90E0EF" />
      </svg>
    )
  }

  // OpenRouter (Multi-Model AI Gateway)
  if (matches('open_router', 'openrouter')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#18181B" />
        <circle cx="6" cy="12" r="2.5" fill="#6366F1" />
        <circle cx="18" cy="7" r="2.5" fill="#EC4899" />
        <circle cx="18" cy="17" r="2.5" fill="#10B981" />
        <path d="M8.5 12h3m0 0l4-5m-4 5l4 5" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    )
  }

  // PokeAPI / Pokemon (Official Pokéball)
  if (matches('poke_api', 'pokemon', 'pokeapi')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#FFFFFF" stroke="#232323" strokeWidth="1.5" />
        <path d="M2 12a10 10 0 0 1 20 0H2z" fill="#EE1515" />
        <line x1="2" y1="12" x2="22" y2="12" stroke="#232323" strokeWidth="2" />
        <circle cx="12" cy="12" r="3.5" fill="#FFFFFF" stroke="#232323" strokeWidth="1.8" />
        <circle cx="12" cy="12" r="1.5" fill="#232323" />
      </svg>
    )
  }

  // Developer REST APIs (DummyJSON, JSONPlaceholder, Httpbin)
  if (matches('dummy_json', 'dummyjson', 'json_placeholder', 'jsonplaceholder', 'httpbin')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#0284C7" />
        <text x="12" y="16" fill="#FFFFFF" fontSize="11" fontWeight="bold" textAnchor="middle" fontFamily="monospace">
          {'{ }'}
        </text>
      </svg>
    )
  }

  // Single Sign-On (SSO / OIDC / Google SSO / GitHub SSO)
  if (matches('sso', 'oidc', 'saml', 'identity')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <rect width="20" height="20" x="2" y="2" rx="4" fill="#3B82F6" />
        <path d="M12 5l6 2.5v4.5c0 4-2.5 7-6 8-3.5-1-6-4-6-8V7.5L12 5z" fill="#1D4ED8" stroke="#FFFFFF" strokeWidth="1.2" />
        <circle cx="12" cy="11" r="1.8" fill="#FFFFFF" />
        <path d="M12 12.8v2.5M10.8 14.5h2.4" stroke="#FFFFFF" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    )
  }

  // =========================================================================
  // 2. FLOW & CORE LOGIC NODES (PRECISION VECTOR ARCHITECTURE)
  // =========================================================================

  // HTTP Request (Globe with Coordinates)
  if (matches('http_request', 'http')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="2" y1="12" x2="22" y2="12" />
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
    )
  }

  // Code / Sandbox (Terminal Script </>)
  if (matches('code', 'script')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#fbbf24'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2.5" />
        <line x1="2" y1="20" x2="22" y2="20" />
        <polyline points="7 8 10 11 7 14" />
        <line x1="12" y1="14" x2="16" y2="14" />
      </svg>
    )
  }

  // If Condition (Branching Fork)
  if (matches('if_condition', 'if')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#34d399'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5.5" x2="21" y2="5.5" />
        <polyline points="17 2 21 5.5 17 9" />
        <path d="M8 5.5v6.5a4 4 0 0 0 4 4h9" />
        <polyline points="17 12.5 21 16 17 19.5" />
      </svg>
    )
  }

  // Switch (Multi-Way Distributor)
  if (matches('switch')) {
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

  // Loop / Split in Batches (Capsule Loop)
  if (matches('loop', 'loop_over_items', 'loop_while', 'split_in_batches')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#c084fc'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8a4.5 4.5 0 0 1 4 4.5 4.5 4.5 0 0 1-4.5 4.5H6.5A4.5 4.5 0 0 1 2 12.5a4.5 4.5 0 0 1 4.5-4.5h7.5" />
        <polyline points="10.5 5 14 8 10.5 11" />
      </svg>
    )
  }

  // Split / Split Out (1-to-N Fork)
  if (matches('split', 'split_out')) {
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

  // Merge (Stream Convergence)
  if (matches('merge')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#06b6d4'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5.5" x2="21" y2="5.5" />
        <polyline points="17 2 21 5.5 17 9" />
        <path d="M3 16.5h4c3 0 4.5-5 5-11" />
      </svg>
    )
  }

  // Filter (Precision Funnel)
  if (matches('filter')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="5.5" x2="21" y2="5.5" />
        <line x1="6.5" y1="12" x2="17.5" y2="12" />
        <line x1="9.5" y1="18.5" x2="14.5" y2="18.5" />
      </svg>
    )
  }

  // Set Data / Edit Properties (Sliders)
  if (matches('set_data', 'set') && !matches('dataset')) {
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

  // Aggregate (Layer Stacking)
  if (matches('aggregate')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#8b5cf6'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 2 7 12 12 22 7 12 2" />
        <polyline points="2 17 12 22 22 17" />
        <polyline points="2 12 12 17 22 12" />
      </svg>
    )
  }

  // Compare Datasets (Venn Overlap)
  if (matches('compare_datasets', 'compare')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="9" cy="9" r="6" />
        <circle cx="15" cy="15" r="6" />
      </svg>
    )
  }

  // Data Table (Relational Grid)
  if (matches('data_table', 'table')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#a855f7'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <line x1="3" y1="9" x2="21" y2="9" />
        <line x1="3" y1="15" x2="21" y2="15" />
        <line x1="9" y1="3" x2="9" y2="21" />
      </svg>
    )
  }

  // Database Query (Cylinder Store)
  if (matches('database_query', 'database', 'db')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#bf5af2'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    )
  }

  // Error Trigger (Alert Triangle with Warning)
  if (matches('error_trigger', 'error_handler')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ef4444'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    )
  }

  // Manual Trigger (Play Icon)
  if (matches('manual_trigger', 'manual')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polygon points="10 8 16 12 10 16 10 8" fill={color || '#10b981'} />
      </svg>
    )
  }

  // Schedule Trigger (Clock Timer)
  if (matches('schedule', 'cron')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    )
  }

  // Webhook Trigger (Link Chains)
  if (matches('webhook') && !matches('respond')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#3b82f6'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
      </svg>
    )
  }

  // Respond to Webhook (Return Arrow)
  if (matches('respond_to_webhook')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#3b82f6'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="9 10 4 15 9 20" />
        <path d="M20 4v7a4 4 0 0 1-4 4H4" />
      </svg>
    )
  }

  // Form Trigger (Checklist)
  if (matches('form_trigger', 'form')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <line x1="8" y1="8" x2="16" y2="8" />
        <line x1="8" y1="12" x2="16" y2="12" />
        <line x1="8" y1="16" x2="12" y2="16" />
      </svg>
    )
  }

  // Chat Trigger (Dialog Bubbles)
  if (matches('chat_trigger', 'chat')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        <circle cx="8" cy="10" r="1" fill="currentColor" />
        <circle cx="12" cy="10" r="1" fill="currentColor" />
        <circle cx="16" cy="10" r="1" fill="currentColor" />
      </svg>
    )
  }

  // Execute Workflow Trigger (Incoming Bracket)
  if (matches('execute_workflow_trigger', 'sub_workflow_trigger', 'when_executed_by_another_workflow')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#cbd5e1'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="12" x2="14" y2="12" />
        <polyline points="9 7 14 12 9 17" />
        <path d="M17 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3" />
      </svg>
    )
  }

  // Sub Workflow (Outgoing Sub-Process Portal)
  if (matches('sub_workflow', 'execute_sub_workflow')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#fbbf24'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4" />
        <line x1="7" y1="12" x2="21" y2="12" />
        <polyline points="16 7 21 12 16 17" />
      </svg>
    )
  }

  // Wait / Delay (Hourglass)
  if (matches('wait', 'delay')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="5" y1="3" x2="19" y2="3" />
        <line x1="5" y1="21" x2="19" y2="21" />
        <path d="M6 3v4l4 5-4 5v4" />
        <path d="M18 3v4l-4 5 4 5v4" />
      </svg>
    )
  }

  // Stop and Error (Halt Barrier)
  if (matches('stop_and_error', 'stop', 'error')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ef4444'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
      </svg>
    )
  }

  // Human Approval (User Review)
  if (matches('human_approval', 'approval', 'human')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <polyline points="16 11 18 13 22 9" />
      </svg>
    )
  }

  // Noop (Pass-Through Skip)
  if (matches('noop')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#64748b'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="5 4 15 12 5 20 5 4" fill="currentColor" opacity="0.3" />
        <line x1="19" y1="5" x2="19" y2="19" />
      </svg>
    )
  }

  // AI LLM Completion (Intelligence Star Sparkle)
  if (t === 'ai' || (t.includes('ai') && !t.includes('agent') && !t.includes('airtable'))) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ec4899'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2l2.4 6.8L21 12l-6.6 3.2L12 22l-2.4-6.8L3 12l6.6-3.2L12 2z" />
      </svg>
    )
  }

  // AI Agent (Robot Head / ReAct Agent)
  if (matches('ai_agent', 'agent')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f43f5e'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="10" rx="2" />
        <circle cx="12" cy="5" r="2" />
        <path d="M12 7v4" />
        <line x1="8" y1="16" x2="8" y2="16" />
        <line x1="16" y1="16" x2="16" y2="16" />
      </svg>
    )
  }

  // Embeddings / Vector Search
  if (matches('embeddings', 'embedding', 'vector')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#a855f7'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="6" cy="6" r="3" />
        <circle cx="18" cy="6" r="3" />
        <circle cx="18" cy="18" r="3" />
        <circle cx="6" cy="18" r="3" />
        <line x1="9" y1="6" x2="15" y2="6" />
        <line x1="9" y1="18" x2="15" y2="18" />
        <line x1="6" y1="9" x2="6" y2="15" />
        <line x1="18" y1="9" x2="18" y2="15" />
      </svg>
    )
  }

  // RAG Pipeline (Knowledge Book & Search)
  if (matches('rag_pipeline', 'rag')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ec4899'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        <circle cx="13" cy="10" r="3" />
        <line x1="15.2" y1="12.2" x2="17.5" y2="14.5" />
      </svg>
    )
  }

  // Memory (Neural Chip)
  if (matches('memory')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#8b5cf6'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <rect x="9" y="9" width="6" height="6" />
        <line x1="9" y1="1" x2="9" y2="4" />
        <line x1="15" y1="1" x2="15" y2="4" />
        <line x1="9" y1="20" x2="9" y2="23" />
        <line x1="15" y1="20" x2="15" y2="23" />
        <line x1="20" y1="9" x2="23" y2="9" />
        <line x1="20" y1="15" x2="23" y2="15" />
        <line x1="1" y1="9" x2="4" y2="9" />
        <line x1="1" y1="15" x2="4" y2="15" />
      </svg>
    )
  }

  // Text Splitter (Chunking Document)
  if (matches('text_splitter')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#06b6d4'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <line x1="2" y1="12" x2="22" y2="12" strokeDasharray="3 3" />
      </svg>
    )
  }

  // Output Parser (JSON Structured Extract)
  if (matches('output_parser')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 4c-2 0-3 1-3 3v3c0 1.5-1 2-2 2 1 0 2 .5 2 2v3c0 2 1 3 3 3" />
        <path d="M17 4c2 0 3 1 3 3v3c0 1.5 1 2 2 2-1 0-2 .5-2 2v3c0 2-1 3-3 3" />
        <polyline points="10 12 12 14 15 10" />
      </svg>
    )
  }

  // Token Manager / OAuth Token Fetch
  if (matches('token_manager', 'token_fetch', 'auth_fetch')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 2l-2 2m-1.5 1.5L14 9a5.5 5.5 0 1 0 3 3l6.5-6.5-2-2-1.5 1.5z" />
        <circle cx="7.5" cy="16.5" r="2.5" />
      </svg>
    )
  }

  // Token Store / Vault
  if (matches('token_store', 'auth_store')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <rect x="9" y="11" width="6" height="4" rx="1" />
        <path d="M10 11V9a2 2 0 1 1 4 0v2" />
      </svg>
    )
  }

  // Crypto Tools (Padlock & Hash)
  if (matches('crypto_tools', 'crypto')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#6366f1'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        <circle cx="12" cy="16" r="1.5" fill="currentColor" />
      </svg>
    )
  }

  // CSV / JSON Transform
  if (matches('csv_json_transform', 'csv', 'transform')) {
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

  // Date & Time
  if (matches('date_time', 'time', 'date')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <polyline points="12 13 12 16 15 16" />
      </svg>
    )
  }

  // Email Read (IMAP)
  if (matches('email_read')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ea4335'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
        <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
      </svg>
    )
  }

  // Send Email (SMTP / Mail)
  if (matches('send_email', 'email', 'mail')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#ea4335'} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
      </svg>
    )
  }

  // File I/O
  if (matches('file_io', 'file')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#94a3b8'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    )
  }

  // FTP
  if (matches('ftp')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2z" />
        <polyline points="12 11 12 16 9 13" />
        <polyline points="12 16 15 13" />
      </svg>
    )
  }

  // Git
  if (matches('git')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f05032'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="6" cy="6" r="3" />
        <circle cx="18" cy="18" r="3" />
        <circle cx="6" cy="18" r="3" />
        <line x1="6" y1="9" x2="6" y2="15" />
        <path d="M9 18h6a3 3 0 0 0 3-3V9" />
      </svg>
    )
  }

  // GraphQL
  if (matches('graphql')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#e10098'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 21 7.5 21 17.5 12 23 3 17.5 3 7.5 12 2" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    )
  }

  // HTML Extract
  if (matches('html_extract', 'html')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    )
  }

  // Item Lists
  if (matches('item_lists', 'list')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="8" y1="6" x2="21" y2="6" />
        <line x1="8" y1="12" x2="21" y2="12" />
        <line x1="8" y1="18" x2="21" y2="18" />
        <circle cx="4" cy="6" r="1.5" fill="currentColor" />
        <circle cx="4" cy="12" r="1.5" fill="currentColor" />
        <circle cx="4" cy="18" r="1.5" fill="currentColor" />
      </svg>
    )
  }

  // Markdown Text
  if (matches('markdown_text', 'markdown')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#38bdf8'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="16" rx="2" />
        <polyline points="6 15 6 9 9 12 12 9 12 15" />
        <polyline points="15 12 17 14 19 12" />
        <line x1="17" y1="14" x2="17" y2="9" />
      </svg>
    )
  }

  // Pagination
  if (matches('pagination')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#a855f7'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="14" height="14" x="3" y="3" rx="2" />
        <path d="M7 21h12a2 2 0 0 0 2-2V7" />
      </svg>
    )
  }

  // RSS Feed
  if (matches('rss_feed', 'rss')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f26522'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 11a9 9 0 0 1 9 9" />
        <path d="M4 4a16 16 0 0 1 16 16" />
        <circle cx="5" cy="19" r="1.5" fill="currentColor" />
      </svg>
    )
  }

  // SSH
  if (matches('ssh')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#10b981'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="16" rx="3" />
        <polyline points="6 9 9 12 6 15" />
        <line x1="11" y1="15" x2="15" y2="15" />
      </svg>
    )
  }

  // Telegram
  if (matches('telegram')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#26A5E4" />
        <path d="M5.5 11.5l12-5-4 13-3-4-2.5 1.5.5-3.5 7-6-8.5 5.5-1.5-1.5z" fill="#FFFFFF" />
      </svg>
    )
  }

  // WebSocket
  if (matches('websocket')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#06b6d4'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4.93 4.93a10 10 0 0 0 0 14.14M7.76 7.76a6 6 0 0 0 0 8.48m8.48-8.48a6 6 0 0 1 0 8.48m2.83-11.31a10 10 0 0 1 0 14.14" />
        <circle cx="12" cy="12" r="2" fill="currentColor" />
      </svg>
    )
  }

  // XML Ops
  if (matches('xml_ops', 'xml')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#f59e0b'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="7 8 3 12 7 16" />
        <polyline points="17 8 21 12 17 16" />
        <line x1="14" y1="4" x2="10" y2="20" />
      </svg>
    )
  }

  // If user provided a custom emoji character or text (only when not a placeholder)
  if (
    icon &&
    typeof icon === 'string' &&
    icon.trim() &&
    icon !== '🌐' &&
    icon !== '🔌' &&
    icon !== '•' &&
    icon !== '⚡' &&
    !icon.includes('http')
  ) {
    return (
      <span style={{ fontSize: size * 0.76, lineHeight: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
        {icon}
      </span>
    )
  }

  // Fallback: Elegant Connected Node Hexagon Mark
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color || '#94a3b8'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

export default NodeIcon
