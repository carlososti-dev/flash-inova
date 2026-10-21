"""Os testes usam um PostgreSQL de verdade, porque o isolamento entre hospitais depende do Row Level Security.

TEST_ADMIN_DATABASE_URL: conexão com um superusuário (cria o banco de teste e o usuário da aplicação).
"""
import os
import re
import tempfile
from datetime import datetime, timezone

import pytest

ADMIN_URL = os.environ.get("TEST_ADMIN_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/postgres")
TEST_DB = "flash_inova_test"
APP_ROLE, APP_PASSWORD = "flash_app_test", "flash_app_test"
_server, _ = ADMIN_URL.rsplit("/", 1)
_user_host = _server.split("://", 1)[1].split("@", 1)[1]

os.environ.update({
    "DATABASE_URL": f"postgresql+psycopg://{APP_ROLE}:{APP_PASSWORD}@{_user_host}/{TEST_DB}",
    "EMAIL_BACKEND": "memory",
    "STORAGE_DIR": tempfile.mkdtemp(prefix="flash-storage-"),
    "PRIVATE_STORAGE_DIR": tempfile.mkdtemp(prefix="flash-private-"),
    "SECRET_KEY": "chave-de-teste-com-pelo-menos-32-caracteres",
    "ALLOW_TENANT_OVERRIDE": "true",
    "APP_DB_ROLE": APP_ROLE,
})

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.email import get_email_sender  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Role, Tenant, User, UserStatus  # noqa: E402
from app.security import hash_password  # noqa: E402

OWNER_URL = f"{_server}/{TEST_DB}"
PASSWORD = "senha1234"


@pytest.fixture(scope="session")
def owner_engine():
    server = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with server.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {TEST_DB}"))
        c.execute(text(f"DO $$ BEGIN CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER; "
                       "EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
    server.dispose()
    os.environ["MIGRATIONS_DATABASE_URL"] = OWNER_URL
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    command.upgrade(cfg, "head")
    engine = create_engine(OWNER_URL)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(owner_engine):
    with owner_engine.begin() as c:
        c.execute(text("TRUNCATE idea_coauthors, idea_answers, ideas, campaign_fields, regulation_versions, campaign_lines, campaigns, audit_log, auth_tokens, authorized_members, users, tenants CASCADE"))
    get_email_sender().outbox.clear()
    yield


@pytest.fixture
def owner(owner_engine):
    """Sessão como dono das tabelas (ignora o RLS): só para preparar dados e conferir resultados."""
    with Session(owner_engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client_for(app):
    """client_for('hnsg') → cliente HTTP falando com o endereço daquele hospital; None = plataforma."""
    def make(slug: str | None = None) -> TestClient:
        return TestClient(app, headers={"X-Tenant": slug} if slug else {})
    return make


@pytest.fixture
def make_tenant(owner):
    def make(slug: str, name: str | None = None, active: bool = True) -> Tenant:
        t = Tenant(slug=slug, name=name or slug.upper(), is_active=active)
        owner.add(t)
        owner.commit()
        return t
    return make


@pytest.fixture
def make_user(owner):
    def make(email: str, tenant: Tenant | None = None, role: Role = Role.colaborador, *,
             verified: bool = True, status: UserStatus = UserStatus.ativo, password: str | None = PASSWORD) -> User:
        u = User(tenant_id=tenant.id if tenant else None, role=role, name=email.split("@")[0].title(), email=email,
                 password_hash=hash_password(password) if password else None, status=status,
                 email_verified_at=datetime.now(timezone.utc) if verified else None)
        owner.add(u)
        owner.commit()
        return u
    return make


@pytest.fixture
def outbox():
    return get_email_sender().outbox


def link_token(body: str) -> str:
    return re.search(r"token=([\w-]+)", body).group(1)


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})
