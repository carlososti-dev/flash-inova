import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, type Me, type SiteInfo } from './api'

interface SiteState {
  site: SiteInfo | null
  me: Me | null
  loading: boolean
  error: string | null
  setMe: (me: Me | null) => void
  logout: () => Promise<void>
}

const SiteContext = createContext<SiteState | null>(null)

export function SiteProvider({ children }: { children: ReactNode }) {
  const [site, setSite] = useState<SiteInfo | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const info = await api<SiteInfo>('/api/site')
        if (cancelled) return
        setSite(info)
        try {
          const current = await api<Me>('/api/auth/me')
          if (!cancelled) setMe(current)
        } catch (e) {
          if (!(e instanceof ApiError && (e.status === 401 || e.status === 403))) throw e
        }
      } catch (e) {
        if (cancelled) return
        if (e instanceof ApiError && e.message === 'Hospital não encontrado.') setError(e.message)
        else setError('Não foi possível falar com o servidor. Confira se o backend está rodando (uvicorn na porta 8000).')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = site?.tenant?.theme ?? 'azul'
    document.title = site?.tenant ? `${site.tenant.name} · Ideias` : 'Flash Inova'
  }, [site])

  const logout = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' })
    setMe(null)
  }, [])

  return <SiteContext.Provider value={{ site, me, loading, error, setMe, logout }}>{children}</SiteContext.Provider>
}

export function useSite(): SiteState {
  const ctx = useContext(SiteContext)
  if (!ctx) throw new Error('useSite fora do SiteProvider')
  return ctx
}
