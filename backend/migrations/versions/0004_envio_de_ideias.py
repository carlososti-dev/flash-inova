"""Fatia 4: campos do formulário por campanha, ideias (rascunho e envio), respostas, coautores e versões do
regulamento (o aceite aponta para a versão aceita).

Revision ID: 0004
"""
import os

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flash_app")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALL_TENANTS = "current_setting('app.all_tenants', true) = 'on'"

TABLES = ("regulation_versions", "campaign_fields", "ideas", "idea_answers", "idea_coauthors")


def upgrade() -> None:
    op.execute("""
    CREATE TYPE field_kind AS ENUM ('texto_curto', 'texto_longo', 'lista', 'sim_nao', 'anexo');
    CREATE TYPE idea_stage AS ENUM ('rascunho', 'recebida', 'em_analise', 'empate', 'classificada', 'talvez',
                                    'nao_classificada', 'shortlist', 'selecionada', 'premiada');

    CREATE TABLE regulation_versions (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        version integer NOT NULL,
        text text NOT NULL,
        created_by uuid REFERENCES users(id),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE UNIQUE INDEX regulation_versions_numero ON regulation_versions (campaign_id, version);

    CREATE TABLE campaign_fields (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        kind field_kind NOT NULL,
        label varchar(200) NOT NULL,
        help_text varchar(500),
        required boolean NOT NULL DEFAULT false,
        options jsonb,
        position integer NOT NULL DEFAULT 0,
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE INDEX campaign_fields_campaign ON campaign_fields (campaign_id, position);

    -- Sem ON DELETE CASCADE na campanha e na linha: campanha ou linha com ideias não pode ser apagada.
    CREATE TABLE ideas (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        campaign_id uuid NOT NULL REFERENCES campaigns(id),
        line_id uuid REFERENCES campaign_lines(id),
        author_id uuid NOT NULL REFERENCES users(id),
        number integer,
        title varchar(200) NOT NULL,
        summary text,
        stage idea_stage NOT NULL DEFAULT 'rascunho',
        submitted_at timestamptz,
        regulation_version_id uuid REFERENCES regulation_versions(id),
        regulation_accepted_at timestamptz,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT ideas_enviada_com_aceite CHECK (
            stage = 'rascunho' OR (submitted_at IS NOT NULL AND number IS NOT NULL AND line_id IS NOT NULL
                                   AND regulation_version_id IS NOT NULL AND regulation_accepted_at IS NOT NULL))
    );
    CREATE UNIQUE INDEX ideas_numero ON ideas (campaign_id, number);
    CREATE INDEX ideas_author ON ideas (author_id);
    CREATE INDEX ideas_campaign_stage ON ideas (campaign_id, stage);

    -- Campo com respostas não é apagado, só desativado (RESTRICT no campo).
    CREATE TABLE idea_answers (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        idea_id uuid NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
        field_id uuid NOT NULL REFERENCES campaign_fields(id),
        value jsonb,
        file_path varchar(500),
        file_name varchar(255),
        file_size integer,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE UNIQUE INDEX idea_answers_campo ON idea_answers (idea_id, field_id);

    -- Coautores vêm da lista de autorizados (podem ainda não ter conta).
    CREATE TABLE idea_coauthors (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        idea_id uuid NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
        member_id uuid NOT NULL REFERENCES authorized_members(id),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE UNIQUE INDEX idea_coauthors_pessoa ON idea_coauthors (idea_id, member_id);
    CREATE INDEX idea_coauthors_member ON idea_coauthors (member_id);

    -- O regulamento que já existia vira a versão 1.
    INSERT INTO regulation_versions (id, tenant_id, campaign_id, version, text, created_by, created_at, updated_at)
    SELECT gen_random_uuid(), tenant_id, id, 1, regulation_text, created_by, updated_at, updated_at
    FROM campaigns WHERE regulation_text IS NOT NULL AND btrim(regulation_text) <> '';
    """)
    for table in TABLES:
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_isolamento ON {table}
            USING (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS})
            WITH CHECK (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS});
        GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE};
        """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE idea_coauthors; DROP TABLE idea_answers; DROP TABLE ideas; DROP TABLE campaign_fields;
    DROP TABLE regulation_versions; DROP TYPE idea_stage; DROP TYPE field_kind;
    """)
