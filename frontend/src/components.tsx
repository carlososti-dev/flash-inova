import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import type { Role } from './api'
import { useSite } from './site'

export function Brand() {
  const { site } = useSite()
  const tenant = site?.tenant
  if (tenant?.logo_url) return <img className="brand-logo" src={tenant.logo_url} alt={tenant.name} />
  return <span className="brand-name">{tenant?.name ?? 'Flash Inova'}</span>
}

export function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <main className="auth">
      <div className="card auth-card">
        <div className="auth-brand"><Brand /></div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
        {children}
      </div>
    </main>
  )
}

export function Notice({ kind, children }: { kind: 'error' | 'ok'; children: ReactNode }) {
  return <p className={`notice notice-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</p>
}

/** Envia o formulário mostrando "aguarde" e a mensagem de erro do servidor. */
export function useSubmit<T>(action: () => Promise<T>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível concluir.')
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, onSubmit }
}

// Menu conforme a especificação da página Início.
const MENU: { to: string; label: string; roles: Role[] | 'all' }[] = [
  { to: '/', label: 'Início', roles: 'all' },
  { to: '/minhas-ideias', label: 'Minhas ideias', roles: 'all' },
  { to: '/analise', label: 'Análise', roles: ['administrador', 'consultor', 'membro_comite'] },
  { to: '/classificacao', label: 'Classificação', roles: ['administrador', 'consultor', 'gestor'] },
  { to: '/dashboard', label: 'Dashboard', roles: ['administrador', 'consultor'] },
  { to: '/administracao', label: 'Administração', roles: ['administrador', 'consultor'] },
]

export function Layout({ children }: { children: ReactNode }) {
  const { me, site, logout } = useSite()
  const navigate = useNavigate()
  const items = MENU.filter((m) => m.roles === 'all' || (me && m.roles.includes(me.role)))
  return (
    <>
      <header className="topbar">
        <Link to="/" className="topbar-brand"><Brand /></Link>
        {site?.tenant && (
          <nav className="topbar-nav" aria-label="Menu principal">
            {items.map((m) => <NavLink key={m.to} to={m.to} end>{m.label}</NavLink>)}
          </nav>
        )}
        <div className="topbar-user">
          {me?.role === 'consultor' && <Link to="/plataforma" className="link">Plataforma</Link>}
          {me && <span className="user-chip"><strong>{me.name}</strong><small>{me.role_label}</small></span>}
          {me && <button className="btn btn-ghost" onClick={async () => { await logout(); navigate('/login') }}>Sair</button>}
        </div>
      </header>
      <main className="page">{children}</main>
    </>
  )
}
