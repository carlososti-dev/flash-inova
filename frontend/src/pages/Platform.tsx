import { useCallback, useEffect, useId, useState } from 'react'
import { api, type AdminOut, type TenantAdmin, type Theme } from '../api'
import { Layout, Notice, useSubmit } from '../components'

export default function Platform() {
  const [tenants, setTenants] = useState<TenantAdmin[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setTenants(await api<TenantAdmin[]>('/api/platform/tenants'))
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Erro ao carregar.')
    }
  }, [])
  useEffect(() => { load() }, [load])

  const replace = (t: TenantAdmin) => setTenants((list) => list?.map((x) => (x.id === t.id ? t : x)) ?? null)

  return (
    <Layout>
      <div className="page-head">
        <h1>Hospitais</h1>
        <p className="muted">Cada hospital tem endereço próprio, logotipo, tema e administradores.</p>
      </div>
      <NewTenant onCreated={(t) => { setTenants((l) => [...(l ?? []), t]); setOpenId(t.id) }} />
      {loadError && <Notice kind="error">{loadError}</Notice>}
      {tenants?.length === 0 && <p className="muted">Nenhum hospital cadastrado ainda.</p>}
      <div className="stack">
        {tenants?.map((t) => (
          <TenantCard key={t.id} tenant={t} open={openId === t.id} onToggle={() => setOpenId(openId === t.id ? null : t.id)} onChange={replace} />
        ))}
      </div>
    </Layout>
  )
}

function NewTenant({ onCreated }: { onCreated: (t: TenantAdmin) => void }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [theme, setTheme] = useState<Theme>('verde')
  const { busy, error, onSubmit } = useSubmit(async () => {
    const t = await api<TenantAdmin>('/api/platform/tenants', { json: { name, slug, theme } })
    setName(''); setSlug('')
    onCreated(t)
  })
  return (
    <form className="card form form-inline" onSubmit={onSubmit}>
      <h2>Novo hospital</h2>
      <label>Nome<input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Endereço (subdomínio)
        <input required pattern="[a-z0-9]([a-z0-9-]*[a-z0-9])?" title="Letras minúsculas, números e hífen" placeholder="hnsg"
          value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} />
      </label>
      <ThemePicker value={theme} onChange={setTheme} />
      {error && <Notice kind="error">{error}</Notice>}
      <button className="btn btn-primary" disabled={busy}>{busy ? 'Criando…' : 'Criar hospital'}</button>
    </form>
  )
}

function ThemePicker({ value, onChange }: { value: Theme; onChange: (t: Theme) => void }) {
  const name = useId()
  return (
    <fieldset className="theme-picker">
      <legend>Tema</legend>
      {(['verde', 'azul'] as Theme[]).map((t) => (
        <label key={t} className={`swatch swatch-${t}`}>
          <input type="radio" name={name} checked={value === t} onChange={() => onChange(t)} />
          {t === 'verde' ? 'Verde' : 'Azul'}
        </label>
      ))}
    </fieldset>
  )
}

function TenantCard({ tenant, open, onToggle, onChange }: {
  tenant: TenantAdmin; open: boolean; onToggle: () => void; onChange: (t: TenantAdmin) => void
}) {
  const [error, setError] = useState<string | null>(null)
  async function patch(body: Partial<Pick<TenantAdmin, 'theme' | 'is_active'>>) {
    setError(null)
    try { onChange(await api<TenantAdmin>(`/api/platform/tenants/${tenant.id}`, { method: 'PATCH', json: body })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Erro ao salvar.') }
  }
  async function upload(file: File | undefined) {
    if (!file) return
    setError(null)
    const form = new FormData()
    form.append('file', file)
    try { onChange(await api<TenantAdmin>(`/api/platform/tenants/${tenant.id}/logo`, { form })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Erro ao enviar.') }
  }
  return (
    <section className={`card tenant ${tenant.is_active ? '' : 'tenant-off'}`}>
      <button className="tenant-head" onClick={onToggle} aria-expanded={open}>
        {tenant.logo_url ? <img src={tenant.logo_url} alt="" /> : <span className="logo-empty">sem logo</span>}
        <span>
          <strong>{tenant.name}</strong>
          <small className="muted">{tenant.slug} · {tenant.admins} administrador(es) · {tenant.is_active ? 'ativo' : 'suspenso'}</small>
        </span>
      </button>
      {open && (
        <div className="tenant-body">
          <div className="grid2">
            <label className="file">Logotipo (PNG, JPG ou WEBP, até 2 MB)
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => upload(e.target.files?.[0])} />
            </label>
            <ThemePicker value={tenant.theme} onChange={(theme) => patch({ theme })} />
          </div>
          <a className="link" href={`/login?tenant=${tenant.slug}`} target="_blank" rel="noreferrer">Abrir a tela de login deste hospital</a>
          {error && <Notice kind="error">{error}</Notice>}
          <Admins tenantId={tenant.id} onCreated={() => onChange({ ...tenant, admins: tenant.admins + 1 })} />
          <button className="btn btn-ghost" onClick={() => patch({ is_active: !tenant.is_active })}>
            {tenant.is_active ? 'Suspender acesso do hospital' : 'Reativar acesso do hospital'}
          </button>
        </div>
      )}
    </section>
  )
}

function Admins({ tenantId, onCreated }: { tenantId: string; onCreated: () => void }) {
  const [admins, setAdmins] = useState<AdminOut[]>([])
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  useEffect(() => { api<AdminOut[]>(`/api/platform/tenants/${tenantId}/admins`).then(setAdmins).catch(() => {}) }, [tenantId])
  const { busy, error, onSubmit } = useSubmit(async () => {
    const a = await api<AdminOut>(`/api/platform/tenants/${tenantId}/admins`, { json: { name, email } })
    setAdmins((l) => [...l, a]); setName(''); setEmail('')
    setSent(`Enviamos para ${a.email} o link para ativar o acesso.`)
    onCreated()
  })
  return (
    <div>
      <h3>Administradores</h3>
      {admins.length === 0 && <p className="muted">Nenhum ainda. Crie o primeiro abaixo.</p>}
      <ul className="admins">
        {admins.map((a) => <li key={a.id}>{a.name} · {a.email} <span className={`tag ${a.activated ? 'tag-ok' : ''}`}>{a.activated ? 'ativo' : 'aguardando ativação'}</span></li>)}
      </ul>
      <form className="form form-inline" onSubmit={onSubmit}>
        <label>Nome<input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>E-mail<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        {error && <Notice kind="error">{error}</Notice>}
        {sent && <Notice kind="ok">{sent}</Notice>}
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Criando…' : 'Criar administrador'}</button>
      </form>
    </div>
  )
}
