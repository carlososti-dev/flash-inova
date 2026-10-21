"""Cria o primeiro Consultor: python -m app.cli criar-consultor --nome "..." --email ..."""
import argparse
import getpass
import sys

from sqlalchemy import func, select

from .db import get_sessionmaker
from .models import Role, User, utcnow
from .security import hash_password, password_problem


def criar_consultor(nome: str, email: str) -> None:
    password = getpass.getpass("Senha: ")
    problem = password_problem(password)
    if problem:
        sys.exit(problem)
    db = get_sessionmaker()()
    db.info["all_tenants"] = True
    if db.scalar(select(User).where(func.lower(User.email) == email.lower())):
        sys.exit("Este e-mail já existe.")
    db.add(User(role=Role.consultor, name=nome, email=email.lower(), password_hash=hash_password(password),
                email_verified_at=utcnow()))
    db.commit()
    print(f"Consultor {email} criado.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar-consultor")
    c.add_argument("--nome", required=True)
    c.add_argument("--email", required=True)
    args = parser.parse_args()
    if args.cmd == "criar-consultor":
        criar_consultor(args.nome, args.email)


if __name__ == "__main__":
    main()
