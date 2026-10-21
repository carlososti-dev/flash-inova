import logging
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


@lru_cache
def get_email_sender() -> EmailSender:
    # Produção: implementar um serviço transacional (ex.: SendGrid, SES) com o mesmo método send().
    if get_settings().email_backend == "memory":
        return MemoryEmailSender()
    return ConsoleEmailSender()
