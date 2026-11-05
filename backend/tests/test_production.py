"""Fatia 9: peças de produção (e-mail SMTP, app servido pelo backend, arquivos e Consultor por convite)."""
import smtplib

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.config import get_settings
from app.email import EmailMessage, SmtpEmailSender
from app.main import create_app
from app.models import Role, User
from app.storage import LocalStorage


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, msg):
        FakeSMTP.sent.append((self, msg))


def test_smtp_envia_com_starttls_e_login(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "email-smtp.sa-east-1.amazonaws.com")
    monkeypatch.setattr(s, "smtp_user", "AKIA")
    monkeypatch.setattr(s, "smtp_password", "x")
    monkeypatch.setattr(s, "email_from", "nao-responda@inova.exemplo.com.br")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent.clear()
    SmtpEmailSender().send(EmailMessage(to="ana@hosp.com.br", subject="Ative seu acesso — HNSG", body="Olá, Ana."))
    conn, msg = FakeSMTP.sent[0]
    assert conn.host == "email-smtp.sa-east-1.amazonaws.com" and conn.port == 587
    assert conn.calls == ["starttls", "login:AKIA"]
    assert msg["To"] == "ana@hosp.com.br" and "nao-responda@inova.exemplo.com.br" in msg["From"]
    assert msg["Subject"] == "Ative seu acesso — HNSG"
    assert msg.get_content().strip() == "Olá, Ana."


def test_smtp_falha_nao_derruba_quem_pediu(monkeypatch, caplog):
    def broken(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(smtplib, "SMTP", broken)
    SmtpEmailSender().send(EmailMessage(to="ana@hosp.com.br", subject="Teste", body="x"))
    assert "Falha ao enviar e-mail" in caplog.text


def test_backend_entrega_o_app_e_cai_no_index(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(get_settings(), "frontend_dist", str(tmp_path))
    client = TestClient(create_app())
    assert client.get("/").text == "<div id=root></div>"
    assert client.get("/campanhas/123/ideias").text == "<div id=root></div>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/nao-existe").status_code == 404
    assert client.get("/../../etc/passwd").text == "<div id=root></div>"


def test_armazenamento_local_nao_sai_da_pasta(tmp_path):
    storage = LocalStorage(str(tmp_path / "arquivos"))
    path = storage.save("tenants/hnsg", b"%PDF-1.4", "pdf")
    assert storage.read(path) == b"%PDF-1.4"
    (tmp_path / "segredo.txt").write_text("não")
    assert storage.read("../segredo.txt") is None
    assert storage.read("tenants/hnsg/nao-existe.pdf") is None


def test_consultor_com_senha_da_variavel(owner, monkeypatch, client_for):
    monkeypatch.setenv("CONSULTOR_SENHA", "senha-forte-123")
    cli.criar_consultor("Osti", "Osti@Flash.com.br")
    user = owner.scalar(select(User).where(User.email == "osti@flash.com.br"))
    assert user.role == Role.consultor and user.email_verified_at is not None
    r = client_for(None).post("/api/auth/login", json={"email": "osti@flash.com.br", "password": "senha-forte-123"})
    assert r.status_code == 200
