"""Campanhas: configuração na Administração e página inicial para quem entra no hospital."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..campaigns import (
    MAX_ACTIVE_LINES, date_order_problem, featured_campaign, lines_of, phases, submission_state, youtube_embed,
    youtube_id,
)
from ..config import get_settings
from ..deps import RequestContext, get_context, get_current_user, require_active_tenant
from ..ideas import clean_options, current_regulation
from ..models import (
    Campaign, CampaignField, CampaignLine, FieldKind, Idea, IdeaAnswer, IdeaStage, RegulationVersion, Role, User,
)
from ..schemas import (
    CampaignAdminOut, CampaignCreate, CampaignFieldIn, CampaignFieldOrder, CampaignFieldOut, CampaignFieldUpdate,
    CampaignLineIn, CampaignLineOrder, CampaignLineOut, CampaignLineUpdate, CampaignPublic, CampaignSummary,
    CampaignUpdate,
)
from ..storage import get_storage, image_extension
from .admin import AdminCtx, admin_ctx

router = APIRouter(prefix="/api", tags=["campanhas"])

MANAGERS = {Role.administrador, Role.consultor}


def _line_out(line: CampaignLine) -> CampaignLineOut:
    return CampaignLineOut(id=line.id, name=line.name, description=line.description, position=line.position,
                           is_active=line.is_active)


def fields_of(db, campaign_id: uuid.UUID, only_active: bool = False) -> list[CampaignField]:
    query = select(CampaignField).where(CampaignField.campaign_id == campaign_id)
    if only_active:
        query = query.where(CampaignField.is_active.is_(True))
    return list(db.scalars(query.order_by(CampaignField.position, CampaignField.label)))


def field_out(f: CampaignField, answers: int = 0) -> CampaignFieldOut:
    return CampaignFieldOut(id=f.id, kind=f.kind, label=f.label, help_text=f.help_text, required=f.required,
                            options=f.options, position=f.position, is_active=f.is_active, answers=answers)


def _summary_fields(db, c: Campaign) -> dict:
    active = db.scalar(select(func.count()).select_from(CampaignLine).where(
        CampaignLine.campaign_id == c.id, CampaignLine.is_active.is_(True))) or 0
    return dict(id=c.id, title=c.title, is_published=c.is_published, submission_start=c.submission_start,
                submission_end=c.submission_end, submission_state=submission_state(c), current_phase=c.current_phase,
                active_lines=active)


def _admin_out(db, c: Campaign) -> CampaignAdminOut:
    fields = {k: getattr(c, k) for k in CampaignAdminOut.model_fields
              if hasattr(Campaign, k) and k not in {"id", "title", "is_published", "submission_start",
                                                    "submission_end", "current_phase"}}
    answers = dict(db.execute(
        select(IdeaAnswer.field_id, func.count()).join(CampaignField, CampaignField.id == IdeaAnswer.field_id)
        .where(CampaignField.campaign_id == c.id).group_by(IdeaAnswer.field_id)).all())
    regulation = current_regulation(db, c.id)
    submitted = db.scalar(select(func.count()).select_from(Idea).where(
        Idea.campaign_id == c.id, Idea.stage != IdeaStage.rascunho)) or 0
    return CampaignAdminOut(**_summary_fields(db, c), **fields, banner_url=get_storage().url(c.banner_path),
                            lines=[_line_out(x) for x in lines_of(db, c.id)],
                            fields=[field_out(f, answers.get(f.id, 0)) for f in fields_of(db, c.id)],
                            regulation_version=regulation.version if regulation else None,
                            ideas_submitted=submitted)


def _get_campaign(a: AdminCtx, campaign_id: uuid.UUID) -> Campaign:
    c = a.db.get(Campaign, campaign_id)
    if c is None or c.tenant_id != a.tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    return c


def _get_line(a: AdminCtx, line_id: uuid.UUID) -> CampaignLine:
    line = a.db.get(CampaignLine, line_id)
    if line is None or line.tenant_id != a.tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linha de ideias não encontrada.")
    return line


def _active_lines(a: AdminCtx, campaign_id: uuid.UUID) -> int:
    return a.db.scalar(select(func.count()).select_from(CampaignLine).where(
        CampaignLine.campaign_id == campaign_id, CampaignLine.is_active.is_(True))) or 0


# ---------- Administração ----------

@router.get("/admin/campaigns", response_model=list[CampaignSummary])
def list_campaigns(a: AdminCtx = Depends(admin_ctx)) -> list[CampaignSummary]:
    rows = a.db.scalars(select(Campaign).where(Campaign.tenant_id == a.tenant.id)
                        .order_by(Campaign.submission_start.desc()))
    return [CampaignSummary(**_summary_fields(a.db, c)) for c in rows]


@router.post("/admin/campaigns", response_model=CampaignAdminOut, status_code=status.HTTP_201_CREATED)
def create_campaign(body: CampaignCreate, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    if body.submission_start >= body.submission_end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "A data de fim das inscrições deve ser depois da data de início das inscrições.")
    t = a.tenant
    # Regras da avaliação copiadas dos padrões do hospital (cada campanha pode mudar depois).
    c = Campaign(tenant_id=t.id, title=body.title.strip(), submission_start=body.submission_start,
                 submission_end=body.submission_end, num_evaluators=t.default_num_evaluators,
                 weight_classify=t.default_weight_classify, weight_maybe=t.default_weight_maybe,
                 cutoff_score=t.default_cutoff_score, created_by=a.actor.id)
    a.db.add(c)
    a.db.flush()
    a.record("campanha_criada", entity="campaign", entity_id=c.id, details=body.model_dump(mode="json"))
    a.db.commit()
    return _admin_out(a.db, c)


@router.get("/admin/campaigns/{campaign_id}", response_model=CampaignAdminOut)
def get_campaign(campaign_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    return _admin_out(a.db, _get_campaign(a, campaign_id))


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


@router.patch("/admin/campaigns/{campaign_id}", response_model=CampaignAdminOut)
def update_campaign(campaign_id: uuid.UUID, body: CampaignUpdate, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    changes = body.model_dump(exclude_unset=True)
    for required in ("title", "submission_start", "submission_end", "num_evaluators", "weight_classify",
                     "weight_maybe", "cutoff_score", "num_winners", "is_published", "blind_review",
                     "defense_use_cutoff"):
        if required in changes and changes[required] is None:
            raise _unprocessable("Preencha o título, o período de inscrição e as regras da avaliação.")
    if changes.get("video_url") and youtube_id(changes["video_url"]) is None:
        raise _unprocessable("Informe um link de vídeo do YouTube (por exemplo, https://youtu.be/...).")

    merged = {k: changes.get(k, getattr(c, k)) for k in CampaignUpdate.model_fields}
    if (problem := date_order_problem(merged)) is not None:
        raise _unprocessable(problem)
    n, x, winners = merged["num_defense_finalists"], merged["num_voting_finalists"], merged["num_winners"]
    if n is not None and x is not None and x > n:
        raise _unprocessable("As finalistas da votação não podem ser mais que as finalistas da defesa.")
    if x is not None and winners > x:
        raise _unprocessable("O número de premiadas não pode ser maior que o de finalistas da votação.")
    if changes.get("is_published") is False and c.is_published and a.db.scalar(
            select(func.count()).select_from(Idea).where(Idea.campaign_id == c.id)):
        raise _unprocessable("A campanha já tem ideias e não pode voltar a ser rascunho.")
    if changes.get("is_published") and _active_lines(a, c.id) == 0:
        raise _unprocessable("Cadastre ao menos uma linha de ideias antes de publicar a campanha.")

    for field, value in changes.items():
        setattr(c, field, value.strip() if isinstance(value, str) and field != "regulation_text" else value)
    # Cada texto novo do regulamento vira uma versão: o aceite de quem envia aponta para a versão que leu.
    if changes.get("regulation_text"):
        latest = current_regulation(a.db, c.id)
        if latest is None or latest.text != c.regulation_text:
            a.db.add(RegulationVersion(tenant_id=a.tenant.id, campaign_id=c.id, text=c.regulation_text,
                                       version=(latest.version if latest else 0) + 1, created_by=a.actor.id))
    if changes:
        a.record("campanha_alterada", entity="campaign", entity_id=c.id,
                 details={k: v for k, v in body.model_dump(exclude_unset=True, mode="json").items()
                          if k not in {"home_text", "tips_text", "regulation_text"}} | {
                     k: "(texto alterado)" for k in ("home_text", "tips_text", "regulation_text") if k in changes})
    a.db.commit()
    return _admin_out(a.db, c)


@router.delete("/admin/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> Response:
    c = _get_campaign(a, campaign_id)
    if c.is_published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Só é possível excluir uma campanha que não foi publicada.")
    a.db.delete(c)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta campanha já tem ideias e não pode ser excluída.")
    a.record("campanha_excluida", entity="campaign", entity_id=campaign_id, details={"titulo": c.title})
    a.db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/admin/campaigns/{campaign_id}/banner", response_model=CampaignAdminOut)
async def upload_banner(campaign_id: uuid.UUID, file: UploadFile = File(...),
                        a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    limit = get_settings().max_banner_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "O banner deve ter no máximo 5 MB.")
    extension = image_extension(data)
    if extension is None:
        raise _unprocessable("Envie o banner em PNG, JPG ou WEBP.")
    c.banner_path = get_storage().save(f"tenants/{a.tenant.slug}/campaigns", data, extension)
    a.record("banner_alterado", entity="campaign", entity_id=c.id)
    a.db.commit()
    return _admin_out(a.db, c)


@router.delete("/admin/campaigns/{campaign_id}/banner", response_model=CampaignAdminOut)
def remove_banner(campaign_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    c.banner_path = None
    a.record("banner_removido", entity="campaign", entity_id=c.id)
    a.db.commit()
    return _admin_out(a.db, c)


# ---------- Linhas de ideias (temáticas) ----------

DUPLICATE_LINE = "Já existe uma linha de ideias com este nome nesta campanha."
TOO_MANY_LINES = f"A campanha pode ter no máximo {MAX_ACTIVE_LINES} linhas de ideias ativas."


@router.post("/admin/campaigns/{campaign_id}/lines", response_model=CampaignAdminOut,
             status_code=status.HTTP_201_CREATED)
def add_line(campaign_id: uuid.UUID, body: CampaignLineIn, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    if _active_lines(a, c.id) >= MAX_ACTIVE_LINES:
        raise _unprocessable(TOO_MANY_LINES)
    last = a.db.scalar(select(func.max(CampaignLine.position)).where(CampaignLine.campaign_id == c.id))
    line = CampaignLine(tenant_id=a.tenant.id, campaign_id=c.id, name=body.name.strip(),
                        description=(body.description or "").strip() or None, position=(last or 0) + 1)
    a.db.add(line)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_LINE)
    a.record("linha_criada", entity="campaign_line", entity_id=line.id, details={"nome": line.name})
    a.db.commit()
    return _admin_out(a.db, c)


@router.patch("/admin/campaign-lines/{line_id}", response_model=CampaignAdminOut)
def update_line(line_id: uuid.UUID, body: CampaignLineUpdate, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    line = _get_line(a, line_id)
    c = _get_campaign(a, line.campaign_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)
    if "is_active" in changes and changes["is_active"] is None:
        changes.pop("is_active")
    if changes.get("is_active") and not line.is_active and _active_lines(a, c.id) >= MAX_ACTIVE_LINES:
        raise _unprocessable(TOO_MANY_LINES)
    if changes.get("is_active") is False and line.is_active and c.is_published and _active_lines(a, c.id) == 1:
        raise _unprocessable("A campanha publicada precisa de ao menos uma linha de ideias ativa.")
    for field, value in changes.items():
        setattr(line, field, (value.strip() or None) if isinstance(value, str) else value)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_LINE)
    a.record("linha_alterada", entity="campaign_line", entity_id=line.id, details=body.model_dump(exclude_unset=True))
    a.db.commit()
    return _admin_out(a.db, c)


@router.delete("/admin/campaign-lines/{line_id}", response_model=CampaignAdminOut)
def delete_line(line_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    """Linha com ideias não pode ser apagada, só renomeada ou desativada (o banco garante quando houver ideias)."""
    line = _get_line(a, line_id)
    c = _get_campaign(a, line.campaign_id)
    if line.is_active and c.is_published and _active_lines(a, c.id) == 1:
        raise _unprocessable("A campanha publicada precisa de ao menos uma linha de ideias ativa.")
    a.db.delete(line)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta linha já tem ideias: desative-a em vez de excluir.")
    a.record("linha_excluida", entity="campaign_line", entity_id=line_id, details={"nome": line.name})
    a.db.commit()
    return _admin_out(a.db, c)


@router.put("/admin/campaigns/{campaign_id}/lines/order", response_model=CampaignAdminOut)
def reorder_lines(campaign_id: uuid.UUID, body: CampaignLineOrder, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    lines = {line.id: line for line in lines_of(a.db, c.id)}
    if set(body.ids) != set(lines) or len(body.ids) != len(lines):
        raise _unprocessable("Envie a ordem com todas as linhas da campanha.")
    for position, line_id in enumerate(body.ids, start=1):
        lines[line_id].position = position
    a.record("linhas_reordenadas", entity="campaign", entity_id=c.id)
    a.db.commit()
    return _admin_out(a.db, c)


# ---------- Campos do formulário de envio ----------

def _get_field(a: AdminCtx, field_id: uuid.UUID) -> CampaignField:
    f = a.db.get(CampaignField, field_id)
    if f is None or f.tenant_id != a.tenant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campo não encontrado.")
    return f


def _options_for(kind: FieldKind, options: list[str] | None) -> list[str] | None:
    if kind != FieldKind.lista:
        return None
    try:
        return clean_options(options)
    except ValueError as e:
        raise _unprocessable(str(e))


@router.post("/admin/campaigns/{campaign_id}/fields", response_model=CampaignAdminOut,
             status_code=status.HTTP_201_CREATED)
def add_field(campaign_id: uuid.UUID, body: CampaignFieldIn, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    last = a.db.scalar(select(func.max(CampaignField.position)).where(CampaignField.campaign_id == c.id))
    f = CampaignField(tenant_id=a.tenant.id, campaign_id=c.id, kind=body.kind, label=body.label.strip(),
                      help_text=(body.help_text or "").strip() or None, required=body.required,
                      options=_options_for(body.kind, body.options), position=(last or 0) + 1)
    a.db.add(f)
    a.db.flush()
    a.record("campo_criado", entity="campaign_field", entity_id=f.id,
             details={"rotulo": f.label, "tipo": f.kind.value, "obrigatorio": f.required})
    a.db.commit()
    return _admin_out(a.db, c)


@router.patch("/admin/campaign-fields/{field_id}", response_model=CampaignAdminOut)
def update_field(field_id: uuid.UUID, body: CampaignFieldUpdate, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    f = _get_field(a, field_id)
    c = _get_campaign(a, f.campaign_id)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items()
               if v is not None or k == "help_text"}
    if "options" in changes:
        changes["options"] = _options_for(f.kind, changes["options"])
    if "label" in changes:
        changes["label"] = changes["label"].strip()
    if "help_text" in changes:
        changes["help_text"] = (changes["help_text"] or "").strip() or None
    for field, value in changes.items():
        setattr(f, field, value)
    a.record("campo_alterado", entity="campaign_field", entity_id=f.id, details=body.model_dump(exclude_unset=True))
    a.db.commit()
    return _admin_out(a.db, c)


@router.delete("/admin/campaign-fields/{field_id}", response_model=CampaignAdminOut)
def delete_field(field_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    """Campo com respostas não é apagado, só desativado (o banco garante)."""
    f = _get_field(a, field_id)
    c = _get_campaign(a, f.campaign_id)
    a.db.delete(f)
    try:
        a.db.flush()
    except IntegrityError:
        a.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Este campo já tem respostas: desative-o em vez de excluir.")
    a.record("campo_excluido", entity="campaign_field", entity_id=field_id, details={"rotulo": f.label})
    a.db.commit()
    return _admin_out(a.db, c)


@router.put("/admin/campaigns/{campaign_id}/fields/order", response_model=CampaignAdminOut)
def reorder_fields(campaign_id: uuid.UUID, body: CampaignFieldOrder, a: AdminCtx = Depends(admin_ctx)) -> CampaignAdminOut:
    c = _get_campaign(a, campaign_id)
    fields = {f.id: f for f in fields_of(a.db, c.id)}
    if set(body.ids) != set(fields) or len(body.ids) != len(fields):
        raise _unprocessable("Envie a ordem com todos os campos do formulário.")
    for position, field_id in enumerate(body.ids, start=1):
        fields[field_id].position = position
    a.record("campos_reordenados", entity="campaign", entity_id=c.id)
    a.db.commit()
    return _admin_out(a.db, c)


# ---------- Página inicial ----------

def _public_out(db, c: Campaign, tenant) -> CampaignPublic:
    storage = get_storage()
    regulation = current_regulation(db, c.id)
    return CampaignPublic(
        id=c.id, title=c.title, is_published=c.is_published, home_headline=c.home_headline, home_text=c.home_text,
        tips_text=c.tips_text, regulation_text=c.regulation_text,
        regulation_version=regulation.version if regulation else None,
        regulation_updated_at=regulation.created_at if regulation else None,
        banner_url=storage.url(c.banner_path or tenant.default_banner_path),
        video_embed_url=youtube_embed(c.video_url or tenant.default_video_url),
        submission_start=c.submission_start, submission_end=c.submission_end, submission_state=submission_state(c),
        current_phase=c.current_phase, phases=phases(c), num_winners=c.num_winners,
        lines=[_line_out(x) for x in lines_of(db, c.id, only_active=True)],
    )


def member_ctx(user: User = Depends(get_current_user), ctx: RequestContext = Depends(get_context)):
    return user, ctx, require_active_tenant(ctx)


@router.get("/campaigns/current", response_model=CampaignPublic | None)
def current_campaign(m=Depends(member_ctx)) -> CampaignPublic | None:
    _, ctx, tenant = m
    c = featured_campaign(ctx.db, tenant.id)
    return _public_out(ctx.db, c, tenant) if c else None


@router.get("/campaigns/{campaign_id}", response_model=CampaignPublic)
def campaign_page(campaign_id: uuid.UUID, m=Depends(member_ctx)) -> CampaignPublic:
    """Qualquer campanha publicada; rascunhos só para quem administra (pré-visualização)."""
    user, ctx, tenant = m
    c = ctx.db.get(Campaign, campaign_id)
    if c is None or c.tenant_id != tenant.id or (not c.is_published and user.role not in MANAGERS):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    return _public_out(ctx.db, c, tenant)
