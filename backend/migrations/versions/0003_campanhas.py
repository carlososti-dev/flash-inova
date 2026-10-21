"""Fatia 3: campanhas (datas das fases, textos, banner, vídeo, regulamento, regras) e linhas de ideias.

Revision ID: 0003
"""
import os

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flash_app")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALL_TENANTS = "current_setting('app.all_tenants', true) = 'on'"


def upgrade() -> None:
    op.execute("""
    CREATE TYPE campaign_phase AS ENUM ('recepcao', 'analise', 'classificacao', 'defesa', 'votacao', 'encerrada');

    CREATE TABLE campaigns (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        title varchar(200) NOT NULL,
        is_published boolean NOT NULL DEFAULT false,
        submission_start timestamptz NOT NULL,
        submission_end timestamptz NOT NULL,
        analysis_start timestamptz,
        analysis_end timestamptz,
        classification_end timestamptz,
        defense_date timestamptz,
        voting_start timestamptz,
        voting_end timestamptz,
        home_headline varchar(300),
        home_text text,
        tips_text text,
        regulation_text text,
        banner_path varchar(500),
        video_url varchar(500),
        num_evaluators integer NOT NULL,
        weight_classify integer NOT NULL,
        weight_maybe integer NOT NULL,
        cutoff_score integer NOT NULL,
        blind_review boolean NOT NULL DEFAULT true,
        num_defense_finalists integer,
        num_voting_finalists integer,
        num_winners integer NOT NULL DEFAULT 3,
        current_phase campaign_phase NOT NULL DEFAULT 'recepcao',
        created_by uuid REFERENCES users(id),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT campaigns_periodo_inscricao CHECK (submission_start < submission_end)
    );
    CREATE INDEX campaigns_tenant ON campaigns (tenant_id, submission_start);

    CREATE TABLE campaign_lines (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        name varchar(120) NOT NULL,
        description varchar(500),
        position integer NOT NULL DEFAULT 0,
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE UNIQUE INDEX campaign_lines_nome ON campaign_lines (campaign_id, lower(name));
    """)
    for table, policy in (("campaigns", "campaigns_isolamento"), ("campaign_lines", "campaign_lines_isolamento")):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {policy} ON {table}
            USING (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS})
            WITH CHECK (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS});
        GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE};
        """)


def downgrade() -> None:
    op.execute("DROP TABLE campaign_lines; DROP TABLE campaigns; DROP TYPE campaign_phase;")
