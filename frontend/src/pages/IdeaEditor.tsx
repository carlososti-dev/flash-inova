import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api, fmtDateTime, fmtSize, type AnswerValue, type CampaignField, type Idea, type IdeaForm, type Person,
} from '../api'
import { Layout, Notice } from '../components'

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')

interface Draft { title: string; line_id: string | null; summary: string; answers: Record<string, AnswerValue>; coauthors: Person[] }

const emptyDraft: Draft = { title: '', line_id: null, summary: '', answers: {}, coauthors: [] }

function fromIdea(idea: Idea): Draft {
  const answers: Record<string, AnswerValue> = {}
  for (const a of idea.answers) if (a.kind !== 'anexo') answers[a.field_id] = a.value
  return { title: idea.title, line_id: idea.line_id, summary: idea.summary ?? '', answers, coauthors: idea.coauthors }
}

/** Formulário de envio: novo (/ideias/nova?campanha=…) ou edição (/ideias/:id/editar). */
export default function IdeaEditor() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [form, setForm] = useState<IdeaForm | null>(null)
  const [idea, setIdea] = useState<Idea | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [accept, setAccept] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  // Ao criar o rascunho a URL muda para /ideias/:id/editar; a ideia já está na tela, não precisa recarregar.
  const created = useRef<string | null>(null)

  useEffect(() => {
    if (id && id === created.current) return
    (async () => {
      try {
        let campaignId = params.get('campanha')
        if (id) {
          const loaded = await api<Idea>(`/api/ideas/${id}`)
          setIdea(loaded)
          setDraft(fromIdea(loaded))
          campaignId = loaded.campaign_id
        }
        if (!campaignId) throw new Error('Campanha não informada. Volte ao início e use o botão "Enviar projeto".')
        setForm(await api<IdeaForm>(`/api/campaigns/${campaignId}/form`))
      } catch (e) { setError(errText(e)) }
    })()
  }, [id, params])

  if (idea && !idea.can_edit) return <Navigate to={`/ideias/${idea.id}`} replace />
  if (!form) return <Layout>{error ? <Notice kind="error">{error}</Notice> : <p className="muted">Carregando…</p>}</Layout>

  const sent = idea !== null && idea.stage !== 'rascunho'
  const open = form.submission_state === 'aberta'
  const body = () => ({
    title: draft.title, line_id: draft.line_id, summary: draft.summary,
    answers: Object.fromEntries(form.fields.filter((f) => f.kind !== 'anexo').map((f) => [f.id, draft.answers[f.id] ?? null])),
    coauthor_ids: draft.coauthors.map((p) => p.id),
  })

  /** Grava (cria o rascunho na primeira vez) e devolve a ideia salva. */
  async function save(): Promise<Idea> {
    if (draft.title.trim().length < 3) throw new Error('Dê um título à ideia (pelo menos 3 caracteres) para salvar.')
    const saved = idea
      ? await api<Idea>(`/api/ideas/${idea.id}`, { method: 'PUT', json: body() })
      : await api<Idea>('/api/ideas', { json: { ...body(), campaign_id: form!.campaign_id } })
    setIdea(saved)
    if (!idea) {
      created.current = saved.id
      navigate(`/ideias/${saved.id}/editar`, { replace: true })
    }
    return saved
  }

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label); setError(null); setOk(null)
    try { await action() } catch (e) { setError(errText(e)) } finally { setBusy(null) }
  }
  const saveDraft = () => run('save', async () => {
    await save()
    setOk(sent ? 'Alterações salvas. A ideia continua enviada.' : 'Rascunho salvo. Só você vê esta ideia até enviá-la.')
  })
  const submit = () => run('submit', async () => {
    const saved = await save()
    const done = await api<Idea>(`/api/ideas/${saved.id}/submit`, { json: { accept_regulation: accept } })
    navigate('/minhas-ideias', { state: { sent: done.number } })
  })

  async function upload(field: CampaignField, file: File) {
    await run(`file-${field.id}`, async () => {
      const target = idea ?? await save()
      const data = new FormData()
      data.append('file', file)
      setIdea(await api<Idea>(`/api/ideas/${target.id}/files/${field.id}`, { form: data }))
    })
  }
  const removeFile = (field: CampaignField) => run(`file-${field.id}`, async () => {
    setIdea(await api<Idea>(`/api/ideas/${idea!.id}/files/${field.id}`, { method: 'DELETE' }))
  })
  async function removeDraft() {
    if (!idea || !window.confirm('Excluir este rascunho? Esta ação não pode ser desfeita.')) return
    await run('delete', async () => { await api(`/api/ideas/${idea.id}`, { method: 'DELETE' }); navigate('/minhas-ideias') })
  }

  const setAnswer = (fieldId: string, value: AnswerValue) => setDraft({ ...draft, answers: { ...draft.answers, [fieldId]: value } })
  const files = Object.fromEntries((idea?.answers ?? []).filter((a) => a.kind === 'anexo').map((a) => [a.field_id, a]))

  return (
    <Layout>
      <div className="stack idea-editor">
        <div>
          <p><Link className="link" to="/minhas-ideias">← Minhas ideias</Link></p>
          <h1>{sent ? `Ideia #${idea!.number}` : idea ? 'Rascunho da ideia' : 'Nova ideia'}</h1>
          <p className="muted">
            {form.campaign_title} · {open ? `inscrições abertas até ${fmtDateTime(form.submission_end)}` : form.submission_state === 'antes'
              ? `as inscrições abrem em ${fmtDateTime(form.submission_start)}; você já pode guardar um rascunho`
              : 'inscrições encerradas'}
          </p>
          {sent && <Notice kind="ok">Ideia enviada em {fmtDateTime(idea!.submitted_at)}. Você pode alterá-la até {fmtDateTime(form.submission_end)}.</Notice>}
        </div>

        <section className="card form">
          <h2>Sua ideia</h2>
          <label><span>Título<span className="req">*</span></span>
            <input required minLength={3} maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </label>
          <fieldset className="choices">
            <legend><span>Linha de ideias<span className="req">*</span></span></legend>
            {form.lines.map((l) => (
              <label key={l.id} className={`choice${draft.line_id === l.id ? ' choice-on' : ''}`}>
                <input type="radio" name="line" checked={draft.line_id === l.id} onChange={() => setDraft({ ...draft, line_id: l.id })} />
                <span><strong>{l.name}</strong>{l.description && <small>{l.description}</small>}</span>
              </label>
            ))}
          </fieldset>
          <label><span>Resumo<span className="req">*</span></span>
            <small className="help">Em poucas linhas: qual o problema e o que você propõe.</small>
            <textarea rows={5} maxLength={2000} value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })} />
            <small className="counter">{draft.summary.length}/2000</small>
          </label>
        </section>

        {form.fields.length > 0 && (
          <section className="card form">
            <h2>Detalhes</h2>
            {form.fields.map((f) => (
              <FieldInput key={f.id} field={f} value={draft.answers[f.id] ?? null} onChange={(v) => setAnswer(f.id, v)}
                file={files[f.id]} busy={busy === `file-${f.id}`} maxMb={form.max_attachment_mb}
                onUpload={(file) => upload(f, file)} onRemove={() => removeFile(f)} />
            ))}
          </section>
        )}

        <Coauthors people={draft.coauthors} onChange={(coauthors) => setDraft({ ...draft, coauthors })} />

        {!sent && (
          <section className="card">
            <h2>Regulamento</h2>
            {form.regulation_version ? (
              <label className="check accept">
                <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
                <span>
                  Li e aceito o <Link className="link" to={`/campanhas/${form.campaign_id}/regulamento`} target="_blank">regulamento da campanha</Link> (versão {form.regulation_version}),
                  incluindo a cessão de direitos sobre a ideia e o uso dos meus dados para a campanha.
                </span>
              </label>
            ) : <Notice kind="error">A campanha ainda não publicou o regulamento, por isso o envio está bloqueado. Você pode guardar o rascunho.</Notice>}
          </section>
        )}

        {error && <Notice kind="error">{error}</Notice>}
        <div className="actions sticky-save">
          {sent ? (
            <button className="btn btn-primary" disabled={busy !== null} onClick={saveDraft}>{busy === 'save' ? 'Salvando…' : 'Salvar alterações'}</button>
          ) : (
            <>
              <button className="btn btn-ghost" disabled={busy !== null} onClick={saveDraft}>{busy === 'save' ? 'Salvando…' : 'Salvar rascunho'}</button>
              <button className="btn btn-primary" disabled={busy !== null || !open || !accept || !form.regulation_version} onClick={submit}
                title={!open ? 'Só é possível enviar durante o período de inscrição.' : !accept ? 'Aceite o regulamento para enviar.' : undefined}>
                {busy === 'submit' ? 'Enviando…' : 'Enviar ideia'}
              </button>
              {idea && <button className="btn btn-ghost btn-danger push-right" disabled={busy !== null} onClick={removeDraft}>Excluir rascunho</button>}
            </>
          )}
          {ok && <span className="muted save-ok">{ok}</span>}
          {!sent && !open && <small className="muted save-ok">O envio só é liberado durante o período de inscrição.</small>}
        </div>
      </div>
    </Layout>
  )
}

function FieldInput({ field: f, value, onChange, file, busy, maxMb, onUpload, onRemove }: {
  field: CampaignField; value: AnswerValue; onChange: (v: AnswerValue) => void
  file?: { file_name: string | null; file_size: number | null }; busy: boolean; maxMb: number
  onUpload: (file: File) => void; onRemove: () => void
}) {
  const [key, setKey] = useState(0)
  const title = (
    <span className="field-title">
      <span>{f.label}{f.required && <span className="req">*</span>}</span>
      {f.help_text && <small className="help">{f.help_text}</small>}
    </span>
  )
  if (f.kind === 'texto_curto') return <label>{title}<input maxLength={300} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} /></label>
  if (f.kind === 'texto_longo') return <label>{title}<textarea rows={5} maxLength={5000} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} /></label>
  if (f.kind === 'lista') {
    return (
      <label>{title}
        <select value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">Escolha…</option>
          {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    )
  }
  if (f.kind === 'sim_nao') {
    return (
      <fieldset className="choices choices-inline">
        <legend>{title}</legend>
        {[true, false].map((v) => (
          <label key={String(v)} className={`choice${value === v ? ' choice-on' : ''}`}>
            <input type="radio" name={f.id} checked={value === v} onChange={() => onChange(v)} /> {v ? 'Sim' : 'Não'}
          </label>
        ))}
      </fieldset>
    )
  }
  return (
    <div className="file-field">
      <span className="file-label">{title}</span>
      {file?.file_name && <span className="file-current">📎 {file.file_name} <small className="muted">{fmtSize(file.file_size)}</small></span>}
      <div className="actions">
        <label className="btn btn-ghost btn-sm file-btn">{busy ? 'Enviando…' : file?.file_name ? 'Trocar arquivo' : 'Escolher arquivo'}
          <input key={key} type="file" disabled={busy} accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx,.pptx"
            onChange={(e) => { const chosen = e.target.files?.[0]; if (chosen) onUpload(chosen); setKey((k) => k + 1) }} />
        </label>
        {file?.file_name && <button type="button" className="btn btn-ghost btn-sm btn-danger" disabled={busy} onClick={onRemove}>Remover</button>}
      </div>
      <small className="muted">PDF, imagem, Word, Excel ou PowerPoint, até {maxMb} MB.</small>
    </div>
  )
}

function Coauthors({ people, onChange }: { people: Person[]; onChange: (p: Person[]) => void }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Person[]>([])
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    window.clearTimeout(timer.current)
    if (q.trim().length < 2) { setResults([]); return }
    timer.current = window.setTimeout(() => {
      api<Person[]>(`/api/ideas/people?q=${encodeURIComponent(q.trim())}`).then(setResults).catch(() => setResults([]))
    }, 250)
  }, [q])
  const chosen = new Set(people.map((p) => p.id))
  return (
    <section className="card">
      <h2>Coautores</h2>
      <p className="muted">Opcional. Inclua colegas que criaram a ideia com você (até 10). Busque pelo nome ou pela matrícula.</p>
      {people.length > 0 && (
        <ul className="chips">
          {people.map((p) => (
            <li key={p.id} className="chip">{p.name}{p.sector && <small> · {p.sector}</small>}
              <button type="button" aria-label={`Remover ${p.name}`} onClick={() => onChange(people.filter((x) => x.id !== p.id))}>×</button>
            </li>
          ))}
        </ul>
      )}
      {people.length < 10 && (
        <div className="form">
          <input placeholder="Nome ou matrícula" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar coautor" />
          {results.length > 0 && (
            <ul className="search-results">
              {results.filter((p) => !chosen.has(p.id)).map((p) => (
                <li key={p.id}><button type="button" onClick={() => { onChange([...people, p]); setQ('') }}>
                  <strong>{p.name}</strong>{p.sector && <small className="muted"> · {p.sector}</small>}
                </button></li>
              ))}
            </ul>
          )}
          {q.trim().length >= 2 && results.length === 0 && <small className="muted">Ninguém encontrado na lista de autorizados.</small>}
        </div>
      )}
    </section>
  )
}
