import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import Role, Theme, UserStatus


class TenantPublic(BaseModel):
    slug: str
    name: str
    theme: Theme
    logo_url: str | None


class SiteInfo(BaseModel):
    """O que a tela de login precisa saber: qual hospital (ou a área da plataforma)."""
    tenant: TenantPublic | None
    tenant_active: bool = True


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class SetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class Me(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: Role
    role_label: str
    tenant: TenantPublic | None


class Message(BaseModel):
    message: str


class TenantAdmin(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    theme: Theme
    logo_url: str | None
    is_active: bool
    admins: int


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    name: str = Field(min_length=2, max_length=200)
    theme: Theme = Theme.verde


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    theme: Theme | None = None
    is_active: bool | None = None


class AdminCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr


class AdminOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    activated: bool


class RegisterIn(BaseModel):
    matricula: str = Field(min_length=1, max_length=50)
    email: EmailStr


# Perfis que a lista de autorizados pode dar; administrador é promovido na gestão de usuários.
MEMBER_ROLES = {Role.colaborador, Role.membro_comite, Role.gestor}


def _member_role(value: Role | None) -> Role | None:
    if value is not None and value not in MEMBER_ROLES:
        raise ValueError("Perfil inicial deve ser colaborador, membro de comitê ou gestor.")
    return value


class AuthorizedIn(BaseModel):
    matricula: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    sector: str | None = Field(default=None, max_length=200)
    default_role: Role | None = None

    _role = field_validator("default_role")(_member_role)


class AuthorizedUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    sector: str | None = Field(default=None, max_length=200)
    default_role: Role | None = None
    is_active: bool | None = None

    _role = field_validator("default_role")(_member_role)


class AuthorizedOut(BaseModel):
    id: uuid.UUID
    matricula: str
    name: str
    email: str
    sector: str | None
    default_role: Role | None
    is_active: bool
    registered: bool


class AuthorizedPage(BaseModel):
    items: list[AuthorizedOut]
    total: int
    active: int
    registered: int


class ImportLineError(BaseModel):
    line: int
    message: str


class ImportReport(BaseModel):
    applied: bool
    lines: int
    created: int
    updated: int
    unchanged: int
    errors: list[ImportLineError]


class UserAdminOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    matricula: str | None
    sector: str | None
    role: Role
    role_label: str
    status: UserStatus
    activated: bool
    created_at: datetime


class UserAdminUpdate(BaseModel):
    role: Role | None = None
    status: UserStatus | None = None
