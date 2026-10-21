"""Fatia 1: hospitais, usuários, tokens, auditoria e isolamento por hospital.

Revision ID: 0001
"""
import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flash_app")

# Hospital da requisição e modo "todos os hospitais" (só o Consultor), definidos pela aplicação a cada transação.
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALL_TENANTS = "current_setting('app.all_tenants', true) = 'on'"


def upgrade() -> None:
    op.execute("""
    CREATE TYPE theme AS ENUM ('verde', 'azul');
    CREATE TYPE user_role AS ENUM ('consultor', 'administrador', 'gestor', 'membro_comite', 'colaborador');
    CREATE TYPE user_status AS ENUM ('ativo', 'inativo');
    CREATE TYPE token_purpose AS ENUM ('verify_email', 'reset_password');

    CREATE TABLE tenants (
        id uuid PRIMARY KEY,
        slug varchar(63) NOT NULL UNIQUE CONSTRAINT tenants_slug_format CHECK (slug ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'),
        name varchar(200) NOT NULL,
        logo_path varchar(500),
        theme theme NOT NULL DEFAULT 'verde',
        default_banner_path varchar(500),
        default_video_url varchar(500),
        default_num_evaluators integer NOT NULL DEFAULT 3,
        default_weight_classify integer NOT NULL DEFAULT 5,
        default_weight_maybe integer NOT NULL DEFAULT 1,
        default_cutoff_score integer NOT NULL DEFAULT 70,
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );

    CREATE TABLE users (
        id uuid PRIMARY KEY,
        tenant_id uuid REFERENCES tenants(id),
        role user_role NOT NULL,
        name varchar(200) NOT NULL,
        email varchar(320) NOT NULL,
        password_hash varchar(255),
        matricula varchar(50),
        sector varchar(200),
        phone varchar(50),
        status user_status NOT NULL DEFAULT 'ativo',
        email_verified_at timestamptz,
        session_version integer NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT users_consultor_sem_hospital CHECK ((tenant_id IS NULL) = (role = 'consultor'))
    );
    CREATE UNIQUE INDEX users_email_unique ON users (lower(email));
    CREATE UNIQUE INDEX users_matricula_unique ON users (tenant_id, matricula);
    CREATE INDEX users_tenant ON users (tenant_id);

    CREATE TABLE auth_tokens (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose token_purpose NOT NULL,
        token_hash varchar(64) NOT NULL UNIQUE,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE INDEX auth_tokens_user ON auth_tokens (user_id);

    CREATE TABLE audit_log (
        id uuid PRIMARY KEY,
        tenant_id uuid REFERENCES tenants(id),
        actor_user_id uuid REFERENCES users(id),
        action varchar(100) NOT NULL,
        entity varchar(100),
        entity_id varchar(100),
        details jsonb,
        created_at timestamptz NOT NULL
    );
    CREATE INDEX audit_log_tenant ON audit_log (tenant_id, created_at);
    """)

    # Isolamento entre hospitais no banco (segunda barreira, além do filtro na aplicação).
    op.execute(f"""
    ALTER TABLE users ENABLE ROW LEVEL SECURITY;
    ALTER TABLE users FORCE ROW LEVEL SECURITY;
    -- Usuários do hospital da requisição; o Consultor (sem hospital) é visível para conseguir entrar em qualquer hospital.
    CREATE POLICY users_isolamento ON users
        USING (tenant_id = {CURRENT_TENANT} OR tenant_id IS NULL OR {ALL_TENANTS})
        WITH CHECK (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS});

    ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
    ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
    CREATE POLICY audit_isolamento ON audit_log
        USING (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS})
        WITH CHECK (tenant_id = {CURRENT_TENANT} OR tenant_id IS NULL OR {ALL_TENANTS});
    """)

    op.execute(f"""
    GRANT SELECT, INSERT, UPDATE ON tenants, users, auth_tokens TO {APP_ROLE};
    GRANT SELECT, INSERT ON audit_log TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE audit_log; DROP TABLE auth_tokens; DROP TABLE users; DROP TABLE tenants;
    DROP TYPE token_purpose; DROP TYPE user_status; DROP TYPE user_role; DROP TYPE theme;
    """)
