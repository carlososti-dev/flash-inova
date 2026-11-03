"""Votação: todos do hospital votam em uma ideia da Shortlist, pelo QR code no evento ou pelo link na web.

Identificação: quem tem conta usa o login; quem não tem digita a matrícula e recebe um código de 6 dígitos por
e-mail, que dá um acesso só para votar. Um voto por pessoa, sem troca. A tabela de quem votou (voters) não tem
ligação com a de votos (ballots).

O administrador acompanha a contagem ao vivo e encerra a votação: as mais votadas são premiadas (1º, 2º, 3º...) e a
campanha passa para Premiação (fase "encerrada").
"""
import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..deps import RequestContext, get_context, get_current_user, require_active_tenant, require_roles
from ..email import EmailMessage, get_email_sender
from ..links import frontend_link
from ..models import (
    AuthorizedMember, Ballot, Campaign, CampaignLine, CampaignPhase, FieldKind, Idea, IdeaAnswer, IdeaCoauthor,
    IdeaStage, Role, Tenant, User, UserStatus, VoteCode, Voter, utcnow,
)
from ..schemas import (
    BoardCampaign, Message, VoteCodeIn, VoteCodeSent, VoteIdea, VoteIn, VoteOut, VoterOut, VoteVerifyIn, VotingIdea,
    VotingOut,
)
from ..voting import Standing, email_hint, hash_code, new_code, podium, same_code, voting_state
from .admin import AdminCtx, admin_ctx
from .campaigns import _get_campaign
from .classification import _classified, _pick_campaign, _published
from .ideas import FOLLOWERS, answers_out, attachment_response

router = APIRouter(prefix="/api", tags=["votação"])

BAD_CODE = "Código inválido ou vencido. Peça um novo código."


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


# ---------- Quem está votando ----------

@dataclass
class VoterId:
    name: str
    method: str  # login | codigo
    member_id: uuid.UUID | None
    user_id: uuid.UUID | None


def _vote_token(tenant: Tenant, campaign: Campaign, member: AuthorizedMember) -> str:
    s = get_settings()
    payload = {"purpose": "voto", "mid": str(member.id), "tid": str(tenant.id), "cid": str(campaign.id),
               "exp": utcnow() + timedelta(hours=s.vote_session_hours)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def _member_voter(db, member: AuthorizedMember | None) -> VoterId | None:
    if member is None or not member.is_active:
        return None
    if member.user_id is not None:
        user = db.get(User, member.user_id)
        if user is None or user.status != UserStatus.ativo:
            return None
    return VoterId(name=member.name, method="codigo", member_id=member.id, user_id=member.user_id)


def _current_voter(request: Request, ctx: RequestContext, c: Campaign) -> VoterId | None:
    """Primeiro o acesso por código (pedido de propósito para votar, mesmo num aparelho com outra conta aberta);
    depois o login."""
    s = get_settings()
    token = request.cookies.get(s.vote_cookie)
    if token:
        try:
            claims = jwt.decode(token, s.secret_key, algorithms=["HS256"])
        except jwt.PyJWTError:
            claims = {}
        if (claims.get("purpose") == "voto" and claims.get("tid") == str(ctx.tenant.id)
                and claims.get("cid") == str(c.id)):
            return _member_voter(ctx.db, ctx.db.get(AuthorizedMember, uuid.UUID(claims["mid"])))
    try:
        user = get_current_user(request, ctx)
    except HTTPException:
        return None
    if user.role == Role.consultor:
        return None  # o Consultor não é do hospital
    member_id = ctx.db.scalar(select(AuthorizedMember.id).where(AuthorizedMember.user_id == user.id))
    return VoterId(name=user.name, method="login", member_id=member_id, user_id=user.id)


def _has_voted(db, c: Campaign, v: VoterId) -> bool:
    keys = [Voter.member_id == v.member_id] if v.member_id else []
    keys += [Voter.user_id == v.user_id] if v.user_id else []
    return db.scalar(select(Voter.id).where(Voter.campaign_id == c.id, or_(*keys)).limit(1)) is not None


# ---------- Tela de votação (pública: abre pelo QR code, sem login) ----------

def _vote_campaign(db, tenant: Tenant, campaign_id: uuid.UUID | None) -> Campaign | None:
    if campaign_id is not None:
        c = db.get(Campaign, campaign_id)
        if c is None or c.tenant_id != tenant.id or not c.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
        return c
    # Sem campanha no link: a que está em votação; senão, a mais recente publicada.
    published = select(Campaign).where(Campaign.tenant_id == tenant.id, Campaign.is_published.is_(True))
    return (db.scalar(published.where(Campaign.current_phase == CampaignPhase.votacao)
                      .order_by(Campaign.submission_start.desc()).limit(1))
            or db.scalar(published.order_by(Campaign.submission_start.desc()).limit(1)))


def _shortlist(db, c: Campaign) -> list[VoteIdea]:
    rows = db.execute(
        select(Idea, User.name, CampaignLine.name).join(User, User.id == Idea.author_id)
        .outerjoin(CampaignLine, CampaignLine.id == Idea.line_id)
        .where(Idea.campaign_id == c.id, Idea.stage == IdeaStage.shortlist).order_by(Idea.number)).all()
    coauthors: dict[uuid.UUID, list[str]] = {}
    for idea_id, name in db.execute(
            select(IdeaCoauthor.idea_id, AuthorizedMember.name)
            .join(AuthorizedMember, AuthorizedMember.id == IdeaCoauthor.member_id)
            .where(IdeaCoauthor.idea_id.in_([i.id for i, _, _ in rows])).order_by(AuthorizedMember.name)):
        coauthors.setdefault(idea_id, []).append(name)
    return [VoteIdea(id=i.id, number=i.number, title=i.title, line_name=line, author_name=author,
                     coauthors=coauthors.get(i.id, []), summary=i.summary,
                     answers=[a for a in answers_out(db, i.id)
                              if (a.file_name if a.kind == FieldKind.anexo else a.value is not None)])
            for i, author, line in rows]


def _vote_out(request: Request, ctx: RequestContext, c: Campaign | None, voter: VoterId | None = None) -> VoteOut:
    if c is None:
        return VoteOut(campaign_id=None, campaign_title=None, state="antes", voting_start=None, voting_end=None,
                       ideas=[], voter=None)
    state = voting_state(c)
    voter = voter or _current_voter(request, ctx, c)
    return VoteOut(
        campaign_id=c.id, campaign_title=c.title, state=state, voting_start=c.voting_start, voting_end=c.voting_end,
        ideas=_shortlist(ctx.db, c) if state == "aberta" else [],
        voter=VoterOut(name=voter.name, method=voter.method, voted=_has_voted(ctx.db, c, voter)) if voter else None)


def _open_campaign(ctx: RequestContext, campaign_id: uuid.UUID) -> Campaign:
    c = _vote_campaign(ctx.db, require_active_tenant(ctx), campaign_id)
    if voting_state(c) != "aberta":
        raise HTTPException(status.HTTP_409_CONFLICT, "A votação não está aberta.")
    return c


def _find_member(ctx: RequestContext, matricula: str) -> AuthorizedMember | None:
    return ctx.db.scalar(select(AuthorizedMember).where(
        AuthorizedMember.tenant_id == ctx.tenant.id,
        func.lower(AuthorizedMember.matricula) == matricula.strip().lower()))


@router.get("/vote", response_model=VoteOut)
def vote_page(request: Request, campaign_id: uuid.UUID | None = None,
              ctx: RequestContext = Depends(get_context)) -> VoteOut:
    tenant = require_active_tenant(ctx)
    return _vote_out(request, ctx, _vote_campaign(ctx.db, tenant, campaign_id))


@router.post("/vote/code", response_model=VoteCodeSent)
def send_code(body: VoteCodeIn, ctx: RequestContext = Depends(get_context)) -> VoteCodeSent:
    """Manda o código de 6 dígitos para o e-mail da pessoa na lista de autorizados."""
    s = get_settings()
    c = _open_campaign(ctx, body.campaign_id)
    member = _find_member(ctx, body.matricula)
    if member is None or not member.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Matrícula não encontrada. Confira o número ou procure a organização da votação.")
    if _member_voter(ctx.db, member) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu acesso está inativo. Procure o administrador.")
    now = utcnow()
    last = ctx.db.scalar(select(VoteCode).where(VoteCode.campaign_id == c.id, VoteCode.member_id == member.id)
                         .order_by(VoteCode.created_at.desc()).limit(1))
    if last is not None and last.used_at is None and now - last.created_at < timedelta(seconds=s.vote_code_resend_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Já enviamos um código há pouco. Confira seu e-mail ou aguarde um minuto para pedir outro.")
    # Um código novo invalida os anteriores.
    ctx.db.execute(update(VoteCode).where(VoteCode.campaign_id == c.id, VoteCode.member_id == member.id,
                                          VoteCode.used_at.is_(None)).values(used_at=now))
    code = new_code()
    ctx.db.add(VoteCode(tenant_id=ctx.tenant.id, campaign_id=c.id, member_id=member.id,
                        code_hash=hash_code(member.id, code), expires_at=now + timedelta(minutes=s.vote_code_minutes)))
    ctx.db.commit()
    get_email_sender().send(EmailMessage(
        to=member.email, subject=f"Seu código para votar: {code}",
        body=(f"Olá, {member.name}.\n\nSeu código para votar em \"{c.title}\" é:\n\n{code}\n\n"
              f"Ele vale por {s.vote_code_minutes} minutos. Se você não pediu, ignore este e-mail.")))
    return VoteCodeSent(message="Enviamos um código de 6 dígitos para o seu e-mail.", email_hint=email_hint(member.email))


@router.post("/vote/verify", response_model=VoteOut)
def verify_code(body: VoteVerifyIn, request: Request, response: Response,
                ctx: RequestContext = Depends(get_context)) -> VoteOut:
    s = get_settings()
    c = _open_campaign(ctx, body.campaign_id)
    member = _find_member(ctx, body.matricula)
    row = None if member is None else ctx.db.scalar(
        select(VoteCode).where(VoteCode.campaign_id == c.id, VoteCode.member_id == member.id,
                               VoteCode.used_at.is_(None)).order_by(VoteCode.created_at.desc()).limit(1).with_for_update())
    if row is None or row.expires_at <= utcnow() or row.attempts >= s.vote_code_attempts:
        raise _unprocessable(BAD_CODE)
    if not same_code(member.id, body.code, row.code_hash):
        row.attempts += 1
        ctx.db.commit()
        left = s.vote_code_attempts - row.attempts
        raise _unprocessable("Código incorreto." + (f" Restam {left} tentativa(s)." if left else " Peça um novo código."))
    voter = _member_voter(ctx.db, member)
    if voter is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu acesso está inativo. Procure o administrador.")
    row.used_at = utcnow()
    ctx.db.commit()
    response.set_cookie(s.vote_cookie, _vote_token(ctx.tenant, c, member), max_age=s.vote_session_hours * 3600,
                        httponly=True, secure=s.cookie_secure, samesite="lax", path="/")
    return _vote_out(request, ctx, c, voter)


@router.post("/vote/exit", response_model=Message)
def exit_vote(response: Response) -> Message:
    """Encerra o acesso por código (útil num aparelho compartilhado). Não mexe no login."""
    response.delete_cookie(get_settings().vote_cookie, path="/")
    return Message(message="Pronto. O próximo pode votar.")


@router.post("/vote", response_model=VoteOut)
def cast_vote(body: VoteIn, request: Request, ctx: RequestContext = Depends(get_context)) -> VoteOut:
    c = _vote_campaign(ctx.db, require_active_tenant(ctx), body.campaign_id)
    voter = _current_voter(request, ctx, c)
    if voter is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifique-se para votar.")
    # Trava compartilhada: vários votos ao mesmo tempo, mas nenhum durante a apuração.
    ctx.db.execute(select(Campaign.id).where(Campaign.id == c.id).with_for_update(read=True))
    ctx.db.refresh(c)
    if voting_state(c) != "aberta":
        raise HTTPException(status.HTTP_409_CONFLICT, "A votação não está aberta.")
    idea = ctx.db.get(Idea, body.idea_id)
    if idea is None or idea.campaign_id != c.id or idea.stage != IdeaStage.shortlist:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ideia não encontrada na votação.")
    if _has_voted(ctx.db, c, voter):
        raise HTTPException(status.HTTP_409_CONFLICT, "Você já votou nesta campanha.")
    ctx.db.add(Voter(tenant_id=ctx.tenant.id, campaign_id=c.id, member_id=voter.member_id, user_id=voter.user_id,
                     method=voter.method))
    ctx.db.add(Ballot(tenant_id=ctx.tenant.id, campaign_id=c.id, idea_id=idea.id))
    try:
        ctx.db.commit()
    except IntegrityError:  # o mesmo voto chegou duas vezes ao mesmo tempo
        ctx.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Você já votou nesta campanha.") from None
    return _vote_out(request, ctx, c, voter)


@router.get("/vote/ideas/{idea_id}/files/{field_id}")
def vote_attachment(idea_id: uuid.UUID, field_id: uuid.UUID, request: Request,
                    ctx: RequestContext = Depends(get_context)):
    """Anexo de uma ideia da votação, para quem já se identificou, enquanto a votação está aberta."""
    tenant = require_active_tenant(ctx)
    idea = ctx.db.get(Idea, idea_id)
    if idea is None or idea.tenant_id != tenant.id or idea.stage != IdeaStage.shortlist:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    c = ctx.db.get(Campaign, idea.campaign_id)
    if voting_state(c) != "aberta":
        raise HTTPException(status.HTTP_409_CONFLICT, "A votação não está aberta.")
    if _current_voter(request, ctx, c) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifique-se para ver os anexos.")
    answer = ctx.db.scalar(select(IdeaAnswer).where(IdeaAnswer.idea_id == idea.id, IdeaAnswer.field_id == field_id))
    if answer is None or answer.file_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    return attachment_response(answer.file_path, answer.file_name)


# ---------- Acompanhamento e apuração (menu Classificação → Votação) ----------

def _standings(db, c: Campaign) -> tuple[list[VotingIdea], int]:
    """Contagem atual com o desempate. Devolve as ideias na ordem e o total de votos."""
    counts = dict(db.execute(select(Ballot.idea_id, func.count()).where(Ballot.campaign_id == c.id)
                             .group_by(Ballot.idea_id)).all())
    ranking = {i.id: i for i in _classified(db, c, managers=False)}
    rows = db.scalars(select(Idea).where(Idea.campaign_id == c.id,
                                         Idea.stage.in_([IdeaStage.shortlist, IdeaStage.premiada])))
    ideas = {i.id: i for i in rows if i.id in ranking}
    ordered, winners = podium([Standing(id=i.id, votes=counts.get(i.id, 0), score=i.classification_score,
                                        rank=ranking[i.id].rank, number=i.number) for i in ideas.values()],
                              c.num_winners)
    ties = {}
    for s in ordered:
        ties[s.votes] = ties.get(s.votes, 0) + 1
    out = [VotingIdea(id=s.id, number=s.number, title=ideas[s.id].title, line_name=ranking[s.id].line_name,
                      author_name=ranking[s.id].author_name, score=s.score, votes=s.votes, position=k,
                      tied=s.votes > 0 and ties[s.votes] > 1,
                      winner=ideas[s.id].award_position is not None if c.voting_closed_at else s.id in winners,
                      award_position=ideas[s.id].award_position)
           for k, s in enumerate(ordered, start=1)]
    return out, sum(counts.values())


def _close_blocker(c: Campaign, total: int) -> str | None:
    if c.current_phase == CampaignPhase.encerrada or c.voting_closed_at is not None:
        return "A votação desta campanha já foi apurada."
    if c.current_phase != CampaignPhase.votacao:
        return "A campanha ainda não está na fase de Votação: feche a Defesa antes."
    if c.voting_start is None or c.voting_end is None:
        return "Defina a abertura e o fechamento da votação."
    if voting_state(c) == "antes":
        return "A votação ainda não começou."
    if total == 0:
        return "Nenhum voto registrado ainda."
    return None


def _voting_out(db, user: User, tenant: Tenant, campaigns: list[Campaign], c: Campaign | None) -> VotingOut:
    can_manage = user.role == Role.administrador
    if c is None:
        return VotingOut(campaigns=[], campaign_id=None, current_phase=None, state=None, voting_start=None,
                         voting_end=None, voting_closed_at=None, num_winners=3, vote_url=None, qr_svg=None, voters=0,
                         eligible=0, can_manage=can_manage, close_blocker=None, ideas=[])
    ideas, total = _standings(db, c)
    url = frontend_link(tenant, "/votacao", campanha=str(c.id))
    # Quem pode votar: a lista de autorizados ativa mais quem tem conta ativa fora dela (ex.: o administrador).
    members = db.scalar(select(func.count()).select_from(AuthorizedMember).where(
        AuthorizedMember.tenant_id == tenant.id, AuthorizedMember.is_active.is_(True))) or 0
    linked = select(AuthorizedMember.user_id).where(AuthorizedMember.tenant_id == tenant.id,
                                                    AuthorizedMember.user_id.isnot(None))
    accounts = db.scalar(select(func.count()).select_from(User).where(
        User.tenant_id == tenant.id, User.status == UserStatus.ativo, User.id.not_in(linked))) or 0
    eligible = members + accounts
    voters = db.scalar(select(func.count()).select_from(Voter).where(Voter.campaign_id == c.id)) or 0
    return VotingOut(
        campaigns=[BoardCampaign(id=x.id, title=x.title) for x in campaigns], campaign_id=c.id,
        current_phase=c.current_phase, state=voting_state(c), voting_start=c.voting_start, voting_end=c.voting_end,
        voting_closed_at=c.voting_closed_at, num_winners=c.num_winners, vote_url=url,
        qr_svg=segno.make(url, error="m").svg_data_uri(scale=10, border=2), voters=voters, eligible=eligible,
        can_manage=can_manage, close_blocker=_close_blocker(c, total), ideas=ideas)


@router.get("/voting", response_model=VotingOut)
def voting(campaign_id: uuid.UUID | None = None, user: User = Depends(require_roles(*FOLLOWERS)),
           ctx: RequestContext = Depends(get_context)) -> VotingOut:
    tenant = require_active_tenant(ctx)
    return _voting_out(ctx.db, user, tenant, *_pick_campaign(ctx.db, tenant.id, campaign_id))


def _require_administrator(a: AdminCtx = Depends(admin_ctx)) -> AdminCtx:
    if a.actor.role != Role.administrador:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A votação é encerrada pelo administrador do hospital.")
    return a


@router.post("/admin/campaigns/{campaign_id}/voting/close", response_model=VotingOut)
def close_voting(campaign_id: uuid.UUID, a: AdminCtx = Depends(_require_administrator)) -> VotingOut:
    """Encerra a votação (no fechamento ou antes dele) e apura: as mais votadas são premiadas."""
    c = _get_campaign(a, campaign_id)
    a.db.execute(select(Campaign.id).where(Campaign.id == c.id).with_for_update())
    a.db.refresh(c)
    ideas, total = _standings(a.db, c)
    if (blocker := _close_blocker(c, total)) is not None:
        raise _unprocessable(blocker)
    now = utcnow()
    early = c.voting_end is not None and now < c.voting_end
    podium_log = []
    place = 0
    for item in ideas:
        idea = a.db.get(Idea, item.id)
        idea.vote_count = item.votes
        if item.winner:
            place += 1
            idea.stage, idea.award_position = IdeaStage.premiada, place
            podium_log.append({"lugar": place, "ideia": idea.number, "votos": item.votes})
    c.voting_closed_at, c.current_phase = now, CampaignPhase.encerrada
    voters = a.db.scalar(select(func.count()).select_from(Voter).where(Voter.campaign_id == c.id)) or 0
    a.record("votacao_apurada", entity="campaign", entity_id=c.id,
             details={"votos": total, "votantes": voters, "premiadas": podium_log, "antes_do_fechamento": early,
                      "contagem": {str(i.number): i.votes for i in ideas}})
    a.db.commit()
    return _voting_out(a.db, a.actor, a.tenant, _published(a.db, a.tenant.id), c)
