import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_sessionmaker
from .models import Role, Tenant, User, UserStatus
from .security import read_session


def resolve_tenant_slug(request: Request) -> str | None:
    """Hospital pelo subdomínio (hnsg.<base_domain>); em desenvolvimento, também por X-Tenant ou ?tenant=."""
    s = get_settings()
    if s.allow_tenant_override:
        override = request.headers.get("x-tenant") or request.query_params.get("tenant")
        if override:
            return override.strip().lower()
    host = (request.headers.get("host") or "").split(":")[0].lower()
    suffix = "." + s.base_domain.lower()
    if host.endswith(suffix):
        sub = host[: -len(suffix)]
        if sub and "." not in sub and sub != "www":
            return sub
    return None


@dataclass
class RequestContext:
    db: Session
    tenant: Tenant | None


def get_context(request: Request) -> Iterator[RequestContext]:
    """Sessão de banco já presa ao hospital da requisição (Row Level Security)."""
    db = get_sessionmaker()()
    try:
        tenant = None
        slug = resolve_tenant_slug(request)
        if slug:
            tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
            if tenant is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Hospital não encontrado.")
            db.commit()  # encerra a transação aberta sem contexto
            db.info["tenant_id"] = tenant.id
        yield RequestContext(db=db, tenant=tenant)
    finally:
        db.close()


def require_active_tenant(ctx: RequestContext) -> Tenant:
    if ctx.tenant is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hospital não informado.")
    if not ctx.tenant.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este hospital está com o acesso suspenso.")
    return ctx.tenant


def get_current_user(request: Request, ctx: RequestContext = Depends(get_context)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar.")
    token = request.cookies.get(get_settings().session_cookie)
    claims = read_session(token) if token else None
    try:
        user_id = uuid.UUID(claims["sub"]) if claims else None
    except (KeyError, ValueError):
        user_id = None
    if user_id is None:
        raise unauthorized
    # O RLS já esconde usuários de outro hospital; a comparação abaixo é a barreira da aplicação.
    user = ctx.db.get(User, user_id)
    if user is None or user.status != UserStatus.ativo or user.email_verified_at is None:
        raise unauthorized
    if user.session_version != claims.get("sv"):
        raise unauthorized
    if user.role != Role.consultor:
        if ctx.tenant is None or user.tenant_id != ctx.tenant.id:
            raise unauthorized
        require_active_tenant(ctx)
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Você não tem permissão para esta ação.")
        return user

    return checker


def enter_platform_mode(ctx: RequestContext) -> None:
    """Modo "todos os hospitais" do Consultor: libera o RLS a partir da próxima transação."""
    ctx.db.commit()
    ctx.db.info["all_tenants"] = True
