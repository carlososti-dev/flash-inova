import { useEffect, useState } from 'react'
import { api, fmtDate, PHASE_LABELS, type CampaignIndicators, type CampaignPhase, type CampaignsComparison } from '../api'
import { useSearchParams } from 'react-router-dom'
import { Notice, SubTabs } from '../components'

type Value = number | null
type Row = { label: string; hint?: string; from?: CampaignPhase; value: (c: CampaignIndicators, eligible: number) => Value; unit?: '%' | 'dias'; decimals?: number }
type Group = { title: string; rows: Row[] }

const ORDER: CampaignPhase[] = ['recepcao', 'analise', 'classificacao', 'defesa', 'votacao', 'encerrada']
/** A campanha já passou pela fase? Antes disso o indicador não existe (mostra "—", não zero). */
const reached = (c: CampaignIndicators, from?: CampaignPhase) => !from || ORDER.indexOf(c.phase) >= ORDER.indexOf(from)

const pct = (part: number, whole: number): Value => (whole > 0 ? Math.round((1000 * part) / whole) / 10 : null)

const GROUPS: Group[] = [
  {
    title: 'Participação',
    rows: [
      { label: 'Ideias enviadas', value: (c) => c.ideas_sent },
      { label: 'Pessoas participando', hint: 'autores e coautores, sem repetir', value: (c) => c.participants },
      { label: 'Participação', hint: 'pessoas participando ÷ lista de autorizados atual', unit: '%', decimals: 1, value: (c, e) => pct(c.participants, e) },
      { label: 'Setores com ideias', value: (c) => c.sectors },
    ],
  },
  {
    title: 'Funil',
    rows: [
      { label: 'Classificadas', from: 'classificacao', hint: '% das enviadas', unit: '%', decimals: 1, value: (c) => pct(c.classified, c.ideas_sent) },
      { label: 'Foram para a Defesa', from: 'defesa', hint: '% das enviadas', unit: '%', decimals: 1, value: (c) => pct(c.defense, c.ideas_sent) },
      { label: 'Shortlist', from: 'votacao', hint: '% das enviadas', unit: '%', decimals: 1, value: (c) => pct(c.shortlist, c.ideas_sent) },
      { label: 'Premiadas', from: 'encerrada', value: (c) => c.awarded },
    ],
  },
  {
    title: 'Análise',
    rows: [
      { label: 'Avaliadores', value: (c) => c.evaluators },
      { label: 'Pareceres dados', hint: '% dos distribuídos', unit: '%', decimals: 1, value: (c) => pct(c.reviews_done, c.reviews_total) },
      { label: 'Divergência entre avaliadores', hint: 'ideias em que os pareceres não foram iguais', unit: '%', decimals: 1, value: (c) => c.divergence_pct },
      { label: 'Decididas no Voto de Minerva', from: 'classificacao', value: (c) => c.ties },
      { label: 'Nota média da Classificação', from: 'classificacao', decimals: 1, value: (c) => c.avg_score },
    ],
  },
  {
    title: 'Votação',
    rows: [
      { label: 'Pessoas que votaram', from: 'votacao', value: (c) => c.voters },
      { label: 'Participação na votação', from: 'votacao', hint: 'votantes ÷ lista de autorizados atual', unit: '%', decimals: 1, value: (c, e) => pct(c.voters, e) },
    ],
  },
  {
    title: 'Tempo',
    rows: [
      { label: 'Inscrições abertas', unit: 'dias', value: (c) => c.submission_days },
      { label: 'Prazo da análise', unit: 'dias', value: (c) => c.analysis_days },
      { label: 'Ciclo completo', hint: 'do início das inscrições à apuração da votação', unit: 'dias', value: (c) => c.cycle_days },
    ],
  },
]

const num = (v: number, decimals = 0) => v.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: decimals })
const show = (v: Value, row: Row) => (v === null ? '—' : `${num(v, row.decimals)}${row.unit === '%' ? '%' : row.unit === 'dias' ? ' dias' : ''}`)

function Delta({ now, before, row }: { now: Value; before: Value; row: Row }) {
  if (now === null || before === null) return null
  const d = Math.round((now - before) * 10) / 10
  if (d === 0) return <span className="delta">= igual</span>
  const unit = row.unit === '%' ? ' p.p.' : row.unit === 'dias' ? ' dias' : ''
  return <span className="delta">{d > 0 ? '▲ +' : '▼ −'}{num(Math.abs(d), row.decimals)}{unit}</span>
}

const STEPS: { label: string; from?: CampaignPhase; key: keyof Pick<CampaignIndicators, 'ideas_sent' | 'classified' | 'defense' | 'shortlist' | 'awarded'> }[] = [
  { label: 'Enviadas', key: 'ideas_sent' }, { label: 'Classificadas', key: 'classified', from: 'classificacao' },
  { label: 'Defesa', key: 'defense', from: 'defesa' }, { label: 'Shortlist', key: 'shortlist', from: 'votacao' },
  { label: 'Premiadas', key: 'awarded', from: 'encerrada' },
]

/** Um funil por campanha, todos na mesma escala, para comparar o tamanho e a conversão de cada ciclo. */
function Funnels({ campaigns }: { campaigns: CampaignIndicators[] }) {
  const max = Math.max(1, ...campaigns.map((c) => c.ideas_sent))
  return (
    <div className="funnels">
      {campaigns.map((c) => (
        <figure key={c.id} className="funnel">
          <figcaption><strong>{c.title}</strong><span>{PHASE_LABELS[c.phase]}</span></figcaption>
          {STEPS.map((s) => {
            const n = c[s.key]
            const share = pct(n, c.ideas_sent)
            if (!reached(c, s.from)) {
              return (
                <div key={s.key} className="funnel-row" title={`${c.title} · ${s.label}: a campanha ainda não chegou a esta etapa`}>
                  <span className="funnel-label">{s.label}</span><span className="funnel-track funnel-pending" /><span className="funnel-value">—</span>
                </div>
              )
            }
            const tip = `${c.title} · ${s.label}: ${n}${s.key !== 'ideas_sent' && share !== null ? ` (${num(share, 1)}% das enviadas)` : ''}`
            return (
              <div key={s.key} className="funnel-row" title={tip}>
                <span className="funnel-label">{s.label}</span>
                <span className="funnel-track"><span className="funnel-bar" style={{ width: `${(100 * n) / max}%` }} /></span>
                <span className="funnel-value">{n}{s.key !== 'ideas_sent' && share !== null && <small> {num(share, 0)}%</small>}</span>
              </div>
            )
          })}
        </figure>
      ))}
    </div>
  )
}

/** Tabela "nome × campanha" (linhas de ideias ou setores), juntando pelo nome. */
function Breakdown({ title, note, campaigns, pick }: { title: string; note: string; campaigns: CampaignIndicators[]; pick: (c: CampaignIndicators) => { name: string; count: number }[] }) {
  const names = [...new Set(campaigns.flatMap((c) => pick(c).map((x) => x.name)))]
  const total = (name: string) => campaigns.reduce((n, c) => n + (pick(c).find((x) => x.name === name)?.count ?? 0), 0)
  names.sort((a, b) => total(b) - total(a) || a.localeCompare(b, 'pt-BR'))
  return (
    <section className="card">
      <h2>{title}</h2>
      <p className="muted">{note}</p>
      {names.length === 0 ? <p className="muted">Nenhuma ideia enviada ainda.</p> : (
        <div className="table-wrap">
          <table className="table compare-table">
            <thead><tr><th>{title.replace('Ideias por ', '')}</th>{campaigns.map((c) => <th key={c.id}>{c.title}</th>)}</tr></thead>
            <tbody>
              {names.map((name) => (
                <tr key={name}>
                  <td>{name}</td>
                  {campaigns.map((c) => {
                    const n = pick(c).find((x) => x.name === name)?.count ?? 0
                    const share = pct(n, c.ideas_sent)
                    return <td key={c.id}>{n}{n > 0 && share !== null && <small className="muted-inline"> ({num(share, 0)}%)</small>}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** Comparação entre campanhas (ciclos): os mesmos indicadores lado a lado, da mais antiga para a mais recente. */
const VIEWS = [
  { key: 'funil', label: 'Funil' }, { key: 'indicadores', label: 'Indicadores' }, { key: 'linhas', label: 'Linhas e setores' },
] as const
type View = (typeof VIEWS)[number]['key']

export default function CampaignCompare() {
  const [params] = useSearchParams()
  const view: View = VIEWS.find((v) => v.key === params.get('ver'))?.key ?? 'funil'
  const [data, setData] = useState<CampaignsComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api<CampaignsComparison>('/api/dashboard/campaigns').then(setData, (e) => setError(e instanceof Error ? e.message : 'Erro ao carregar.'))
  }, [])

  if (error) return <Notice kind="error">{error}</Notice>
  if (!data) return <p className="muted">Carregando…</p>
  const cs = data.campaigns
  if (cs.length === 0) return <section className="card"><p className="muted">Nenhuma campanha publicada ainda.</p></section>
  return (
    <div className="stack">
      {cs.length === 1 && <p className="notice notice-ok">Só há uma campanha publicada. A variação aparece a partir da segunda.</p>}

      <SubTabs items={VIEWS} value={view} />

      {view === 'funil' && (
      <section className="card">
        <h2>Funil por campanha</h2>
        <p className="muted">Quantas ideias chegaram a cada etapa. As barras usam a mesma escala em todas as campanhas; a porcentagem é sobre as enviadas.</p>
        <Funnels campaigns={cs} />
      </section>
      )}

      {view === 'indicadores' && (
      <section className="card">
        <h2>Indicadores</h2>
        <p className="muted">Cada coluna é uma campanha, da mais antiga para a mais recente. Abaixo de cada número, a variação em relação à campanha anterior. Campanhas em andamento ainda vão mudar; “—” indica uma etapa a que a campanha ainda não chegou.</p>
        <div className="table-wrap">
          <table className="table compare-table">
            <thead>
              <tr>
                <th>Indicador</th>
                {cs.map((c) => <th key={c.id}><span className="compare-title">{c.title}</span><small>{fmtDate(c.submission_start)} · {PHASE_LABELS[c.phase]}</small></th>)}
              </tr>
            </thead>
            <tbody>
              {GROUPS.map((g) => [
                <tr key={g.title} className="compare-group"><td colSpan={cs.length + 1}>{g.title}</td></tr>,
                ...g.rows.map((row) => (
                  <tr key={`${g.title}-${row.label}`}>
                    <td>{row.label}{row.hint && <small className="compare-hint">{row.hint}</small>}</td>
                    {cs.map((c, i) => {
                      const value = (x: CampaignIndicators) => (reached(x, row.from) ? row.value(x, data.eligible) : null)
                      const v = value(c)
                      return (
                        <td key={c.id} className="compare-cell">
                          <strong>{show(v, row)}</strong>
                          {i > 0 && <Delta now={v} before={value(cs[i - 1])} row={row} />}
                        </td>
                      )
                    })}
                  </tr>
                )),
              ])}
            </tbody>
          </table>
        </div>
        <p className="muted small-note">Base da participação: {data.eligible} pessoa(s) ativa(s) na lista de autorizados hoje.</p>
      </section>
      )}

      {view === 'linhas' && <Breakdown title="Ideias por linha" note="Linhas com o mesmo nome em campanhas diferentes ficam na mesma linha da tabela. Entre parênteses, a fatia das ideias da campanha."
        campaigns={cs} pick={(c) => c.by_line} />}
      {view === 'linhas' && <Breakdown title="Ideias por setor" note="Setor do autor principal, como está no cadastro hoje."
        campaigns={cs} pick={(c) => c.by_sector} />}
    </div>
  )
}
