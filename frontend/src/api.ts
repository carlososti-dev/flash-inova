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
