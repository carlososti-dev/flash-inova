import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, type Me } from '../api'
import { AuthCard, Notice, useSubmit } from '../components'
import { useSite } from '../site'

export default function Login() {
  const { site, me, setMe } = useSite()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, onSubmit } = useSubmit(async () => {
    const user = await api<Me>('/api/auth/login', { json: { email, password } })
    setMe(user)
    navigate(user.role === 'consultor' && !site?.tenant ? '/plataforma' : '/')
  })

  if (me) return <Navigate to={me.role === 'consultor' && !site?.tenant ? '/plataforma' : '/'} replace />
  const where = site?.tenant ? site.tenant.name : 'Área da plataforma'
  return (
    <AuthCard title="Entrar" subtitle={where}>
      {site?.tenant && !site.tenant_active && <Notice kind="error">O acesso deste hospital está suspenso.</Notice>}
      <form onSubmit={onSubmit} className="form">
        <label>E-mail
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>Senha
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <Notice kind="error">{error}</Notice>}
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Entrando…' : 'Entrar'}</button>
      </form>
      <p className="auth-links"><Link to="/esqueci-senha" className="link">Esqueci minha senha</Link></p>
      {site?.tenant && (
        <p className="auth-links muted">Primeiro acesso? <Link to="/cadastro" className="link">Cadastre-se com sua matrícula</Link></p>
      )}
    </AuthCard>
  )
}
