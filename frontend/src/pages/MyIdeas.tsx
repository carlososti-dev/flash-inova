import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api, fmtDateTime, type IdeaSummary } from '../api'
import { Layout, Notice } from '../components'

/** Ideias da pessoa (como autora ou coautora) e a etapa de cada uma. Nunca mostra quem avaliou. */
export default function MyIdeas() {
  const location = useLocation()
  const sentNumber = (location.state as { sent?: number } | null)?.sent
  const [ideas, setIdeas] = useState<IdeaSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api<IdeaSummary[]>('/api/ideas/mine').then(setIdeas).catch((e) => setError(e instanceof Error ? e.message : 'Erro ao carregar.'))
  }, [])

  return (
    <Layout>
      <div className="page-head">
        <h1>Minhas ideias</h1>
        <p className="muted">As ideias que você escreveu ou de que é coautor, e a etapa em que cada uma está.</p>
      </div>
      {sentNumber && <Notice kind="ok">Ideia #{sentNumber} enviada! Ela já está com a equipe da campanha. Você pode alterá-la até o fim das inscrições.</Notice>}
      {error && <Notice kind="error">{error}</Notice>}
      {ideas === null && !error && <p className="muted">Carregando…</p>}
      {ideas?.length === 0 && (
        <section className="card">
          <p className="muted">Você ainda não tem ideias. Que tal começar pela campanha aberta?</p>
          <Link className="btn btn-primary" to="/">Ver a campanha</Link>
        </section>
      )}
      {ideas && ideas.length > 0 && (
        <ul className="idea-list">
          {ideas.map((i) => (
            <li key={i.id} className="card idea-item">
              <div className="idea-main">
                <span className={`stage stage-${i.stage}`}>{i.stage_label}</span>
                <Link className="idea-title" to={i.can_edit ? `/ideias/${i.id}/editar` : `/ideias/${i.id}`}>
                  {i.number && <span className="muted">#{i.number} </span>}{i.title}
                </Link>
                <small className="muted">
                  {i.campaign_title}{i.line_name && ` · ${i.line_name}`}{i.role === 'coautor' && ' · você é coautor'}
                </small>
                <small className="muted">{i.submitted_at ? `Enviada em ${fmtDateTime(i.submitted_at)}` : `Rascunho salvo em ${fmtDateTime(i.updated_at)}`}</small>
              </div>
              <div className="actions">
                {i.can_edit
                  ? <Link className="btn btn-ghost btn-sm" to={`/ideias/${i.id}/editar`}>{i.stage === 'rascunho' ? 'Continuar' : 'Editar'}</Link>
                  : <Link className="btn btn-ghost btn-sm" to={`/ideias/${i.id}`}>Ver</Link>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Layout>
  )
}
