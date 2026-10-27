import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fmtDateTime, type EvaluatorsReport } from '../api'
import { Layout, Notice } from '../components'

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')
const DAY = 24 * 60 * 60 * 1000

/** Acompanhamento da análise: quantas ideias cada avaliador ainda tem por avaliar, e o alerta por e-mail. */
export default function Dashboard() {
  const [params, setParams] = useSearchParams()
  const campaign = params.get('campanha')
  const [r, setR] = useState<EvaluatorsReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    try { setR(await api<EvaluatorsReport>(`/api/dashboard/evaluators${campaign ? `?campaign_id=${campaign}` : ''}`)); setError(null) }
    catch (e) { setError(errText(e)) }
  }, [campaign])
  useEffect(() => { load() }, [load])

  const withPending = r?.evaluators.filter((e) => e.pending > 0) ?? []
  const targets = selected.size > 0 ? withPending.filter((e) => selected.has(e.id)) : withPending
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })

  async function remind() {
    if (!r?.campaign_id || targets.length === 0) return
    if (!window.confirm(`Enviar o alerta por e-mail para ${targets.length} avaliador(es) com parecer pendente?`)) return
    setBusy(true); setError(null); setOk(null)
    try {
      const res = await api<{ sent: number; recipients: string[] }>(`/api/admin/campaigns/${r.campaign_id}/reminders`, {
        method: 'POST', json: { evaluator_ids: selected.size > 0 ? [...selected] : null, message: message.trim() || null },
      })
      setOk(`Alerta enviado para ${res.recipients.join(', ')}.`)
      setSelected(new Set()); setMessage('')
      await load()
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  const daysLeft = r?.analysis_end ? Math.ceil((new Date(r.analysis_end).getTime() - Date.now()) / DAY) : null
  const percent = r && r.reviews_total > 0 ? Math.round((r.reviews_done / r.reviews_total) * 100) : 0
  return (
    <Layout>
      <div className="page-head board-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Acompanhamento da análise: quantas ideias cada membro do comitê ainda tem por avaliar.</p>
        </div>
        {r && r.campaigns.length > 1 && (
          <select className="board-select" value={r.campaign_id ?? ''} onChange={(e) => setParams({ campanha: e.target.value })} aria-label="Campanha">
            {r.campaigns.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        )}
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {r && !r.campaign_id && <section className="card"><p className="muted">Nenhuma ideia foi distribuída para o comitê ainda. O relatório aparece depois da distribuição.</p></section>}
      {r?.campaign_id && (
        <div className="stack">
          <div className="kpis">
            <div className="kpi"><strong>{r.reviews_done} de {r.reviews_total}</strong><span>pareceres dados ({percent}%)</span></div>
            <div className="kpi"><strong>{withPending.length}</strong><span>avaliador(es) com pendência</span></div>
            <div className="kpi"><strong>{r.ideas.filter((i) => i.done < i.total).length}</strong><span>ideia(s) aguardando parecer</span></div>
            <div className="kpi">
              <strong>{r.evaluation_state === 'encerrada' ? 'Encerrada' : daysLeft === null ? 'Sem data' : daysLeft <= 0 ? 'Último dia' : `${daysLeft} dia(s)`}</strong>
              <span>{r.analysis_end ? `prazo da análise: ${fmtDateTime(r.analysis_end)}` : 'defina o fim da análise na campanha'}</span>
            </div>
          </div>

          <section className="card">
            <h2>Avaliadores</h2>
            {ok && <Notice kind="ok">{ok}</Notice>}
            <div className="table-wrap">
              <table className="table">
                <thead><tr>{r.can_remind && <th aria-label="Selecionar" />}<th>Avaliador</th><th>Setor</th><th>Ideias</th><th>Avaliadas</th><th>Pendentes</th><th>Último parecer</th><th>Último alerta</th></tr></thead>
                <tbody>
                  {r.evaluators.map((e) => (
                    <tr key={e.id}>
                      {r.can_remind && <td>{e.pending > 0 && <input type="checkbox" aria-label={`Selecionar ${e.name}`} checked={selected.has(e.id)} onChange={() => toggle(e.id)} />}</td>}
                      <td>{e.name}</td>
                      <td>{e.sector ?? '—'}</td>
                      <td>{e.assigned}</td>
                      <td>{e.evaluated}</td>
                      <td>{e.pending > 0 ? <span className="tag tag-wait">{e.pending}</span> : <span className="tag tag-ok">em dia</span>}</td>
                      <td>{fmtDateTime(e.last_evaluated_at)}</td>
                      <td>{fmtDateTime(e.last_reminder_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {r.can_remind ? (
              <div className="form reminder">
                <h3>Alerta por e-mail</h3>
                <p className="muted">Cada avaliador recebe quantas ideias faltam, o prazo e o link para o menu Análise. {selected.size > 0 ? 'Vai só para os selecionados.' : 'Sem seleção, vai para todos com pendência.'}</p>
                <label>
                  <span>Mensagem (opcional)</span>
                  <textarea rows={2} maxLength={2000} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ex.: Faltam poucos dias. Contamos com seu parecer!" />
                </label>
                <div className="actions">
                  <button className="btn btn-primary" disabled={busy || targets.length === 0} onClick={remind}>{busy ? 'Enviando…' : `Enviar alerta para ${targets.length} avaliador(es)`}</button>
                </div>
              </div>
            ) : (
              <p className="muted">{withPending.length === 0 ? 'Todos os avaliadores estão em dia.' : 'O período de análise terminou: pareceres em branco não contam na apuração.'}</p>
            )}
          </section>

          <section className="card">
            <h2>Ideias</h2>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Ideia</th><th>Linha</th><th>Pareceres</th><th>Aguardando</th></tr></thead>
                <tbody>
                  {r.ideas.map((i) => (
                    <tr key={i.id}>
                      <td><Link className="link" to={`/ideias/${i.id}`}>#{i.number} {i.title}</Link></td>
                      <td>{i.line_name ?? '—'}</td>
                      <td>{i.done} de {i.total}</td>
                      <td>{i.pending_evaluators.length > 0 ? i.pending_evaluators.join(', ') : <span className="tag tag-ok">completa</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </Layout>
  )
}
