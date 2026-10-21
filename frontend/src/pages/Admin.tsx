import { useCallback, useEffect, useState } from 'react'
import {
  api, download, ROLE_LABELS, type Authorized, type AuthorizedPage, type ImportReport, type MemberRole, type Role,
  type UserAdmin, type UserStatus,
} from '../api'
import { useSearchParams } from 'react-router-dom'
import { Layout, Notice, useSubmit } from '../components'
import { useSite } from '../site'
import CampaignsTab from './AdminCampaigns'

const TABS = { campanhas: 'Campanhas', autorizados: 'Lista de autorizados', usuarios: 'Usuários' } as const
type Tab = keyof typeof TABS

export default function Admin() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('aba')
  const tab: Tab = requested && requested in TABS ? (requested as Tab) : 'campanhas'
  return (
    <Layout>
      <div className="page-head">
        <h1>Administração</h1>
        <p className="muted">Campanhas do hospital, quem pode se cadastrar e o que cada usuário pode fazer.</p>
      </div>
      <div className="tabs" role="tablist">
        {(Object.keys(TABS) as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setParams({ aba: t }, { replace: true })}>{TABS[t]}</button>
        ))}
      </div>
      {tab === 'campanhas' ? <CampaignsTab /> : tab === 'autorizados' ? <AuthorizedTab /> : <UsersTab />}
    </Layout>
  )
}

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')

/* ---------------- Lista de autorizados ---------------- */

function AuthorizedTab() {
  const [page, setPage] = useState<AuthorizedPage | null>(null)
  const [q, setQ] = useState('')
  const [situacao, setSituacao] = useState('todos')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ q, situacao })
      setPage(await api<AuthorizedPage>(`/api/admin/authorized?${params}`))
      setError(null)
    } catch (e) { setError(errText(e)) }
  }, [q, situacao])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  async function toggle(m: Authorized) {
    try {
      const updated = await api<Authorized>(`/api/admin/authorized/${m.id}`, { method: 'PATCH', json: { is_active: !m.is_active } })
      setPage((p) => p && { ...p, items: p.items.map((x) => (x.id === m.id ? updated : x)), active: p.active + (updated.is_active ? 1 : -1) })
    } catch (e) { setError(errText(e)) }
  }

  return (
    <div className="stack">
      {page && (
        <p className="muted stats">
          <strong>{page.active}</strong> pessoas ativas na lista · <strong>{page.registered}</strong> já se cadastraram
        </p>
      )}
      <Importer onDone={load} />
      <AddMember onAdded={load} />
      <section className="card">
        <div className="filters">
          <input type="search" placeholder="Buscar por nome, matrícula, e-mail ou setor" value={q} onChange={(e) => setQ(e.target.value)} />
          <select value={situacao} onChange={(e) => setSituacao(e.target.value)} aria-label="Situação">
            <option value="todos">Todos</option>
            <option value="ativos">Ativos</option>
            <option value="sem_cadastro">Ativos sem cadastro</option>
            <option value="inativos">Inativos</option>
          </select>
        </div>
        {error && <Notice kind="error">{error}</Notice>}
        {page && page.items.length === 0 && <p className="muted">Ninguém encontrado. Importe a planilha do RH para começar.</p>}
        {page && page.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Matrícula</th><th>Nome</th><th>E-mail</th><th>Setor</th><th>Perfil inicial</th><th>Situação</th><th /></tr></thead>
              <tbody>
                {page.items.map((m) => (
                  <tr key={m.id} className={m.is_active ? '' : 'row-off'}>
                    <td>{m.matricula}</td>
                    <td>{m.name}</td>
                    <td className="cell-email">{m.email}</td>
                    <td>{m.sector ?? '—'}</td>
                    <td>{ROLE_LABELS[m.default_role ?? 'colaborador']}</td>
                    <td>
                      {!m.is_active ? <span className="tag">inativo</span>
                        : m.registered ? <span className="tag tag-ok">cadastrado</span>
                        : <span className="tag tag-wait">aguardando cadastro</span>}
                    </td>
                    <td><button className="btn btn-ghost btn-sm" onClick={() => toggle(m)}>{m.is_active ? 'Desativar' : 'Reativar'}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {page.total > page.items.length && <p className="muted">Mostrando {page.items.length} de {page.total}. Refine a busca para ver os demais.</p>}
          </div>
        )}
      </section>
    </div>
  )
}

function Importer({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [inputKey, setInputKey] = useState(0)

  async function send(f: File, confirm: boolean) {
    setBusy(true); setError(null)
    const form = new FormData()
    form.append('file', f)
    form.append('confirm', String(confirm))
    try {
      const r = await api<ImportReport>('/api/admin/authorized/import', { form })
      setReport(r)
      if (confirm) { setFile(null); setInputKey((k) => k + 1); onDone() }
    } catch (e) { setError(errText(e)); setReport(null) }
    finally { setBusy(false) }
  }

  const valid = report ? report.created + report.updated : 0
  return (
    <section className="card">
      <h2>Importar planilha</h2>
      <p className="muted">
        CSV ou Excel (.xlsx) com as colunas <strong>matricula, nome, email</strong> e, se quiser, <strong>setor</strong> e <strong>perfil</strong>{' '}
        (colaborador, membro de comitê ou gestor). Quem já está na lista é atualizado pela matrícula; ninguém é removido.{' '}
        <button type="button" className="link link-btn" onClick={() => download('/api/admin/authorized/modelo.csv', 'modelo-lista-de-autorizados.csv').catch((e) => setError(errText(e)))}>
          Baixar modelo
        </button>
      </p>
      <label className="file">Arquivo
        <input key={inputKey} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); setReport(null); if (f) send(f, false) }} />
      </label>
      {busy && <p className="muted">Conferindo…</p>}
      {error && <Notice kind="error">{error}</Notice>}
      {report && (
        <div className="report">
          {report.applied
            ? <Notice kind="ok">Importação concluída: {report.created} pessoa(s) incluída(s) e {report.updated} atualizada(s).{report.errors.length > 0 && ` ${report.errors.length} linha(s) com erro ficaram de fora.`}</Notice>
            : <p><strong>{report.lines}</strong> linha(s) no arquivo: {report.created} nova(s), {report.updated} com alteração, {report.unchanged} sem mudança e <strong>{report.errors.length}</strong> com erro.</p>}
          {report.errors.length > 0 && (
            <div className="table-wrap errors">
              <table className="table">
                <thead><tr><th>Linha</th><th>Problema</th></tr></thead>
                <tbody>{report.errors.map((e) => <tr key={e.line}><td>{e.line}</td><td>{e.message}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {!report.applied && file && (
            <div className="actions">
              <button className="btn btn-primary" disabled={busy || valid === 0} onClick={() => send(file, true)}>
                {valid === 0 ? 'Nada para importar' : `Importar ${valid} linha(s) válida(s)`}
              </button>
              <button className="btn btn-ghost" onClick={() => { setFile(null); setReport(null); setInputKey((k) => k + 1) }}>Cancelar</button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function AddMember({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const empty = { matricula: '', name: '', email: '', sector: '', default_role: 'colaborador' as MemberRole }
  const [form, setForm] = useState(empty)
  const [ok, setOk] = useState<string | null>(null)
  const { busy, error, onSubmit } = useSubmit(async () => {
    await api<Authorized>('/api/admin/authorized', { json: { ...form, sector: form.sector || null } })
    setOk(`${form.name} foi incluído(a) na lista e já pode fazer o primeiro acesso.`)
    setForm(empty)
    onAdded()
  })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  if (!open) return <div><button className="btn btn-ghost" onClick={() => setOpen(true)}>Incluir uma pessoa</button></div>
  return (
    <form className="card form form-inline" onSubmit={onSubmit}>
      <h2>Incluir uma pessoa</h2>
      <label>Matrícula<input required maxLength={50} value={form.matricula} onChange={set('matricula')} /></label>
      <label>Nome<input required minLength={2} value={form.name} onChange={set('name')} /></label>
      <label>E-mail<input type="email" required value={form.email} onChange={set('email')} /></label>
      <label>Setor<input value={form.sector} onChange={set('sector')} /></label>
      <label>Perfil inicial
        <select value={form.default_role} onChange={set('default_role')}>
          <option value="colaborador">Colaborador</option>
          <option value="membro_comite">Membro de comitê</option>
          <option value="gestor">Gestor</option>
        </select>
      </label>
      {error && <Notice kind="error">{error}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}
      <div className="actions">
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Incluindo…' : 'Incluir'}</button>
        <button type="button" className="btn btn-ghost" onClick={() => { setOpen(false); setOk(null) }}>Fechar</button>
      </div>
    </form>
  )
}

/* ---------------- Usuários ---------------- */

const ASSIGNABLE: Role[] = ['colaborador', 'membro_comite', 'gestor', 'administrador']

function UsersTab() {
  const { me } = useSite()
  const [users, setUsers] = useState<UserAdmin[] | null>(null)
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [situacao, setSituacao] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ q })
      if (role) params.set('role', role)
      if (situacao) params.set('situacao', situacao)
      setUsers(await api<UserAdmin[]>(`/api/admin/users?${params}`))
      setError(null)
    } catch (e) { setError(errText(e)) }
  }, [q, role, situacao])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  async function patch(u: UserAdmin, body: { role?: Role; status?: UserStatus }) {
    setError(null); setOk(null)
    try {
      const updated = await api<UserAdmin>(`/api/admin/users/${u.id}`, { method: 'PATCH', json: body })
      setUsers((list) => list?.map((x) => (x.id === u.id ? updated : x)) ?? null)
    } catch (e) { setError(errText(e)) }
  }
  async function resend(u: UserAdmin) {
    setError(null); setOk(null)
    try { setOk((await api<{ message: string }>(`/api/admin/users/${u.id}/resend-activation`, { method: 'POST' })).message) }
    catch (e) { setError(errText(e)) }
  }

  return (
    <section className="card stack-tight">
      <div className="filters">
        <input type="search" placeholder="Buscar por nome, e-mail, matrícula ou setor" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Perfil">
          <option value="">Todos os perfis</option>
          {ASSIGNABLE.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
        </select>
        <select value={situacao} onChange={(e) => setSituacao(e.target.value)} aria-label="Situação">
          <option value="">Ativos e inativos</option>
          <option value="ativo">Ativos</option>
          <option value="inativo">Inativos</option>
        </select>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {users?.length === 0 && <p className="muted">Nenhum usuário encontrado.</p>}
      {users && users.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Nome</th><th>E-mail</th><th>Matrícula</th><th>Perfil</th><th>Acesso</th><th /></tr></thead>
            <tbody>
              {users.map((u) => {
                const self = u.id === me?.id
                return (
                  <tr key={u.id} className={u.status === 'ativo' ? '' : 'row-off'}>
                    <td>{u.name}{self && <small className="muted"> (você)</small>}</td>
                    <td className="cell-email">{u.email}</td>
                    <td>{u.matricula ?? '—'}</td>
                    <td>
                      <select value={u.role} disabled={self} aria-label={`Perfil de ${u.name}`} onChange={(e) => patch(u, { role: e.target.value as Role })}>
                        {ASSIGNABLE.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                      </select>
                    </td>
                    <td>
                      {u.status === 'inativo' ? <span className="tag">inativo</span>
                        : u.activated ? <span className="tag tag-ok">ativo</span>
                        : <span className="tag tag-wait">aguardando ativação</span>}
                    </td>
                    <td className="cell-actions">
                      {!u.activated && u.status === 'ativo' && <button className="btn btn-ghost btn-sm" onClick={() => resend(u)}>Reenviar convite</button>}
                      {!self && (
                        <button className="btn btn-ghost btn-sm" onClick={() => patch(u, { status: u.status === 'ativo' ? 'inativo' : 'ativo' })}>
                          {u.status === 'ativo' ? 'Desativar' : 'Reativar'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
