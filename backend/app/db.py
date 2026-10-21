from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    """Informa ao PostgreSQL o hospital da requisição a cada transação.

    As políticas de Row Level Security leem estas variáveis; elas valem só dentro
    da transação (set_config(..., true)), por isso são reaplicadas a cada início.
    """
    tenant_id = session.info.get("tenant_id")
    all_tenants = session.info.get("all_tenants", False)
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tid, true), set_config('app.all_tenants', :all, true)"),
        {"tid": str(tenant_id) if tenant_id else "", "all": "on" if all_tenants else "off"},
    )


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
