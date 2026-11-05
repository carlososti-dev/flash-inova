import logging
import smtplib
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, make_msgid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from .config import get_settings

log = logging.getLogger("flash.email")


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Desenvolvimento: o e-mail aparece no terminal do backend."""

    def send(self, message: EmailMessage) -> None:
        log.warning("\n--- E-MAIL ---\nPara: %s\nAssunto: %s\n\n%s\n--------------", message.to, message.subject, message.body)


@dataclass
class MemoryEmailSender:
    """Testes: guarda os e-mails enviados."""

    outbox: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


class SmtpEmailSender:
    """Produção: SMTP com STARTTLS (Amazon SES, Resend, Google Workspace...). Uma conexão por e-mail."""

    def send(self, message: EmailMessage) -> None:
        s = get_settings()
        mime = MimeMessage()
        mime["From"] = formataddr((s.email_from_name, s.email_from))
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime["Message-ID"] = make_msgid(domain=s.email_from.rsplit("@", 1)[-1])
        mime.set_content(message.body)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(mime)
        except (smtplib.SMTPException, OSError):
            # Não derruba a tela de quem pediu o e-mail; o erro fica no log (e no monitoramento).
            log.exception("Falha ao enviar e-mail para %s (%s)", message.to, message.subject)


@lru_cache
def get_email_sender() -> EmailSender:
    backend = get_settings().email_backend
    if backend == "memory":
        return MemoryEmailSender()
    if backend == "smtp":
        return SmtpEmailSender()
    return ConsoleEmailSender()
