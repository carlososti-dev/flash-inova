import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import get_settings

_hasher = PasswordHasher()
# Usado quando o e-mail não existe, para o tempo de resposta não revelar se a conta existe.
_DUMMY_HASH = _hasher.hash("senha-ficticia-para-tempo-constante")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "A senha deve ter letras e números."
    return None


def new_token() -> tuple[str, str]:
    """Devolve (token para o link, hash para guardar). Só o hash vai para o banco."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: uuid.UUID, tenant_id: uuid.UUID | None, session_version: int) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "sv": session_version,
        "exp": datetime.now(timezone.utc) + timedelta(hours=s.session_hours),
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def read_session(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
