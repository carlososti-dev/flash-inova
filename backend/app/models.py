import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Timestamps:
    # Valores gerados na aplicação (não no banco) para evitar RETURNING, que esbarraria no Row Level Security.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Theme(str, enum.Enum):
    verde = "verde"
    azul = "azul"


class Role(str, enum.Enum):
    consultor = "consultor"
    administrador = "administrador"
    gestor = "gestor"
    membro_comite = "membro_comite"
    colaborador = "colaborador"


class UserStatus(str, enum.Enum):
    ativo = "ativo"
    inativo = "inativo"


class TokenPurpose(str, enum.Enum):
    verify_email = "verify_email"
    reset_password = "reset_password"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Tenant(Timestamps, Base):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    logo_path: Mapped[str | None] = mapped_column(String(500))
    theme: Mapped[Theme] = mapped_column(_enum(Theme, "theme"), default=Theme.verde)
    default_banner_path: Mapped[str | None] = mapped_column(String(500))
    default_video_url: Mapped[str | None] = mapped_column(String(500))
    default_num_evaluators: Mapped[int] = mapped_column(Integer, default=3)
    default_weight_classify: Mapped[int] = mapped_column(Integer, default=5)
    default_weight_maybe: Mapped[int] = mapped_column(Integer, default=1)
    default_cutoff_score: Mapped[int] = mapped_column(Integer, default=70)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'", name="tenants_slug_format"),)


class User(Timestamps, Base):
    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    matricula: Mapped[str | None] = mapped_column(String(50))
    sector: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[UserStatus] = mapped_column(_enum(UserStatus, "user_status"), default=UserStatus.ativo)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Muda a cada troca de senha: derruba as sessões abertas.
    session_version: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        CheckConstraint("(tenant_id IS NULL) = (role = 'consultor')", name="users_consultor_sem_hospital"),
        Index("users_email_unique", func.lower(email), unique=True),
        Index("users_matricula_unique", "tenant_id", "matricula", unique=True),
    )


class AuthToken(Timestamps, Base):
    __tablename__ = "auth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(_enum(TokenPurpose, "token_purpose"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthorizedMember(Timestamps, Base):
    """Lista de autorizados: só quem está aqui consegue se cadastrar no hospital (D18)."""
    __tablename__ = "authorized_members"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    matricula: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    sector: Mapped[str | None] = mapped_column(String(200))
    # Perfil com que a pessoa nasce ao se cadastrar (vazio = colaborador).
    default_role: Mapped[Role | None] = mapped_column(_enum(Role, "user_role"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("authorized_members_matricula", "tenant_id", "matricula", unique=True),
        Index("authorized_members_email", "tenant_id", func.lower(email), unique=True),
    )


class CampaignPhase(str, enum.Enum):
    recepcao = "recepcao"
    analise = "analise"
    classificacao = "classificacao"
    defesa = "defesa"
    votacao = "votacao"
    encerrada = "encerrada"


class Campaign(Timestamps, Base):
    """Uma edição do programa de ideias. O período de inscrição é calculado pelas datas; a fase atual é gravada,
    porque avança por ação do administrador ("Fechar fase")."""
    __tablename__ = "campaigns"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    title: Mapped[str] = mapped_column(String(200))
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    submission_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submission_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    analysis_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    defense_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voting_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voting_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_headline: Mapped[str | None] = mapped_column(String(300))
    home_text: Mapped[str | None] = mapped_column(Text)
    tips_text: Mapped[str | None] = mapped_column(Text)
    regulation_text: Mapped[str | None] = mapped_column(Text)
    banner_path: Mapped[str | None] = mapped_column(String(500))
    video_url: Mapped[str | None] = mapped_column(String(500))
    num_evaluators: Mapped[int] = mapped_column(Integer)
    weight_classify: Mapped[int] = mapped_column(Integer)
    weight_maybe: Mapped[int] = mapped_column(Integer)
    cutoff_score: Mapped[int] = mapped_column(Integer)
    blind_review: Mapped[bool] = mapped_column(Boolean, default=True)
    num_defense_finalists: Mapped[int | None] = mapped_column(Integer)
    num_voting_finalists: Mapped[int | None] = mapped_column(Integer)
    num_winners: Mapped[int] = mapped_column(Integer, default=3)
    current_phase: Mapped[CampaignPhase] = mapped_column(_enum(CampaignPhase, "campaign_phase"),
                                                         default=CampaignPhase.recepcao)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class CampaignLine(Timestamps, Base):
    """Linha de ideias (temática): toda ideia pertence a uma."""
    __tablename__ = "campaign_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RegulationVersion(Timestamps, Base):
    """Cada texto do regulamento publicado fica guardado: o aceite de quem envia aponta para a versão aceita."""
    __tablename__ = "regulation_versions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class FieldKind(str, enum.Enum):
    texto_curto = "texto_curto"
    texto_longo = "texto_longo"
    lista = "lista"
    sim_nao = "sim_nao"
    anexo = "anexo"


class CampaignField(Timestamps, Base):
    """Campo configurável do formulário de envio (título, linha e resumo são fixos e não ficam aqui)."""
    __tablename__ = "campaign_fields"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    kind: Mapped[FieldKind] = mapped_column(_enum(FieldKind, "field_kind"))
    label: Mapped[str] = mapped_column(String(200))
    help_text: Mapped[str | None] = mapped_column(String(500))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[list | None] = mapped_column(JSONB)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class IdeaStage(str, enum.Enum):
    rascunho = "rascunho"
    recebida = "recebida"
    em_analise = "em_analise"
    empate = "empate"
    classificada = "classificada"
    talvez = "talvez"
    nao_classificada = "nao_classificada"
    shortlist = "shortlist"
    selecionada = "selecionada"
    premiada = "premiada"


class Idea(Timestamps, Base):
    __tablename__ = "ideas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"))
    line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign_lines.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # Número sequencial na campanha, dado no primeiro envio (#1, #2...).
    number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[IdeaStage] = mapped_column(_enum(IdeaStage, "idea_stage"), default=IdeaStage.rascunho)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regulation_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regulation_versions.id"))
    regulation_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdeaAnswer(Timestamps, Base):
    __tablename__ = "idea_answers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"))
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign_fields.id"))
    # Texto, opção escolhida ou sim/não; anexos usam as colunas file_*.
    value: Mapped[object | None] = mapped_column(JSONB)
    file_path: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer)


class IdeaCoauthor(Timestamps, Base):
    __tablename__ = "idea_coauthors"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"))
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("authorized_members.id"))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


ROLE_LABELS = {
    Role.consultor: "Consultor",
    Role.administrador: "Administrador",
    Role.gestor: "Gestor",
    Role.membro_comite: "Membro de comitê",
    Role.colaborador: "Colaborador",
}
