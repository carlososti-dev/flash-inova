import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Message } from '../api'
import { AuthCard, Notice, useSubmit } from '../components'

/** Mesma tela para ativar a conta (primeiro acesso) e para redefinir a senha. */
export default function SetPassword({ mode }: { mode: 'activate' | 'reset' }) {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const [mismatch, setMismatch] = useState(false)
  const { busy, error, onSubmit } = useSubmit(async () => {
    if (password !== confirm) { setMismatch(true); return }
    setMismatch(false)
    const path = mode === 'activate' ? '/api/auth/activate' : '/api/auth/reset-password'
    const r = await api<Message>(path, { json: { token, password } })
    setDone(r.message)
  })
  const title = mode === 'activate' ? 'Ative seu acesso' : 'Nova senha'
  if (!token) return <AuthCard title={title}><Notice kind="error">Link incompleto. Abra o link do e-mail novamente.</Notice></AuthCard>
  return (
    <AuthCard title={title} subtitle="Crie uma senha com pelo menos 8 caracteres, com letras e números.">
      {done ? (
        <>
          <Notice kind="ok">{done}</Notice>
          <Link to="/login" className="btn btn-primary">Ir para o login</Link>
        </>
      ) : (
        <form onSubmit={onSubmit} className="form">
          <label>Nova senha
            <input type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <label>Repita a senha
            <input type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </label>
          {mismatch && <Notice kind="error">As senhas não conferem.</Notice>}
          {error && <Notice kind="error">{error}</Notice>}
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Salvando…' : 'Salvar senha'}</button>
        </form>
      )}
    </AuthCard>
  )
}
