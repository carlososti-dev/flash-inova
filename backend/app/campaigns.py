"""Regras da campanha que não dependem da tela: período de inscrição, ordem das datas, vídeo e qual campanha
aparece na página inicial."""
import re
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Campaign, CampaignLine, CampaignPhase, utcnow

# Máximo de linhas de ideias (temáticas) ativas por campanha, conforme a especificação da página Início.
MAX_ACTIVE_LINES = 5

# Ordem cronológica das datas da campanha, com o nome que aparece nas mensagens.
DATE_ORDER = [
    ("submission_start", "início das inscrições"),
    ("submission_end", "fim das inscrições"),
    ("analysis_start", "início da análise"),
    ("analysis_end", "fim da análise"),
    ("classification_end", "fim da classificação"),
    ("defense_date", "defesa"),
    ("voting_start", "abertura da votação"),
    ("voting_end", "fechamento da votação"),
]
# Pares início/fim que não podem ser iguais.
STRICT_PAIRS = {("submission_start", "submission_end"), ("analysis_start", "analysis_end"),
                ("voting_start", "voting_end")}

PHASE_LABELS = {
    CampaignPhase.recepcao: "Recepção de ideias",
    CampaignPhase.analise: "Análise",
    CampaignPhase.classificacao: "Classificação",
    CampaignPhase.defesa: "Defesa",
    CampaignPhase.votacao: "Votação",
    CampaignPhase.encerrada: "Encerrada",
}


def submission_state(c: Campaign, now: datetime | None = None) -> str:
    """antes | aberta | encerrada, calculado pelas datas (não é gravado)."""
    now = now or utcnow()
    if now < c.submission_start:
        return "antes"
    if now <= c.submission_end:
        return "aberta"
    return "encerrada"


def date_order_problem(values: dict[str, datetime | None]) -> str | None:
    """Confere se as datas preenchidas estão em ordem cronológica. Datas vazias são ignoradas."""
    previous: tuple[str, str, datetime] | None = None
    for field, label in DATE_ORDER:
        value = values.get(field)
        if value is None:
            continue
        if previous is not None:
            prev_field, prev_label, prev_value = previous
            if value < prev_value or (value == prev_value and (prev_field, field) in STRICT_PAIRS):
                return f"A data de {label} deve ser depois da data de {prev_label}."
        previous = (field, label, value)
    return None


def phases(c: Campaign) -> list[dict]:
    return [
        {"key": "recepcao", "label": PHASE_LABELS[CampaignPhase.recepcao], "start": c.submission_start,
         "end": c.submission_end},
        {"key": "analise", "label": PHASE_LABELS[CampaignPhase.analise], "start": c.analysis_start,
         "end": c.analysis_end},
        {"key": "classificacao", "label": PHASE_LABELS[CampaignPhase.classificacao], "start": None,
         "end": c.classification_end},
        {"key": "defesa", "label": PHASE_LABELS[CampaignPhase.defesa], "start": c.defense_date, "end": None},
        {"key": "votacao", "label": "Votação (Dia da Qualidade)", "start": c.voting_start, "end": c.voting_end},
    ]


_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com",
                  "youtube-nocookie.com"}


def youtube_id(url: str) -> str | None:
    """Identificador do vídeo a partir dos formatos comuns de link do YouTube; None se não for do YouTube."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
        return None
    path = [p for p in parsed.path.split("/") if p]
    if parsed.hostname.lower() == "youtu.be":
        candidate = path[0] if path else None
    elif path[:1] == ["watch"]:
        candidate = parse_qs(parsed.query).get("v", [None])[0]
    elif len(path) >= 2 and path[0] in {"embed", "shorts", "live", "v"}:
        candidate = path[1]
    else:
        candidate = None
    return candidate if candidate and _YOUTUBE_ID.match(candidate) else None


def youtube_embed(url: str | None) -> str | None:
    vid = youtube_id(url) if url else None
    # youtube-nocookie: o vídeo não grava cookies de rastreamento até a pessoa dar o play.
    return f"https://www.youtube-nocookie.com/embed/{vid}" if vid else None


def featured_campaign(db: Session, tenant_id: uuid.UUID) -> Campaign | None:
    """Campanha da página inicial: a publicada mais recente que ainda não foi encerrada; se todas estiverem
    encerradas, a mais recente delas."""
    return db.scalar(
        select(Campaign)
        .where(Campaign.tenant_id == tenant_id, Campaign.is_published.is_(True))
        .order_by((Campaign.current_phase == CampaignPhase.encerrada).asc(), Campaign.submission_start.desc())
        .limit(1)
    )


def lines_of(db: Session, campaign_id: uuid.UUID, only_active: bool = False) -> list[CampaignLine]:
    query = select(CampaignLine).where(CampaignLine.campaign_id == campaign_id)
    if only_active:
        query = query.where(CampaignLine.is_active.is_(True))
    return list(db.scalars(query.order_by(CampaignLine.position, CampaignLine.name)))
