"""Fatia 6: apuração da Classificação, nota de ranking e Voto de Minerva.

Revision ID: 0006
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE campaigns ADD COLUMN classified_at timestamptz;

    ALTER TABLE ideas
        ADD COLUMN classification_score integer,
        ADD COLUMN minerva_verdict verdict,
        ADD COLUMN minerva_comment text,
        ADD COLUMN minerva_by uuid REFERENCES users(id),
        ADD COLUMN minerva_at timestamptz,
        ADD CONSTRAINT ideas_nota_0_100 CHECK (classification_score BETWEEN 0 AND 100);
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE ideas DROP CONSTRAINT ideas_nota_0_100, DROP COLUMN minerva_at, DROP COLUMN minerva_by,
        DROP COLUMN minerva_comment, DROP COLUMN minerva_verdict, DROP COLUMN classification_score;
    ALTER TABLE campaigns DROP COLUMN classified_at;
    """)
