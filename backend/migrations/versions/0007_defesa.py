"""Fatia 7: Defesa. Classificadas entram na Defesa; a banca dá o parecer de viabilidade; as viáveis formam a Shortlist.

A etapa "selecionada" (que nenhuma ideia chegou a usar) vira "desclassificada", e entra "em_defesa".

Revision ID: 0007
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TYPE idea_stage RENAME VALUE 'selecionada' TO 'desclassificada';
    ALTER TYPE idea_stage ADD VALUE 'em_defesa' BEFORE 'shortlist';

    ALTER TABLE campaigns ADD COLUMN defense_use_cutoff boolean NOT NULL DEFAULT false;

    ALTER TABLE ideas
        ADD COLUMN defense_reasons jsonb,
        ADD COLUMN defense_comment text,
        ADD COLUMN defense_by uuid REFERENCES users(id),
        ADD COLUMN defense_at timestamptz;
    """)


def downgrade() -> None:
    # O PostgreSQL não remove valores de um tipo enum: "em_defesa" fica no tipo, sem uso.
    op.execute("""
    UPDATE ideas SET stage = 'classificada' WHERE stage IN ('em_defesa', 'shortlist', 'desclassificada');
    ALTER TABLE ideas DROP COLUMN defense_at, DROP COLUMN defense_by, DROP COLUMN defense_comment,
        DROP COLUMN defense_reasons;
    ALTER TABLE campaigns DROP COLUMN defense_use_cutoff;
    ALTER TYPE idea_stage RENAME VALUE 'desclassificada' TO 'selecionada';
    """)
