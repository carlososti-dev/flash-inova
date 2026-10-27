// Em desenvolvimento o hospital vem de ?tenant=slug (guardado na aba); em produção, do subdomínio.
const TENANT_KEY = 'flash-tenant'

export function currentTenantOverride(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get('tenant')
  try {
    if (fromUrl !== null) {
      if (fromUrl) sessionStorage.setItem(TENANT_KEY, fromUrl)
      else sessionStorage.removeItem(TENANT_KEY)
      return fromUrl || null
    }
    return sessionStorage.getItem(TENANT_KEY)
  } catch {
    return fromUrl || null
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function errorMessage(body: unknown): string {
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const field = detail[0]?.loc?.at(-1)
    if (field === 'email') return 'Informe um e-mail válido.'
    if (field === 'slug') return 'Endereço inválido: use letras minúsculas, números e hífen.'
    if (field === 'default_role') return 'Perfil inicial deve ser colaborador, membro de comitê ou gestor.'
    if (field === 'name') return 'O nome deve ter pelo menos 2 caracteres.'
    if (field === 'title') return 'O título deve ter pelo menos 3 caracteres.'
    if (field === 'label') return 'O nome do campo deve ter pelo menos 2 caracteres.'
    if (field === 'summary') return 'O resumo deve ter no máximo 2000 caracteres.'
    if (field === 'coauthor_ids') return 'A ideia pode ter no máximo 10 coautores.'
    return 'Confira os campos preenchidos.'
  }
  return 'Não foi possível concluir. Tente novamente.'
}

export async function api<T>(path: string, options: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const tenant = currentTenantOverride()
  if (tenant) headers['X-Tenant'] = tenant
  let body: BodyInit | undefined
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  } else if (options.form) {
    body = options.form
  }
  const res = await fetch(path, { method: options.method ?? (body ? 'POST' : 'GET'), headers, body, credentials: 'same-origin' })
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, errorMessage(data))
  return data as T
}

export type Role = 'consultor' | 'administrador' | 'gestor' | 'membro_comite' | 'colaborador'
export type Theme = 'verde' | 'azul'

export interface TenantPublic { slug: string; name: string; theme: Theme; logo_url: string | null }
export interface SiteInfo { tenant: TenantPublic | null; tenant_active: boolean }
export interface Me { id: string; name: string; email: string; role: Role; role_label: string; tenant: TenantPublic | null }
export interface Message { message: string }
export interface TenantAdmin { id: string; slug: string; name: string; theme: Theme; logo_url: string | null; is_active: boolean; admins: number }
export interface AdminOut { id: string; name: string; email: string; activated: boolean }

export const ROLE_LABELS: Record<Role, string> = {
  consultor: 'Consultor', administrador: 'Administrador', gestor: 'Gestor', membro_comite: 'Membro de comitê', colaborador: 'Colaborador',
}
export type MemberRole = 'colaborador' | 'membro_comite' | 'gestor'
export interface Authorized {
  id: string; matricula: string; name: string; email: string; sector: string | null
  default_role: MemberRole | null; is_active: boolean; registered: boolean
}
export interface AuthorizedPage { items: Authorized[]; total: number; active: number; registered: number }
export interface ImportReport {
  applied: boolean; lines: number; created: number; updated: number; unchanged: number
  errors: { line: number; message: string }[]
}
export type UserStatus = 'ativo' | 'inativo'
export interface UserAdmin {
  id: string; name: string; email: string; matricula: string | null; sector: string | null
  role: Role; role_label: string; status: UserStatus; activated: boolean; created_at: string
}

/** Baixa um arquivo da API (com o hospital no cabeçalho) e entrega ao navegador. */
export async function download(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {}
  const tenant = currentTenantOverride()
  if (tenant) headers['X-Tenant'] = tenant
  const res = await fetch(path, { headers, credentials: 'same-origin' })
  if (!res.ok) throw new ApiError(res.status, 'Não foi possível baixar o arquivo.')
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}

export type CampaignPhase = 'recepcao' | 'analise' | 'classificacao' | 'defesa' | 'votacao' | 'encerrada'
export type SubmissionState = 'antes' | 'aberta' | 'encerrada'
export interface CampaignLine { id: string; name: string; description: string | null; position: number; is_active: boolean }
export interface CampaignSummary {
  id: string; title: string; is_published: boolean; submission_start: string; submission_end: string
  submission_state: SubmissionState; current_phase: CampaignPhase; active_lines: number
}
export interface CampaignAdmin extends CampaignSummary {
  analysis_start: string | null; analysis_end: string | null; classification_end: string | null
  defense_date: string | null; voting_start: string | null; voting_end: string | null
  home_headline: string | null; home_text: string | null; tips_text: string | null; regulation_text: string | null
  banner_url: string | null; video_url: string | null
  num_evaluators: number; weight_classify: number; weight_maybe: number; cutoff_score: number; blind_review: boolean
  num_defense_finalists: number | null; num_voting_finalists: number | null; num_winners: number
  lines: CampaignLine[]; fields: CampaignField[]; regulation_version: number | null; ideas_submitted: number
}
export interface PhaseInfo { key: string; label: string; start: string | null; end: string | null }
export interface CampaignPublic {
  id: string; title: string; is_published: boolean; home_headline: string | null; home_text: string | null
  tips_text: string | null; regulation_text: string | null; regulation_version: number | null
  regulation_updated_at: string | null; banner_url: string | null; video_embed_url: string | null
  submission_start: string; submission_end: string; submission_state: SubmissionState; current_phase: CampaignPhase
  phases: PhaseInfo[]; num_winners: number; lines: CampaignLine[]
}

export type FieldKind = 'texto_curto' | 'texto_longo' | 'lista' | 'sim_nao' | 'anexo'
export const FIELD_KIND_LABELS: Record<FieldKind, string> = {
  texto_curto: 'Texto curto', texto_longo: 'Texto longo', lista: 'Lista de opções', sim_nao: 'Sim ou não', anexo: 'Anexo',
}
export interface CampaignField {
  id: string; kind: FieldKind; label: string; help_text: string | null; required: boolean
  options: string[] | null; position: number; is_active: boolean; answers: number
}

export type IdeaStage = 'rascunho' | 'recebida' | 'em_analise' | 'empate' | 'classificada' | 'talvez'
  | 'nao_classificada' | 'shortlist' | 'selecionada' | 'premiada'
export type AnswerValue = string | boolean | null
export interface Person { id: string; name: string; sector: string | null }
export interface IdeaForm {
  campaign_id: string; campaign_title: string; submission_state: SubmissionState; submission_start: string
  submission_end: string; lines: CampaignLine[]; fields: CampaignField[]; regulation_version: number | null
  max_attachment_mb: number
}
export interface IdeaSummary {
  id: string; campaign_id: string; campaign_title: string; number: number | null; title: string
  line_name: string | null; stage: IdeaStage; stage_label: string; role: 'autor' | 'coautor' | 'acompanha'
  submitted_at: string | null; updated_at: string; can_edit: boolean
}
export interface IdeaAnswer {
  field_id: string; label: string; kind: FieldKind; value: AnswerValue; file_name: string | null; file_size: number | null
}
export interface Idea extends IdeaSummary {
  line_id: string | null; summary: string | null; author_name: string; answers: IdeaAnswer[]; coauthors: Person[]
  regulation_version: number | null; regulation_accepted_at: string | null
}
export interface BoardCard {
  id: string; number: number | null; title: string; line_name: string | null; author_name: string
  author_sector: string | null; coauthors: number; submitted_at: string | null
  reviews_done: number; reviews_total: number; score: number | null
}
export interface Board {
  campaigns: { id: string; title: string }[]; campaign_id: string | null
  columns: { key: string; label: string; cards: BoardCard[] }[]
}

export type Verdict = 'classificar' | 'talvez' | 'nao_classificar'
export const VERDICT_LABELS: Record<Verdict, string> = { classificar: 'Classificar', talvez: 'Talvez', nao_classificar: 'Não classificar' }
export interface Distribution {
  submission_state: SubmissionState; pending: number; distributed: number; num_evaluators: number; committee: number
  blocker: string | null
  evaluators: { id: string; name: string; sector: string | null; assigned: number; evaluated: number }[]
}
export type EvaluationState = 'antes' | 'aberta' | 'encerrada'
export interface AnalysisBoard {
  overview: boolean; evaluators: { id: string; title: string }[]; evaluator_id: string | null
  campaigns: { id: string; title: string }[]; campaign_id: string | null; evaluation_state: EvaluationState | null
  analysis_start: string | null; analysis_end: string | null
  columns: { key: string; label: string; cards: { assignment_id: string; idea_id: string; evaluator_name: string | null; number: number | null; title: string; line_name: string | null; evaluated_at: string | null }[] }[]
}
export interface Assignment {
  id: string; campaign_title: string; number: number | null; title: string; line_name: string | null
  summary: string | null; answers: IdeaAnswer[]; author_name: string | null; coauthors: string[] | null
  verdict: Verdict | null; comment: string | null; evaluated_at: string | null; evaluation_state: EvaluationState
  analysis_end: string | null; can_evaluate: boolean
}

export const STAGE_LABELS: Record<IdeaStage, string> = {
  rascunho: 'Rascunho', recebida: 'Recebida', em_analise: 'Em análise', empate: 'Empate', classificada: 'Classificada',
  talvez: 'Talvez', nao_classificada: 'Não classificada', shortlist: 'Shortlist', selecionada: 'Selecionada', premiada: 'Premiada',
}
export interface ClassifiedIdea {
  id: string; number: number | null; title: string; line_name: string | null; author_name: string; author_sector: string | null
  stage: IdeaStage; outcome: IdeaStage; classify: number; maybe: number; reject: number; reviews_total: number
  score: number | null; weighted: number; rank: number | null; above_cutoff: boolean
  minerva_verdict: Verdict | null; minerva_comment: string | null; minerva_by: string | null; minerva_at: string | null
  reviews: { verdict: Verdict | null; comment: string | null; evaluator_name: string | null }[]
}
export interface Classification {
  campaigns: { id: string; title: string }[]; campaign_id: string | null; evaluation_state: EvaluationState | null
  analysis_end: string | null; classified_at: string | null; blocker: string | null; pending_reviews: number
  cutoff_score: number; num_defense_finalists: number | null; can_manage: boolean; can_minerva: boolean
  ideas: ClassifiedIdea[]
}
export interface EvaluatorsReport {
  campaigns: { id: string; title: string }[]; campaign_id: string | null; evaluation_state: EvaluationState | null
  analysis_end: string | null; can_remind: boolean; reviews_done: number; reviews_total: number
  evaluators: {
    id: string; name: string; sector: string | null; assigned: number; evaluated: number; pending: number
    last_evaluated_at: string | null; last_reminder_at: string | null
  }[]
  ideas: { id: string; number: number | null; title: string; line_name: string | null; done: number; total: number; pending_evaluators: string[] }[]
}

export const fmtSize = (bytes: number | null) =>
  bytes == null ? '' : bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`

export const PHASE_LABELS: Record<CampaignPhase, string> = {
  recepcao: 'Recepção de ideias', analise: 'Análise', classificacao: 'Classificação', defesa: 'Defesa',
  votacao: 'Votação', encerrada: 'Encerrada',
}

const dateFmt = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
export const fmtDate = (iso: string | null) => (iso ? dateFmt.format(new Date(iso)) : '—')
export const fmtDateTime = (iso: string | null) => (iso ? dateTimeFmt.format(new Date(iso)) : '—')
