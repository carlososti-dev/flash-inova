"""Regras da Análise: distribuição duplo-cego por menor carga (como na prova de conceito) e período de avaliação."""
import uuid
from dataclasses import dataclass
from datetime import datetime

from .models import Campaign, utcnow


@dataclass
class Evaluator:
    id: uuid.UUID
    name: str
    load: int  # ideias já atribuídas na campanha
    last_assigned: datetime | None


def assign(ideas: list[tuple[uuid.UUID, set[uuid.UUID]]], evaluators: list[Evaluator],
           per_idea: int) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Guloso de menor carga. Para cada ideia, em ordem: escolhe os `per_idea` avaliadores com menor carga
    (empate: quem recebeu há mais tempo, nunca antes de quem nunca recebeu; depois o nome), sem pôr ninguém para
    avaliar ideia de que é autor ou coautor. A carga é atualizada antes da próxima ideia.

    `ideas` traz, para cada ideia, quem não pode avaliá-la. Levanta ValueError se faltar avaliador.
    """
    # Ordem de "recebeu por último": 0 = nunca recebeu; depois, do mais antigo ao mais recente.
    ordered = sorted((e for e in evaluators if e.last_assigned is not None), key=lambda e: e.last_assigned)
    recency = {e.id: i for i, e in enumerate(ordered, start=1)}
    loads = {e.id: e.load for e in evaluators}
    counter = len(ordered)
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    for idea_id, blocked in ideas:
        eligible = [e for e in evaluators if e.id not in blocked]
        if len(eligible) < per_idea:
            raise ValueError(per_idea)
        eligible.sort(key=lambda e: (loads[e.id], recency.get(e.id, 0), e.name.lower(), str(e.id)))
        chosen = eligible[:per_idea]
        for e in chosen:
            loads[e.id] += 1
            counter += 1
            recency[e.id] = counter
        result[idea_id] = [e.id for e in chosen]
    return result


def evaluation_state(c: Campaign, now: datetime | None = None) -> str:
    """antes | aberta | encerrada, pelas datas da análise. Sem data, aquele lado do período fica livre."""
    now = now or utcnow()
    if c.analysis_start is not None and now < c.analysis_start:
        return "antes"
    if c.analysis_end is not None and now > c.analysis_end:
        return "encerrada"
    return "aberta"
