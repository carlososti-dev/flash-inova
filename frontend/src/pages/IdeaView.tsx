import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, download, fmtDateTime, fmtSize, type Idea, type IdeaAnswer } from '../api'
import { Layout, Notice } from '../components'

/** Ideia em modo leitura: para coautores, para quem acompanha o processo e para o autor depois das inscrições. */
export default function IdeaView() {
  const { id } = useParams()
  const [idea, setIdea] = useState<Idea | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api<Idea>(`/api/ideas/${id}`).then(setIdea).catch((e) => setError(e instanceof Error ? e.message : 'Erro ao carregar.'))
  }, [id])

  if (!idea) return <Layout>{error ? <Notice kind="error">{error}</Notice> : <p className="muted">Carregando…</p>}</Layout>
  const back = idea.role === 'acompanha' ? { to: '/classificacao', label: '← Classificação' } : { to: '/minhas-ideias', label: '← Minhas ideias' }
  return (
    <Layout>
      <article className="stack idea-view">
        <div>
          <p><Link className="link" to={back.to}>{back.label}</Link></p>
          <span className={`stage stage-${idea.stage}`}>{idea.stage_label}</span>
          <h1>{idea.number && <span className="muted">#{idea.number} </span>}{idea.title}</h1>
          <p className="muted">{idea.campaign_title}{idea.line_name && ` · ${idea.line_name}`}</p>
          {idea.can_edit && <Link className="btn btn-primary btn-sm" to={`/ideias/${idea.id}/editar`}>Editar</Link>}
        </div>
        {idea.stage === 'desclassificada' && idea.defense_reasons.length > 0 && (
          <section className="card">
            <h2>Desclassificada na Defesa</h2>
            <ul>{idea.defense_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            {idea.defense_comment && <p className="prose"><strong>Comentário da banca:</strong> {idea.defense_comment}</p>}
          </section>
        )}
        <section className="card">
          <dl className="answers">
            <dt>Autor</dt><dd>{idea.author_name}</dd>
            {idea.coauthors.length > 0 && <><dt>Coautores</dt><dd>{idea.coauthors.map((p) => p.name).join(', ')}</dd></>}
            <dt>Resumo</dt><dd className="prose">{idea.summary || '—'}</dd>
            {idea.answers.map((a) => <Answer key={a.field_id} a={a} fileUrl={`/api/ideas/${idea.id}/files/${a.field_id}`} />)}
          </dl>
        </section>
        <p className="muted">
          {idea.submitted_at ? `Enviada em ${fmtDateTime(idea.submitted_at)}` : 'Rascunho (ainda não enviado)'}
          {idea.regulation_version && ` · regulamento versão ${idea.regulation_version} aceito em ${fmtDateTime(idea.regulation_accepted_at)}`}
        </p>
      </article>
    </Layout>
  )
}

export function Answer({ a, fileUrl }: { a: IdeaAnswer; fileUrl: string }) {
  const [error, setError] = useState<string | null>(null)
  let value: ReactNode = typeof a.value === 'boolean' ? (a.value ? 'Sim' : 'Não') : a.value
  if (a.kind === 'anexo') {
    value = (
      <>
        <button className="link link-btn" onClick={() => download(fileUrl, a.file_name ?? 'anexo')
          .catch((e) => setError(e.message))}>📎 {a.file_name}</button> <small className="muted">{fmtSize(a.file_size)}</small>
        {error && <Notice kind="error">{error}</Notice>}
      </>
    )
  }
  return <><dt>{a.label}</dt><dd className="prose">{value}</dd></>
}
