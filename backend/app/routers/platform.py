"""Área do Consultor: hospitais da plataforma. Toda ação fica na auditoria."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..accounts import send_activation
from ..config import get_settings
from ..deps import RequestContext, enter_platform_mode, get_context, require_roles
from ..models import Role, Tenant, User
from ..schemas import AdminCreate, AdminOut, TenantAdmin, TenantCreate, TenantUpdate
from ..storage import get_storage, image_extension

router = APIRouter(prefix="/api/platform", tags=["plataforma"])


def platform_ctx(
    consultor: User = Depends(require_roles(Role.consultor)), ctx: RequestContext = Depends(get_context)
) -> tuple[User, RequestContext]:
    enter_platform_mode(ctx)
    return consultor, ctx


def _get_tenant(ctx: RequestContext, tenant_id: uuid.UUID) -> Tenant:
    tenant = ctx.db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hospital não encontrado.")
    return tenant


def _out(ctx: RequestContext, tenant: Tenant) -> TenantAdmin:
    admins = ctx.db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == tenant.id, User.role == Role.administrador)
    )
    return TenantAdmin(
        id=tenant.id, slug=tenant.slug, name=tenant.name, theme=tenant.theme,
        logo_url=get_storage().url(tenant.logo_path), is_active=tenant.is_active, admins=admins or 0,
    )


@router.get("/tenants", response_model=list[TenantAdmin])
def list_tenants(p=Depends(platform_ctx)) -> list[TenantAdmin]:
    _, ctx = p
    return [_out(ctx, t) for t in ctx.db.scalars(select(Tenant).order_by(Tenant.name))]


@router.post("/tenants", response_model=TenantAdmin, status_code=status.HTTP_201_CREATED)
def create_tenant(body: TenantCreate, p=Depends(platform_ctx)) -> TenantAdmin:
    consultor, ctx = p
    if body.slug in {"www", "api", "admin", "app"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Este endereço é reservado.")
    tenant = Tenant(slug=body.slug, name=body.name, theme=body.theme)
    ctx.db.add(tenant)
    try:
        ctx.db.flush()
    except IntegrityError:
        ctx.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um hospital com este endereço.")
    audit.record(ctx.db, "hospital_criado", actor_id=consultor.id, tenant_id=tenant.id, entity="tenant",
                 entity_id=tenant.id, details=body.model_dump(mode="json"))
    ctx.db.commit()
    return _out(ctx, tenant)


@router.patch("/tenants/{tenant_id}", response_model=TenantAdmin)
def update_tenant(tenant_id: uuid.UUID, body: TenantUpdate, p=Depends(platform_ctx)) -> TenantAdmin:
    consultor, ctx = p
    tenant = _get_tenant(ctx, tenant_id)
    changes = body.model_dump(exclude_unset=True, mode="json")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    audit.record(ctx.db, "hospital_alterado", actor_id=consultor.id, tenant_id=tenant.id, entity="tenant",
                 entity_id=tenant.id, details=changes)
    ctx.db.commit()
    return _out(ctx, tenant)


@router.post("/tenants/{tenant_id}/logo", response_model=TenantAdmin)
async def upload_logo(tenant_id: uuid.UUID, file: UploadFile = File(...), p=Depends(platform_ctx)) -> TenantAdmin:
    consultor, ctx = p
    tenant = _get_tenant(ctx, tenant_id)
    limit = get_settings().max_logo_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "O logotipo deve ter no máximo 2 MB.")
    extension = image_extension(data)
    if extension is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Envie o logotipo em PNG, JPG ou WEBP.")
    tenant.logo_path = get_storage().save(f"tenants/{tenant.slug}", data, extension)
    audit.record(ctx.db, "logotipo_alterado", actor_id=consultor.id, tenant_id=tenant.id, entity="tenant",
                 entity_id=tenant.id)
    ctx.db.commit()
    return _out(ctx, tenant)


@router.get("/tenants/{tenant_id}/admins", response_model=list[AdminOut])
def list_admins(tenant_id: uuid.UUID, p=Depends(platform_ctx)) -> list[AdminOut]:
    _, ctx = p
    _get_tenant(ctx, tenant_id)
    admins = ctx.db.scalars(
        select(User).where(User.tenant_id == tenant_id, User.role == Role.administrador).order_by(User.name)
    )
    return [AdminOut(id=u.id, name=u.name, email=u.email, activated=u.email_verified_at is not None) for u in admins]


@router.post("/tenants/{tenant_id}/admins", response_model=AdminOut, status_code=status.HTTP_201_CREATED)
def create_admin(tenant_id: uuid.UUID, body: AdminCreate, p=Depends(platform_ctx)) -> AdminOut:
    consultor, ctx = p
    tenant = _get_tenant(ctx, tenant_id)
    user = User(tenant_id=tenant.id, role=Role.administrador, name=body.name, email=str(body.email).lower())
    ctx.db.add(user)
    try:
        ctx.db.flush()
    except IntegrityError:
        ctx.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Este e-mail já tem acesso à plataforma.")
    send_activation(ctx.db, user, tenant, invited_by=consultor.name)
    audit.record(ctx.db, "administrador_criado", actor_id=consultor.id, tenant_id=tenant.id, entity="user",
                 entity_id=user.id, details={"email": user.email})
    ctx.db.commit()
    return AdminOut(id=user.id, name=user.name, email=user.email, activated=False)
