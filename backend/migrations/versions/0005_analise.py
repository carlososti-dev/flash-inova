"""Fatia 5: distribuição das ideias para o comitê e pareceres (menu Análise).

Revision ID: 0005
"""
import os

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flash_app")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALL_TENANTS = "current_setting('app.all_tenants', true) = 'on'"


def upgrade() -> None:
    op.execute(f"""
    CREATE TYPE verdict AS ENUM ('classificar', 'talvez', 'nao_classificar');

    -- Uma linha por ideia e avaliador. A carga de cada avaliador é a contagem desta tabela (sem contador gravado).
    CREATE TABLE assignments (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id),
        idea_id uuid NOT NULL REFERENCES ideas(id),
        evaluator_id uuid NOT NULL REFERENCES users(id),
        verdict verdict,
        comment text,
        evaluated_at timestamptz,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT assignments_talvez_com_parecer CHECK (verdict IS DISTINCT FROM 'talvez' OR btrim(comment) <> '')
    );
    CREATE UNIQUE INDEX assignments_ideia_avaliador ON assignments (idea_id, evaluator_id);
    CREATE INDEX assignments_avaliador ON assignments (evaluator_id, campaign_id);

    ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
    ALTER TABLE assignments FORCE ROW LEVEL SECURITY;
    CREATE POLICY assignments_isolamento ON assignments
        USING (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS})
        WITH CHECK (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS});
    GRANT SELECT, INSERT, UPDATE ON assignments TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("DROP TABLE assignments; DROP TYPE verdict;")
