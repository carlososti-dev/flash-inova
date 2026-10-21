from datetime import timedelta

from sqlalchemy import select, update

from app.models import AuditLog, AuthToken, Role, UserStatus, utcnow

from .conftest import PASSWORD, link_token, login


def test_login_e_sessao(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg")
    make_user("ana@hnsg.org", hnsg)
    c = client_for("hnsg")
    r = login(c, "ANA@hnsg.org")
    assert r.status_code == 200
    assert r.json()["role"] == "colaborador"
    assert r.json()["tenant"]["slug"] == "hnsg"
    assert c.get("/api/auth/me").json()["email"] == "ana@hnsg.org"
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_senha_errada_e_email_inexistente_tem_a_mesma_resposta(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg")
    make_user("ana@hnsg.org", hnsg)
    c = client_for("hnsg")
    errada = login(c, "ana@hnsg.org", "outra-senha1")
    inexistente = login(c, "ninguem@hnsg.org")
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()


def test_email_nao_confirmado_e_usuario_inativo_nao_entram(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg")
    make_user("nova@hnsg.org", hnsg, verified=False)
    make_user("saiu@hnsg.org", hnsg, status=UserStatus.inativo)
    c = client_for("hnsg")
    assert "Confirme seu e-mail" in login(c, "nova@hnsg.org").json()["detail"]
    assert "inativo" in login(c, "saiu@hnsg.org").json()["detail"]


def test_usuario_de_um_hospital_nao_entra_em_outro(client_for, make_tenant, make_user):
    hnsg, hsc = make_tenant("hnsg"), make_tenant("hsc")
    make_user("ana@hnsg.org", hnsg)
    assert login(client_for("hsc"), "ana@hnsg.org").status_code == 401
    assert login(client_for(None), "ana@hnsg.org").status_code == 401


def test_sessao_de_um_hospital_nao_vale_em_outro(client_for, make_tenant, make_user):
    hnsg, _ = make_tenant("hnsg"), make_tenant("hsc")
    make_user("ana@hnsg.org", hnsg)
    c = client_for("hnsg")
    login(c, "ana@hnsg.org")
    c.headers["X-Tenant"] = "hsc"
    assert c.get("/api/auth/me").status_code == 401


def test_hospital_suspenso_bloqueia_login(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg", active=False)
    make_user("ana@hnsg.org", hnsg)
    assert login(client_for("hnsg"), "ana@hnsg.org").status_code == 403


def test_hospital_desconhecido(client_for):
    assert client_for("naoexiste").get("/api/site").status_code == 404


def test_consultor_entra_na_plataforma_e_em_qualquer_hospital(client_for, make_tenant, make_user):
    make_tenant("hnsg")
    make_user("consultor@flash.com", None, Role.consultor)
    assert login(client_for(None), "consultor@flash.com").status_code == 200
    c = client_for("hnsg")
    assert login(c, "consultor@flash.com").status_code == 200
    assert c.get("/api/auth/me").json()["role"] == "consultor"


def test_redefinicao_de_senha(client_for, make_tenant, make_user, outbox, owner):
    hnsg = make_tenant("hnsg")
    make_user("ana@hnsg.org", hnsg)
    antiga = client_for("hnsg")
    login(antiga, "ana@hnsg.org")

    c = client_for("hnsg")
    r = c.post("/api/auth/forgot-password", json={"email": "ana@hnsg.org"})
    assert r.status_code == 200 and len(outbox) == 1
    assert "tenant=hnsg" in outbox[0].body
    token = link_token(outbox[0].body)

    assert c.post("/api/auth/reset-password", json={"token": token, "password": "curta"}).status_code == 422
    assert c.post("/api/auth/reset-password", json={"token": token, "password": "novaSenha9"}).status_code == 200
    # o link só vale uma vez
    assert c.post("/api/auth/reset-password", json={"token": token, "password": "outraSenha9"}).status_code == 400
    # a sessão aberta com a senha antiga cai
    assert antiga.get("/api/auth/me").status_code == 401
    assert login(c, "ana@hnsg.org", PASSWORD).status_code == 401
    assert login(c, "ana@hnsg.org", "novaSenha9").status_code == 200
    actions = owner.scalars(select(AuditLog.action)).all()
    assert "senha_redefinida" in actions


def test_esqueci_senha_nao_revela_quem_tem_conta(client_for, make_tenant, outbox):
    make_tenant("hnsg")
    r = client_for("hnsg").post("/api/auth/forgot-password", json={"email": "ninguem@hnsg.org"})
    assert r.status_code == 200 and "Se este e-mail" in r.json()["message"]
    assert outbox == []


def test_link_expirado_nao_vale(client_for, make_tenant, make_user, outbox, owner):
    hnsg = make_tenant("hnsg")
    make_user("ana@hnsg.org", hnsg)
    c = client_for("hnsg")
    c.post("/api/auth/forgot-password", json={"email": "ana@hnsg.org"})
    owner.execute(update(AuthToken).values(expires_at=utcnow() - timedelta(minutes=1)))
    owner.commit()
    r = c.post("/api/auth/reset-password", json={"token": link_token(outbox[0].body), "password": "novaSenha9"})
    assert r.status_code == 400


def test_link_de_um_hospital_nao_vale_em_outro(client_for, make_tenant, make_user, outbox):
    hnsg, _ = make_tenant("hnsg"), make_tenant("hsc")
    make_user("ana@hnsg.org", hnsg)
    client_for("hnsg").post("/api/auth/forgot-password", json={"email": "ana@hnsg.org"})
    token = link_token(outbox[0].body)
    r = client_for("hsc").post("/api/auth/reset-password", json={"token": token, "password": "novaSenha9"})
    assert r.status_code == 400


def test_novo_link_invalida_o_anterior(client_for, make_tenant, make_user, outbox):
    hnsg = make_tenant("hnsg")
    make_user("ana@hnsg.org", hnsg)
    c = client_for("hnsg")
    c.post("/api/auth/forgot-password", json={"email": "ana@hnsg.org"})
    c.post("/api/auth/forgot-password", json={"email": "ana@hnsg.org"})
    primeiro, segundo = (link_token(m.body) for m in outbox)
    assert c.post("/api/auth/reset-password", json={"token": primeiro, "password": "novaSenha9"}).status_code == 400
    assert c.post("/api/auth/reset-password", json={"token": segundo, "password": "novaSenha9"}).status_code == 200
