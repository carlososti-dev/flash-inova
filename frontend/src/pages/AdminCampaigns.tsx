import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  api, fmtDate, FIELD_KIND_LABELS, PHASE_LABELS, type CampaignAdmin, type CampaignLine,
  type CampaignSummary, type Distribution, type FieldKind, type SubmissionState,
} from '../api'
import { Notice, useSubmit } from '../components'

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')

// O campo datetime-local trabalha no horário do computador; a API recebe e devolve com fuso (ISO).
const pad = (n: number) => String(n).padStart(2, '0')
function toInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const fromInput = (v: string) => (v ? new Date(v).toISOString() : null)

const SUBMISSION_LABELS: Record<SubmissionState, string> = {
  antes: 'inscrições ainda não abriram', aberta: 'inscrições abertas', encerrada: 'inscrições encerradas',
}

export default function CampaignsTab() {
  const [list, setList] = useState<CampaignSummary[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setList(await api<CampaignSummary[]>('/api/admin/campaigns')); setError(null) }
    catch (e) { setError(errText(e)) }
  }, [])
  useEffect(() => { load() }, [load])

  if (selected) return <CampaignEditor id={selected} onClose={() => { setSelected(null); load() }} />
  return (
    <div className="stack">
      <NewCampaign onCreated={(id) => setSelected(id)} />
      <section className="card">
        <h2>Campanhas</h2>
        {error && <Notice kind="error">{error}</Notice>}
        {list?.length === 0 && <p className="muted">Nenhuma campanha ainda. Crie a primeira acima.</p>}
        {list && list.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Campanha</th><th>Inscrições</th><th>Fase</th><th>Linhas</th><th>Situação</th><th /></tr></thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id}>
                    <td><strong>{c.title}</strong></td>
                    <td>{fmtDate(c.submission_start)} a {fmtDate(c.submission_end)}<br /><small className="muted">{SUBMISSION_LABELS[c.submission_state]}</small></td>
                    <td>{PHASE_LABELS[c.current_phase]}</td>
                    <td>{c.active_lines}</td>
                    <td>{c.is_published ? <span className="tag tag-ok">publicada</span> : <span className="tag tag-wait">rascunho</span>}</td>
                    <td className="cell-actions"><button className="btn btn-ghost btn-sm" onClick={() => setSelected(c.id)}>Configurar</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function NewCampaign({ onCreated }: { onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', start: '', end: '' })
  const { busy, error, onSubmit } = useSubmit(async () => {
    const c = await api<CampaignAdmin>('/api/admin/campaigns', {
      json: { title: form.title, submission_start: fromInput(form.start), submission_end: fromInput(form.end) },
    })
    onCreated(c.id)
  })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  if (!open) return <div><button className="btn btn-primary" onClick={() => setOpen(true)}>Nova campanha</button></div>
  return (
    <form className="card form form-inline" onSubmit={onSubmit}>
      <h2>Nova campanha</h2>
      <label>Título<input required minLength={3} maxLength={200} placeholder="Ex.: 3º Prêmio de Inovação 2027" value={form.title} onChange={set('title')} /></label>
      <label>Inscrições abrem em<input type="datetime-local" required value={form.start} onChange={set('start')} /></label>
      <label>Inscrições encerram em<input type="datetime-local" required value={form.end} onChange={set('end')} /></label>
      {error && <Notice kind="error">{error}</Notice>}
      <div className="actions">
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Criando…' : 'Criar e configurar'}</button>
        <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>Cancelar</button>
      </div>
    </form>
  )
}

/* ---------------- Configuração de uma campanha ---------------- */

const DATE_FIELDS = [
  ['submission_start', 'Inscrições: início'], ['submission_end', 'Inscrições: fim'],
  ['analysis_start', 'Análise: início'], ['analysis_end', 'Análise: fim'],
  ['classification_end', 'Classificação: fim'], ['defense_date', 'Defesa (pitch)'],
  ['voting_start', 'Votação: abertura'], ['voting_end', 'Votação: fechamento'],
] as const
const TEXT_FIELDS = ['title', 'home_headline', 'home_text', 'tips_text', 'regulation_text', 'video_url'] as const
const NUMBER_FIELDS = [
  ['num_evaluators', 'Avaliadores por ideia'], ['weight_classify', 'Peso do "Classificar"'], ['weight_maybe', 'Peso do "Talvez"'],
  ['cutoff_score', 'Linha de corte (0 a 100)'], ['num_defense_finalists', 'Finalistas da defesa (N)'],
  ['num_voting_finalists', 'Finalistas da votação (X)'], ['num_winners', 'Premiadas'],
] as const
const OPTIONAL_NUMBERS = new Set(['num_defense_finalists', 'num_voting_finalists'])

type Draft = Record<string, string>

function toDraft(c: CampaignAdmin): Draft {
  const d: Draft = {}
  for (const [k] of DATE_FIELDS) d[k] = toInput(c[k])
  for (const k of TEXT_FIELDS) d[k] = c[k] ?? ''
  for (const [k] of NUMBER_FIELDS) d[k] = c[k] == null ? '' : String(c[k])
  return d
}

function CampaignEditor({ id, onClose }: { id: string; onClose: () => void }) {
  const [c, setC] = useState<CampaignAdmin | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [blind, setBlind] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const apply = useCallback((data: CampaignAdmin) => { setC(data); setDraft(toDraft(data)); setBlind(data.blind_review) }, [])
  useEffect(() => {
    api<CampaignAdmin>(`/api/admin/campaigns/${id}`).then(apply).catch((e) => setError(errText(e)))
  }, [id, apply])

  const { busy, error: saveError, onSubmit } = useSubmit(async () => {
    setOk(null)
    const body: Record<string, unknown> = { blind_review: blind }
    for (const [k] of DATE_FIELDS) body[k] = fromInput(draft[k])
    for (const k of TEXT_FIELDS) body[k] = draft[k]
    for (const [k] of NUMBER_FIELDS) body[k] = draft[k] === '' && OPTIONAL_NUMBERS.has(k) ? null : Number(draft[k])
    apply(await api<CampaignAdmin>(`/api/admin/campaigns/${id}`, { method: 'PATCH', json: body }))
    setOk('Alterações salvas.')
  })

  async function call(action: () => Promise<CampaignAdmin>, message?: string) {
    setError(null); setOk(null)
    try { const data = await action(); setC(data); if (message) setOk(message) }
    catch (e) { setError(errText(e)) }
  }
  const publish = (value: boolean) => call(
    () => api<CampaignAdmin>(`/api/admin/campaigns/${id}`, { method: 'PATCH', json: { is_published: value } }),
    value ? 'Campanha publicada: ela já aparece na página inicial.' : 'A campanha voltou a ser rascunho.',
  )
  async function remove() {
    if (!c || !window.confirm(`Excluir a campanha "${c.title}"? Esta ação não pode ser desfeita.`)) return
    try { await api(`/api/admin/campaigns/${id}`, { method: 'DELETE' }); onClose() }
    catch (e) { setError(errText(e)) }
  }

  if (!c) return <div className="stack">{error ? <Notice kind="error">{error}</Notice> : <p className="muted">Carregando…</p>}</div>
  const set = (k: string) => (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value })

  return (
    <div className="stack">
      <div className="editor-head">
        <button className="btn btn-ghost btn-sm" onClick={onClose}>← Campanhas</button>
        <h2>{c.title}</h2>
        {c.is_published ? <span className="tag tag-ok">publicada</span> : <span className="tag tag-wait">rascunho</span>}
        <span className="tag tag-info">fase: {PHASE_LABELS[c.current_phase]}</span>
        <div className="actions editor-actions">
          <Link className="btn btn-ghost btn-sm" to={`/campanhas/${c.id}`}>Ver página</Link>
          {c.is_published
            ? <button className="btn btn-ghost btn-sm" onClick={() => publish(false)}>Voltar para rascunho</button>
            : <button className="btn btn-primary btn-sm" onClick={() => publish(true)}>Publicar</button>}
          {!c.is_published && <button className="btn btn-ghost btn-sm btn-danger" onClick={remove}>Excluir</button>}
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}

      <Lines campaign={c} onChange={setC} onError={setError} />
      <FormFields campaign={c} onChange={setC} onError={setError} />
      {c.is_published && <DistributionCard campaignId={c.id} onDone={() => api<CampaignAdmin>(`/api/admin/campaigns/${id}`).then(setC)} />}
      <Banner campaign={c} call={call} />

      <form className="stack" onSubmit={onSubmit}>
        <section className="card form">
          <h2>Página inicial</h2>
          <label>Título da campanha<input required minLength={3} maxLength={200} value={draft.title} onChange={set('title')} /></label>
          <label>Chamada<input maxLength={300} placeholder="Ex.: Sua ideia pode transformar o hospital" value={draft.home_headline} onChange={set('home_headline')} /></label>
          <label>Apresentação<textarea rows={4} maxLength={5000} value={draft.home_text} onChange={set('home_text')} /></label>
          <label>Dicas para uma boa ideia<textarea rows={5} maxLength={5000} placeholder="Uma dica por linha" value={draft.tips_text} onChange={set('tips_text')} /></label>
          <label>Vídeo do YouTube<input type="url" placeholder="https://youtu.be/..." value={draft.video_url} onChange={set('video_url')} /></label>
        </section>

        <section className="card">
          <h2>Calendário das fases</h2>
          <p className="muted">As inscrições abrem e fecham sozinhas pelas datas. As demais datas aparecem no calendário da página inicial; a passagem de fase será confirmada pelo administrador.</p>
          <div className="form form-grid">
            {DATE_FIELDS.map(([k, label]) => (
              <label key={k}>{label}<input type="datetime-local" required={k.startsWith('submission')} value={draft[k]} onChange={set(k)} /></label>
            ))}
          </div>
        </section>

        <section className="card">
          <h2>Regras</h2>
          <p className="muted">Avaliação (copiada dos padrões do hospital ao criar a campanha), defesa e votação.</p>
          <div className="form form-grid">
            {NUMBER_FIELDS.map(([k, label]) => (
              <label key={k}>{label}<input type="number" min={OPTIONAL_NUMBERS.has(k) || k === 'num_winners' || k === 'num_evaluators' ? 1 : 0}
                max={k === 'cutoff_score' ? 100 : undefined} required={!OPTIONAL_NUMBERS.has(k)} value={draft[k]} onChange={set(k)} /></label>
            ))}
            <label className="check"><input type="checkbox" checked={blind} onChange={(e) => setBlind(e.target.checked)} /> Duplo-cego (o comitê não vê o autor)</label>
          </div>
        </section>

        <section className="card form">
          <h2>Regulamento</h2>
          <p className="muted">
            Quem envia uma ideia precisa aceitar este texto (cessão de direitos e uso dos dados); o aceite fica gravado com a data e a versão.
            Cada alteração salva gera uma nova versão. {c.regulation_version ? `Versão atual: ${c.regulation_version}.` : 'Sem regulamento, as ideias não podem ser enviadas.'}
          </p>
          <label>Texto do regulamento<textarea rows={12} maxLength={100000} value={draft.regulation_text} onChange={set('regulation_text')} /></label>
        </section>

        {saveError && <Notice kind="error">{saveError}</Notice>}
        <div className="actions sticky-save">
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Salvando…' : 'Salvar alterações'}</button>
          {ok && <span className="muted save-ok">{ok}</span>}
        </div>
      </form>
    </div>
  )
}

function Banner({ campaign, call }: { campaign: CampaignAdmin; call: (a: () => Promise<CampaignAdmin>, m?: string) => Promise<void> }) {
  const [key, setKey] = useState(0)
  function upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    call(() => api<CampaignAdmin>(`/api/admin/campaigns/${campaign.id}/banner`, { form }), 'Banner atualizado.').finally(() => setKey((k) => k + 1))
  }
  return (
    <section className="card">
      <h2>Banner</h2>
      <p className="muted">Imagem larga (sugestão: 1600 × 500 px), em PNG, JPG ou WEBP, até 5 MB. Sem banner, a página mostra o título sobre a cor do hospital.</p>
      {campaign.banner_url && <img className="banner-preview" src={campaign.banner_url} alt="Banner da campanha" />}
      <div className="actions">
        <label className="file">{campaign.banner_url ? 'Trocar banner' : 'Enviar banner'}
          <input key={key} type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }} />
        </label>
        {campaign.banner_url && (
          <button className="btn btn-ghost btn-sm" onClick={() => call(() => api<CampaignAdmin>(`/api/admin/campaigns/${campaign.id}/banner`, { method: 'DELETE' }), 'Banner removido.')}>
            Remover banner
          </button>
        )}
      </div>
    </section>
  )
}

function Lines({ campaign, onChange, onError }: { campaign: CampaignAdmin; onChange: (c: CampaignAdmin) => void; onError: (m: string | null) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const lines = campaign.lines
  const base = `/api/admin/campaign-lines`

  async function run(action: () => Promise<CampaignAdmin>) {
    onError(null)
    try { onChange(await action()); return true }
    catch (e) { onError(errText(e)); return false }
  }
  async function add(e: FormEvent) {
    e.preventDefault()
    if (await run(() => api<CampaignAdmin>(`/api/admin/campaigns/${campaign.id}/lines`, { json: { name, description: description || null } }))) {
      setName(''); setDescription('')
    }
  }
  function move(index: number, delta: number) {
    const ids = lines.map((l) => l.id)
    const [item] = ids.splice(index, 1)
    ids.splice(index + delta, 0, item)
    run(() => api<CampaignAdmin>(`/api/admin/campaigns/${campaign.id}/lines/order`, { method: 'PUT', json: { ids } }))
  }

  return (
    <section className="card">
      <h2>Linhas de ideias (temáticas)</h2>
      <p className="muted">Toda ideia pertence a uma linha. Até 5 linhas ativas. Uma linha que já tiver ideias não poderá ser excluída, só desativada.</p>
      {lines.length > 0 && (
        <ol className="lines">
          {lines.map((l, i) => editing === l.id
            ? <LineEdit key={l.id} line={l} onCancel={() => setEditing(null)}
                onSave={async (body) => { if (await run(() => api<CampaignAdmin>(`${base}/${l.id}`, { method: 'PATCH', json: body }))) setEditing(null) }} />
            : (
              <li key={l.id} className={l.is_active ? '' : 'row-off'}>
                <div className="line-text">
                  <strong>{l.name}</strong>{!l.is_active && <span className="tag"> inativa</span>}
                  {l.description && <small className="muted">{l.description}</small>}
                </div>
                <div className="line-actions">
                  <button className="btn btn-ghost btn-sm" aria-label="Subir" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                  <button className="btn btn-ghost btn-sm" aria-label="Descer" disabled={i === lines.length - 1} onClick={() => move(i, 1)}>↓</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setEditing(l.id)}>Editar</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => run(() => api<CampaignAdmin>(`${base}/${l.id}`, { method: 'PATCH', json: { is_active: !l.is_active } }))}>
                    {l.is_active ? 'Desativar' : 'Reativar'}
                  </button>
                  <button className="btn btn-ghost btn-sm btn-danger" onClick={() => window.confirm(`Excluir a linha "${l.name}"?`) && run(() => api<CampaignAdmin>(`${base}/${l.id}`, { method: 'DELETE' }))}>Excluir</button>
                </div>
              </li>
            ))}
        </ol>
      )}
      {campaign.active_lines < 5 && (
        <form className="form form-inline" onSubmit={add}>
          <label>Nova linha<input required minLength={2} maxLength={120} placeholder="Ex.: Segurança do paciente" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label>Descrição (opcional)<input maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          <div className="actions"><button className="btn btn-primary">Adicionar</button></div>
        </form>
      )}
    </section>
  )
}

function LineEdit({ line, onSave, onCancel }: { line: CampaignLine; onSave: (b: { name: string; description: string | null }) => void; onCancel: () => void }) {
  const [name, setName] = useState(line.name)
  const [description, setDescription] = useState(line.description ?? '')
  return (
    <li>
      <form className="form form-inline line-edit" onSubmit={(e) => { e.preventDefault(); onSave({ name, description: description || null }) }}>
        <label>Nome<input required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Descrição<input maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <div className="actions">
          <button className="btn btn-primary btn-sm">Salvar</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancelar</button>
        </div>
      </form>
    </li>
  )
}

/* ---------------- Campos do formulário de envio ---------------- */

const KINDS = Object.keys(FIELD_KIND_LABELS) as FieldKind[]

interface FieldDraft { kind: FieldKind; label: string; help_text: string; required: boolean; options: string }
const emptyField: FieldDraft = { kind: 'texto_longo', label: '', help_text: '', required: false, options: '' }
const optionList = (text: string) => text.split('\n').map((o) => o.trim()).filter(Boolean)

function FormFields({ campaign, onChange, onError }: { campaign: CampaignAdmin; onChange: (c: CampaignAdmin) => void; onError: (m: string | null) => void }) {
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const fields = campaign.fields
  const base = '/api/admin/campaign-fields'

  async function run(action: () => Promise<CampaignAdmin>) {
    onError(null)
    try { onChange(await action()); return true }
    catch (e) { onError(errText(e)); return false }
  }
  function move(index: number, delta: number) {
    const ids = fields.map((f) => f.id)
    const [item] = ids.splice(index, 1)
    ids.splice(index + delta, 0, item)
    run(() => api<CampaignAdmin>(`/api/admin/campaigns/${campaign.id}/fields/order`, { method: 'PUT', json: { ids } }))
  }
  const payload = (d: FieldDraft) => ({
    label: d.label, help_text: d.help_text || null, required: d.required, options: d.kind === 'lista' ? optionList(d.options) : null,
  })

  return (
    <section className="card">
      <h2>Formulário de envio</h2>
      <p className="muted">
        Título, linha de ideias e resumo são fixos e sempre obrigatórios. Acrescente aqui as demais perguntas.
        Um campo que já tem respostas não pode ser excluído, só desativado.
      </p>
      <ol className="lines">
        <li className="row-fixed"><div className="line-text"><strong>Título · Linha de ideias · Resumo</strong><small className="muted">campos fixos</small></div></li>
        {fields.map((f, i) => editing === f.id
          ? <FieldEdit key={f.id} initial={{ kind: f.kind, label: f.label, help_text: f.help_text ?? '', required: f.required, options: (f.options ?? []).join('\n') }}
              kindLocked onCancel={() => setEditing(null)}
              onSave={async (d) => { if (await run(() => api<CampaignAdmin>(`${base}/${f.id}`, { method: 'PATCH', json: payload(d) }))) setEditing(null) }} />
          : (
            <li key={f.id} className={f.is_active ? '' : 'row-off'}>
              <div className="line-text">
                <strong>{f.label}{f.required && <span className="req">*</span>}</strong>
                <small className="muted">
                  {FIELD_KIND_LABELS[f.kind]}{f.kind === 'lista' && f.options && `: ${f.options.join(', ')}`}
                  {f.answers > 0 && ` · ${f.answers} ${f.answers === 1 ? 'resposta' : 'respostas'}`}
                  {!f.is_active && ' · inativo'}
                </small>
                {f.help_text && <small className="muted">{f.help_text}</small>}
              </div>
              <div className="line-actions">
                <button className="btn btn-ghost btn-sm" aria-label="Subir" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                <button className="btn btn-ghost btn-sm" aria-label="Descer" disabled={i === fields.length - 1} onClick={() => move(i, 1)}>↓</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setEditing(f.id)}>Editar</button>
                <button className="btn btn-ghost btn-sm" onClick={() => run(() => api<CampaignAdmin>(`${base}/${f.id}`, { method: 'PATCH', json: { is_active: !f.is_active } }))}>
                  {f.is_active ? 'Desativar' : 'Reativar'}
                </button>
                {f.answers === 0 && <button className="btn btn-ghost btn-sm btn-danger" onClick={() => window.confirm(`Excluir o campo "${f.label}"?`) && run(() => api<CampaignAdmin>(`${base}/${f.id}`, { method: 'DELETE' }))}>Excluir</button>}
              </div>
            </li>
          ))}
      </ol>
      {adding
        ? <FieldEdit initial={emptyField} onCancel={() => setAdding(false)}
            onSave={async (d) => { if (await run(() => api<CampaignAdmin>(`/api/admin/campaigns/${campaign.id}/fields`, { json: { kind: d.kind, ...payload(d) } }))) setAdding(false) }} />
        : <button className="btn btn-primary" onClick={() => setAdding(true)}>Adicionar campo</button>}
    </section>
  )
}

function FieldEdit({ initial, kindLocked, onSave, onCancel }: { initial: FieldDraft; kindLocked?: boolean; onSave: (d: FieldDraft) => void; onCancel: () => void }) {
  const [d, setD] = useState(initial)
  const set = (k: keyof FieldDraft) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value })
  const Wrapper = kindLocked ? 'li' : 'div'
  return (
    <Wrapper className={kindLocked ? '' : 'field-new'}>
      <form className="form form-grid line-edit" onSubmit={(e: FormEvent) => { e.preventDefault(); onSave(d) }}>
        <label>Tipo
          <select value={d.kind} disabled={kindLocked} onChange={set('kind')}>
            {KINDS.map((k) => <option key={k} value={k}>{FIELD_KIND_LABELS[k]}</option>)}
          </select>
        </label>
        <label>Pergunta (rótulo)<input required minLength={2} maxLength={200} placeholder="Ex.: Qual problema a ideia resolve?" value={d.label} onChange={set('label')} /></label>
        <label>Texto de ajuda (opcional)<input maxLength={500} value={d.help_text} onChange={set('help_text')} /></label>
        <label className="check"><input type="checkbox" checked={d.required} onChange={(e) => setD({ ...d, required: e.target.checked })} /> Obrigatório</label>
        {d.kind === 'lista' && (
          <label className="span-all">Opções (uma por linha, ao menos duas)<textarea rows={4} value={d.options} onChange={set('options')} /></label>
        )}
        <div className="actions span-all">
          <button className="btn btn-primary btn-sm">Salvar campo</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancelar</button>
        </div>
      </form>
    </Wrapper>
  )
}

/* ---------------- Distribuição para o comitê ---------------- */

function DistributionCard({ campaignId, onDone }: { campaignId: string; onDone: () => void }) {
  const [d, setD] = useState<Distribution | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const url = `/api/admin/campaigns/${campaignId}/distribution`
  useEffect(() => { api<Distribution>(url).then(setD).catch((e) => setError(errText(e))) }, [url])

  async function distribute() {
    if (!d || !window.confirm(`Distribuir ${d.pending} ideia(s) para o comitê, ${d.num_evaluators} avaliador(es) por ideia? As ideias passam para "Em análise" e não poderão mais ser editadas pelos autores.`)) return
    setBusy(true); setError(null); setOk(null)
    try {
      const pending = d.pending
      setD(await api<Distribution>(url, { method: 'POST' }))
      setOk(`${pending} ideia(s) distribuída(s). Os avaliadores já as veem no menu Análise.`)
      onDone()
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <section className="card">
      <h2>Distribuição para o comitê</h2>
      <p className="muted">
        Cada ideia recebida vai para {d?.num_evaluators ?? '…'} membro(s) do comitê, escolhidos pela menor carga (empate: quem recebeu há mais tempo).
        Ninguém avalia ideia de que é autor ou coautor. Os avaliadores só veem as ideias depois da distribuição.
      </p>
      {error && <Notice kind="error">{error}</Notice>}
      {ok && <Notice kind="ok">{ok}</Notice>}
      {d && (
        <>
          <p className="stats">
            <strong>{d.pending}</strong> aguardando distribuição · <strong>{d.distributed}</strong> distribuída(s) · comitê com <strong>{d.committee}</strong> membro(s) ativo(s)
          </p>
          {d.blocker && d.pending > 0 && <p className="muted">{d.blocker}</p>}
          {d.pending > 0 && (
            <div className="actions">
              <button className="btn btn-primary" disabled={busy || d.blocker !== null} onClick={distribute}>
                {busy ? 'Distribuindo…' : `Distribuir ${d.pending} ideia(s)`}
              </button>
            </div>
          )}
          {d.evaluators.length > 0 && (
            <div className="table-wrap">
              <table className="table table-narrow">
                <thead><tr><th>Avaliador</th><th>Setor</th><th>Ideias</th><th>Com parecer</th></tr></thead>
                <tbody>
                  {d.evaluators.map((e) => (
                    <tr key={e.id}><td>{e.name}</td><td>{e.sector ?? '—'}</td><td>{e.assigned}</td><td>{e.evaluated}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {d.committee === 0 && <p className="muted">Ninguém tem o perfil Membro de comitê ainda. Ajuste em Administração › Usuários.</p>}
        </>
      )}
    </section>
  )
}
