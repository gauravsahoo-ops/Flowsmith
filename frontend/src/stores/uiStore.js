// uiStore: selection, panel state (spec 11), and node editor modal (Phase 17).

import { create } from 'zustand'

export const useUiStore = create((set) => ({
  selectedNodeId: null,
  selectNode: (id) => set({ selectedNodeId: id }),

  // Node editor modal (centered overlay)
  nodeEditorOpen: false,
  nodeEditorTab: 'parameters', // 'input' | 'parameters' | 'output'
  openNodeEditor: (nodeId, tab = 'parameters') =>
    set({ nodeEditorOpen: true, selectedNodeId: nodeId, nodeEditorTab: tab }),
  closeNodeEditor: () => set({ nodeEditorOpen: false }),
  setNodeEditorTab: (tab) => set({ nodeEditorTab: tab }),

  // Sidebar visibility (default: false so workflows open full-screen in fit view)
  sidebarOpen: false,
  toggleSidebar: () =>
    set((s) => {
      const next = !s.sidebarOpen
      return next ? { sidebarOpen: true, historyDrawerOpen: false } : { sidebarOpen: false }
    }),
  openSidebar: () => set({ sidebarOpen: true, historyDrawerOpen: false }),
  closeSidebar: () => set({ sidebarOpen: false }),

  // Workflow History Drawer (slide-out panel)
  historyDrawerOpen: false,
  historyTab: 'versions', // 'versions' | 'timeline'
  openHistoryDrawer: (tab = 'versions') => set({ historyDrawerOpen: true, historyTab: tab, sidebarOpen: false }),
  closeHistoryDrawer: () => set({ historyDrawerOpen: false }),
  toggleHistoryDrawer: () =>
    set((s) => {
      const next = !s.historyDrawerOpen
      return next ? { historyDrawerOpen: true, sidebarOpen: false } : { historyDrawerOpen: false }
    }),
  setHistoryTab: (tab) => set({ historyTab: tab }),

  // Canvas MiniMap visibility (default: false / hidden)
  showMiniMap: typeof localStorage !== 'undefined' ? localStorage.getItem('canvas_show_minimap') === 'true' : false,
  toggleMiniMap: () =>
    set((s) => {
      const next = !s.showMiniMap
      try { localStorage.setItem('canvas_show_minimap', String(next)) } catch {}
      return { showMiniMap: next }
    }),

  // Workflow audio cues (opt-in; default: false / muted)
  soundEffects: typeof localStorage !== 'undefined' ? localStorage.getItem('flowsmith_sound_effects') === 'true' : false,
  toggleSoundEffects: () =>
    set((s) => {
      const next = !s.soundEffects
      try { localStorage.setItem('flowsmith_sound_effects', String(next)) } catch {}
      return { soundEffects: next }
    }),
}))

// E2E/test hook (mirrors __wfStore) — dev only
if (typeof window !== 'undefined' && import.meta.env?.DEV) window.__uiStore = useUiStore
