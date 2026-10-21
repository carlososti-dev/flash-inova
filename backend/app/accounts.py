"""Tokens de e-mail (ativação de conta e redefinição de senha)."""
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .email import EmailMessage, get_email_sender
from .links import frontend_link
from .models import AuthToken, Tenant, TokenPurpose, User, utcnow
from .security import hash_token, new_token


def issue_token(db: Session, user: User, purpose: TokenPurpose) -> str:
    s = get_settings()
    hours = s.reset_token_hours if purpose == TokenPurpose.reset_password else s.activation_token_hours
    # Um link novo invalida os anteriores do mesmo tipo.
    db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    token, token_hash = new_token()
    db.add(AuthToken(user_id=user.id, purpose=purpose, token_hash=token_hash, expires_at=utcnow() + timedelta(hours=hours)))
    return token


def consume_token(db: Session, token: str, purpose: TokenPurpose) -> User | None:
    """Valida e marca o token como usado. O usuário só aparece se for do hospital da requisição (RLS)."""
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(token), AuthToken.purpose == purpose))
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        return None
    user = db.get(User, row.user_id)
    if user is None:
        return None
    row.used_at = utcnow()
    return user


def send_activation(db: Session, user: User, tenant: Tenant | None, invited_by: str | None) -> None:
    """invited_by=None: a própria pessoa pediu o cadastro."""
    token = issue_token(db, user, TokenPurpose.verify_email)
    link = frontend_link(tenant, "/ativar-conta", token=token)
    where = tenant.name if tenant else "Flash Inova"
    hours = get_settings().activation_token_hours
    intro = (f"Recebemos seu cadastro na plataforma de ideias de {where}." if invited_by is None
             else f"{invited_by} criou seu acesso à plataforma de ideias de {where}.")
    get_email_sender().send(EmailMessage(
        to=user.email,
        subject=f"Ative seu acesso — {where}",
        body=(
            f"Olá, {user.name}.\n\n{intro}\n"
            f"Para confirmar seu e-mail e criar sua senha, acesse:\n{link}\n\n"
            f"O link vale por {hours} horas."
        ),
    ))


def send_reset(db: Session, user: User, tenant: Tenant | None) -> None:
    token = issue_token(db, user, TokenPurpose.reset_password)
    link = frontend_link(tenant, "/redefinir-senha", token=token)
    hours = get_settings().reset_token_hours
    get_email_sender().send(EmailMessage(
        to=user.email,
        subject="Redefinição de senha",
        body=(
            f"Olá, {user.name}.\n\nRecebemos um pedido para redefinir sua senha.\n"
            f"Para criar uma nova senha, acesse:\n{link}\n\n"
            f"O link vale por {hours} hora(s). Se você não pediu, ignore este e-mail."
        ),
    ))
