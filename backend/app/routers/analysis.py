"""Análise: distribuição das ideias para o comitê (Administração) e o kanban pessoal de cada avaliador.

O avaliador só vê as ideias distribuídas a ele e, com o duplo-cego ligado, nunca vê autor nem coautores.
Dentro do período da análise, pode dar parecer, voltar atrás e reavaliar quantas vezes quiser.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from .. import audit
from ..analysis import Evaluator, assign, evaluation_state
from ..campaigns import submission_state
from ..deps import RequestContext, get_context, require_active_tenant, require_roles
from ..models import (
    Assignment, AuthorizedMember, Campaign, CampaignField, CampaignLine, CampaignPhase, FieldKind, Idea,
    IdeaAnswer, IdeaCoauthor, IdeaStage, Role, User, UserStatus, Verdict, utcnow,
)
from ..schemas import (
    AnalysisBoardOut, AnalysisCard, AnalysisColumn, AssignmentOut, BoardCampaign, DistributionOut, EvaluatorLoad,
    VerdictIn,
)
from .admin import AdminCtx, admin_ctx
from .campaigns import _get_campaign
from .ideas import answers_out, attachment_response

router = APIRouter(prefix="/api", tags=["análise"])

# Quem pode ter o menu Análise (conforme o menu da página Início).
ANALYSIS_ROLES = (Role.administrador, Role.consultor, Role.membro_comite)

COLUMNS = [(None, "para_analise", "Para análise"), (Verdict.classificar, "classificadas", "Classificadas"),
           (Verdict.nao_classificar, "nao_classificadas", "Não classificadas"), (Verdict.talvez, "talvez", "Talvez")]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


# ---------- Distribuição (Administração) ----------

def _committee(db, tenant_id: uuid.UUID) -> list[User]:
    return list(db.scalars(select(User).where(
        User.tenant_id == tenant_id, User.role == Role.membro_comite, User.status == UserStatus.ativo,
        User.email_verified_at.isnot(None)).order_by(User.name)))


def _distribution_out(a: AdminCtx, c: Campaign) -> DistributionOut:
    db = a.db
    pending = db.scalar(select(func.count()).select_from(Idea).where(
        Idea.campaign_id == c.id, Idea.stage == IdeaStage.recebida)) or 0
    distributed = db.scalar(select(func.count(func.distinct(Assignment.idea_id))).where(
        Assignment.campaign_id == c.id)) or 0
    committee = _committee(db, a.tenant.id)
    loads = {row[0]: (row[1], row[2]) for row in db.execute(
        select(Assignment.evaluator_id, func.count(), func.count(Assignment.verdict))
        .where(Assignment.campaign_id == c.id).group_by(Assignment.evaluator_id))}
    people = {u.id: u for u in committee}
    # Quem já recebeu ideias e saiu do comitê continua na lista, com a carga que tem.
    for user_id in loads.keys() - people.keys():
        people[user_id] = db.get(User, user_id)

    blocker = None
    if submission_state(c) != "encerrada":
        blocker = "A distribuição é feita depois do fim das inscrições."
    elif pending == 0:
        blocker = "Não há ideias recebidas aguardando distribuição."
    elif len(committee) < c.num_evaluators:
        blocker = (f"A campanha pede {c.num_evaluators} avaliadores por ideia, mas o comitê tem {len(committee)} "
                   "membro(s) ativo(s). Dê o perfil Membro de comitê a mais pessoas ou reduza o número nas regras.")
    return DistributionOut(
        submission_state=submission_state(c), pending=pending, distributed=distributed,
        num_evaluators=c.num_evaluators, committee=len(committee), blocker=blocker,
        evaluators=[EvaluatorLoad(id=u.id, name=u.name, sector=u.sector, assigned=loads.get(u.id, (0, 0))[0],
                                  evaluated=loads.get(u.id, (0, 0))[1])
                    for u in sorted(people.values(), key=lambda u: u.name.lower())],
    )


@router.get("/admin/campaigns/{campaign_id}/distribution", response_model=DistributionOut)
def distribution(campaign_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> DistributionOut:
    return _distribution_out(a, _get_campaign(a, campaign_id))


@router.post("/admin/campaigns/{campaign_id}/distribution", response_model=DistributionOut)
def distribute(campaign_id: uuid.UUID, a: AdminCtx = Depends(admin_ctx)) -> DistributionOut:
    """Distribui todas as ideias recebidas: cada uma vai para N avaliadores e passa para "Em análise"."""
    c = _get_campaign(a, campaign_id)
    a.db.execute(select(Campaign.id).where(Campaign.id == c.id).with_for_update())
    current = _distribution_out(a, c)
    if current.blocker:
        raise _unprocessable(current.blocker)

    db = a.db
    ideas = list(db.scalars(select(Idea).where(Idea.campaign_id == c.id, Idea.stage == IdeaStage.recebida)
                            .order_by(Idea.number)))
    # Ninguém avalia ideia de que é autor ou coautor.
    coauthor_users: dict[uuid.UUID, set[uuid.UUID]] = {}
    for idea_id, user_id in db.execute(
            select(IdeaCoauthor.idea_id, AuthorizedMember.user_id)
            .join(AuthorizedMember, AuthorizedMember.id == IdeaCoauthor.member_id)
            .where(IdeaCoauthor.idea_id.in_([i.id for i in ideas]), AuthorizedMember.user_id.isnot(None))):
        coauthor_users.setdefault(idea_id, set()).add(user_id)
    last = dict(db.execute(select(Assignment.evaluator_id, func.max(Assignment.created_at))
                           .where(Assignment.campaign_id == c.id).group_by(Assignment.evaluator_id)).all())
    loads = {e.id: e.assigned for e in current.evaluators}
    evaluators = [Evaluator(id=u.id, name=u.name, load=loads.get(u.id, 0), last_assigned=last.get(u.id))
                  for u in _committee(db, a.tenant.id)]
    try:
        plan = assign([(i.id, {i.author_id} | coauthor_users.get(i.id, set())) for i in ideas], evaluators,
                      c.num_evaluators)
    except ValueError:
        raise _unprocessable("Não há avaliadores suficientes que não sejam autores ou coautores de uma das ideias. "
                             "Inclua mais membros no comitê ou reduza o número de avaliadores por ideia.")

    for idea in ideas:
        for evaluator_id in plan[idea.id]:
            db.add(Assignment(tenant_id=a.tenant.id, campaign_id=c.id, idea_id=idea.id, evaluator_id=evaluator_id))
        idea.stage = IdeaStage.em_analise
    if c.current_phase == CampaignPhase.recepcao:
        c.current_phase = CampaignPhase.analise
    a.record("distribuicao_executada", entity="campaign", entity_id=c.id,
             details={"ideias": len(ideas), "avaliadores_por_ideia": c.num_evaluators,
                      "comite": len(evaluators)})
    db.commit()
    return _distribution_out(a, c)


# ---------- Kanban do avaliador ----------

class EvaluatorCtx:
    def __init__(self, user: User, ctx: RequestContext):
        self.user, self.db, self.tenant = user, ctx.db, require_active_tenant(ctx)


def evaluator_ctx(user: User = Depends(require_roles(*ANALYSIS_ROLES)),
                  ctx: RequestContext = Depends(get_context)) -> EvaluatorCtx:
    return EvaluatorCtx(user, ctx)


# Quem acompanha todas as avaliações no menu Análise, sem dar parecer.
OVERVIEW_ROLES = {Role.administrador, Role.consultor}


@router.get("/analysis", response_model=AnalysisBoardOut)
def analysis_board(campaign_id: uuid.UUID | None = None, evaluator_id: uuid.UUID | None = None,
                   e: EvaluatorCtx = Depends(evaluator_ctx)) -> AnalysisBoardOut:
    """Avaliador: só as ideias distribuídas a ele. Administrador e consultor: todas as atribuições da campanha
    (um cartão por ideia e avaliador). Nada aparece antes da distribuição."""
    overview = e.user.role in OVERVIEW_ROLES
    mine = Assignment.evaluator_id == e.user.id
    scope = select(Assignment.campaign_id).where(Assignment.tenant_id == e.tenant.id)
    campaigns = list(e.db.scalars(
        select(Campaign).where(Campaign.id.in_(scope if overview else scope.where(mine)))
        .order_by(Campaign.submission_start.desc())))
    if campaign_id is None and campaigns:
        campaign_id = campaigns[0].id
    c = next((x for x in campaigns if x.id == campaign_id), None)
    if campaign_id is not None and c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")

    cards: dict[Verdict | None, list[AnalysisCard]] = {v: [] for v, _, _ in COLUMNS}
    evaluators: list[BoardCampaign] = []
    if c is not None:
        query = (select(Assignment, Idea.number, Idea.title, CampaignLine.name, User.name)
                 .join(Idea, Idea.id == Assignment.idea_id).join(User, User.id == Assignment.evaluator_id)
                 .outerjoin(CampaignLine, CampaignLine.id == Idea.line_id)
                 .where(Assignment.campaign_id == c.id).order_by(Idea.number, User.name))
        if overview:
            evaluators = [BoardCampaign(id=uid, title=name) for uid, name in e.db.execute(
                select(User.id, User.name).where(User.id.in_(
                    select(Assignment.evaluator_id).where(Assignment.campaign_id == c.id))).order_by(User.name))]
            if evaluator_id is not None:
                query = query.where(Assignment.evaluator_id == evaluator_id)
        else:
            query = query.where(mine)
        for asg, number, title, line, evaluator in e.db.execute(query):
            cards[asg.verdict].append(AnalysisCard(
                assignment_id=asg.id, idea_id=asg.idea_id, evaluator_name=evaluator if overview else None,
                number=number, title=title, line_name=line, evaluated_at=asg.evaluated_at))
    return AnalysisBoardOut(
        overview=overview, evaluators=evaluators, evaluator_id=evaluator_id if overview else None,
        campaigns=[BoardCampaign(id=x.id, title=x.title) for x in campaigns], campaign_id=campaign_id,
        evaluation_state=evaluation_state(c) if c else None, analysis_start=c.analysis_start if c else None,
        analysis_end=c.analysis_end if c else None,
        columns=[AnalysisColumn(key=key, label=label, cards=cards[v]) for v, key, label in COLUMNS])


def _get_assignment(e: EvaluatorCtx, assignment_id: uuid.UUID) -> tuple[Assignment, Idea, Campaign]:
    asg = e.db.get(Assignment, assignment_id)
    if asg is None or asg.tenant_id != e.tenant.id or asg.evaluator_id != e.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ideia não encontrada na sua lista de análise.")
    return asg, e.db.get(Idea, asg.idea_id), e.db.get(Campaign, asg.campaign_id)


def _assignment_out(e: EvaluatorCtx, asg: Assignment, idea: Idea, c: Campaign) -> AssignmentOut:
    line = e.db.get(CampaignLine, idea.line_id) if idea.line_id else None
    state = evaluation_state(c)
    author, coauthors = None, None
    if not c.blind_review:
        author = e.db.get(User, idea.author_id).name
        coauthors = list(e.db.scalars(
            select(AuthorizedMember.name).join(IdeaCoauthor, IdeaCoauthor.member_id == AuthorizedMember.id)
            .where(IdeaCoauthor.idea_id == idea.id).order_by(AuthorizedMember.name)))
    return AssignmentOut(
        id=asg.id, campaign_title=c.title, number=idea.number, title=idea.title, line_name=line.name if line else None,
        summary=idea.summary, answers=answers_out(e.db, idea.id), author_name=author, coauthors=coauthors,
        verdict=asg.verdict, comment=asg.comment, evaluated_at=asg.evaluated_at, evaluation_state=state,
        analysis_end=c.analysis_end, can_evaluate=state == "aberta" and idea.stage == IdeaStage.em_analise)


@router.get("/analysis/{assignment_id}", response_model=AssignmentOut)
def get_assignment(assignment_id: uuid.UUID, e: EvaluatorCtx = Depends(evaluator_ctx)) -> AssignmentOut:
    return _assignment_out(e, *_get_assignment(e, assignment_id))


@router.put("/analysis/{assignment_id}", response_model=AssignmentOut)
def save_verdict(assignment_id: uuid.UUID, body: VerdictIn, e: EvaluatorCtx = Depends(evaluator_ctx)) -> AssignmentOut:
    """Registra, troca ou desfaz o parecer (verdict vazio = volta para "Para análise")."""
    asg, idea, c = _get_assignment(e, assignment_id)
    state = evaluation_state(c)
    if state != "aberta" or idea.stage != IdeaStage.em_analise:
        raise HTTPException(status.HTTP_409_CONFLICT, "Antes do início da análise ainda não é possível dar parecer."
                            if state == "antes" else "O período de análise terminou: o parecer não pode mais mudar.")
    comment = (body.comment or "").strip() or None
    if body.verdict == Verdict.talvez and comment is None:
        raise _unprocessable("No parecer \"Talvez\", escreva o comentário: o que falta detalhar na ideia.")
    previous = asg.verdict
    asg.verdict, asg.comment = body.verdict, comment
    asg.evaluated_at = utcnow() if body.verdict else None
    audit.record(e.db, "parecer_registrado" if body.verdict else "parecer_desfeito", actor_id=e.user.id,
                 tenant_id=e.tenant.id, entity="assignment", entity_id=asg.id,
                 details={"ideia": idea.number, "parecer": body.verdict.value if body.verdict else None,
                          "anterior": previous.value if previous else None})
    e.db.commit()
    return _assignment_out(e, asg, idea, c)


@router.get("/analysis/{assignment_id}/files/{field_id}")
def download_for_evaluator(assignment_id: uuid.UUID, field_id: uuid.UUID, e: EvaluatorCtx = Depends(evaluator_ctx)):
    asg, idea, _ = _get_assignment(e, assignment_id)
    f = e.db.get(CampaignField, field_id)
    answer = e.db.scalar(select(IdeaAnswer).where(IdeaAnswer.idea_id == idea.id, IdeaAnswer.field_id == field_id))
    if f is None or f.kind != FieldKind.anexo or answer is None or answer.file_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    return attachment_response(answer.file_path, answer.file_name)
