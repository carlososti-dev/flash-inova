import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDateTime, type Voting, type VotingState } from '../api'
import { Notice } from '../components'

const errText = (e: unknown) => (e instanceof Error ? e.message : 'Não foi possível concluir.')
const pad = (n: number) => String(n).padStart(2, '0')
function toInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const fromInput = (v: string) => (v ? new Date(v).toISOString() : null)

const STATE_TAG: Record<VotingState, [string, string]> = {
  antes: ['tag tag-wait', 'Ainda não aberta'], aberta: ['tag tag-ok', 'Aberta'], encerrada: ['tag tag-muted', 'Fechada'],
}
const MEDALS = ['medal-1', 'medal-2', 'medal-3']
const STEPS = [
  ['Período', 'Defina quando a votação abre e fecha: um dia no evento ou vários dias online.'],
  ['Divulgar', 'Imprima ou projete o QR code. O mesmo link serve para votar pela web.'],
  ['Acompanhar', 'A contagem aparece aqui, ao vivo. Quem vota não vê o placar.'],
  ['Encerrar e apurar', 'As mais votadas são premiadas e a campanha passa para a Premiação.'],
] as const

/** Votação: período, QR code, contagem ao vivo e apuração (pódio). */
export default function VotingPanel({ campaignId, onChange }: { campaignId: string | null; onChange: () => void }) {
  const [data, setData] = useState<Voting | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dates, setDates] = useState({ start: '', end: '' })
  const [copied, setCopied] = useState(false)

  const apply = (d: Voting) => { setData(d); setDates({ start: toInput(d.voting_start), end: toInput(d.voting_end) }) }
  const load = useCallback(async (quiet = false) => {
    try {
      const d = await api<Voting>(`/api/voting${campaignId ? `?campaign_id=${campaignId}` : ''}`)
      if (quiet) setData(d); else apply(d)
      setError(null)
    } catch (e) { setError(errText(e)) }
  }, [campaignId])
  useEffect(() => { load() }, [load])
  // Contagem ao vivo: atualiza a cada 10 segundos enquanto a votação está aberta.
  const live = data?.state === 'aberta'
  useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => load(true), 10000)
    return () => window.clearInterval(timer)
  }, [live, load])

  async function saveDates() {
    if (!data?.campaign_id) return
    setBusy(true); setError(null); setOk(null)
    try {
      await api(`/api/admin/campaigns/${data.campaign_id}`, { method: 'PATCH', json: { voting_start: fromInput(dates.start), voting_end: fromInput(dates.end) } })
      await load(); setOk('Período da votação salvo.')
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  async function close() {
    if (!data?.campaign_id) return
    const early = data.state === 'aberta'
    const question = early
      ? `A votação ainda está aberta até ${fmtDateTime(data.voting_end)}. Encerrar agora e apurar? Ninguém mais poderá votar e não dá para desfazer.`
      : 'Encerrar a votação e apurar o resultado? As mais votadas serão premiadas e não dá para desfazer.'
    if (!window.confirm(question)) return
    setBusy(true); setError(null); setOk(null)
    try {
      apply(await api<Voting>(`/api/admin/campaigns/${data.campaign_id}/voting/close`, { method: 'POST' }))
      setOk('Votação apurada: a campanha está na Premiação.'); onChange()
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  async function copy() {
    if (!data?.vote_url) return
    try { await navigator.clipboard.writeText(data.vote_url); setCopied(true); window.setTimeout(() => setCopied(false), 2000) }
    catch { setError('Não foi possível copiar. Selecione o link e copie manualmente.') }
  }

  if (error && !data) return <Notice kind="error">{error}</Notice>
  if (!data) return <p className="muted">Carregando…</p>
  if (!data.campaign_id) return <section className="card"><p className="muted">Nenhuma campanha publicada ainda.</p></section>

  const phase = data.current_phase
  const ready = phase === 'votacao' || phase === 'encerrada'
  const done = phase === 'encerrada'
  const total = data.ideas.reduce((n, i) => n + i.votes, 0)
  const max = Math.max(1, ...data.ideas.map((i) => i.votes))
  const step = done ? 5 : !data.voting_start || !data.voting_end ? 1 : data.state === 'antes' ? 2 : data.state === 'aberta' ? 3 : 4
  const [tagClass, tagLabel] = STATE_TAG[data.state ?? 'antes']
  const turnout = data.eligible ? Math.round((data.voters / data.eligible) * 100) : null

  return (
    <div className="stack">
      <section className="card">
        <h2>Votação <span className={tagClass}>{tagLabel}</span></h2>
        <p className="muted">
          Todos do hospital votam em uma ideia da Shortlist, pelo QR code no evento ou pelo link na web. Quem tem conta entra com o login;
          quem não tem digita a matrícula e recebe um código por e-mail. Um voto por pessoa, sem troca.
        </p>
        <ol className="steps">
          {STEPS.map(([title, text], k) => (
            <li key={title} className={k + 1 === step ? 'step-on' : k + 1 < step ? 'step-done' : undefined}>
              <strong>{title}</strong>
              <small className="muted">{text}</small>
            </li>
          ))}
        </ol>
        {!ready && <Notice kind="error">A Votação começa depois que a Defesa for fechada.</Notice>}
        {error && <Notice kind="error">{error}</Notice>}
        {ok && <Notice kind="ok">{ok}</Notice>}
      </section>

      {ready && (
        <div className="voting-grid">
          <section className="card">
            <h2>1. Período</h2>
            {data.can_manage && !done ? (
              <div className="form">
                <label>Abre em<input type="datetime-local" value={dates.start} onChange={(e) => setDates({ ...dates, start: e.target.value })} /></label>
                <label>Fecha em<input type="datetime-local" value={dates.end} onChange={(e) => setDates({ ...dates, end: e.target.value })} /></label>
                <div className="actions">
                  <button className="btn btn-primary" disabled={busy || !dates.start || !dates.end} onClick={saveDates}>Salvar período</button>
                </div>
              </div>
            ) : (
              <p>{data.voting_start ? `${fmtDateTime(data.voting_start)} a ${fmtDateTime(data.voting_end)}` : 'Período ainda não definido.'}</p>
            )}
            {done && <p className="muted">Apurada em {fmtDateTime(data.voting_closed_at)}.</p>}
          </section>

          <section className="card qr-card">
            <h2>2. QR code</h2>
            {data.qr_svg && <img className="qr" src={data.qr_svg} alt="QR code da votação" />}
            <p className="qr-link"><a className="link" href={data.vote_url ?? '#'} target="_blank" rel="noreferrer">{data.vote_url}</a></p>
            <div className="actions">
              <button className="btn btn-ghost btn-sm" onClick={copy}>{copied ? 'Link copiado' : 'Copiar link'}</button>
              {data.qr_svg && <a className="btn btn-ghost btn-sm" href={data.qr_svg} download="qrcode-votacao.svg">Baixar QR code</a>}
            </div>
          </section>
        </div>
      )}

      {ready && (
        <section className="card">
          <h2>3. {done ? 'Resultado' : 'Contagem ao vivo'}</h2>
          <p className="stats">
            <strong>{data.voters}</strong> pessoa(s) votaram
            {data.eligible > 0 && <> de <strong>{data.eligible}</strong> na lista de autorizados ({turnout}%)</>}
            {live && <small className="muted"> · atualiza a cada 10 segundos</small>}
          </p>
          <div className="table-wrap">
            <table className="table ranking">
              <thead><tr><th>Posição</th><th>Ideia</th><th>Votos</th><th>Nota da Classificação</th><th>{done ? 'Premiação' : 'Hoje'}</th></tr></thead>
              <tbody>
                {data.ideas.map((i) => (
                  <tr key={i.id} className={i.winner ? 'row-above' : undefined}>
                    <td><strong>{i.position}º</strong></td>
                    <td><Link className="link" to={`/ideias/${i.id}`}>#{i.number} {i.title}</Link><br /><small className="muted">{i.author_name}{i.line_name && ` · ${i.line_name}`}</small></td>
                    <td className="votes-cell">
                      <span className="vote-bar" style={{ width: `${(i.votes / max) * 100}%` }} aria-hidden="true" />
                      <strong>{i.votes}</strong>{total > 0 && <small className="muted"> ({Math.round((i.votes / total) * 100)}%)</small>}
                    </td>
                    <td>{i.score ?? '—'}{i.tied && <><br /><small className="muted">empate nos votos: desempatou pela nota</small></>}</td>
                    <td>
                      {i.award_position
                        ? <span className={`medal ${MEDALS[i.award_position - 1] ?? ''}`}>{i.award_position}º lugar</span>
                        : i.winner ? <span className="tag tag-ok">no pódio</span> : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Premiadas: as {data.num_winners} mais votadas (muda em Administração › Campanhas › Regras). Empate nos votos: vale a maior nota da Classificação.
            Ideia sem voto não é premiada.
          </p>
        </section>
      )}

      {phase === 'votacao' && (
        <section className="card">
          <h2>4. Encerrar e apurar</h2>
          <p className="muted">Pode ser feito no fechamento ou antes dele. As mais votadas viram 1º, 2º e 3º lugar e a campanha passa para a Premiação.</p>
          {data.close_blocker && <Notice kind="error">{data.close_blocker}</Notice>}
          {data.can_manage
            ? <div className="actions"><button className="btn btn-primary" disabled={busy || data.close_blocker !== null} onClick={close}>{busy ? 'Apurando…' : 'Encerrar votação e apurar'}</button></div>
            : <p className="muted">A apuração é feita pelo administrador.</p>}
        </section>
      )}
    </div>
  )
}
