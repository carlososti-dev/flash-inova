"""Fatia 2: lista de autorizados (quem pode se cadastrar em cada hospital).

Revision ID: 0002
"""
import os

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flash_app")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALL_TENANTS = "current_setting('app.all_tenants', true) = 'on'"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE authorized_members (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        matricula varchar(50) NOT NULL,
        name varchar(200) NOT NULL,
        email varchar(320) NOT NULL,
        sector varchar(200),
        default_role user_role,
        user_id uuid REFERENCES users(id),
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT authorized_members_perfil CHECK (default_role IS NULL OR default_role <> 'consultor')
    );
    CREATE UNIQUE INDEX authorized_members_matricula ON authorized_members (tenant_id, matricula);
    CREATE UNIQUE INDEX authorized_members_email ON authorized_members (tenant_id, lower(email));
    """)
    op.execute(f"""
    ALTER TABLE authorized_members ENABLE ROW LEVEL SECURITY;
    ALTER TABLE authorized_members FORCE ROW LEVEL SECURITY;
    CREATE POLICY authorized_isolamento ON authorized_members
        USING (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS})
        WITH CHECK (tenant_id = {CURRENT_TENANT} OR {ALL_TENANTS});
    GRANT SELECT, INSERT, UPDATE ON authorized_members TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("DROP TABLE authorized_members")
