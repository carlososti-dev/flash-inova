from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..accounts import consume_token, send_activation, send_reset
from ..config import get_settings
from ..deps import RequestContext, get_context, get_current_user, require_active_tenant
from ..models import ROLE_LABELS, AuthorizedMember, Role, TokenPurpose, User, UserStatus, utcnow
from ..schemas import EmailIn, LoginIn, Me, Message, RegisterIn, SetPasswordIn, SiteInfo
from ..security import create_session, hash_password, password_problem, verify_password
from .common import tenant_public

router = APIRouter(prefix="/api", tags=["acesso"])

INVALID_LOGIN = "E-mail ou senha inválidos."


@router.get("/site", response_model=SiteInfo)
def site(ctx: RequestContext = Depends(get_context)) -> SiteInfo:
    if ctx.tenant is None:
        return SiteInfo(tenant=None)
    return SiteInfo(tenant=tenant_public(ctx.tenant), tenant_active=ctx.tenant.is_active)


def _find_user(ctx: RequestContext, email: str) -> User | None:
    user = ctx.db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        return None
    # Fora de um hospital, só o Consultor entra; num hospital, só quem é dele (ou o Consultor).
    if user.role == Role.consultor:
        return user
    if ctx.tenant is None or user.tenant_id != ctx.tenant.id:
        return None
    return user


def _set_session_cookie(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie,
        create_session(user.id, user.tenant_id, user.session_version),
        max_age=s.session_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/auth/login", response_model=Me)
def login(body: LoginIn, response: Response, ctx: RequestContext = Depends(get_context)) -> Me:
    if ctx.tenant is not None:
        require_active_tenant(ctx)
    user = _find_user(ctx, body.email)
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        if user is not None:
            audit.record(ctx.db, "login_falhou", actor_id=user.id, tenant_id=ctx.tenant.id if ctx.tenant else None)
            ctx.db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)
    if user.status != UserStatus.ativo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu acesso está inativo. Procure o administrador.")
    if user.email_verified_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Confirme seu e-mail pelo link que enviamos antes de entrar.")
    audit.record(ctx.db, "login", actor_id=user.id, tenant_id=ctx.tenant.id if ctx.tenant else None)
    ctx.db.commit()
    _set_session_cookie(response, user)
    return _me(user, ctx)


@router.post("/auth/logout", response_model=Message)
def logout(response: Response) -> Message:
    response.delete_cookie(get_settings().session_cookie, path="/")
    return Message(message="Você saiu.")


def _me(user: User, ctx: RequestContext) -> Me:
    return Me(
        id=user.id, name=user.name, email=user.email, role=user.role, role_label=ROLE_LABELS[user.role],
        tenant=tenant_public(ctx.tenant) if ctx.tenant else None,
    )


@router.get("/auth/me", response_model=Me)
def me(user: User = Depends(get_current_user), ctx: RequestContext = Depends(get_context)) -> Me:
    return _me(user, ctx)


@router.post("/auth/forgot-password", response_model=Message)
def forgot_password(body: EmailIn, ctx: RequestContext = Depends(get_context)) -> Message:
    # A resposta é sempre a mesma, para não revelar quais e-mails têm conta.
    answer = Message(message="Se este e-mail tiver acesso, enviaremos um link para redefinir a senha.")
    if ctx.tenant is not None and not ctx.tenant.is_active:
        return answer
    user = _find_user(ctx, body.email)
    if user is None or user.status != UserStatus.ativo:
        return answer
    send_reset(ctx.db, user, ctx.tenant)
    audit.record(ctx.db, "senha_link_enviado", actor_id=user.id, tenant_id=user.tenant_id)
    ctx.db.commit()
    return answer


def _set_password(ctx: RequestContext, body: SetPasswordIn, purpose: TokenPurpose, action: str) -> Message:
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    user = consume_token(ctx.db, body.token, purpose)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link inválido ou expirado. Peça um novo.")
    user.password_hash = hash_password(body.password)
    user.session_version += 1  # derruba sessões abertas com a senha antiga
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()  # quem abriu o link controla o e-mail
    audit.record(ctx.db, action, actor_id=user.id, tenant_id=user.tenant_id)
    ctx.db.commit()
    return Message(message="Senha definida. Você já pode entrar.")


@router.post("/auth/reset-password", response_model=Message)
def reset_password(body: SetPasswordIn, ctx: RequestContext = Depends(get_context)) -> Message:
    return _set_password(ctx, body, TokenPurpose.reset_password, "senha_redefinida")


@router.post("/auth/activate", response_model=Message)
def activate(body: SetPasswordIn, ctx: RequestContext = Depends(get_context)) -> Message:
    return _set_password(ctx, body, TokenPurpose.verify_email, "conta_ativada")


@router.post("/auth/register", response_model=Message)
def register(body: RegisterIn, ctx: RequestContext = Depends(get_context)) -> Message:
    """Primeiro acesso: matrícula e e-mail precisam conferir com a lista de autorizados do hospital.

    A resposta é sempre a mesma, para não revelar quem está na lista. Quem já tem conta recebe o link de senha.
    """
    tenant = require_active_tenant(ctx)
    answer = Message(message="Se a matrícula e o e-mail conferirem com a lista do hospital, "
                             "enviaremos um link para você criar sua senha.")
    matricula, email = body.matricula.strip(), str(body.email).lower()
    member = ctx.db.scalar(select(AuthorizedMember).where(
        AuthorizedMember.matricula == matricula, func.lower(AuthorizedMember.email) == email,
        AuthorizedMember.is_active.is_(True),
    ))
    if member is None:
        audit.record(ctx.db, "cadastro_recusado", actor_id=None, tenant_id=tenant.id, details={"matricula": matricula})
        ctx.db.commit()
        return answer

    user = ctx.db.get(User, member.user_id) if member.user_id else None
    if user is None:
        user = ctx.db.scalar(select(User).where(User.tenant_id == tenant.id, or_(
            func.lower(User.email) == email, User.matricula == matricula)))
    if user is not None:
        member.user_id = user.id
        if user.status != UserStatus.ativo:
            audit.record(ctx.db, "cadastro_usuario_inativo", actor_id=user.id, tenant_id=tenant.id)
        elif user.email_verified_at is None:
            send_activation(ctx.db, user, tenant, invited_by=None)
        else:
            send_reset(ctx.db, user, tenant)
        ctx.db.commit()
        return answer

    user = User(tenant_id=tenant.id, role=member.default_role or Role.colaborador, name=member.name,
                email=email, matricula=matricula, sector=member.sector)
    ctx.db.add(user)
    try:
        ctx.db.flush()
    except IntegrityError:
        # E-mail já usado em outro hospital (ou na plataforma): não dá para criar, e a resposta não conta isso.
        ctx.db.rollback()
        return answer
    member.user_id = user.id
    send_activation(ctx.db, user, tenant, invited_by=None)
    audit.record(ctx.db, "cadastro_realizado", actor_id=user.id, tenant_id=tenant.id, entity="user", entity_id=user.id)
    ctx.db.commit()
    return answer
