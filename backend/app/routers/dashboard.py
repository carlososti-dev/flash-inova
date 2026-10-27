"""Dashboard: acompanhamento dos avaliadores (quantas ideias cada um ainda tem por avaliar) e o alerta por e-mail
para quem está com parecer pendente, enviado pelo administrador perto do fim da análise."""
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from ..analysis import evaluation_state
from ..config import get_settings
from ..deps import RequestContext, get_context, require_active_tenant, require_roles
from ..email import EmailMessage, get_email_sender
from ..links import frontend_link
from ..models import Assignment, AuditLog, Campaign, CampaignLine, Idea, IdeaStage, Role, User, UserStatus
from ..schemas import (
    BoardCampaign, EvaluatorReport, EvaluatorsReportOut, IdeaReviewStatus, ReminderIn, ReminderOut,
)
from .admin import AdminCtx, admin_ctx
from .campaigns import _get_campaign

router = APIRouter(prefix="/api", tags=["dashboard"])

REMINDER_ACTION = "lembrete_avaliacao"


def _fmt(value: datetime) -> str:
    return value.astimezone(ZoneInfo(get_settings().timezone)).strftime("%d/%m/%Y às %H:%M")


def _pending(db, c: Campaign) -> dict[uuid.UUID, int]:
    """Pareceres em branco por avaliador, nas ideias ainda em análise."""
    return dict(db.execute(
        select(Assignment.evaluator_id, func.count()).join(Idea, Idea.id == Assignment.idea_id)
        .where(Assignment.campaign_id == c.id, Assignment.verdict.is_(None), Idea.stage == IdeaStage.em_analise)
        .group_by(Assignment.evaluator_id)).all())


def _can_remind(db, c: Campaign) -> bool:
    return evaluation_state(c) != "encerrada" and c.classified_at is None and bool(_pending(db, c))


@router.get("/dashboard/evaluators", response_model=EvaluatorsReportOut)
def evaluators_report(campaign_id: uuid.UUID | None = None,
                      user: User = Depends(require_roles(Role.administrador, Role.consultor)),
                      ctx: RequestContext = Depends(get_context)) -> EvaluatorsReportOut:
    tenant = require_active_tenant(ctx)
    db = ctx.db
    campaigns = list(db.scalars(select(Campaign).where(
        Campaign.tenant_id == tenant.id, Campaign.id.in_(select(Assignment.campaign_id)))
        .order_by(Campaign.submission_start.desc())))
    c = campaigns[0] if campaign_id is None and campaigns else next((x for x in campaigns if x.id == campaign_id), None)
    if campaign_id is not None and c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    listed = [BoardCampaign(id=x.id, title=x.title) for x in campaigns]
    if c is None:
        return EvaluatorsReportOut(campaigns=listed, campaign_id=None, evaluation_state=None, analysis_end=None,
                                   can_remind=False, reviews_done=0, reviews_total=0, evaluators=[], ideas=[])

    rows = list(db.execute(
        select(Assignment, User.name, User.sector, Idea.number, Idea.title, CampaignLine.name)
        .join(User, User.id == Assignment.evaluator_id).join(Idea, Idea.id == Assignment.idea_id)
        .outerjoin(CampaignLine, CampaignLine.id == Idea.line_id)
        .where(Assignment.campaign_id == c.id).order_by(Idea.number, User.name)))
    reminders = dict(db.execute(
        select(AuditLog.entity_id, func.max(AuditLog.created_at))
        .where(AuditLog.tenant_id == tenant.id, AuditLog.action == REMINDER_ACTION,
               AuditLog.details["campanha"].astext == str(c.id))
        .group_by(AuditLog.entity_id)).all())

    people: dict[uuid.UUID, EvaluatorReport] = {}
    ideas: dict[uuid.UUID, IdeaReviewStatus] = {}
    for asg, name, sector, number, title, line in rows:
        p = people.setdefault(asg.evaluator_id, EvaluatorReport(
            id=asg.evaluator_id, name=name, sector=sector, assigned=0, evaluated=0, pending=0,
            last_evaluated_at=None, last_reminder_at=reminders.get(str(asg.evaluator_id))))
        i = ideas.setdefault(asg.idea_id, IdeaReviewStatus(id=asg.idea_id, number=number, title=title,
                                                           line_name=line, done=0, total=0, pending_evaluators=[]))
        p.assigned += 1
        i.total += 1
        if asg.verdict is None:
            p.pending += 1
            i.pending_evaluators.append(name)
        else:
            p.evaluated += 1
            i.done += 1
            if p.last_evaluated_at is None or (asg.evaluated_at and asg.evaluated_at > p.last_evaluated_at):
                p.last_evaluated_at = asg.evaluated_at
    return EvaluatorsReportOut(
        campaigns=listed, campaign_id=c.id, evaluation_state=evaluation_state(c), analysis_end=c.analysis_end,
        can_remind=_can_remind(db, c), reviews_done=sum(i.done for i in ideas.values()),
        reviews_total=sum(i.total for i in ideas.values()),
        evaluators=sorted(people.values(), key=lambda p: (-p.pending, p.name.lower())),
        ideas=sorted(ideas.values(), key=lambda i: (i.done - i.total, i.number or 0)))


@router.post("/admin/campaigns/{campaign_id}/reminders", response_model=ReminderOut)
def send_reminders(campaign_id: uuid.UUID, body: ReminderIn, a: AdminCtx = Depends(admin_ctx)) -> ReminderOut:
    """Alerta por e-mail a cada avaliador com parecer pendente (todos, ou só os escolhidos)."""
    c = _get_campaign(a, campaign_id)
    if evaluation_state(c) == "encerrada" or c.classified_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "O período de análise terminou: não há mais prazo para avisar.")
    pending = _pending(a.db, c)
    if body.evaluator_ids is not None:
        pending = {k: v for k, v in pending.items() if k in set(body.evaluator_ids)}

    link = frontend_link(a.tenant, "/analise")
    deadline = f"O prazo para dar o parecer termina em {_fmt(c.analysis_end)}.\n" if c.analysis_end else ""
    extra = f"\nMensagem da administração:\n{body.message.strip()}\n" if body.message and body.message.strip() else ""
    recipients = list(a.db.scalars(select(User).where(User.id.in_(pending.keys()), User.status == UserStatus.ativo)
                                   .order_by(User.name)))
    if not recipients:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nenhum dos avaliadores tem parecer pendente.")
    for u in recipients:
        n = pending[u.id]
        ideas = "1 ideia aguardando" if n == 1 else f"{n} ideias aguardando"
        get_email_sender().send(EmailMessage(
            to=u.email,
            subject=f"{c.title}: {ideas} seu parecer",
            body=(f"Olá, {u.name}.\n\nVocê tem {ideas} seu parecer na campanha \"{c.title}\".\n{deadline}{extra}\n"
                  f"Para avaliar, acesse o menu Análise:\n{link}"),
        ))
        a.record(REMINDER_ACTION, entity="user", entity_id=u.id, details={"campanha": str(c.id), "pendentes": n})
    a.db.commit()
    return ReminderOut(sent=len(recipients), recipients=[u.name for u in recipients])
