"""Defesa: os autores das ideias classificadas defendem o projeto para uma banca, fora do app.

1. "Fechar Classificação": o administrador confirma quem entra na Defesa. A sugestão segue a regra da campanha
   (todas as Classificadas ou só as com nota ≥ linha de corte, limitadas às N primeiras, se N estiver definido), e
   ele pode tirar ou incluir ideias do ranking para tratar desistências e empates.
2. Parecer da banca, lançado pelo administrador: Viável (vai para a Shortlist) ou Desclassificada, com ao menos um
   motivo e comentário obrigatório. Pode ser corrigido até o fechamento da fase.
3. "Fechar Defesa": todas com parecer e ao menos uma viável. A campanha passa para a Votação.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..deps import RequestContext, get_context, require_active_tenant, require_roles
from ..models import Campaign, CampaignPhase, DefenseReason, Idea, IdeaStage, Role, User, utcnow
from ..schemas import BoardCampaign, DefenseCandidate, DefenseIdea, DefenseOut, DefenseStartIn, DefenseVerdictIn
from .admin import AdminCtx, admin_ctx
from .campaigns import _get_campaign
from .classification import _classified, _pick_campaign, _published
from .ideas import FOLLOWERS

router = APIRouter(prefix="/api", tags=["defesa"])

CANDIDATE_STAGES = {IdeaStage.classificada, IdeaStage.talvez}
DEFENSE_STAGES = {IdeaStage.em_defesa, IdeaStage.shortlist, IdeaStage.desclassificada}


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _start_blocker(c: Campaign, ideas) -> str | None:
    if c.current_phase in {CampaignPhase.recepcao, CampaignPhase.analise} or c.classified_at is None:
        return "Faça a apuração da Classificação antes de fechá-la."
    if c.current_phase != CampaignPhase.classificacao:
        return "A Classificação desta campanha já foi fechada."
    if any(i.stage == IdeaStage.empate for i in ideas):
        return "Há ideias empatadas aguardando o Voto de Minerva."
    if not any(i.stage in CANDIDATE_STAGES for i in ideas):
        return "Nenhuma ideia foi classificada."
    return None


def _close_blocker(c: Campaign, ideas: list[DefenseIdea]) -> str | None:
    if c.current_phase != CampaignPhase.defesa:
        return "A campanha não está na fase de Defesa."
    if pending := sum(1 for i in ideas if i.stage == IdeaStage.em_defesa):
        return f"Falta o parecer da banca em {pending} ideia(s)."
    if not any(i.stage == IdeaStage.shortlist for i in ideas):
        return "Nenhuma ideia foi considerada viável: a Votação precisa de ao menos uma."
    return None


def _out(db, user: User, campaigns: list[Campaign], c: Campaign | None) -> DefenseOut:
    can_manage = user.role == Role.administrador
    if c is None:
        return DefenseOut(campaigns=[], campaign_id=None, current_phase=None, cutoff_score=0, defense_use_cutoff=False,
                          num_defense_finalists=None, can_manage=can_manage, start_blocker=None, close_blocker=None,
                          candidates=[], ideas=[])
    ranking = _classified(db, c, managers=False)
    sector = {i.id: i.author_sector for i in ranking}
    rows = {idea.id: idea for idea in db.scalars(select(Idea).where(Idea.campaign_id == c.id,
                                                                     Idea.stage.in_(DEFENSE_STAGES)))}
    deciders = dict(db.execute(select(User.id, User.name).where(
        User.id.in_({i.defense_by for i in rows.values() if i.defense_by}))).all())
    ideas = [DefenseIdea(id=i.id, number=i.number, title=i.title, line_name=i.line_name, author_name=i.author_name,
                         author_sector=sector[i.id], stage=i.stage, score=i.score, rank=i.rank,
                         reasons=rows[i.id].defense_reasons or [], comment=rows[i.id].defense_comment,
                         decided_by=deciders.get(rows[i.id].defense_by), decided_at=rows[i.id].defense_at)
             for i in ranking if i.id in rows]

    candidates: list[DefenseCandidate] = []
    if c.current_phase == CampaignPhase.classificacao:
        suggested = 0
        for i in ranking:
            if i.stage not in CANDIDATE_STAGES:
                continue
            fits = (i.stage == IdeaStage.classificada and (not c.defense_use_cutoff or i.above_cutoff)
                    and (c.num_defense_finalists is None or suggested < c.num_defense_finalists))
            suggested += fits
            candidates.append(DefenseCandidate(id=i.id, number=i.number, title=i.title, line_name=i.line_name,
                                               author_name=i.author_name, stage=i.stage, score=i.score, rank=i.rank,
                                               suggested=fits))
    return DefenseOut(
        campaigns=[BoardCampaign(id=x.id, title=x.title) for x in campaigns], campaign_id=c.id,
        current_phase=c.current_phase, cutoff_score=c.cutoff_score, defense_use_cutoff=c.defense_use_cutoff,
        num_defense_finalists=c.num_defense_finalists, can_manage=can_manage,
        start_blocker=_start_blocker(c, ranking), close_blocker=_close_blocker(c, ideas),
        candidates=candidates, ideas=ideas)


@router.get("/defense", response_model=DefenseOut)
def defense(campaign_id: uuid.UUID | None = None, user: User = Depends(require_roles(*FOLLOWERS)),
            ctx: RequestContext = Depends(get_context)) -> DefenseOut:
    tenant = require_active_tenant(ctx)
    return _out(ctx.db, user, *_pick_campaign(ctx.db, tenant.id, campaign_id))


def _require_administrator(a: AdminCtx = Depends(admin_ctx)) -> AdminCtx:
    if a.actor.role != Role.administrador:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A Defesa é conduzida pelo administrador do hospital.")
    return a


def _locked_campaign(a: AdminCtx, campaign_id: uuid.UUID) -> Campaign:
    c = _get_campaign(a, campaign_id)
    a.db.execute(select(Campaign.id).where(Campaign.id == c.id).with_for_update())
    return c


@router.post("/admin/campaigns/{campaign_id}/defense/start", response_model=DefenseOut)
def close_classification(campaign_id: uuid.UUID, body: DefenseStartIn,
                         a: AdminCtx = Depends(_require_administrator)) -> DefenseOut:
    """Fecha a Classificação: as ideias escolhidas entram na Defesa e a campanha passa para a fase Defesa."""
    c = _locked_campaign(a, campaign_id)
    ranking = _classified(a.db, c, managers=False)
    if (blocker := _start_blocker(c, ranking)) is not None:
        raise _unprocessable(blocker)
    allowed = {i.id for i in ranking if i.stage in CANDIDATE_STAGES}
    chosen = set(body.idea_ids)
    if not chosen <= allowed:
        raise _unprocessable("Só entram na Defesa ideias Classificadas ou Talvez.")
    numbers = []
    for item in ranking:
        if item.id in chosen:
            a.db.get(Idea, item.id).stage = IdeaStage.em_defesa
            numbers.append(item.number)
    c.current_phase = CampaignPhase.defesa
    a.record("classificacao_fechada", entity="campaign", entity_id=c.id,
             details={"ideias": numbers, "linha_de_corte": c.cutoff_score if c.defense_use_cutoff else None,
                      "n": c.num_defense_finalists})
    a.db.commit()
    return _out(a.db, a.actor, _published(a.db, a.tenant.id), c)


@router.put("/admin/campaigns/{campaign_id}/defense/ideas/{idea_id}", response_model=DefenseOut)
def defense_verdict(campaign_id: uuid.UUID, idea_id: uuid.UUID, body: DefenseVerdictIn,
                    a: AdminCtx = Depends(_require_administrator)) -> DefenseOut:
    """Lança (ou corrige) o parecer da banca sobre uma ideia."""
    c = _get_campaign(a, campaign_id)
    idea = a.db.get(Idea, idea_id)
    if idea is None or idea.campaign_id != c.id or idea.stage not in DEFENSE_STAGES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ideia não encontrada na Defesa.")
    if c.current_phase != CampaignPhase.defesa:
        raise HTTPException(status.HTTP_409_CONFLICT, "A Defesa desta campanha já foi fechada.")
    comment = (body.comment or "").strip() or None
    reasons = list(dict.fromkeys(body.reasons))  # sem repetidos, na ordem em que vieram
    if body.viable:
        reasons = []
    else:
        if not reasons:
            raise _unprocessable("Marque ao menos um motivo da desclassificação.")
        if comment is None:
            raise _unprocessable("Escreva um comentário sobre a desclassificação.")
    previous = idea.stage
    idea.stage = IdeaStage.shortlist if body.viable else IdeaStage.desclassificada
    idea.defense_reasons = [r.value for r in sorted(reasons, key=list(DefenseReason).index)] or None
    idea.defense_comment, idea.defense_by, idea.defense_at = comment, a.actor.id, utcnow()
    a.record("parecer_defesa", entity="idea", entity_id=idea.id,
             details={"ideia": idea.number, "resultado": idea.stage.value, "anterior": previous.value,
                      "motivos": idea.defense_reasons, "comentario": comment})
    a.db.commit()
    return _out(a.db, a.actor, _published(a.db, a.tenant.id), c)


@router.post("/admin/campaigns/{campaign_id}/defense/close", response_model=DefenseOut)
def close_defense(campaign_id: uuid.UUID, a: AdminCtx = Depends(_require_administrator)) -> DefenseOut:
    """Fecha a Defesa: as viáveis (Shortlist) seguem para a Votação."""
    c = _locked_campaign(a, campaign_id)
    current = _out(a.db, a.actor, [], c)
    if current.close_blocker is not None:
        raise _unprocessable(current.close_blocker)
    c.current_phase = CampaignPhase.votacao
    a.record("defesa_fechada", entity="campaign", entity_id=c.id, details={
        "shortlist": [i.number for i in current.ideas if i.stage == IdeaStage.shortlist],
        "desclassificadas": [i.number for i in current.ideas if i.stage == IdeaStage.desclassificada]})
    a.db.commit()
    return _out(a.db, a.actor, _published(a.db, a.tenant.id), c)
