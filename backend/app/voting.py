"""Regras da Votação que não dependem da tela: estado do período, código por e-mail e pódio.

- A votação vale com a campanha na fase Votação, entre a abertura e o fechamento definidos pelo administrador.
- Um voto por pessoa, sem troca. Quem votou fica registrado, mas não em quem votou.
- Pódio: mais votos; no empate, a maior nota da Classificação; persistindo, a melhor posição no ranking.
  Só ideias com ao menos um voto são premiadas.
"""
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from .config import get_settings
from .models import Campaign, CampaignPhase, utcnow


def voting_state(c: Campaign, now: datetime | None = None) -> str:
    """antes | aberta | encerrada. Sem as duas datas, a votação não abre."""
    now = now or utcnow()
    if c.current_phase == CampaignPhase.encerrada or c.voting_closed_at is not None:
        return "encerrada"
    if c.current_phase != CampaignPhase.votacao or c.voting_start is None or c.voting_end is None:
        return "antes"
    if now < c.voting_start:
        return "antes"
    return "aberta" if now <= c.voting_end else "encerrada"


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hash_code(member_id: uuid.UUID, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{member_id}:{code.strip()}".encode(), hashlib.sha256).hexdigest()


def same_code(member_id: uuid.UUID, code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_code(member_id, code), code_hash)


def email_hint(email: str) -> str:
    """ma•••@hospital.org.br: o bastante para a pessoa reconhecer o e-mail, sem mostrá-lo inteiro."""
    local, _, domain = email.partition("@")
    return f"{local[:2]}•••@{domain}"


@dataclass
class Standing:
    id: uuid.UUID
    votes: int
    score: int | None  # nota da Classificação
    rank: int | None  # posição no ranking da Classificação
    number: int | None


def podium(items: list[Standing], num_winners: int) -> tuple[list[Standing], set[uuid.UUID]]:
    """Ordena pela contagem com o desempate e devolve (ordem, premiadas)."""
    ordered = sorted(items, key=lambda i: (-i.votes, -(i.score or 0), i.rank or 10**6, i.number or 0))
    winners = {i.id for i in ordered[:num_winners] if i.votes > 0}
    return ordered, winners
