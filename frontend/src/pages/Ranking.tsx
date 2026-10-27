import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api, download, fmtDateTime, STAGE_LABELS, VERDICT_LABELS, type Classification, type ClassifiedIdea, type Verdict,
} from '../api'
import { Notice } from '../components'

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')
const RESULT_TAG: Partial<Record<string, string>> = {
  classificada: 'tag tag-ok', talvez: 'tag tag-wait', empate: 'tag tag-info', nao_classificada: 'tag tag-muted',
}

/** Apuração da Classificação: prévia durante a análise, apuração, Voto de Minerva e ranking com linha de corte. */
export default function Ranking({ campaignId, onChange }: { campaignId: string | null; onChange: () => void }) {
  const [data, setData] = useState<Classification | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [cutoff, setCutoff] = useState('')

  const apply = (d: Classification) => { setData(d); setCutoff(String(d.cutoff_score)) }
  const load = useCallback(async () => {
    try { apply(await api<Classification>(`/api/classification${campaignId ? `?campaign_id=${campaignId}` : ''}`)); setError(null) }
    catch (e) { setError(errText(e)) }
  }, [campaignId])
  useEffect(() => { load() }, [load])

  async function run() {
    if (!data?.campaign_id) return
    const blank = data.pending_reviews > 0 ? `\n\n${data.pending_reviews} parecer(es) ficaram em branco e não contam.` : ''
    if (!window.confirm(`Gravar a apuração? Cada ideia passa para o resultado dos pareceres e a campanha entra na fase Classificação. A apuração é feita uma vez só.${blank}`)) return
    setBusy(true); setError(null); setOk(null)
    try {
      apply(await api<Classification>(`/api/admin/campaigns/${data.campaign_id}/classification`, { method: 'POST' }))
      setOk('Apuração gravada.'); onChange()
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  async function saveCutoff() {
    if (!data?.campaign_id) return
    setBusy(true); setError(null); setOk(null)
    try {
      await api(`/api/admin/campaigns/${data.campaign_id}`, { method: 'PATCH', json: { cutoff_score: Number(cutoff) } })
      await load(); setOk(`Linha de corte: nota ${cutoff}.`)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  if (error && !data) return <Notice kind="error">{error}</Notice>
  if (!data) return <p className="muted">Carregando…</p>
  if (!data.campaign_id) return <section className="card"><p className="muted">Nenhuma campanha publicada ainda.</p></section>
  if (data.ideas.length === 0) return <section className="card"><p className="muted">Nenhuma ideia foi distribuída para o comitê ainda. A apuração usa os pareceres da Análise.</p></section>

  const applied = data.classified_at !== null
  const ties = data.ideas.filter((i) => applied && (i.stage === 'empate' || i.minerva_verdict))
  const ranked = data.ideas.filter((i) => i.rank !== null)
  const above = ranked.filter((i) => i.above_cutoff).length
  const cutIndex = data.ideas.findIndex((i) => i.rank === null || !i.above_cutoff)
  const cutoffChanged = cutoff !== String(data.cutoff_score)
  return (
    <div className="stack">
      <section className="card">
        <h2>Apuração</h2>
        <p className="muted">
          Pareceres a favor (Classificar + Talvez) contra Não classificar. Mais a favor: Classificada (ou Talvez, se houver mais Talvez que Classificar);
          mais contra: Não classificada; empate: Voto de Minerva do administrador. A nota de 0 a 100 ordena o ranking.
        </p>
        {error && <Notice kind="error">{error}</Notice>}
        {ok && <Notice kind="ok">{ok}</Notice>}
        {applied
          ? <p className="stats">Apurada em <strong>{fmtDateTime(data.classified_at)}</strong> · <strong>{ranked.length}</strong> classificada(s), <strong>{above}</strong> acima da linha de corte</p>
          : (
            <>
              <Notice kind={data.blocker ? 'error' : 'ok'}>
                {data.blocker ?? 'A análise terminou: a apuração está liberada.'}
                {data.evaluation_state !== 'encerrada' && data.analysis_end && ` Fim da análise: ${fmtDateTime(data.analysis_end)}.`}
                {' '}Abaixo, a prévia com os pareceres dados até agora.
              </Notice>
              {data.pending_reviews > 0 && <p className="muted">{data.pending_reviews} parecer(es) em branco. Na apuração, eles não contam. Para cobrar os avaliadores, use o Dashboard.</p>}
              {data.can_manage && (
                <div className="actions">
                  <button className="btn btn-primary" disabled={busy || data.blocker !== null} onClick={run}>{busy ? 'Apurando…' : 'Apurar classificação'}</button>
                </div>
              )}
            </>
          )}
        <div className="cutoff-row">
          <label>
            <span>Linha de corte (nota mínima)</span>
            <input type="number" min={0} max={100} value={cutoff} disabled={!data.can_manage} onChange={(e) => setCutoff(e.target.value)} />
          </label>
          {data.can_manage && <button className="btn btn-ghost btn-sm" disabled={busy || !cutoffChanged || cutoff === ''} onClick={saveCutoff}>Salvar linha de corte</button>}
          <button className="btn btn-ghost btn-sm" onClick={() => download(`/api/classification.csv?campaign_id=${data.campaign_id}`, 'classificacao.csv').catch((e) => setError(errText(e)))}>Exportar CSV</button>
        </div>
        {data.num_defense_finalists && <small className="muted">Shortlist da Defesa: as {data.num_defense_finalists} primeiras do ranking (próxima fase).</small>}
      </section>

      {ties.length > 0 && (
        <section className="card">
          <h2>Voto de Minerva</h2>
          <p className="muted">Ideias empatadas. O voto do administrador entra como um parecer a mais, desfaz o empate e define a nota. Fica registrado na auditoria e pode ser revisto enquanto a campanha estiver na Classificação.</p>
          <div className="stack">
            {ties.map((i) => <Minerva key={i.id} idea={i} campaignId={data.campaign_id!} canVote={data.can_minerva} onDone={(d) => { apply(d); onChange() }} />)}
          </div>
        </section>
      )}

      <section className="card">
        <h2>{applied ? 'Ranking' : 'Prévia do ranking'}</h2>
        <div className="table-wrap">
          <table className="table ranking">
            <thead><tr><th>Posição</th><th>Ideia</th><th>Resultado</th><th>Nota</th><th title="Classificar / Talvez / Não classificar">C / T / Nc</th><th>Pontos</th></tr></thead>
            <tbody>
              {data.ideas.map((i, idx) => (
                <Fragment key={i.id}>
                  {idx === cutIndex && ranked.length > 0 && (
                    <tr className="cutoff-line"><td colSpan={6}>Linha de corte: nota {data.cutoff_score}</td></tr>
                  )}
                  <tr className={i.rank !== null && i.above_cutoff ? 'row-above' : undefined}>
                    <td>{i.rank !== null ? <strong>{i.rank}º</strong> : '—'}</td>
                    <td>
                      <Link className="link" to={`/ideias/${i.id}`}>#{i.number} {i.title}</Link>
                      <br /><small className="muted">{i.author_name}{i.line_name && ` · ${i.line_name}`}</small>
                    </td>
                    <td><span className={RESULT_TAG[i.outcome] ?? 'tag'}>{STAGE_LABELS[i.outcome]}</span>{i.minerva_verdict && <small className="muted"> (Minerva)</small>}</td>
                    <td>{i.score ?? '—'}</td>
                    <td>{i.classify} / {i.maybe} / {i.reject}{blankOf(i) > 0 && <small className="muted"> +{blankOf(i)} em branco</small>}</td>
                    <td>{i.weighted}</td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <small className="muted">Empate na nota: vence quem tem mais pontos (Classificar e Talvez com os pesos da campanha), depois o número da ideia.</small>
      </section>
    </div>
  )
}

const blankOf = (i: ClassifiedIdea) => i.reviews.filter((r) => r.verdict === null).length

const OPTIONS: Verdict[] = ['classificar', 'talvez', 'nao_classificar']

function Minerva({ idea, campaignId, canVote, onDone }: { idea: ClassifiedIdea; campaignId: string; canVote: boolean; onDone: (d: Classification) => void }) {
  const [verdict, setVerdict] = useState<Verdict | null>(idea.minerva_verdict)
  const [comment, setComment] = useState(idea.minerva_comment ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(idea.minerva_verdict === null)

  async function save() {
    setBusy(true); setError(null)
    try {
      onDone(await api<Classification>(`/api/admin/campaigns/${campaignId}/classification/ideas/${idea.id}/minerva`, { method: 'PUT', json: { verdict, comment } }))
      setEditing(false)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  return (
    <article className="minerva">
      <div>
        <Link className="link" to={`/ideias/${idea.id}`}><strong>#{idea.number} {idea.title}</strong></Link>
        <small className="muted"> · {idea.author_name}{idea.line_name && ` · ${idea.line_name}`}</small>
      </div>
      <ul className="reviews">
        {idea.reviews.map((r, k) => (
          <li key={k}>
            <span className={`stage ${r.verdict ? `verdict-${r.verdict}` : 'stage-rascunho'}`}>{r.verdict ? VERDICT_LABELS[r.verdict] : 'Sem parecer'}</span>
            {r.evaluator_name && <small className="muted"> {r.evaluator_name}</small>}
            {r.comment && <p className="prose">{r.comment}</p>}
          </li>
        ))}
      </ul>
      {idea.minerva_verdict && !editing && (
        <p>
          <strong>Voto de Minerva: {VERDICT_LABELS[idea.minerva_verdict]}</strong> → {STAGE_LABELS[idea.outcome]}, nota {idea.score ?? 0}
          <br /><small className="muted">{idea.minerva_by} em {fmtDateTime(idea.minerva_at)}: {idea.minerva_comment}</small>
          {canVote && <><br /><button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>Rever voto</button></>}
        </p>
      )}
      {!idea.minerva_verdict && !canVote && <p className="muted">Aguardando o Voto de Minerva do administrador.</p>}
      {canVote && editing && (
        <div className="form">
          <fieldset className="choices verdicts">
            <legend className="sr-only">Voto de Minerva</legend>
            {OPTIONS.map((v) => (
              <label key={v} className={`choice verdict-choice verdict-${v}${verdict === v ? ' choice-on' : ''}`}>
                <input type="radio" name={`minerva-${idea.id}`} checked={verdict === v} onChange={() => setVerdict(v)} />
                <span><strong>{VERDICT_LABELS[v]}</strong></span>
              </label>
            ))}
          </fieldset>
          <label>
            <span>Justificativa<span className="req">*</span></span>
            <textarea rows={2} maxLength={5000} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          {error && <Notice kind="error">{error}</Notice>}
          <div className="actions">
            <button className="btn btn-primary btn-sm" disabled={busy || !verdict || !comment.trim()} onClick={save}>{busy ? 'Registrando…' : 'Registrar Voto de Minerva'}</button>
            {idea.minerva_verdict && <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancelar</button>}
          </div>
        </div>
      )}
    </article>
  )
}
