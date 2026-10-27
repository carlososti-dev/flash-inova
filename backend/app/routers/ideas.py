"""Ideias: formulário de envio (rascunho e envio), Minhas ideias, anexos e o kanban do menu Classificação.

Quem vê uma ideia: o autor (sempre), os coautores (depois de enviada) e quem acompanha o processo
(administrador, consultor e gestor), também só depois de enviada. O rascunho só o autor vê.
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from .. import audit
from ..campaigns import featured_campaign, lines_of, submission_state
from ..config import get_settings
from ..deps import RequestContext, get_context, get_current_user, require_active_tenant, require_roles
from ..ideas import (
    AUTHOR_STAGE_LABELS, BOARD_COLUMNS, STAGE_LABELS, answered, can_edit, can_submit, clean_answer,
    current_regulation, next_number,
)
from ..models import (
    Assignment, AuthorizedMember, Campaign, CampaignField, CampaignLine, FieldKind, Idea, IdeaAnswer, IdeaCoauthor,
    IdeaStage, RegulationVersion, Role, Tenant, User, utcnow,
)
from ..schemas import (
    AnswerOut, BoardCampaign, BoardCard, BoardColumn, BoardOut, IdeaCreate, IdeaFormOut, IdeaIn, IdeaOut,
    IdeaSummary, PersonOut, SubmitIn,
)
from ..storage import ATTACHMENT_TYPES, attachment_extension, get_private_storage
from .campaigns import _line_out, field_out, fields_of

router = APIRouter(prefix="/api", tags=["ideias"])

# Quem acompanha o processo e vê o kanban.
FOLLOWERS = {Role.administrador, Role.consultor, Role.gestor}


class MemberCtx:
    def __init__(self, user: User, ctx: RequestContext, tenant: Tenant):
        self.user, self.db, self.tenant = user, ctx.db, tenant

    def record(self, action: str, **kwargs) -> None:
        audit.record(self.db, action, actor_id=self.user.id, tenant_id=self.tenant.id, **kwargs)


def member_ctx(user: User = Depends(get_current_user), ctx: RequestContext = Depends(get_context)) -> MemberCtx:
    return MemberCtx(user, ctx, require_active_tenant(ctx))


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


NOT_FOUND = "Ideia não encontrada."


def _campaign_for_author(m: MemberCtx, campaign_id: uuid.UUID) -> Campaign:
    c = m.db.get(Campaign, campaign_id)
    if c is None or c.tenant_id != m.tenant.id or not c.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    return c


def _my_member_ids(m: MemberCtx) -> list[uuid.UUID]:
    return list(m.db.scalars(select(AuthorizedMember.id).where(
        AuthorizedMember.tenant_id == m.tenant.id, AuthorizedMember.user_id == m.user.id)))


def _role_in(m: MemberCtx, idea: Idea) -> str | None:
    """autor | coautor | acompanha | None (não pode ver)."""
    if idea.author_id == m.user.id:
        return "autor"
    if idea.stage == IdeaStage.rascunho:
        return None
    member_ids = _my_member_ids(m)
    if member_ids and m.db.scalar(select(func.count()).select_from(IdeaCoauthor).where(
            IdeaCoauthor.idea_id == idea.id, IdeaCoauthor.member_id.in_(member_ids))):
        return "coautor"
    return "acompanha" if m.user.role in FOLLOWERS else None


def _get_idea(m: MemberCtx, idea_id: uuid.UUID) -> tuple[Idea, Campaign, str]:
    idea = m.db.get(Idea, idea_id)
    role = _role_in(m, idea) if idea is not None and idea.tenant_id == m.tenant.id else None
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return idea, m.db.get(Campaign, idea.campaign_id), role


def _get_own_editable(m: MemberCtx, idea_id: uuid.UUID) -> tuple[Idea, Campaign]:
    idea, c, role = _get_idea(m, idea_id)
    if role != "autor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o autor pode alterar a ideia.")
    if not can_edit(idea, c):
        raise HTTPException(status.HTTP_409_CONFLICT, "As inscrições terminaram: a ideia não pode mais ser alterada.")
    return idea, c


def _answers(db, idea_id: uuid.UUID) -> dict[uuid.UUID, IdeaAnswer]:
    return {a.field_id: a for a in db.scalars(select(IdeaAnswer).where(IdeaAnswer.idea_id == idea_id))}


def _coauthors(db, idea_id: uuid.UUID) -> list[AuthorizedMember]:
    return list(db.scalars(select(AuthorizedMember).join(IdeaCoauthor, IdeaCoauthor.member_id == AuthorizedMember.id)
                           .where(IdeaCoauthor.idea_id == idea_id).order_by(AuthorizedMember.name)))


def _person(p: AuthorizedMember) -> PersonOut:
    return PersonOut(id=p.id, name=p.name, sector=p.sector)


def _summary_fields(db, idea: Idea, c: Campaign, role: str) -> dict:
    line = db.get(CampaignLine, idea.line_id) if idea.line_id else None
    labels = AUTHOR_STAGE_LABELS if role in {"autor", "coautor"} else STAGE_LABELS
    return dict(id=idea.id, campaign_id=c.id, campaign_title=c.title, number=idea.number, title=idea.title,
                line_name=line.name if line else None, stage=idea.stage, stage_label=labels[idea.stage], role=role,
                submitted_at=idea.submitted_at, updated_at=idea.updated_at,
                can_edit=role == "autor" and can_edit(idea, c))


def answers_out(db, idea_id: uuid.UUID) -> list[AnswerOut]:
    rows = db.execute(select(IdeaAnswer, CampaignField).join(CampaignField, CampaignField.id == IdeaAnswer.field_id)
                      .where(IdeaAnswer.idea_id == idea_id).order_by(CampaignField.position, CampaignField.label))
    return [AnswerOut(field_id=a.field_id, label=f.label, kind=f.kind, value=a.value, file_name=a.file_name,
                      file_size=a.file_size) for a, f in rows]


def attachment_response(path: str, filename: str | None) -> FileResponse:
    extension = path.rsplit(".", 1)[-1]
    return FileResponse(get_private_storage().local_path(path),
                        media_type=ATTACHMENT_TYPES.get(extension, "application/octet-stream"),
                        filename=filename, content_disposition_type="attachment",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


def _idea_out(db, idea: Idea, c: Campaign, role: str) -> IdeaOut:
    regulation = db.get(RegulationVersion, idea.regulation_version_id) if idea.regulation_version_id else None
    return IdeaOut(
        **_summary_fields(db, idea, c, role), line_id=idea.line_id, summary=idea.summary,
        author_name=db.get(User, idea.author_id).name,
        answers=answers_out(db, idea.id),
        coauthors=[_person(p) for p in _coauthors(db, idea.id)],
        regulation_version=regulation.version if regulation else None,
        regulation_accepted_at=idea.regulation_accepted_at,
    )


def _missing(db, idea: Idea, c: Campaign) -> list[str]:
    """O que falta para a ideia poder ser enviada (ou continuar enviada depois de uma edição)."""
    missing = []
    line = db.get(CampaignLine, idea.line_id) if idea.line_id else None
    if line is None or not line.is_active:
        missing.append("Linha de ideias")
    if not (idea.summary or "").strip():
        missing.append("Resumo")
    answers = _answers(db, idea.id)
    for f in fields_of(db, c.id, only_active=True):
        a = answers.get(f.id)
        if f.required and not answered(f, a.value if a else None, a.file_path if a else None):
            missing.append(f.label)
    return missing


def _apply(m: MemberCtx, idea: Idea, c: Campaign, body: IdeaIn) -> None:
    """Grava título, linha, resumo, respostas e coautores. Um rascunho pode ficar incompleto."""
    if body.line_id is not None:
        line = m.db.get(CampaignLine, body.line_id)
        if line is None or line.campaign_id != c.id or not line.is_active:
            raise _unprocessable("Escolha uma das linhas de ideias da campanha.")
    idea.title = body.title.strip()
    idea.line_id = body.line_id
    idea.summary = (body.summary or "").strip() or None

    fields = {f.id: f for f in fields_of(m.db, c.id, only_active=True)}
    answers = _answers(m.db, idea.id)
    for field_id, raw in body.answers.items():
        f = fields.get(field_id)
        if f is None:
            raise _unprocessable("O formulário mudou. Recarregue a página e tente de novo.")
        if f.kind == FieldKind.anexo:
            continue  # anexos têm rota própria
        try:
            value = clean_answer(f, raw)
        except ValueError as e:
            raise _unprocessable(str(e))
        if field_id in answers:
            if value is None:
                m.db.delete(answers.pop(field_id))
            else:
                answers[field_id].value = value
        elif value is not None:
            m.db.add(IdeaAnswer(tenant_id=m.tenant.id, idea_id=idea.id, field_id=field_id, value=value))

    wanted = list(dict.fromkeys(body.coauthor_ids))
    people = {p.id: p for p in m.db.scalars(select(AuthorizedMember).where(
        AuthorizedMember.id.in_(wanted), AuthorizedMember.tenant_id == m.tenant.id))} if wanted else {}
    for member_id in wanted:
        p = people.get(member_id)
        if p is None or not p.is_active:
            raise _unprocessable("Coautor não encontrado na lista de autorizados.")
        if p.user_id == idea.author_id:
            raise _unprocessable("Você já é o autor da ideia; não precisa se incluir como coautor.")
    current = {co.member_id: co for co in m.db.scalars(select(IdeaCoauthor).where(IdeaCoauthor.idea_id == idea.id))}
    for member_id, co in current.items():
        if member_id not in people:
            m.db.delete(co)
    for member_id in wanted:
        if member_id not in current:
            m.db.add(IdeaCoauthor(tenant_id=m.tenant.id, idea_id=idea.id, member_id=member_id))
    m.db.flush()


# ---------- Formulário ----------

@router.get("/campaigns/{campaign_id}/form", response_model=IdeaFormOut)
def idea_form(campaign_id: uuid.UUID, m: MemberCtx = Depends(member_ctx)) -> IdeaFormOut:
    c = _campaign_for_author(m, campaign_id)
    regulation = current_regulation(m.db, c.id) if c.regulation_text else None
    return IdeaFormOut(campaign_id=c.id, campaign_title=c.title, submission_state=submission_state(c),
                       submission_start=c.submission_start, submission_end=c.submission_end,
                       lines=[_line_out(x) for x in lines_of(m.db, c.id, only_active=True)],
                       fields=[field_out(f) for f in fields_of(m.db, c.id, only_active=True)],
                       regulation_version=regulation.version if regulation else None,
                       max_attachment_mb=get_settings().max_attachment_bytes // (1024 * 1024))


@router.get("/ideas/people", response_model=list[PersonOut])
def search_people(q: str = "", m: MemberCtx = Depends(member_ctx)) -> list[PersonOut]:
    """Busca de coautores na lista de autorizados, por nome ou matrícula. Não devolve e-mail nem matrícula."""
    q = q.strip().lower()
    if len(q) < 2:
        return []
    rows = m.db.scalars(
        select(AuthorizedMember)
        .where(AuthorizedMember.tenant_id == m.tenant.id, AuthorizedMember.is_active.is_(True),
               or_(AuthorizedMember.user_id.is_(None), AuthorizedMember.user_id != m.user.id),
               or_(func.lower(AuthorizedMember.name).like(f"%{q}%"), func.lower(AuthorizedMember.matricula) == q))
        .order_by(AuthorizedMember.name).limit(10))
    return [_person(p) for p in rows]


# ---------- Minhas ideias ----------

@router.get("/ideas/mine", response_model=list[IdeaSummary])
def my_ideas(m: MemberCtx = Depends(member_ctx)) -> list[IdeaSummary]:
    member_ids = _my_member_ids(m)
    coauthored = select(IdeaCoauthor.idea_id).where(IdeaCoauthor.member_id.in_(member_ids))
    rows = m.db.scalars(
        select(Idea).where(Idea.tenant_id == m.tenant.id, or_(
            Idea.author_id == m.user.id, (Idea.id.in_(coauthored)) & (Idea.stage != IdeaStage.rascunho)))
        .order_by(Idea.updated_at.desc()))
    campaigns: dict[uuid.UUID, Campaign] = {}
    out = []
    for idea in rows:
        c = campaigns.setdefault(idea.campaign_id, m.db.get(Campaign, idea.campaign_id))
        out.append(IdeaSummary(**_summary_fields(m.db, idea, c, "autor" if idea.author_id == m.user.id else "coautor")))
    return out


# ---------- Rascunho, edição e envio ----------

@router.post("/ideas", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
def create_idea(body: IdeaCreate, m: MemberCtx = Depends(member_ctx)) -> IdeaOut:
    c = _campaign_for_author(m, body.campaign_id)
    if utcnow() > c.submission_end:
        raise HTTPException(status.HTTP_409_CONFLICT, "Inscrições de projetos encerradas.")
    idea = Idea(tenant_id=m.tenant.id, campaign_id=c.id, author_id=m.user.id, title=body.title.strip())
    m.db.add(idea)
    m.db.flush()
    _apply(m, idea, c, body)
    m.record("ideia_rascunho_criado", entity="idea", entity_id=idea.id)
    m.db.commit()
    return _idea_out(m.db, idea, c, "autor")


@router.get("/ideas/{idea_id}", response_model=IdeaOut)
def get_idea(idea_id: uuid.UUID, m: MemberCtx = Depends(member_ctx)) -> IdeaOut:
    idea, c, role = _get_idea(m, idea_id)
    return _idea_out(m.db, idea, c, role)


@router.put("/ideas/{idea_id}", response_model=IdeaOut)
def update_idea(idea_id: uuid.UUID, body: IdeaIn, m: MemberCtx = Depends(member_ctx)) -> IdeaOut:
    idea, c = _get_own_editable(m, idea_id)
    _apply(m, idea, c, body)
    if idea.stage != IdeaStage.rascunho:
        # Ideia já enviada continua precisando estar completa.
        if missing := _missing(m.db, idea, c):
            m.db.rollback()
            raise _unprocessable("Preencha os campos obrigatórios: " + ", ".join(missing) + ".")
        m.record("ideia_alterada", entity="idea", entity_id=idea.id)
    idea.updated_at = utcnow()
    m.db.commit()
    return _idea_out(m.db, idea, c, "autor")


@router.post("/ideas/{idea_id}/submit", response_model=IdeaOut)
def submit_idea(idea_id: uuid.UUID, body: SubmitIn, m: MemberCtx = Depends(member_ctx)) -> IdeaOut:
    idea, c = _get_own_editable(m, idea_id)
    if idea.stage != IdeaStage.rascunho:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta ideia já foi enviada.")
    if not can_submit(c):
        raise HTTPException(status.HTTP_409_CONFLICT, "Só é possível enviar durante o período de inscrição.")
    regulation = current_regulation(m.db, c.id) if c.regulation_text else None
    if regulation is None:
        raise _unprocessable("A campanha ainda não publicou o regulamento. Avise a equipe da campanha.")
    if not body.accept_regulation:
        raise _unprocessable("Para enviar, é preciso aceitar o regulamento da campanha.")
    if missing := _missing(m.db, idea, c):
        raise _unprocessable("Preencha os campos obrigatórios: " + ", ".join(missing) + ".")
    # Trava a campanha para dar o próximo número sem repetir.
    m.db.execute(select(Campaign.id).where(Campaign.id == c.id).with_for_update())
    now = utcnow()
    idea.number = next_number(m.db, c.id)
    idea.stage = IdeaStage.recebida
    idea.submitted_at = idea.regulation_accepted_at = idea.updated_at = now
    idea.regulation_version_id = regulation.id
    m.record("ideia_enviada", entity="idea", entity_id=idea.id,
             details={"numero": idea.number, "regulamento_versao": regulation.version,
                      "regulamento_aceito_em": now.isoformat()})
    m.db.commit()
    return _idea_out(m.db, idea, c, "autor")


@router.delete("/ideas/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(idea_id: uuid.UUID, m: MemberCtx = Depends(member_ctx)) -> Response:
    idea, c, role = _get_idea(m, idea_id)
    if role != "autor" or idea.stage != IdeaStage.rascunho:
        raise HTTPException(status.HTTP_409_CONFLICT, "Só é possível excluir um rascunho seu.")
    m.db.delete(idea)
    m.record("ideia_rascunho_excluido", entity="idea", entity_id=idea_id, details={"titulo": idea.title})
    m.db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Anexos ----------

def _attachment_field(m: MemberCtx, c: Campaign, field_id: uuid.UUID, only_active: bool) -> CampaignField:
    f = m.db.get(CampaignField, field_id)
    if f is None or f.campaign_id != c.id or f.kind != FieldKind.anexo or (only_active and not f.is_active):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campo de anexo não encontrado.")
    return f


@router.post("/ideas/{idea_id}/files/{field_id}", response_model=IdeaOut)
async def upload_attachment(idea_id: uuid.UUID, field_id: uuid.UUID, file: UploadFile = File(...),
                            m: MemberCtx = Depends(member_ctx)) -> IdeaOut:
    idea, c = _get_own_editable(m, idea_id)
    f = _attachment_field(m, c, field_id, only_active=True)
    limit = get_settings().max_attachment_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"O anexo deve ter no máximo {limit // (1024 * 1024)} MB.")
    name = (file.filename or "anexo").replace("\\", "/").rsplit("/", 1)[-1][:255]
    extension = attachment_extension(data, name)
    if extension is None:
        raise _unprocessable("Envie o anexo em PDF, imagem (PNG, JPG, WEBP), Word, Excel ou PowerPoint.")
    path = get_private_storage().save(f"tenants/{m.tenant.slug}/ideas/{idea.id}", data, extension)
    answer = _answers(m.db, idea.id).get(f.id)
    if answer is None:
        answer = IdeaAnswer(tenant_id=m.tenant.id, idea_id=idea.id, field_id=f.id)
        m.db.add(answer)
    answer.file_path, answer.file_name, answer.file_size = path, name, len(data)
    idea.updated_at = utcnow()
    m.record("ideia_anexo_enviado", entity="idea", entity_id=idea.id, details={"campo": f.label, "arquivo": name})
    m.db.commit()
    return _idea_out(m.db, idea, c, "autor")


@router.delete("/ideas/{idea_id}/files/{field_id}", response_model=IdeaOut)
def remove_attachment(idea_id: uuid.UUID, field_id: uuid.UUID, m: MemberCtx = Depends(member_ctx)) -> IdeaOut:
    idea, c = _get_own_editable(m, idea_id)
    f = _attachment_field(m, c, field_id, only_active=False)
    if f.required and f.is_active and idea.stage != IdeaStage.rascunho:
        raise _unprocessable(f"\"{f.label}\" é obrigatório: envie outro arquivo para substituir este.")
    answer = _answers(m.db, idea.id).get(f.id)
    if answer is not None:
        m.db.delete(answer)
        idea.updated_at = utcnow()
        m.record("ideia_anexo_removido", entity="idea", entity_id=idea.id, details={"campo": f.label})
        m.db.commit()
    return _idea_out(m.db, idea, c, "autor")


@router.get("/ideas/{idea_id}/files/{field_id}")
def download_attachment(idea_id: uuid.UUID, field_id: uuid.UUID, m: MemberCtx = Depends(member_ctx)) -> FileResponse:
    idea, c, _ = _get_idea(m, idea_id)
    f = _attachment_field(m, c, field_id, only_active=False)
    answer = _answers(m.db, idea.id).get(f.id)
    if answer is None or answer.file_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    return attachment_response(answer.file_path, answer.file_name)


# ---------- Kanban (menu Classificação) ----------

@router.get("/board", response_model=BoardOut)
def board(campaign_id: uuid.UUID | None = None, user: User = Depends(require_roles(*FOLLOWERS)),
          ctx: RequestContext = Depends(get_context)) -> BoardOut:
    tenant = require_active_tenant(ctx)
    db = ctx.db
    campaigns = list(db.scalars(select(Campaign).where(Campaign.tenant_id == tenant.id, Campaign.is_published.is_(True))
                                .order_by(Campaign.submission_start.desc())))
    if campaign_id is None:
        featured = featured_campaign(db, tenant.id)
        campaign_id = featured.id if featured else None
    elif campaign_id not in {c.id for c in campaigns}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")

    cards: dict[str, list[BoardCard]] = {key: [] for key, _ in BOARD_COLUMNS}
    if campaign_id is not None:
        coauthors = select(func.count()).select_from(IdeaCoauthor).where(IdeaCoauthor.idea_id == Idea.id) \
            .correlate(Idea).scalar_subquery()
        reviews = dict(db.execute(
            select(Assignment.idea_id, func.count(Assignment.verdict)).where(Assignment.campaign_id == campaign_id)
            .group_by(Assignment.idea_id)).all())
        totals = dict(db.execute(
            select(Assignment.idea_id, func.count()).where(Assignment.campaign_id == campaign_id)
            .group_by(Assignment.idea_id)).all())
        rows = db.execute(
            select(Idea, User.name, User.sector, CampaignLine.name, coauthors)
            .join(User, User.id == Idea.author_id).outerjoin(CampaignLine, CampaignLine.id == Idea.line_id)
            .where(Idea.campaign_id == campaign_id, Idea.stage != IdeaStage.rascunho)
            .order_by(Idea.number))
        for idea, author, sector, line, n_coauthors in rows:
            cards[idea.stage.value].append(BoardCard(
                id=idea.id, number=idea.number, title=idea.title, line_name=line, author_name=author,
                author_sector=sector, coauthors=n_coauthors, submitted_at=idea.submitted_at,
                reviews_done=reviews.get(idea.id, 0), reviews_total=totals.get(idea.id, 0),
                score=idea.classification_score))
    return BoardOut(campaigns=[BoardCampaign(id=c.id, title=c.title) for c in campaigns], campaign_id=campaign_id,
                    columns=[BoardColumn(key=key, label=label, cards=cards[key]) for key, label in BOARD_COLUMNS])
