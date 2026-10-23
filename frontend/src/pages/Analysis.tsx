import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fmtDateTime, type AnalysisBoard } from '../api'
import { Layout, Notice } from '../components'

/** Kanban pessoal do avaliador: as ideias distribuídas a ele, por parecer. */
export default function Analysis() {
  const [params, setParams] = useSearchParams()
  const campaign = params.get('campanha')
  const evaluator = params.get('avaliador')
  const [board, setBoard] = useState<AnalysisBoard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    const query = new URLSearchParams()
    if (campaign) query.set('campaign_id', campaign)
    if (evaluator) query.set('evaluator_id', evaluator)
    try { setBoard(await api<AnalysisBoard>(`/api/analysis?${query}`)); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : 'Erro ao carregar.') }
  }, [campaign, evaluator])
  useEffect(() => { load() }, [load])

  const total = board?.columns.reduce((n, c) => n + c.cards.length, 0) ?? 0
  const pending = board?.columns[0]?.cards.length ?? 0
  return (
    <Layout>
      <div className="page-head board-head">
        <div>
          <h1>Análise</h1>
          <p className="muted">
            {board?.overview
              ? 'Acompanhamento das avaliações: um cartão por ideia e avaliador, na coluna do parecer que ele deu. Só leitura.'
              : 'As ideias distribuídas para você. Leia cada uma e dê seu parecer; dentro do período de análise você pode mudar de ideia quantas vezes precisar.'}
          </p>
        </div>
        <div className="board-filters">
          {board && board.campaigns.length > 1 && (
            <select className="board-select" value={board.campaign_id ?? ''} onChange={(e) => setParams({ campanha: e.target.value })} aria-label="Campanha">
              {board.campaigns.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
          )}
          {board?.overview && board.evaluators.length > 0 && (
            <select className="board-select" value={evaluator ?? ''} aria-label="Avaliador"
              onChange={(e) => setParams({ ...(board.campaign_id ? { campanha: board.campaign_id } : {}), ...(e.target.value ? { avaliador: e.target.value } : {}) })}>
              <option value="">Todos os avaliadores</option>
              {board.evaluators.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
            </select>
          )}
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {board && !board.campaign_id && (
        <section className="card"><p className="muted">{board.overview
          ? 'Nenhuma ideia foi distribuída ainda. Faça a distribuição em Administração › Campanhas › Configurar.'
          : 'Nenhuma ideia foi distribuída para você ainda. Elas aparecem aqui quando a administração fizer a distribuição.'}</p></section>
      )}
      {board?.campaign_id && (
        <>
          {board.evaluation_state === 'aberta' && (
            <p className="muted">{board.overview ? `${total - pending} de ${total} pareceres dados` : pending === 0 ? (total === 1 ? 'Você já deu parecer na sua ideia.' : `Você já deu parecer nas ${total} ideias.`) : `${pending} de ${total} aguardando seu parecer`}
              {board.analysis_end && ` · prazo: ${fmtDateTime(board.analysis_end)}`}</p>
          )}
          {board.evaluation_state === 'antes' && <Notice kind="ok">A análise começa em {fmtDateTime(board.analysis_start)}. Até lá você já pode ler as ideias.</Notice>}
          {board.evaluation_state === 'encerrada' && <Notice kind="error">O período de análise terminou. Os pareceres ficam só para consulta.</Notice>}
          <div className="board board-4" role="list">
            {board.columns.map((col) => (
              <section key={col.key} className={`board-col col-${col.key}${col.cards.length === 0 ? ' board-col-empty' : ''}`} role="listitem" aria-label={col.label}>
                <h2>{col.label} <span className="count">{col.cards.length}</span></h2>
                {col.cards.map((card) => (
                  <Link key={card.assignment_id} to={board.overview ? `/ideias/${card.idea_id}` : `/analise/${card.assignment_id}`} className="board-card">
                    <small className="muted">#{card.number}{card.evaluator_name && ` · ${card.evaluator_name}`}</small>
                    <strong>{card.title}</strong>
                    {card.line_name && <span className="tag tag-info">{card.line_name}</span>}
                    {card.evaluated_at && <small className="muted">parecer em {fmtDateTime(card.evaluated_at)}</small>}
                  </Link>
                ))}
              </section>
            ))}
          </div>
        </>
      )}
    </Layout>
  )
}
