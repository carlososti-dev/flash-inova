import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api, DEFENSE_REASON_LABELS, fmtDateTime, STAGE_LABELS, type Defense, type DefenseIdea, type DefenseReason,
} from '../api'
import { Notice } from '../components'

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')
const RESULT_TAG: Partial<Record<string, string>> = { em_defesa: 'tag tag-wait', shortlist: 'tag tag-ok', desclassificada: 'tag tag-muted' }
const RESULT_LABEL: Partial<Record<string, string>> = { em_defesa: 'Aguardando parecer', shortlist: 'Viável (Shortlist)', desclassificada: 'Desclassificada' }
const REASONS = Object.keys(DEFENSE_REASON_LABELS) as DefenseReason[]

/** Defesa: fechar a Classificação (quem entra), parecer da banca para cada ideia e fechar a Defesa. */
export default function DefensePanel({ campaignId, onChange }: { campaignId: string | null; onChange: () => void }) {
  const [data, setData] = useState<Defense | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const apply = (d: Defense) => { setData(d); setChosen(new Set(d.candidates.filter((c) => c.suggested).map((c) => c.id))) }
  const load = useCallback(async () => {
    try { apply(await api<Defense>(`/api/defense${campaignId ? `?campaign_id=${campaignId}` : ''}`)); setError(null) }
    catch (e) { setError(errText(e)) }
  }, [campaignId])
  useEffect(() => { load() }, [load])

  async function act(path: string, body: unknown, question: string, message: string) {
    if (!data?.campaign_id || !window.confirm(question)) return
    setBusy(true); setError(null); setOk(null)
    try {
      apply(await api<Defense>(`/api/admin/campaigns/${data.campaign_id}/defense/${path}`, { method: 'POST', json: body }))
      setOk(message); onChange()
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  if (error && !data) return <Notice kind="error">{error}</Notice>
  if (!data) return <p className="muted">Carregando…</p>
  if (!data.campaign_id) return <section className="card"><p className="muted">Nenhuma campanha publicada ainda.</p></section>

  const phase = data.current_phase
  const toggle = (id: string) => { const next = new Set(chosen); if (next.has(id)) next.delete(id); else next.add(id); setChosen(next) }
  const rule = `${data.defense_use_cutoff ? `Classificadas com nota ${data.cutoff_score} ou mais` : 'Todas as Classificadas'}${data.num_defense_finalists ? `, até ${data.num_defense_finalists} ideias` : ''}`
  const viable = data.ideas.filter((i) => i.stage === 'shortlist').length
  const out = data.ideas.filter((i) => i.stage === 'desclassificada').length
  const editable = data.can_manage && phase === 'defesa'
  return (
    <div className="stack">
      <section className="card">
        <h2>Defesa</h2>
        <p className="muted">
          Os autores das ideias classificadas defendem o projeto para a banca (fora do app). A banca dá o parecer de viabilidade:
          as viáveis formam a Shortlist, que segue para a Votação; as desclassificadas ficam registradas com o motivo.
        </p>
        {error && <Notice kind="error">{error}</Notice>}
        {ok && <Notice kind="ok">{ok}</Notice>}
        {(phase === 'recepcao' || phase === 'analise' || (phase === 'classificacao' && data.candidates.length === 0)) && (
          <Notice kind="error">{data.start_blocker ?? 'A Defesa começa depois da apuração e do fechamento da Classificação.'}</Notice>
        )}
        {data.ideas.length > 0 && (
          <p className="stats"><strong>{data.ideas.length}</strong> ideia(s) na Defesa · <strong>{viable}</strong> viável(is) · <strong>{out}</strong> desclassificada(s)</p>
        )}
      </section>

      {phase === 'classificacao' && data.candidates.length > 0 && (
        <section className="card">
          <h2>Fechar Classificação</h2>
          <p className="muted">
            Regra da campanha: <strong>{rule}</strong> (muda em Administração › Campanhas › Regras). As ideias abaixo já vêm marcadas pela regra;
            desmarque ou inclua outras para tratar desistências e empates. Depois de fechar, a Classificação e o Voto de Minerva não mudam mais.
          </p>
          {data.start_blocker && <Notice kind="error">{data.start_blocker}</Notice>}
          <div className="table-wrap">
            <table className="table ranking">
              <thead><tr><th>Entra</th><th>Posição</th><th>Ideia</th><th>Resultado</th><th>Nota</th></tr></thead>
              <tbody>
                {data.candidates.map((c) => (
                  <tr key={c.id} className={chosen.has(c.id) ? 'row-above' : undefined}>
                    <td><input type="checkbox" aria-label={`Incluir #${c.number}`} checked={chosen.has(c.id)} disabled={!data.can_manage} onChange={() => toggle(c.id)} /></td>
                    <td>{c.rank ? <strong>{c.rank}º</strong> : '—'}</td>
                    <td><Link className="link" to={`/ideias/${c.id}`}>#{c.number} {c.title}</Link><br /><small className="muted">{c.author_name}{c.line_name && ` · ${c.line_name}`}</small></td>
                    <td>{STAGE_LABELS[c.stage]}</td>
                    <td>{c.score ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.can_manage
            ? (
              <div className="actions">
                <button className="btn btn-primary" disabled={busy || data.start_blocker !== null || chosen.size === 0}
                  onClick={() => act('start', { idea_ids: [...chosen] },
                    `Fechar a Classificação? ${chosen.size} ideia(s) entram na Defesa e a campanha passa para a fase Defesa. Não dá para desfazer.`,
                    'Classificação fechada: a campanha está na Defesa.')}>
                  {busy ? 'Fechando…' : `Fechar Classificação (${chosen.size} na Defesa)`}
                </button>
              </div>
            )
            : <p className="muted">O fechamento da Classificação é feito pelo administrador.</p>}
        </section>
      )}

      {data.ideas.length > 0 && (
        <section className="card">
          <h2>Parecer da banca</h2>
          {editable && <p className="muted">Lance o parecer que a banca decidiu. Para desclassificar, marque ao menos um motivo e escreva o comentário. Dá para corrigir até fechar a Defesa.</p>}
          <div className="stack">
            {data.ideas.map((i) => <Verdict key={i.id} idea={i} campaignId={data.campaign_id!} editable={editable} onDone={(d) => { apply(d); onChange() }} />)}
          </div>
        </section>
      )}

      {phase === 'defesa' && (
        <section className="card">
          <h2>Fechar Defesa</h2>
          <p className="muted">As viáveis formam a Shortlist e seguem para a Votação. As desclassificadas ficam para o banco de ideias.</p>
          {data.close_blocker && <Notice kind="error">{data.close_blocker}</Notice>}
          {data.can_manage
            ? (
              <div className="actions">
                <button className="btn btn-primary" disabled={busy || data.close_blocker !== null}
                  onClick={() => act('close', undefined,
                    `Fechar a Defesa? ${viable} ideia(s) seguem para a Votação e os pareceres não poderão mais ser alterados.`,
                    'Defesa fechada: a campanha está na Votação.')}>
                  {busy ? 'Fechando…' : 'Fechar Defesa'}
                </button>
              </div>
            )
            : <p className="muted">O fechamento da Defesa é feito pelo administrador.</p>}
        </section>
      )}
    </div>
  )
}

function Verdict({ idea, campaignId, editable, onDone }: { idea: DefenseIdea; campaignId: string; editable: boolean; onDone: (d: Defense) => void }) {
  const [viable, setViable] = useState<boolean | null>(idea.stage === 'em_defesa' ? null : idea.stage === 'shortlist')
  const [reasons, setReasons] = useState<DefenseReason[]>(idea.reasons)
  const [comment, setComment] = useState(idea.comment ?? '')
  const [editing, setEditing] = useState(idea.stage === 'em_defesa')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggle = (r: DefenseReason) => setReasons(reasons.includes(r) ? reasons.filter((x) => x !== r) : [...reasons, r])
  const ready = viable === true || (viable === false && reasons.length > 0 && comment.trim() !== '')
  async function save() {
    setBusy(true); setError(null)
    try {
      onDone(await api<Defense>(`/api/admin/campaigns/${campaignId}/defense/ideas/${idea.id}`, {
        method: 'PUT', json: { viable, reasons: viable ? [] : reasons, comment },
      }))
      setEditing(false)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <article className="minerva">
      <div>
        <span className={RESULT_TAG[idea.stage] ?? 'tag'}>{RESULT_LABEL[idea.stage]}</span>{' '}
        <Link className="link" to={`/ideias/${idea.id}`}><strong>#{idea.number} {idea.title}</strong></Link>
        <small className="muted"> · {idea.author_name}{idea.line_name && ` · ${idea.line_name}`}{idea.rank && ` · ${idea.rank}º na Classificação, nota ${idea.score ?? 0}`}</small>
      </div>
      {idea.stage !== 'em_defesa' && !editing && (
        <p>
          {idea.reasons.length > 0 && <><strong>Motivos:</strong> {idea.reasons.map((r) => DEFENSE_REASON_LABELS[r]).join('; ')}<br /></>}
          {idea.comment && <span className="prose">{idea.comment}<br /></span>}
          <small className="muted">{idea.decided_by} em {fmtDateTime(idea.decided_at)}</small>
          {editable && <><br /><button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>Corrigir parecer</button></>}
        </p>
      )}
      {idea.stage === 'em_defesa' && !editable && <p className="muted">Aguardando o parecer da banca.</p>}
      {editable && editing && (
        <div className="form">
          <fieldset className="choices choices-inline">
            <legend className="sr-only">Parecer da banca</legend>
            <label className={`choice${viable === true ? ' choice-on' : ''}`}>
              <input type="radio" name={`defesa-${idea.id}`} checked={viable === true} onChange={() => setViable(true)} />
              <span><strong>Viável</strong></span>
            </label>
            <label className={`choice${viable === false ? ' choice-on' : ''}`}>
              <input type="radio" name={`defesa-${idea.id}`} checked={viable === false} onChange={() => setViable(false)} />
              <span><strong>Desclassificada</strong></span>
            </label>
          </fieldset>
          {viable === false && (
            <fieldset className="choices">
              <legend><span>Motivo(s)<span className="req">*</span></span></legend>
              {REASONS.map((r) => (
                <label key={r} className={`choice${reasons.includes(r) ? ' choice-on' : ''}`}>
                  <input type="checkbox" checked={reasons.includes(r)} onChange={() => toggle(r)} />
                  <span>{DEFENSE_REASON_LABELS[r]}</span>
                </label>
              ))}
            </fieldset>
          )}
          <label>
            <span>Comentário{viable === false ? <span className="req">*</span> : ' (opcional)'}</span>
            <textarea rows={2} maxLength={5000} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          {error && <Notice kind="error">{error}</Notice>}
          <div className="actions">
            <button className="btn btn-primary btn-sm" disabled={busy || !ready} onClick={save}>{busy ? 'Registrando…' : 'Registrar parecer'}</button>
            {idea.stage !== 'em_defesa' && <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancelar</button>}
          </div>
        </div>
      )}
    </article>
  )
}
