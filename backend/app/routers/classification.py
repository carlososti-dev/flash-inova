"""Classificação: apuração dos pareceres, ranking com linha de corte e Voto de Minerva (menu Classificação).

A apuração só é feita depois do fim do período de análise e é gravada uma vez: cada ideia em análise passa para
Classificada, Talvez, Não classificada ou Empate. As empatadas aguardam o Voto de Minerva, dado só pelo
administrador e registrado na auditoria.
"""
import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from ..analysis import evaluation_state
from ..campaigns import featured_campaign
from ..classification import tally
from ..deps import RequestContext, get_context, require_active_tenant, require_roles
from ..ideas import STAGE_LABELS
from ..models import (
    Assignment, Campaign, CampaignLine, CampaignPhase, Idea, IdeaStage, Role, User, Verdict, utcnow,
)
from ..schemas import BoardCampaign, ClassificationOut, ClassifiedIdea, MinervaIn, ReviewOut
from .admin import AdminCtx, admin_ctx
from .campaigns import _get_campaign
from .ideas import FOLLOWERS

router = APIRouter(prefix="/api", tags=["classificação"])

MANAGERS = {Role.administrador, Role.consultor}
# Etapas que entram no ranking (as que passaram da Classificação também, com a nota que tiveram).
RANKED = {IdeaStage.classificada, IdeaStage.talvez, IdeaStage.shortlist, IdeaStage.selecionada, IdeaStage.premiada}
RESULT_STAGES = {IdeaStage.classificada, IdeaStage.talvez, IdeaStage.nao_classificada}


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _blocker(db, c: Campaign) -> str | None:
    if c.classified_at is not None:
        return "A apuração desta campanha já foi feita."
    if not db.scalar(select(Assignment.id).where(Assignment.campaign_id == c.id).limit(1)):
        return "Ainda não há ideias distribuídas para o comitê."
    if c.analysis_end is None:
        return "Defina a data de fim da análise na campanha: a apuração é feita depois dela."
    if evaluation_state(c) != "encerrada":
        return "A apuração é feita depois do fim do período de análise."
    return None


def _classified(db, c: Campaign, managers: bool) -> list[ClassifiedIdea]:
    """Ideias da campanha com a apuração (gravada ou, antes dela, a prévia pelos pareceres atuais), em ordem de
    ranking: classificadas pela nota, depois empates e não classificadas."""
    reviews: dict[uuid.UUID, list[tuple[Assignment, str]]] = {}
    for asg, evaluator in db.execute(select(Assignment, User.name).join(User, User.id == Assignment.evaluator_id)
                                     .where(Assignment.campaign_id == c.id).order_by(User.name)):
        reviews.setdefault(asg.idea_id, []).append((asg, evaluator))
    rows = db.execute(
        select(Idea, User.name, User.sector, CampaignLine.name)
        .join(User, User.id == Idea.author_id).outerjoin(CampaignLine, CampaignLine.id == Idea.line_id)
        .where(Idea.campaign_id == c.id, Idea.id.in_(select(Assignment.idea_id).where(Assignment.campaign_id == c.id))))
    minerva_names = dict(db.execute(select(User.id, User.name).where(User.id.in_(
        select(Idea.minerva_by).where(Idea.campaign_id == c.id, Idea.minerva_by.isnot(None))))).all())

    items: list[ClassifiedIdea] = []
    for idea, author, sector, line in rows:
        own = reviews.get(idea.id, [])
        t = tally([a.verdict for a, _ in own], c.num_evaluators, c.weight_classify, c.weight_maybe,
                  minerva=idea.minerva_verdict)
        outcome = t.outcome if idea.stage == IdeaStage.em_analise else idea.stage
        score = idea.classification_score if c.classified_at else (None if t.outcome == IdeaStage.empate else t.score)
        items.append(ClassifiedIdea(
            id=idea.id, number=idea.number, title=idea.title, line_name=line, author_name=author, author_sector=sector,
            stage=idea.stage, outcome=outcome, classify=t.classify, maybe=t.maybe, reject=t.reject,
            reviews_total=len(own), score=score, weighted=t.weighted, rank=None, above_cutoff=False,
            minerva_verdict=idea.minerva_verdict, minerva_comment=idea.minerva_comment,
            minerva_by=minerva_names.get(idea.minerva_by), minerva_at=idea.minerva_at,
            reviews=[ReviewOut(verdict=a.verdict, comment=a.comment, evaluator_name=name if managers else None)
                     for a, name in own]))

    group = {IdeaStage.empate: 1, IdeaStage.nao_classificada: 2, IdeaStage.em_analise: 3}
    items.sort(key=lambda i: (group.get(i.outcome, 0), -(i.score or 0), -i.weighted, i.number or 0))
    position = 0
    for i in items:
        if i.outcome in RANKED:
            position += 1
            i.rank = position
            i.above_cutoff = (i.score or 0) >= c.cutoff_score
    return items


def _published(db, tenant_id: uuid.UUID) -> list[Campaign]:
    return list(db.scalars(select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.is_published.is_(True))
                           .order_by(Campaign.submission_start.desc())))


def _pick_campaign(db, tenant_id: uuid.UUID, campaign_id: uuid.UUID | None) -> tuple[list[Campaign], Campaign | None]:
    campaigns = _published(db, tenant_id)
    if campaign_id is None:
        featured = featured_campaign(db, tenant_id)
        return campaigns, featured if featured and featured.is_published else None
    c = next((x for x in campaigns if x.id == campaign_id), None)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    return campaigns, c


def _out(db, user: User, campaigns: list[Campaign], c: Campaign | None) -> ClassificationOut:
    managers = user.role in MANAGERS
    if c is None:
        return ClassificationOut(campaigns=[], campaign_id=None, evaluation_state=None, analysis_end=None,
                                 classified_at=None, blocker=None, pending_reviews=0, cutoff_score=0,
                                 num_defense_finalists=None, can_manage=managers,
                                 can_minerva=user.role == Role.administrador, ideas=[])
    ideas = _classified(db, c, managers)
    pending = sum(1 for i in ideas if i.stage == IdeaStage.em_analise for r in i.reviews if r.verdict is None)
    return ClassificationOut(
        campaigns=[BoardCampaign(id=x.id, title=x.title) for x in campaigns], campaign_id=c.id,
        evaluation_state=evaluation_state(c), analysis_end=c.analysis_end, classified_at=c.classified_at,
        blocker=_blocker(db, c), pending_reviews=pending, cutoff_score=c.cutoff_score,
        num_defense_finalists=c.num_defense_finalists, can_manage=managers,
        can_minerva=user.role == Role.administrador, ideas=ideas)


@router.get("/classification", response_model=ClassificationOut)
def classification(campaign_id: uuid.UUID | None = None, user: User = Depends(require_roles(*FOLLOWERS)),
                   ctx: RequestContext = Depends(get_context)) -> ClassificationOut:
    tenant = require_active_tenant(ctx)
    return _out(ctx.db, user, *_pick_campaign(ctx.db, tenant.id, campaign_id))


@router.post("/admin/campaigns/{campaign_id}/classification", response_model=ClassificationOut)
def run_classification(campaign_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> ClassificationOut:
    """Grava a apuração: cada ideia em análise passa para o resultado dos pareceres. Pareceres em branco não contam."""
    c = _get_campaign(a, campaign_id)
    a.db.execute(select(Campaign.id).where(Campaign.id == c.id).with_for_update())
    if (blocker := _blocker(a.db, c)) is not None:
        raise _unprocessable(blocker)

    counts = {stage.value: 0 for stage in (*RESULT_STAGES, IdeaStage.empate)}
    for item in _classified(a.db, c, managers=True):
        if item.stage != IdeaStage.em_analise:
            continue
        idea = a.db.get(Idea, item.id)
        idea.stage, idea.classification_score = item.outcome, item.score
        counts[item.outcome.value] += 1
    c.classified_at = utcnow()
    if c.current_phase in {CampaignPhase.recepcao, CampaignPhase.analise}:
        c.current_phase = CampaignPhase.classificacao
    a.record("classificacao_apurada", entity="campaign", entity_id=c.id,
             details=counts | {"linha_de_corte": c.cutoff_score})
    a.db.commit()
    return _out(a.db, a.actor, _published(a.db, a.tenant.id), c)


def _require_administrator(a: AdminCtx = Depends(admin_ctx)) -> AdminCtx:
    if a.actor.role != Role.administrador:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "O Voto de Minerva é dado pelo administrador do hospital.")
    return a


@router.put("/admin/campaigns/{campaign_id}/classification/ideas/{idea_id}/minerva", response_model=ClassificationOut)
def minerva(campaign_id: uuid.UUID, idea_id: uuid.UUID, body: MinervaIn,
            a: AdminCtx = Depends(_require_administrator)) -> ClassificationOut:
    """Desempata a ideia: o voto entra como um parecer a mais. Pode ser trocado enquanto a campanha estiver na
    Classificação."""
    c = _get_campaign(a, campaign_id)
    idea = a.db.get(Idea, idea_id)
    if idea is None or idea.campaign_id != c.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ideia não encontrada.")
    decided = idea.minerva_verdict is not None and idea.stage in RESULT_STAGES
    if idea.stage != IdeaStage.empate and not decided:
        raise HTTPException(status.HTTP_409_CONFLICT, "O Voto de Minerva é só para ideias empatadas.")
    if c.current_phase != CampaignPhase.classificacao:
        raise HTTPException(status.HTTP_409_CONFLICT, "A Classificação desta campanha já foi fechada.")
    comment = body.comment.strip()
    if not comment:
        raise _unprocessable("Escreva a justificativa do Voto de Minerva.")

    verdicts = a.db.scalars(select(Assignment.verdict).where(Assignment.idea_id == idea.id))
    t = tally(verdicts, c.num_evaluators, c.weight_classify, c.weight_maybe, minerva=body.verdict)
    previous = idea.minerva_verdict
    idea.stage, idea.classification_score = t.outcome, t.score
    idea.minerva_verdict, idea.minerva_comment = body.verdict, comment
    idea.minerva_by, idea.minerva_at = a.actor.id, utcnow()
    a.record("voto_de_minerva", entity="idea", entity_id=idea.id,
             details={"ideia": idea.number, "voto": body.verdict.value, "resultado": t.outcome.value,
                      "nota": t.score, "anterior": previous.value if previous else None, "justificativa": comment})
    a.db.commit()
    return _out(a.db, a.actor, _published(a.db, a.tenant.id), c)


VERDICT_SHORT = {Verdict.classificar: "Classificar", Verdict.talvez: "Talvez", Verdict.nao_classificar: "Não classificar"}


@router.get("/classification.csv")
def export_ranking(campaign_id: uuid.UUID | None = None, user: User = Depends(require_roles(*FOLLOWERS)),
                   ctx: RequestContext = Depends(get_context)) -> Response:
    tenant = require_active_tenant(ctx)
    _, c = _pick_campaign(ctx.db, tenant.id, campaign_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Posição", "Nº", "Título", "Linha de ideias", "Autor", "Setor", "Resultado", "Nota",
                "Classificar", "Talvez", "Não classificar", "Pontos", "Acima da linha de corte", "Voto de Minerva",
                "Justificativa do Voto de Minerva"])
    for i in _classified(ctx.db, c, managers=False):
        w.writerow([i.rank or "", i.number or "", i.title, i.line_name or "", i.author_name, i.author_sector or "",
                    STAGE_LABELS[i.outcome] + ("" if c.classified_at else " (prévia)"),
                    "" if i.score is None else i.score, i.classify, i.maybe, i.reject, i.weighted,
                    ("Sim" if i.above_cutoff else "Não") if i.rank else "",
                    VERDICT_SHORT[i.minerva_verdict] if i.minerva_verdict else "", i.minerva_comment or ""])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="classificacao.csv"'})
