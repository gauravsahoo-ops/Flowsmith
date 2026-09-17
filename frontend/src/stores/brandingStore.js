// brandingStore: custom company branding and white-labeling state.

import { create } from 'zustand'
import { api } from '../api'

const STORAGE_KEY = 'flowsmith_branding'

export const DEFAULT_BRANDING = {
  appName: 'Flowsmith',
  tagline: 'Next-Gen Workflow Automation',
  logoUrl: null,
  logoData: null,
  faviconUrl: null,
  primaryColor: '#6366f1',
}

function hexToRgb(hex) {
  const clean = hex.replace('#', '')
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16)
    const g = parseInt(clean[1] + clean[1], 16)
    const b = parseInt(clean[2] + clean[2], 16)
    return `${r}, ${g}, ${b}`
  }
  if (clean.length === 6) {
    const r = parseInt(clean.substring(0, 2), 16)
    const g = parseInt(clean.substring(2, 4), 16)
    const b = parseInt(clean.substring(4, 6), 16)
    return `${r}, ${g}, ${b}`
  }
  return '99, 102, 241'
}

function applyToDom(branding) {
  if (typeof document === 'undefined') return

  const appName = branding.appName || DEFAULT_BRANDING.appName
  const color = branding.primaryColor || DEFAULT_BRANDING.primaryColor

  // Update root CSS variables
  const root = document.documentElement
  root.style.setProperty('--brand-primary', color)
  root.style.setProperty('--brand-primary-rgb', hexToRgb(color))
  root.style.setProperty(
    '--brand-gradient',
    `linear-gradient(135deg, ${color} 0%, rgba(${hexToRgb(color)}, 0.75) 100%)`
  )
  root.style.setProperty(
    '--brand-shadow',
    `0 4px 14px rgba(${hexToRgb(color)}, 0.4)`
  )

  // Update document title if applicable
  if (document.title.includes('Flowsmith') || document.title.includes(appName)) {
    document.title = document.title.replace(/Flowsmith|.*?(?= —|$)/, appName)
  }

  // Update favicon if custom logo available
  const logo = branding.logoData || branding.logoUrl
  if (logo) {
    let link = document.querySelector("link[rel~='icon']")
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      document.getElementsByTagName('head')[0].appendChild(link)
    }
    link.href = logo
  }
}

function getStoredBranding() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      return { ...DEFAULT_BRANDING, ...parsed }
    }
  } catch {}
  return DEFAULT_BRANDING
}

const initial = getStoredBranding()
if (typeof document !== 'undefined') {
  applyToDom(initial)
}

export const useBrandingStore = create((set, get) => ({
  appName: initial.appName,
  tagline: initial.tagline,
  logoUrl: initial.logoUrl,
  logoData: initial.logoData,
  faviconUrl: initial.faviconUrl,
  primaryColor: initial.primaryColor,
  loading: false,
  error: null,

  init: async () => {
    try {
      set({ loading: true, error: null })
      const res = await api.getBranding()
      if (res) {
        const next = {
          appName: res.app_name || DEFAULT_BRANDING.appName,
          tagline: res.tagline || DEFAULT_BRANDING.tagline,
          logoUrl: res.logo_url || null,
          logoData: res.logo_data || null,
          faviconUrl: res.favicon_url || null,
          primaryColor: res.primary_color || DEFAULT_BRANDING.primaryColor,
        }
        set(next)
        applyToDom(next)
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
        } catch {}
      }
    } catch (err) {
      set({ error: err.message })
    } finally {
      set({ loading: false })
    }
  },

  updateBranding: async (payload) => {
    set({ loading: true, error: null })
    try {
      const backendPayload = {
        app_name: payload.appName,
        tagline: payload.tagline,
        logo_url: payload.logoUrl,
        logo_data: payload.logoData,
        favicon_url: payload.faviconUrl,
        primary_color: payload.primaryColor,
      }
      const res = await api.updateBranding(backendPayload)
      const next = {
        appName: res.app_name || DEFAULT_BRANDING.appName,
        tagline: res.tagline || DEFAULT_BRANDING.tagline,
        logoUrl: res.logo_url || null,
        logoData: res.logo_data || null,
        faviconUrl: res.favicon_url || null,
        primaryColor: res.primary_color || DEFAULT_BRANDING.primaryColor,
      }
      set(next)
      applyToDom(next)
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {}
      return next
    } catch (err) {
      set({ error: err.message })
      throw err
    } finally {
      set({ loading: false })
    }
  },

  resetBranding: async () => {
    set({ loading: true, error: null })
    try {
      const res = await api.resetBranding()
      const next = {
        appName: res.app_name || DEFAULT_BRANDING.appName,
        tagline: res.tagline || DEFAULT_BRANDING.tagline,
        logoUrl: null,
        logoData: null,
        faviconUrl: null,
        primaryColor: res.primary_color || DEFAULT_BRANDING.primaryColor,
      }
      set(next)
      applyToDom(next)
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {}
      return next
    } catch (err) {
      set({ error: err.message })
      throw err
    } finally {
      set({ loading: false })
    }
  },
}))

if (typeof window !== 'undefined' && import.meta.env?.DEV) {
  window.__brandingStore = useBrandingStore
}
