import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, fmtDate, fmtDateTime, type CampaignPublic, type PhaseInfo } from '../api'
import { Layout, Notice } from '../components'
import { useSite } from '../site'

function useCampaign(id?: string) {
  const [campaign, setCampaign] = useState<CampaignPublic | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api<CampaignPublic | null>(id ? `/api/campaigns/${id}` : '/api/campaigns/current')
      .then(setCampaign)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setCampaign(null)
        else setError(e instanceof Error ? e.message : 'Não foi possível carregar a campanha.')
      })
  }, [id])
  return { campaign, error }
}

export default function Home() {
  const { id } = useParams()
  const { me } = useSite()
  const { campaign, error } = useCampaign(id)
  const manager = me?.role === 'administrador' || me?.role === 'consultor'

  if (error) return <Layout><Notice kind="error">{error}</Notice></Layout>
  if (campaign === undefined) return <Layout><p className="muted">Carregando…</p></Layout>
  if (campaign === null) {
    return (
      <Layout>
        <section className="card">
          <h1>Olá, {me?.name}</h1>
          <p className="muted">{id ? 'Campanha não encontrada.' : 'Ainda não há uma campanha de ideias publicada. Volte em breve!'}</p>
          {manager && <Link className="btn btn-primary" to="/administracao?aba=campanhas">Configurar uma campanha</Link>}
        </section>
      </Layout>
    )
  }
  return <Layout><CampaignPage c={campaign} /></Layout>
}

/** Texto digitado pelo administrador: parágrafos por quebra de linha, sem HTML. */
function Paragraphs({ text }: { text: string }) {
  return <>{text.split(/\n{2,}/).map((p, i) => <p key={i} className="prose">{p}</p>)}</>
}

function CampaignPage({ c }: { c: CampaignPublic }) {
  const tips = (c.tips_text ?? '').split('\n').map((t) => t.replace(/^[-•*]\s*/, '').trim()).filter(Boolean)
  const open = c.submission_state === 'aberta'
  return (
    <div className="campaign">
      {!c.is_published && <Notice kind="error">Pré-visualização: esta campanha ainda é um rascunho e só quem administra consegue vê-la.</Notice>}
      <header className={`hero${c.banner_url ? ' hero-image' : ''}`}>
        {c.banner_url ? <img src={c.banner_url} alt={c.title} /> : <h1>{c.title}</h1>}
      </header>
      {c.banner_url && <h1 className="campaign-title">{c.title}</h1>}
      {c.home_headline && <p className="headline">{c.home_headline}</p>}

      <section className={`card period period-${c.submission_state}`}>
        {c.submission_state === 'antes' && <><strong>As inscrições abrem em {fmtDateTime(c.submission_start)}</strong><span>e vão até {fmtDateTime(c.submission_end)}.</span></>}
        {open && <><strong>Inscrições abertas até {fmtDateTime(c.submission_end)}</strong><span>Período de inscrição de ideias: {fmtDate(c.submission_start)} a {fmtDate(c.submission_end)}.</span></>}
        {c.submission_state === 'encerrada' && <><strong>Inscrições de projetos encerradas</strong><span>O período foi de {fmtDate(c.submission_start)} a {fmtDate(c.submission_end)}.</span></>}
      </section>

      {c.home_text && <section className="card"><Paragraphs text={c.home_text} /></section>}

      {(c.video_embed_url || tips.length > 0) && (
        <div className="media-row">
          {c.video_embed_url && (
            <div className="video">
              <iframe src={c.video_embed_url} title={`Vídeo: ${c.title}`} loading="lazy" allowFullScreen
                allow="accelerometer; encrypted-media; gyroscope; picture-in-picture" referrerPolicy="strict-origin-when-cross-origin" />
            </div>
          )}
          {tips.length > 0 && (
            <section className="card tips">
              <h2>Dicas para uma boa ideia</h2>
              <ul>{tips.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </section>
          )}
        </div>
      )}

      {c.lines.length > 0 && (
        <section>
          <h2>Temáticas</h2>
          <p className="muted">Toda ideia pertence a uma destas linhas.</p>
          <div className="lines-grid">
            {c.lines.map((l, i) => (
              <div key={l.id} className="line-card">
                <span className="line-num">{i + 1}</span>
                <strong>{l.name}</strong>
                {l.description && <small>{l.description}</small>}
              </div>
            ))}
          </div>
        </section>
      )}

      <Timeline phases={c.phases} />

      <div className="cta">
        {c.regulation_text && <Link className="link" to={`/campanhas/${c.id}/regulamento`}>Leia o regulamento</Link>}
        {open
          ? <Link className="btn btn-primary btn-lg" to={`/ideias/nova?campanha=${c.id}`}>Enviar projeto</Link>
          : <button className="btn btn-primary btn-lg" disabled>Enviar projeto</button>}
        {!open && <small className="muted">{c.submission_state === 'antes' ? 'O botão é liberado quando as inscrições abrirem.' : 'Inscrições de projetos encerradas.'}</small>}
      </div>
    </div>
  )
}

function Timeline({ phases }: { phases: PhaseInfo[] }) {
  const dated = phases.filter((p) => p.start || p.end)
  if (dated.length <= 1) return null
  const now = Date.now()
  return (
    <section>
      <h2>Calendário</h2>
      <ol className="timeline">
        {dated.map((p) => {
          const last = p.end ?? p.start!
          const done = new Date(last).getTime() < now
          const when = p.start && p.end
            ? (fmtDate(p.start) === fmtDate(p.end) ? `${fmtDateTime(p.start)} às ${new Date(p.end).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}` : `${fmtDate(p.start)} a ${fmtDate(p.end)}`)
            : p.start ? fmtDate(p.start) : `até ${fmtDate(p.end)}`
          return <li key={p.key} className={done ? 'done' : ''}><strong>{p.label}</strong><span>{when}</span></li>
        })}
      </ol>
    </section>
  )
}

export function Regulation() {
  const { id } = useParams()
  const { campaign, error } = useCampaign(id)
  return (
    <Layout>
      {error && <Notice kind="error">{error}</Notice>}
      {campaign === undefined && !error && <p className="muted">Carregando…</p>}
      {campaign === null && <p className="muted">Campanha não encontrada.</p>}
      {campaign && (
        <article className="card">
          <p><Link className="link" to={campaign.is_published ? '/' : `/campanhas/${campaign.id}`}>← Voltar</Link></p>
          <h1>Regulamento</h1>
          <p className="muted">
            {campaign.title}
            {campaign.regulation_version && <> · versão {campaign.regulation_version}, de {fmtDate(campaign.regulation_updated_at)}</>}
          </p>
          {campaign.regulation_text ? <Paragraphs text={campaign.regulation_text} /> : <p className="muted">O regulamento ainda não foi publicado.</p>}
        </article>
      )}
    </Layout>
  )
}
