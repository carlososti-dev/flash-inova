import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, fmtDateTime, VERDICT_LABELS, type Assignment, type Verdict } from '../api'
import { Layout, Notice } from '../components'
import { Answer } from './IdeaView'

const VERDICTS: { value: Verdict; help: string }[] = [
  { value: 'classificar', help: 'A ideia deve seguir no processo.' },
  { value: 'talvez', help: 'Promissora, mas ainda carece de detalhamento. Comentário obrigatório.' },
  { value: 'nao_classificar', help: 'A ideia não deve seguir.' },
]

/** Leitura da ideia e parecer do avaliador. No duplo-cego, autor e coautores não aparecem. */
export default function AssignmentPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [a, setA] = useState<Assignment | null>(null)
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const apply = (data: Assignment) => { setA(data); setVerdict(data.verdict); setComment(data.comment ?? '') }
  useEffect(() => {
    api<Assignment>(`/api/analysis/${id}`).then(apply).catch((e) => setError(e instanceof Error ? e.message : 'Erro ao carregar.'))
  }, [id])

  async function save(value: Verdict | null) {
    setBusy(true); setError(null); setOk(null)
    try {
      const saved = await api<Assignment>(`/api/analysis/${id}`, { method: 'PUT', json: { verdict: value, comment } })
      if (value) {
        // Volta ao kanban, onde o cartão já aparece na coluna do parecer.
        navigate('/analise', { state: { ok: `Parecer registrado em "${saved.title}": ${VERDICT_LABELS[value]}.` } })
        return
      }
      apply(saved)
      setOk('Parecer desfeito: a ideia voltou para "Para análise".')
    } catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível salvar.') }
    finally { setBusy(false) }
  }

  if (!a) return <Layout>{error ? <Notice kind="error">{error}</Notice> : <p className="muted">Carregando…</p>}</Layout>
  const changed = verdict !== a.verdict || comment.trim() !== (a.comment ?? '')
  return (
    <Layout>
      <article className="stack idea-view">
        <div>
          <p><Link className="link" to="/analise">← Análise</Link></p>
          <span className={`stage ${a.verdict ? `verdict-${a.verdict}` : 'stage-rascunho'}`}>{a.verdict ? VERDICT_LABELS[a.verdict] : 'Aguardando seu parecer'}</span>
          <h1>{a.number && <span className="muted">#{a.number} </span>}{a.title}</h1>
          <p className="muted">{a.campaign_title}{a.line_name && ` · ${a.line_name}`}</p>
        </div>
        <section className="card">
          <dl className="answers">
            {a.author_name
              ? <><dt>Autor</dt><dd>{a.author_name}{a.coauthors && a.coauthors.length > 0 && ` (coautores: ${a.coauthors.join(', ')})`}</dd></>
              : <><dt>Autor</dt><dd className="muted">Oculto (avaliação duplo-cego)</dd></>}
            <dt>Resumo</dt><dd className="prose">{a.summary || '—'}</dd>
            {a.answers.map((x) => <Answer key={x.field_id} a={x} fileUrl={`/api/analysis/${a.id}/files/${x.field_id}`} />)}
          </dl>
        </section>

        <section className="card form">
          <h2>Seu parecer</h2>
          {a.evaluation_state === 'antes' && <Notice kind="ok">A análise ainda não começou. Você já pode ler a ideia; o parecer é liberado no início do período.</Notice>}
          {a.evaluation_state === 'encerrada' && <Notice kind="error">O período de análise terminou. O parecer não pode mais mudar.</Notice>}
          <fieldset className="choices verdicts" disabled={!a.can_evaluate}>
            <legend className="sr-only">Parecer</legend>
            {VERDICTS.map((v) => (
              <label key={v.value} className={`choice verdict-choice verdict-${v.value}${verdict === v.value ? ' choice-on' : ''}`}>
                <input type="radio" name="verdict" checked={verdict === v.value} onChange={() => setVerdict(v.value)} />
                <span><strong>{VERDICT_LABELS[v.value]}</strong><small>{v.help}</small></span>
              </label>
            ))}
          </fieldset>
          <label>
            <span>Comentário{verdict === 'talvez' && <span className="req">*</span>}</span>
            <small className="help">{verdict === 'talvez' ? 'Explique o que falta detalhar na ideia.' : 'Opcional.'}</small>
            <textarea rows={4} maxLength={5000} value={comment} disabled={!a.can_evaluate} onChange={(e) => setComment(e.target.value)} />
          </label>
          {error && <Notice kind="error">{error}</Notice>}
          {ok && <Notice kind="ok">{ok}</Notice>}
          {a.can_evaluate && (
            <div className="actions">
              <button className="btn btn-primary" disabled={busy || !verdict || !changed} onClick={() => save(verdict)}>{busy ? 'Salvando…' : 'Salvar parecer'}</button>
              {a.verdict && <button className="btn btn-ghost" disabled={busy} onClick={() => save(null)}>Desfazer parecer</button>}
            </div>
          )}
          {a.evaluated_at && <small className="muted">Último parecer em {fmtDateTime(a.evaluated_at)}{a.analysis_end && a.can_evaluate && ` · você pode mudar até ${fmtDateTime(a.analysis_end)}`}</small>}
        </section>
      </article>
    </Layout>
  )
}
