"""Regras da Classificação: apuração dos pareceres como na prova de conceito (lib/classifier.ts).

A favor = Classificar + Talvez; contra = Não classificar.
- A favor > contra → Classificada (C > T) ou Talvez (T ≥ C).
- Contra > a favor → Não classificada.
- A favor = contra → Empate: vai para o Voto de Minerva do administrador.

O Voto de Minerva entra na conta como um parecer a mais, o que desfaz o empate e dá a nota da ideia.
"""
import math
from collections.abc import Iterable
from dataclasses import dataclass

from .models import IdeaStage, Verdict

# Nota fixa quando todos os pareceres são Classificar, com 1, 2 ou 3 Talvez.
MAYBE_SCORES = {1: 70, 2: 50, 3: 30}
ONLY_MAYBE_SCORE = 20


@dataclass(frozen=True)
class Tally:
    classify: int
    maybe: int
    reject: int
    outcome: IdeaStage  # classificada | talvez | nao_classificada | empate
    score: int  # nota de ranking, 0 a 100
    weighted: int  # C × peso + T × peso, usado como desempate no ranking


def _round5(value: float) -> int:
    # Meio para cima, como o Math.round da prova de conceito (o round do Python arredonda 4,5 para 4).
    return 5 * math.floor(value / 5 + 0.5)


def score(c: int, t: int, nc: int, quorum: int) -> int:
    """Nota de ranking de 0 a 100 (tabela da prova de conceito)."""
    total = c + t + nc
    if total == 0 or nc >= c + t:
        return 0
    if nc == 0 and t == 0:
        return 100 if c >= quorum else math.floor(c / quorum * 100 + 0.5)
    if nc == 0 and c > 0 and t in MAYBE_SCORES:
        return MAYBE_SCORES[t]
    if nc == 0 and c == 0:
        return ONLY_MAYBE_SCORE
    raw = (100 * c - 30 * t - 80 * nc) / max(total, quorum)
    return max(0, min(100, _round5(raw)))


def tally(verdicts: Iterable[Verdict | None], quorum: int, weight_classify: int, weight_maybe: int,
          minerva: Verdict | None = None) -> Tally:
    """Apura os pareceres de uma ideia. Pareceres em branco não contam."""
    given = [v for v in verdicts if v is not None]
    if minerva is not None:
        given.append(minerva)
    c, t, nc = (given.count(v) for v in (Verdict.classificar, Verdict.talvez, Verdict.nao_classificar))
    favor = c + t
    if favor > nc:
        outcome = IdeaStage.classificada if c > t else IdeaStage.talvez
    elif nc > favor:
        outcome = IdeaStage.nao_classificada
    else:
        outcome = IdeaStage.empate
    return Tally(c, t, nc, outcome, score(c, t, nc, quorum), c * weight_classify + t * weight_maybe)
