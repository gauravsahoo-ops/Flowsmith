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

  async remove(id) {
    await api.deleteCredential(id)
    set({ credentials: get().credentials.filter((c) => c.id !== id) })
  },

  // Generic OAuth connect (Phase 33): provider is 'hubspot' | 'salesforce'.
  async connectOAuth(provider, loginUrl) {
    const { authorize_url, state } = await api.connectOAuth(provider, loginUrl)
    return { authorizeUrl: authorize_url, state }
  },
}))
