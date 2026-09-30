// credentialStore: credential metadata (id/name/type) — secrets never
// leave the backend (spec 12: metadata only, encrypted at rest).

import { create } from 'zustand'
import { api } from '../api'

export const useCredentialStore = create((set, get) => ({
  credentials: [],
  types: [],
  loaded: false,
  error: null,

  async load() {
    try {
      const [credentials, types] = await Promise.all([
        api.listCredentials(),
        api.listCredentialTypes(),
      ])
      set({ credentials, types, loaded: true, error: null })
    } catch (err) {
      set({ error: err.message })
    }
  },

  async create(data) {
    const meta = await api.createCredential(data)
    set({ credentials: [...get().credentials, meta] })
    return meta
  },

  async update(id, payload) {
    const meta = await api.updateCredential(id, payload)
    set({
      credentials: get().credentials.map((c) => (c.id === id ? { ...c, ...meta } : c)),
    })
    return meta
  },


  async remove(id) {
    await api.deleteCredential(id)
    set({ credentials: get().credentials.filter((c) => c.id !== id) })
  },

  async logout(id) {
    const result = await api.logoutCredential(id)
    set({ credentials: get().credentials.filter((c) => c.id !== id) })
    return result
  },

  // Generic OAuth connect: provider is 'salesforce' | 'hubspot' | 'google_*'.
  async connectOAuth(provider, loginUrl, prompt, extra = {}) {
    const { authorize_url, state } = await api.connectOAuth(provider, loginUrl, prompt, extra)
    return { authorizeUrl: authorize_url, state }
  },
}))
