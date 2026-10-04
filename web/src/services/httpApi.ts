/**
 * DayOneApi backed by the local Python API (api/main.py, port 8000).
 * The dashboard is read-only: it polls /api/snapshot and never writes records.
 * Captures, reviews and patient choices arrive through the WhatsApp agent.
 * Only the viewer's settings (role, language, midwife ID) live in this browser.
 */
import type { AppState, DayOneApi } from './api'

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const POLL_MS = 4000
const SETTINGS_KEY = 'dayone.settings.v1'

type Settings = Pick<AppState, 'midwifeId' | 'role' | 'lang'>
type Snapshot = Pick<AppState, 'records' | 'patients' | 'visits' | 'busy'>

function loadSettings(): Partial<Settings> {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}') as Partial<Settings>
  } catch {
    return {}
  }
}

class HttpApi implements DayOneApi {
  private state: AppState
  private listeners = new Set<() => void>()
  private inFlight = false

  constructor() {
    const s = loadSettings()
    this.state = {
      online: true, // optimistic until the first request answers
      records: {},
      patients: {},
      visits: {},
      busy: [],
      activity: [],
      midwifeId: s.midwifeId ?? '',
      role: s.role ?? 'MIDWIFE',
      lang: s.lang ?? 'fr',
    }
    void this.refresh()
    setInterval(() => void this.refresh(), POLL_MS)
    window.addEventListener('focus', () => void this.refresh())
  }

  getState = () => this.state
  subscribe = (l: () => void) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }

  private set(patch: Partial<AppState>) {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((l) => l())
  }

  async refresh() {
    if (this.inFlight) return
    this.inFlight = true
    try {
      const r = await fetch(`${API_URL}/api/snapshot`)
      if (!r.ok) throw new Error(String(r.status))
      const snap = (await r.json()) as Snapshot
      // Images are served by the API: make their paths absolute.
      for (const rec of Object.values(snap.records))
        for (const p of rec.pages) if (p.imageUrl?.startsWith('/')) p.imageUrl = API_URL + p.imageUrl
      this.set({ ...snap, online: true })
    } catch {
      if (this.state.online) this.set({ online: false }) // keep showing the last data received
    } finally {
      this.inFlight = false
    }
  }

  private saveSettings(patch: Partial<Settings>) {
    this.set(patch)
    try {
      const { midwifeId, role, lang } = this.state
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ midwifeId, role, lang }))
    } catch {
      /* private mode: settings live in memory only */
    }
  }

  setRole(role: AppState['role']) {
    this.saveSettings({ role })
  }
  setLang(lang: AppState['lang']) {
    this.saveSettings({ lang })
  }
  setMidwifeId(midwifeId: string) {
    this.saveSettings({ midwifeId })
  }
  clearLocalSettings() {
    try {
      localStorage.removeItem(SETTINGS_KEY)
    } catch {
      /* nothing stored */
    }
    this.set({ midwifeId: '', role: 'MIDWIFE', lang: 'fr' })
  }
}

export const httpApi = new HttpApi()
