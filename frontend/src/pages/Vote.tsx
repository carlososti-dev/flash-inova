import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fmtDateTime, type VotePage } from '../api'
import { Brand, Notice, useSubmit } from '../components'
import { useSite } from '../site'

/** Tela de votação: abre pelo QR code no evento ou pelo link na web. Feita para o celular. */
export default function Vote() {
  const [params] = useSearchParams()
  const campaign = params.get('campanha')
  const { site, me } = useSite()
  const [page, setPage] = useState<VotePage | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setPage(await api<VotePage>(`/api/vote${campaign ? `?campaign_id=${campaign}` : ''}`)); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível carregar a votação.') }
  }, [campaign])
  useEffect(() => { load() }, [load, me])

  return (
    <main className="vote">
      <header className="vote-head"><Brand /></header>
      {error && <Notice kind="error">{error}</Notice>}
      {!page && !error && <p className="muted">Carregando…</p>}
      {page && <VoteBody page={page} onChange={setPage} reload={load} tenantActive={site?.tenant_active ?? true} />}
    </main>
  )
}

function VoteBody({ page, onChange, reload, tenantActive }: {
  page: VotePage; onChange: (p: VotePage) => void; reload: () => void; tenantActive: boolean
}) {
  const title = page.campaign_title ?? 'Votação'
  if (!tenantActive) return <section className="card"><h1>{title}</h1><Notice kind="error">O acesso deste hospital está suspenso.</Notice></section>
  if (page.state === 'antes') {
    return (
      <section className="card vote-msg">
        <h1>{title}</h1>
        <p className="vote-big">A votação ainda não começou.</p>
        {page.voting_start && <p className="muted">Abre em {fmtDateTime(page.voting_start)}.</p>}
      </section>
    )
  }
  if (page.state === 'encerrada') {
    return <section className="card vote-msg"><h1>{title}</h1><p className="vote-big">Votação fechada.</p><p className="muted">Obrigado a todos que participaram.</p></section>
  }
  if (!page.voter) return <Identify page={page} onChange={onChange} />
  if (page.voter.voted) return <Thanks page={page} reload={reload} />
  return <Ballot page={page} onChange={onChange} reload={reload} />
}

function Identify({ page, onChange }: { page: VotePage; onChange: (p: VotePage) => void }) {
  const [matricula, setMatricula] = useState('')
  const [code, setCode] = useState('')
  const [hint, setHint] = useState<string | null>(null)
  const ask = useSubmit(async () => {
    const r = await api<{ email_hint: string }>('/api/vote/code', { json: { campaign_id: page.campaign_id, matricula } })
    setHint(r.email_hint)
  })
  const verify = useSubmit(async () => {
    onChange(await api<VotePage>('/api/vote/verify', { json: { campaign_id: page.campaign_id, matricula, code } }))
  })
  const back = `/votacao${page.campaign_id ? `?campanha=${page.campaign_id}` : ''}`

  return (
    <section className="card">
      <h1>{page.campaign_title}</h1>
      <p>Escolha a sua ideia preferida entre as finalistas. <strong>Cada pessoa vota uma vez.</strong></p>
      {page.voting_end && <p className="muted">A votação vai até {fmtDateTime(page.voting_end)}.</p>}
      {hint === null ? (
        <form className="form" onSubmit={ask.onSubmit}>
          <label>Sua matrícula
            <input inputMode="numeric" autoComplete="off" required value={matricula} onChange={(e) => setMatricula(e.target.value)} />
          </label>
          {ask.error && <Notice kind="error">{ask.error}</Notice>}
          <button className="btn btn-primary btn-lg" disabled={ask.busy}>{ask.busy ? 'Enviando…' : 'Receber código por e-mail'}</button>
        </form>
      ) : (
        <form className="form" onSubmit={verify.onSubmit}>
          <Notice kind="ok">Enviamos um código de 6 dígitos para {hint}.</Notice>
          <label>Código
            <input className="code-input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required autoFocus
              value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
          </label>
          {verify.error && <Notice kind="error">{verify.error}</Notice>}
          <button className="btn btn-primary btn-lg" disabled={verify.busy || code.length !== 6}>{verify.busy ? 'Conferindo…' : 'Continuar'}</button>
          <button type="button" className="btn btn-ghost" onClick={() => { setHint(null); setCode('') }}>Trocar matrícula ou pedir outro código</button>
        </form>
      )}
      <p className="auth-links muted">Já tem conta? <Link className="link" to={`/login?proximo=${encodeURIComponent(back)}`}>Entrar com e-mail e senha</Link></p>
    </section>
  )
}

function Ballot({ page, onChange, reload }: { page: VotePage; onChange: (p: VotePage) => void; reload: () => void }) {
  const [choice, setChoice] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const chosen = page.ideas.find((i) => i.id === choice)
  const send = useSubmit(async () => {
    try {
      onChange(await api<VotePage>('/api/vote', { json: { campaign_id: page.campaign_id, idea_id: choice } }))
    } catch (e) {
      reload() // ex.: votou em outro aparelho ou a votação fechou: a tela mostra a situação atual
      throw e
    }
  })

  return (
    <section className="card">
      <h1>{page.campaign_title}</h1>
      <p>Olá, <strong>{page.voter!.name}</strong>. Escolha uma ideia e confirme. Depois de confirmado, o voto não pode ser trocado.</p>
      <form className="form" onSubmit={(e) => { e.preventDefault(); if (choice) setConfirming(true) }}>
        <fieldset className="choices vote-list" disabled={confirming}>
          <legend className="sr-only">Ideias finalistas</legend>
          {page.ideas.map((i) => (
            <label key={i.id} className={`choice vote-option${choice === i.id ? ' choice-on' : ''}`}>
              <input type="radio" name="ideia" checked={choice === i.id} onChange={() => setChoice(i.id)} />
              <span>
                <strong>{i.title}</strong>
                <small>{[i.author_name, ...i.coauthors].join(', ')}{i.line_name && ` · ${i.line_name}`}</small>
                {i.summary && <span className="vote-summary">{i.summary}</span>}
              </span>
            </label>
          ))}
        </fieldset>
        {!confirming && <button className="btn btn-primary btn-lg vote-send" disabled={!choice}>Votar</button>}
      </form>
      {confirming && chosen && (
        <form className="vote-confirm" onSubmit={send.onSubmit} aria-label="Confirmar voto">
          <p>Confirmar seu voto em <strong>{chosen.title}</strong>?</p>
          {send.error && <Notice kind="error">{send.error}</Notice>}
          <div className="actions">
            <button className="btn btn-primary btn-lg" disabled={send.busy}>{send.busy ? 'Registrando…' : 'Confirmar voto'}</button>
            <button type="button" className="btn btn-ghost" disabled={send.busy} onClick={() => setConfirming(false)}>Voltar</button>
          </div>
        </form>
      )}
    </section>
  )
}

function Thanks({ page, reload }: { page: VotePage; reload: () => void }) {
  async function exit() {
    await api('/api/vote/exit', { method: 'POST' })
    reload()
  }
  return (
    <section className="card vote-msg">
      <h1>{page.campaign_title}</h1>
      <p className="vote-big">Voto registrado. Obrigado!</p>
      {page.voter!.method === 'codigo' && (
        <>
          <p className="muted">Está usando um aparelho de outra pessoa? Saia para que ela também possa votar.</p>
          <button className="btn btn-ghost" onClick={exit}>Sair</button>
        </>
      )}
    </section>
  )
}
