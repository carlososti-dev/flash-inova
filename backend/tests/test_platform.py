from sqlalchemy import select

from app.models import AuditLog, Role, Tenant

from .conftest import link_token, login

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def consultor_client(client_for, make_user):
    make_user("consultor@flash.com", None, Role.consultor)
    c = client_for(None)
    login(c, "consultor@flash.com")
    return c


def test_area_do_consultor_exige_consultor(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg")
    assert client_for(None).get("/api/platform/tenants").status_code == 401
    for role in (Role.administrador, Role.gestor, Role.membro_comite, Role.colaborador):
        make_user(f"{role.value}@hnsg.org", hnsg, role)
        c = client_for("hnsg")
        login(c, f"{role.value}@hnsg.org")
        assert c.get("/api/platform/tenants").status_code == 403, role


def test_criar_hospital_logo_tema_e_primeiro_administrador(client_for, make_user, outbox, owner):
    c = consultor_client(client_for, make_user)

    r = c.post("/api/platform/tenants", json={"slug": "hnsg", "name": "Hospital N. S. das Graças", "theme": "azul"})
    assert r.status_code == 201
    tenant_id = r.json()["id"]
    assert c.post("/api/platform/tenants", json={"slug": "hnsg", "name": "Outro"}).status_code == 409
    assert c.post("/api/platform/tenants", json={"slug": "HN SG", "name": "Inválido"}).status_code == 422

    r = c.post(f"/api/platform/tenants/{tenant_id}/logo", files={"file": ("logo.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["logo_url"].startswith("/files/tenants/hnsg/")
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    r = c.post(f"/api/platform/tenants/{tenant_id}/logo", files={"file": ("logo.svg", svg, "image/svg+xml")})
    assert r.status_code == 422

    assert c.patch(f"/api/platform/tenants/{tenant_id}", json={"theme": "verde"}).json()["theme"] == "verde"

    r = c.post(f"/api/platform/tenants/{tenant_id}/admins", json={"name": "Carlos", "email": "Carlos@HNSG.org"})
    assert r.status_code == 201 and r.json()["activated"] is False
    assert c.post(f"/api/platform/tenants/{tenant_id}/admins",
                  json={"name": "Dup", "email": "carlos@hnsg.org"}).status_code == 409

    # O administrador ativa a conta pelo link e entra no endereço do hospital
    assert len(outbox) == 1 and outbox[0].to == "carlos@hnsg.org"
    token = link_token(outbox[0].body)
    hospital = client_for("hnsg")
    assert login(hospital, "carlos@hnsg.org").status_code == 401  # ainda sem senha
    assert hospital.post("/api/auth/activate", json={"token": token, "password": "segura123"}).status_code == 200
    r = login(hospital, "carlos@hnsg.org", "segura123")
    assert r.status_code == 200 and r.json()["role"] == "administrador"
    assert c.get(f"/api/platform/tenants/{tenant_id}/admins").json()[0]["activated"] is True

    # Toda ação do Consultor fica registrada com autor
    log = owner.scalars(select(AuditLog).where(AuditLog.actor_user_id.isnot(None))).all()
    actions = {a.action for a in log}
    assert {"hospital_criado", "logotipo_alterado", "hospital_alterado", "administrador_criado"} <= actions


def test_suspender_hospital(client_for, make_tenant, make_user, owner):
    hnsg = make_tenant("hnsg")
    make_user("ana@hnsg.org", hnsg)
    c = consultor_client(client_for, make_user)
    colaboradora = client_for("hnsg")
    login(colaboradora, "ana@hnsg.org")
    assert c.patch(f"/api/platform/tenants/{hnsg.id}", json={"is_active": False}).status_code == 200
    assert colaboradora.get("/api/auth/me").status_code == 403
    assert owner.get(Tenant, hnsg.id) is not None


def test_site_informa_identidade_do_hospital(client_for, make_tenant):
    make_tenant("hnsg", "Hospital N. S. das Graças")
    r = client_for("hnsg").get("/api/site").json()
    assert r["tenant"]["name"] == "Hospital N. S. das Graças" and r["tenant"]["theme"] == "verde"
    assert client_for(None).get("/api/site").json()["tenant"] is None
