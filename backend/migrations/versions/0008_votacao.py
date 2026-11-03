"""Fatia 8: Votação. Um voto por pessoa (login ou matrícula com código por e-mail) e apuração com pódio.

Quem votou (voters) e em quem (ballots) ficam em tabelas separadas, sem ligação entre elas.

Revision ID: 0008
"""
import os

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flash_app")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALL_TENANTS = "current_setting('app.all_tenants', true) = 'on'"


def _rls(table: str, grants: str) -> str:
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {table}_isolamento ON {table}
        USING (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS})
        WITH CHECK (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS});
    GRANT {grants} ON {table} TO {APP_ROLE};
    """


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE campaigns ADD COLUMN voting_closed_at timestamptz;
    ALTER TABLE ideas
        ADD COLUMN vote_count integer,
        ADD COLUMN award_position integer,
        ADD CONSTRAINT ideas_lugar_positivo CHECK (award_position > 0);

    CREATE TABLE voters (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id),
        member_id uuid REFERENCES authorized_members(id),
        user_id uuid REFERENCES users(id),
        method varchar(20) NOT NULL,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT voters_identificado CHECK (member_id IS NOT NULL OR user_id IS NOT NULL)
    );
    -- Um voto por pessoa, pelo login ou pela matrícula: as duas chaves são únicas na campanha.
    CREATE UNIQUE INDEX voters_um_por_matricula ON voters (campaign_id, member_id) WHERE member_id IS NOT NULL;
    CREATE UNIQUE INDEX voters_um_por_usuario ON voters (campaign_id, user_id) WHERE user_id IS NOT NULL;
    {_rls("voters", "SELECT, INSERT")}

    CREATE TABLE ballots (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id),
        idea_id uuid NOT NULL REFERENCES ideas(id)
    );
    CREATE INDEX ballots_campanha ON ballots (campaign_id, idea_id);
    {_rls("ballots", "SELECT, INSERT")}

    CREATE TABLE vote_codes (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id),
        member_id uuid NOT NULL REFERENCES authorized_members(id),
        code_hash varchar(64) NOT NULL,
        expires_at timestamptz NOT NULL,
        attempts integer NOT NULL DEFAULT 0,
        used_at timestamptz,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE INDEX vote_codes_pessoa ON vote_codes (campaign_id, member_id);
    {_rls("vote_codes", "SELECT, INSERT, UPDATE")}
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE vote_codes; DROP TABLE ballots; DROP TABLE voters;
    UPDATE ideas SET stage = 'shortlist' WHERE stage = 'premiada';
    ALTER TABLE ideas DROP CONSTRAINT ideas_lugar_positivo, DROP COLUMN award_position, DROP COLUMN vote_count;
    ALTER TABLE campaigns DROP COLUMN voting_closed_at;
    UPDATE campaigns SET current_phase = 'votacao' WHERE current_phase = 'encerrada';
    """)
