"""Regras das ideias que não dependem da tela: etapas, colunas do kanban, quem edita e validação das respostas."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .campaigns import submission_state
from .models import (
    Campaign, CampaignField, DefenseReason, FieldKind, Idea, IdeaStage, RegulationVersion, utcnow,
)

STAGE_LABELS = {
    IdeaStage.rascunho: "Rascunho",
    IdeaStage.recebida: "Recebida",
    IdeaStage.em_analise: "Em análise",
    IdeaStage.empate: "Empate",
    IdeaStage.classificada: "Classificada",
    IdeaStage.talvez: "Talvez",
    IdeaStage.nao_classificada: "Não classificada",
    IdeaStage.em_defesa: "Em defesa",
    IdeaStage.shortlist: "Shortlist",
    IdeaStage.desclassificada: "Desclassificada",
    IdeaStage.premiada: "Premiada",
}
DEFENSE_REASON_LABELS = {
    DefenseReason.viabilidade_tecnica: "Viabilidade técnica",
    DefenseReason.viabilidade_financeira: "Viabilidade financeira",
    DefenseReason.projeto_em_andamento: "Existe um projeto igual em andamento",
    DefenseReason.outro: "Outro",
}

# O autor não vê o empate (é uma decisão interna, o Voto de Minerva): para ele a ideia segue em classificação.
AUTHOR_STAGE_LABELS = STAGE_LABELS | {IdeaStage.empate: "Em classificação"}

# Colunas do kanban (menu Classificação). Os cartões mudam de coluna só pelas ações do processo, nunca arrastados.
BOARD_COLUMNS = [
    ("recebida", "Recebidas"), ("em_analise", "Em análise"), ("empate", "Empate"),
    ("classificada", "Classificadas"), ("talvez", "Talvez"), ("nao_classificada", "Não classificadas"),
    ("em_defesa", "Em defesa"), ("shortlist", "Shortlist"), ("desclassificada", "Desclassificadas"),
    ("premiada", "Premiadas"),
]

EDITABLE_STAGES = {IdeaStage.rascunho, IdeaStage.recebida}
MAX_TEXT = {FieldKind.texto_curto: 300, FieldKind.texto_longo: 5000}
MAX_OPTIONS = 30


def can_edit(idea: Idea, campaign: Campaign) -> bool:
    """O autor edita a ideia, enviada ou não, até o fim das inscrições."""
    return campaign.is_published and idea.stage in EDITABLE_STAGES and utcnow() <= campaign.submission_end


def can_submit(campaign: Campaign) -> bool:
    return campaign.is_published and submission_state(campaign) == "aberta"


def clean_options(options: list[str] | None) -> list[str]:
    """Opções de um campo de lista: sem vazias nem repetidas, ao menos duas."""
    cleaned: list[str] = []
    for option in options or []:
        option = option.strip()
        if not option:
            continue
        if len(option) > 120:
            raise ValueError("Cada opção da lista deve ter no máximo 120 caracteres.")
        if option.lower() in {o.lower() for o in cleaned}:
            raise ValueError(f"A opção \"{option}\" está repetida.")
        cleaned.append(option)
    if len(cleaned) < 2:
        raise ValueError("Uma lista de opções precisa de ao menos duas opções.")
    if len(cleaned) > MAX_OPTIONS:
        raise ValueError(f"A lista pode ter no máximo {MAX_OPTIONS} opções.")
    return cleaned


def clean_answer(field: CampaignField, raw: object) -> object:
    """Resposta normalizada (None = em branco). Levanta ValueError com a mensagem para o autor."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if field.kind in MAX_TEXT:
        if not isinstance(raw, str):
            raise ValueError(f"Responda \"{field.label}\" com um texto.")
        text = raw.strip()
        if len(text) > MAX_TEXT[field.kind]:
            raise ValueError(f"\"{field.label}\" deve ter no máximo {MAX_TEXT[field.kind]} caracteres.")
        return text
    if field.kind == FieldKind.lista:
        if not isinstance(raw, str) or raw.strip() not in (field.options or []):
            raise ValueError(f"Escolha uma das opções de \"{field.label}\".")
        return raw.strip()
    if field.kind == FieldKind.sim_nao:
        if not isinstance(raw, bool):
            raise ValueError(f"Responda \"{field.label}\" com sim ou não.")
        return raw
    raise ValueError(f"Envie o arquivo de \"{field.label}\" pelo botão de anexo.")


def answered(field: CampaignField, value: object, file_path: str | None) -> bool:
    return file_path is not None if field.kind == FieldKind.anexo else value is not None


def current_regulation(db: Session, campaign_id: uuid.UUID) -> RegulationVersion | None:
    return db.scalar(select(RegulationVersion).where(RegulationVersion.campaign_id == campaign_id)
                     .order_by(RegulationVersion.version.desc()).limit(1))


def next_number(db: Session, campaign_id: uuid.UUID) -> int:
    """Próximo número da campanha. Quem chama já travou a linha da campanha (SELECT ... FOR UPDATE)."""
    return (db.scalar(select(func.max(Idea.number)).where(Idea.campaign_id == campaign_id)) or 0) + 1
