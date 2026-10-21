import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, field_validator

from .models import CampaignPhase, Role, Theme, UserStatus


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


# ---------- Campanhas ----------

class CampaignLineIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class CampaignLineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class CampaignLineOrder(BaseModel):
    ids: list[uuid.UUID]


class CampaignLineOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    position: int
    is_active: bool


class CampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    submission_start: AwareDatetime
    submission_end: AwareDatetime


def _blank_to_none(value: str | None) -> str | None:
    return value if value is None or value.strip() else None


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    is_published: bool | None = None
    submission_start: AwareDatetime | None = None
    submission_end: AwareDatetime | None = None
    analysis_start: AwareDatetime | None = None
    analysis_end: AwareDatetime | None = None
    classification_end: AwareDatetime | None = None
    defense_date: AwareDatetime | None = None
    voting_start: AwareDatetime | None = None
    voting_end: AwareDatetime | None = None
    home_headline: str | None = Field(default=None, max_length=300)
    home_text: str | None = Field(default=None, max_length=5000)
    tips_text: str | None = Field(default=None, max_length=5000)
    regulation_text: str | None = Field(default=None, max_length=100_000)
    video_url: str | None = Field(default=None, max_length=500)
    num_evaluators: int | None = Field(default=None, ge=1, le=20)
    weight_classify: int | None = Field(default=None, ge=0, le=100)
    weight_maybe: int | None = Field(default=None, ge=0, le=100)
    cutoff_score: int | None = Field(default=None, ge=0, le=100)
    blind_review: bool | None = None
    num_defense_finalists: int | None = Field(default=None, ge=1, le=500)
    num_voting_finalists: int | None = Field(default=None, ge=1, le=500)
    num_winners: int | None = Field(default=None, ge=1, le=20)

    _blank = field_validator("home_headline", "home_text", "tips_text", "regulation_text", "video_url")(_blank_to_none)


class PhaseOut(BaseModel):
    key: str
    label: str
    start: datetime | None
    end: datetime | None


class CampaignSummary(BaseModel):
    id: uuid.UUID
    title: str
    is_published: bool
    submission_start: datetime
    submission_end: datetime
    submission_state: str
    current_phase: CampaignPhase
    active_lines: int


class CampaignAdminOut(CampaignSummary):
    analysis_start: datetime | None
    analysis_end: datetime | None
    classification_end: datetime | None
    defense_date: datetime | None
    voting_start: datetime | None
    voting_end: datetime | None
    home_headline: str | None
    home_text: str | None
    tips_text: str | None
    regulation_text: str | None
    banner_url: str | None
    video_url: str | None
    num_evaluators: int
    weight_classify: int
    weight_maybe: int
    cutoff_score: int
    blind_review: bool
    num_defense_finalists: int | None
    num_voting_finalists: int | None
    num_winners: int
    lines: list[CampaignLineOut]


class CampaignPublic(BaseModel):
    """O que a página inicial mostra a quem entra no hospital."""
    id: uuid.UUID
    title: str
    is_published: bool
    home_headline: str | None
    home_text: str | None
    tips_text: str | None
    regulation_text: str | None
    banner_url: str | None
    video_embed_url: str | None
    submission_start: datetime
    submission_end: datetime
    submission_state: str
    current_phase: CampaignPhase
    phases: list[PhaseOut]
    num_winners: int
    lines: list[CampaignLineOut]
