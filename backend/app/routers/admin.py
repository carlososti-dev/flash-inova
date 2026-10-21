"""Administração do hospital: lista de autorizados e usuários. Toda alteração fica na auditoria."""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..accounts import send_activation
from ..deps import RequestContext, get_context, require_active_tenant, require_roles
from ..models import ROLE_LABELS, AuthorizedMember, Role, Tenant, User, UserStatus
from ..roster import TEMPLATE_CSV, RosterFileError, parse_roster
from ..schemas import (
    AuthorizedIn, AuthorizedOut, AuthorizedPage, AuthorizedUpdate, ImportLineError, ImportReport, Message,
    UserAdminOut, UserAdminUpdate,
)

router = APIRouter(prefix="/api/admin", tags=["administração"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024
PAGE_SIZE = 200


class AdminCtx:
    def __init__(self, actor: User, ctx: RequestContext, tenant: Tenant):
        self.actor, self.db, self.tenant = actor, ctx.db, tenant

    def record(self, action: str, **kwargs) -> None:
        audit.record(self.db, action, actor_id=self.actor.id, tenant_id=self.tenant.id, **kwargs)


def admin_ctx(
    actor: User = Depends(require_roles(Role.administrador, Role.consultor)), ctx: RequestContext = Depends(get_context)
) -> AdminCtx:
    return AdminCtx(actor, ctx, require_active_tenant(ctx))


def _search(column_list, q: str | None):
    if not q or not q.strip():
        return None
    like = f"%{q.strip().lower()}%"
    return or_(*(func.lower(c).like(like) for c in column_list))


# ---------- Lista de autorizados ----------

def _member_out(m: AuthorizedMember) -> AuthorizedOut:
    return AuthorizedOut(id=m.id, matricula=m.matricula, name=m.name, email=m.email, sector=m.sector,
                         default_role=m.default_role, is_active=m.is_active, registered=m.user_id is not None)


@router.get("/authorized", response_model=AuthorizedPage)
def list_authorized(q: str | None = None, situacao: str = "todos", offset: int = 0, a: AdminCtx = Depends(admin_ctx)):
    base = select(AuthorizedMember).where(AuthorizedMember.tenant_id == a.tenant.id)
    count = lambda *where: a.db.scalar(  # noqa: E731
        select(func.count()).select_from(AuthorizedMember).where(AuthorizedMember.tenant_id == a.tenant.id, *where)) or 0
    query = base
    if (cond := _search([AuthorizedMember.matricula, AuthorizedMember.name, AuthorizedMember.email,
                         AuthorizedMember.sector], q)) is not None:
        query = query.where(cond)
    if situacao == "ativos":
        query = query.where(AuthorizedMember.is_active.is_(True))
    elif situacao == "inativos":
        query = query.where(AuthorizedMember.is_active.is_(False))
    elif situacao == "sem_cadastro":
        query = query.where(AuthorizedMember.is_active.is_(True), AuthorizedMember.user_id.is_(None))
    rows = a.db.scalars(query.order_by(AuthorizedMember.name).offset(max(offset, 0)).limit(PAGE_SIZE))
    total = a.db.scalar(select(func.count()).select_from(query.subquery())) or 0
    return AuthorizedPage(items=[_member_out(m) for m in rows], total=total,
                          active=count(AuthorizedMember.is_active.is_(True)),
                          registered=count(AuthorizedMember.user_id.isnot(None)))


def _get_member(a: AdminCtx, member_id: uuid.UUID) -> AuthorizedMember:
    m = a.db.get(AuthorizedMember, member_id)
    if m is None or m.tenant_id != a.tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pessoa não encontrada na lista.")
    return m


DUPLICATE_MEMBER = "Já existe alguém na lista com esta matrícula ou este e-mail."


@router.post("/authorized", response_model=AuthorizedOut, status_code=status.HTTP_201_CREATED)
def add_authorized(body: AuthorizedIn, a: AdminCtx = Depends(admin_ctx)) -> AuthorizedOut:
    m = AuthorizedMember(tenant_id=a.tenant.id, matricula=body.matricula.strip(), name=body.name.strip(),
                         email=str(body.email).lower(), sector=(body.sector or "").strip() or None,
                         default_role=body.default_role)
    a.db.add(m)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_MEMBER)
    a.record("autorizado_incluido", entity="authorized_member", entity_id=m.id, details={"matricula": m.matricula})
    a.db.commit()
    return _member_out(m)


@router.patch("/authorized/{member_id}", response_model=AuthorizedOut)
def update_authorized(member_id: uuid.UUID, body: AuthorizedUpdate, a: AdminCtx = Depends(admin_ctx)) -> AuthorizedOut:
    m = _get_member(a, member_id)
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "email" in changes:
        changes["email"] = changes["email"].lower()
    for field, value in changes.items():
        setattr(m, field, Role(value) if field == "default_role" and value else value)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_MEMBER)
    a.record("autorizado_alterado", entity="authorized_member", entity_id=m.id, details=changes)
    a.db.commit()
    return _member_out(m)


@router.get("/authorized/modelo.csv")
def roster_template(_: AdminCtx = Depends(admin_ctx)) -> Response:
    # BOM no início para o Excel abrir os acentos corretamente.
    return Response("﻿" + TEMPLATE_CSV, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="modelo-lista-de-autorizados.csv"'})


@router.post("/authorized/import", response_model=ImportReport)
async def import_authorized(file: UploadFile = File(...), confirm: bool = Form(False),
                            a: AdminCtx = Depends(admin_ctx)) -> ImportReport:
    """Sem confirm: só confere e devolve o relatório. Com confirm: grava as linhas válidas e ignora as com erro.

    A importação inclui pessoas novas e atualiza nome, e-mail, setor e perfil inicial de quem já está na lista
    (pela matrícula). Não desativa quem ficou fora do arquivo.
    """
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "O arquivo deve ter no máximo 5 MB.")
    try:
        rows, row_errors, lines = parse_roster(data)
    except RosterFileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    existing = list(a.db.scalars(select(AuthorizedMember).where(AuthorizedMember.tenant_id == a.tenant.id)))
    by_matricula = {m.matricula: m for m in existing}
    by_email = {m.email.lower(): m for m in existing}
    errors = [ImportLineError(line=e.line, message=e.message) for e in row_errors]
    created = updated = unchanged = 0
    for row in rows:
        member = by_matricula.get(row.matricula)
        owner = by_email.get(row.email)
        if owner is not None and owner is not member:
            errors.append(ImportLineError(line=row.line, message=(
                f"E-mail já está na lista com outra matrícula ({owner.matricula}).")))
            continue
        new_values = {"name": row.name, "email": row.email, "sector": row.sector, "default_role": row.role}
        if member is None:
            created += 1
            if confirm:
                m = AuthorizedMember(tenant_id=a.tenant.id, matricula=row.matricula, **new_values)
                a.db.add(m)
                by_matricula[row.matricula] = by_email[row.email] = m
        elif any(getattr(member, k) != v for k, v in new_values.items()):
            updated += 1
            if confirm:
                by_email.pop(member.email.lower(), None)
                for k, v in new_values.items():
                    setattr(member, k, v)
                by_email[row.email] = member
        else:
            unchanged += 1
    errors.sort(key=lambda e: e.line)

    if confirm:
        try:
            a.db.flush()
        except IntegrityError:
            a.db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Conflito de matrícula ou e-mail ao gravar. Confira o arquivo e tente de novo.")
        a.record("autorizados_importados", entity="authorized_member", details={
            "arquivo": file.filename, "linhas": lines, "incluidos": created, "atualizados": updated,
            "com_erro": len(errors)})
        a.db.commit()
    return ImportReport(applied=confirm, lines=lines, created=created, updated=updated, unchanged=unchanged,
                        errors=errors)


# ---------- Usuários ----------

def _user_out(u: User) -> UserAdminOut:
    return UserAdminOut(id=u.id, name=u.name, email=u.email, matricula=u.matricula, sector=u.sector, role=u.role,
                        role_label=ROLE_LABELS[u.role], status=u.status, activated=u.email_verified_at is not None,
                        created_at=u.created_at)


@router.get("/users", response_model=list[UserAdminOut])
def list_users(q: str | None = None, role: Role | None = None, situacao: UserStatus | None = None,
               a: AdminCtx = Depends(admin_ctx)) -> list[UserAdminOut]:
    # O Consultor (sem hospital) não aparece aqui.
    query = select(User).where(User.tenant_id == a.tenant.id)
    if (cond := _search([User.name, User.email, User.matricula, User.sector], q)) is not None:
        query = query.where(cond)
    if role:
        query = query.where(User.role == role)
    if situacao:
        query = query.where(User.status == situacao)
    return [_user_out(u) for u in a.db.scalars(query.order_by(User.name).limit(1000))]


def _get_user(a: AdminCtx, user_id: uuid.UUID) -> User:
    u = a.db.get(User, user_id)
    if u is None or u.tenant_id != a.tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    return u


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: uuid.UUID, body: UserAdminUpdate, a: AdminCtx = Depends(admin_ctx)) -> UserAdminOut:
    u = _get_user(a, user_id)
    if u.id == a.actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode alterar o seu próprio perfil ou situação.")
    if body.role == Role.consultor:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "O perfil Consultor é exclusivo da plataforma.")
    changes = {}
    if body.role is not None and body.role != u.role:
        changes["perfil"] = [u.role.value, body.role.value]
        u.role = body.role
    if body.status is not None and body.status != u.status:
        changes["situacao"] = [u.status.value, body.status.value]
        u.status = body.status
        if body.status == UserStatus.inativo:
            u.session_version += 1  # derruba as sessões abertas
    if changes:
        a.record("usuario_alterado", entity="user", entity_id=u.id, details=changes)
    a.db.commit()
    return _user_out(u)


@router.post("/users/{user_id}/resend-activation", response_model=Message)
def resend_activation(user_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> Message:
    u = _get_user(a, user_id)
    if u.email_verified_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este usuário já ativou o acesso.")
    if u.status != UserStatus.ativo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reative o usuário antes de reenviar o convite.")
    send_activation(a.db, u, a.tenant, invited_by=a.actor.name)
    a.record("ativacao_reenviada", entity="user", entity_id=u.id)
    a.db.commit()
    return Message(message=f"Enviamos um novo link de ativação para {u.email}.")
