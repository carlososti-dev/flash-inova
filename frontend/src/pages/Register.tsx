import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { api, type Message } from '../api'
import { AuthCard, Notice, useSubmit } from '../components'
import { useSite } from '../site'

export default function Register() {
  const { site } = useSite()
  const [matricula, setMatricula] = useState('')
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const { busy, error, onSubmit } = useSubmit(async () => {
    const r = await api<Message>('/api/auth/register', { json: { matricula, email } })
    setSent(r.message)
  })
  if (!site?.tenant) return <Navigate to="/login" replace />
  return (
    <AuthCard title="Primeiro acesso" subtitle={`Informe sua matrícula e o e-mail cadastrado em ${site.tenant.name}.`}>
      {sent ? <Notice kind="ok">{sent}</Notice> : (
        <form onSubmit={onSubmit} className="form">
          <label>Matrícula
            <input required maxLength={50} autoComplete="off" value={matricula} onChange={(e) => setMatricula(e.target.value)} />
          </label>
          <label>E-mail
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {error && <Notice kind="error">{error}</Notice>}
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Enviando…' : 'Receber link para criar senha'}</button>
        </form>
      )}
      <p className="auth-links"><Link to="/login" className="link">Voltar para o login</Link></p>
    </AuthCard>
  )
}
