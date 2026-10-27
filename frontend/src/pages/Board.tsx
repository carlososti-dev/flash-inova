import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fmtDate, type Board as BoardData } from '../api'
import { Layout, Notice } from '../components'
import Ranking from './Ranking'

/** Kanban da campanha. Os cartões não são arrastados: mudam de coluna pelas ações do processo. */
export default function Board() {
  const [params, setParams] = useSearchParams()
  const campaign = params.get('campanha')
  const tab = params.get('aba') === 'ranking' ? 'ranking' : 'kanban'
  const setTab = (aba: string) => setParams({ ...(campaign ? { campanha: campaign } : {}), aba }, { replace: true })
  const [board, setBoard] = useState<BoardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    try { setBoard(await api<BoardData>(`/api/board${campaign ? `?campaign_id=${campaign}` : ''}`)); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : 'Erro ao carregar.') }
  }, [campaign])
  useEffect(() => { load() }, [load])

  const total = board?.columns.reduce((n, c) => n + c.cards.length, 0) ?? 0
  return (
    <Layout>
      <div className="page-head board-head">
        <div>
          <h1>Classificação</h1>
          <p className="muted">As ideias enviadas, por etapa. Os cartões avançam pelas ações do processo (distribuir, apurar, Voto de Minerva, selecionar), sem arrastar, para que toda mudança fique registrada.</p>
        </div>
        {board && board.campaigns.length > 1 && (
          <select className="board-select" value={board.campaign_id ?? ''} onChange={(e) => setParams({ campanha: e.target.value, aba: tab })} aria-label="Campanha">
            {board.campaigns.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        )}
      </div>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'kanban'} onClick={() => setTab('kanban')}>Kanban</button>
        <button role="tab" aria-selected={tab === 'ranking'} onClick={() => setTab('ranking')}>Apuração e ranking</button>
      </div>
      {tab === 'ranking' && board && <Ranking campaignId={board.campaign_id} onChange={load} />}
      {error && <Notice kind="error">{error}</Notice>}
      {tab === 'kanban' && board && !board.campaign_id && <section className="card"><p className="muted">Nenhuma campanha publicada ainda.</p></section>}
      {tab === 'kanban' && board?.campaign_id && (
        <>
          <p className="muted">{total === 1 ? '1 ideia enviada' : `${total} ideias enviadas`} · rascunhos não aparecem aqui.</p>
          <div className="board" role="list">
            {board.columns.map((col) => (
              <section key={col.key} className={`board-col${col.cards.length === 0 ? ' board-col-empty' : ''}`} role="listitem" aria-label={col.label}>
                <h2>{col.label} <span className="count">{col.cards.length}</span></h2>
                {col.cards.map((card) => (
                  <Link key={card.id} to={`/ideias/${card.id}`} className="board-card">
                    <small className="muted">#{card.number} · {fmtDate(card.submitted_at)}</small>
                    <strong>{card.title}</strong>
                    {card.line_name && <span className="tag tag-info">{card.line_name}</span>}
                    {card.score !== null && <small><strong>Nota {card.score}</strong></small>}
                    {card.reviews_total > 0 && <small className="muted">pareceres: {card.reviews_done} de {card.reviews_total}</small>}
                    <small>{card.author_name}{card.author_sector && ` · ${card.author_sector}`}{card.coauthors > 0 && ` +${card.coauthors}`}</small>
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
