import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Message } from '../api'
import { AuthCard, Notice, useSubmit } from '../components'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const { busy, error, onSubmit } = useSubmit(async () => {
    const r = await api<Message>('/api/auth/forgot-password', { json: { email } })
    setSent(r.message)
  })
  return (
    <AuthCard title="Esqueci minha senha" subtitle="Enviaremos um link para você criar uma nova senha.">
      {sent ? <Notice kind="ok">{sent}</Notice> : (
        <form onSubmit={onSubmit} className="form">
          <label>E-mail
            <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {error && <Notice kind="error">{error}</Notice>}
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Enviando…' : 'Enviar link'}</button>
        </form>
      )}
      <p className="auth-links"><Link to="/login" className="link">Voltar para o login</Link></p>
    </AuthCard>
  )
}
