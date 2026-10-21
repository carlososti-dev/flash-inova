"""Migrações rodam com o usuário DONO das tabelas (MIGRATIONS_DATABASE_URL).

A aplicação usa outro usuário, sem privilégios (APP_DB_ROLE), para o Row Level Security valer.
"""
import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

# Lê o backend/.env, se existir, sem sobrescrever variáveis já definidas.
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

url = os.environ.get("MIGRATIONS_DATABASE_URL") or context.config.get_main_option("sqlalchemy.url")
if not url:
    raise SystemExit("Defina MIGRATIONS_DATABASE_URL (usuário dono do banco).")

engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
