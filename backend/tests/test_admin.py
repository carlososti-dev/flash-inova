import io

from openpyxl import Workbook
from sqlalchemy import select

from app.models import AuditLog, AuthorizedMember, Role, User, UserStatus

from .conftest import link_token, login

CSV = (
    "Matrícula;Nome;E-mail;Setor;Perfil\n"
    "100;Ana Lima;ana@hnsg.org;Enfermagem;colaborador\n"
    "200;Bruno Reis;BRUNO@hnsg.org;Qualidade;Membro de Comitê\n"
    "300;;sem-nome@hnsg.org;;\n"
    "400;Carla;email-invalido;;\n"
    "200;Duplicado;dup@hnsg.org;;\n"
    "500;Davi;davi@hnsg.org;;diretor\n"
).encode("utf-8")


def admin_client(client_for, make_tenant, make_user, slug="hnsg"):
    tenant = make_tenant(slug)
    admin = make_user(f"admin@{slug}.org", tenant, Role.administrador)
    c = client_for(slug)
    login(c, f"admin@{slug}.org")
    return c, tenant, admin


def upload(c, data: bytes, confirm: bool, name="lista.csv"):
    return c.post("/api/admin/authorized/import", files={"file": (name, data)}, data={"confirm": str(confirm).lower()})


def test_administracao_exige_administrador(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg")
    assert client_for("hnsg").get("/api/admin/users").status_code == 401
    for role in (Role.gestor, Role.membro_comite, Role.colaborador):
        make_user(f"{role.value}@hnsg.org", hnsg, role)
        c = client_for("hnsg")
        login(c, f"{role.value}@hnsg.org")
        assert c.get("/api/admin/authorized").status_code == 403, role
        assert c.get("/api/admin/users").status_code == 403, role


def test_importacao_confere_antes_e_grava_so_as_linhas_validas(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)

    r = upload(c, CSV, confirm=False)
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["applied"] is False and report["lines"] == 6
    assert report["created"] == 2 and report["updated"] == 0
    assert [e["line"] for e in report["errors"]] == [4, 5, 6, 7]
    assert "nome vazio" in report["errors"][0]["message"].lower()
    assert "inválido" in report["errors"][1]["message"]
    assert "linha 3" in report["errors"][2]["message"]
    assert "perfil desconhecido" in report["errors"][3]["message"].lower()
    assert owner.scalars(select(AuthorizedMember)).all() == []  # conferência não grava nada

    assert upload(c, CSV, confirm=True).json()["applied"] is True
    members = {m.matricula: m for m in owner.scalars(select(AuthorizedMember))}
    assert set(members) == {"100", "200"}
    assert members["200"].email == "bruno@hnsg.org" and members["200"].default_role == Role.membro_comite

    # Reimportar: atualiza quem mudou (pela matrícula) e não duplica
    novo = "matricula,nome,email,setor\n100,Ana Lima,ana@hnsg.org,UTI\n200,Bruno Reis,bruno@hnsg.org,Qualidade\n"
    r = upload(c, novo.encode(), confirm=True).json()
    assert (r["created"], r["updated"], r["unchanged"]) == (0, 2, 0)  # setor da Ana e perfil do Bruno (vazio)
    assert owner.scalars(select(AuditLog).where(AuditLog.action == "autorizados_importados")).first() is not None


def test_importacao_xlsx_e_arquivos_invalidos(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    wb = Workbook()
    wb.active.append(["Matrícula", "Nome", "Email"])
    wb.active.append([12345, "Ana Lima", "ana@hnsg.org"])  # matrícula numérica
    buf = io.BytesIO()
    wb.save(buf)
    r = upload(c, buf.getvalue(), confirm=True, name="lista.xlsx").json()
    assert r["created"] == 1 and r["errors"] == []
    assert c.get("/api/admin/authorized").json()["items"][0]["matricula"] == "12345"

    assert "Faltam colunas" in upload(c, b"nome;setor\nAna;UTI\n", confirm=False).json()["detail"]
    assert ".xls" in upload(c, b"\xd0\xcf\x11\xe0" + b"\x00" * 100, confirm=False).json()["detail"]
    assert upload(c, b"", confirm=False).status_code == 422


def test_email_de_outra_matricula_e_erro(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    upload(c, b"matricula;nome;email\n100;Ana;ana@hnsg.org\n", confirm=True)
    r = upload(c, b"matricula;nome;email\n999;Outra Ana;ana@hnsg.org\n", confirm=False).json()
    assert "outra matrícula (100)" in r["errors"][0]["message"]


def test_cadastro_pela_lista_de_autorizados(client_for, make_tenant, make_user, outbox, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    upload(c, b"matricula;nome;email;setor;perfil\n100;Ana Lima;ana@hnsg.org;UTI;membro de comite\n", confirm=True)
    publico = client_for("hnsg")

    # Matrícula ou e-mail que não conferem: mesma resposta, nenhum e-mail
    ok = publico.post("/api/auth/register", json={"matricula": "100", "email": "ana@hnsg.org"}).json()
    errado = publico.post("/api/auth/register", json={"matricula": "100", "email": "outra@hnsg.org"}).json()
    assert ok == errado
    assert [m.to for m in outbox] == ["ana@hnsg.org"]
    assert "Recebemos seu cadastro" in outbox[0].body

    user = owner.scalar(select(User).where(User.email == "ana@hnsg.org"))
    assert user.role == Role.membro_comite and user.matricula == "100" and user.sector == "UTI"
    assert login(publico, "ana@hnsg.org").status_code == 401  # ainda sem senha
    assert publico.post("/api/auth/activate", json={"token": link_token(outbox[0].body), "password": "segura123"}).status_code == 200
    assert login(publico, "ana@hnsg.org", "segura123").json()["role"] == "membro_comite"
    assert c.get("/api/admin/authorized").json()["registered"] == 1

    # Quem já tem conta e pede de novo recebe o link de redefinição de senha
    publico.post("/api/auth/register", json={"matricula": "100", "email": "ANA@hnsg.org"})
    assert outbox[-1].subject == "Redefinição de senha"
    assert owner.scalar(select(AuditLog).where(AuditLog.action == "cadastro_recusado")) is not None


def test_cadastro_bloqueado_para_inativos_e_outros_hospitais(client_for, make_tenant, make_user, outbox):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    make_tenant("hsc")
    upload(c, b"matricula;nome;email\n100;Ana;ana@hnsg.org\n200;Bia;bia@hnsg.org\n", confirm=True)
    bia = next(m for m in c.get("/api/admin/authorized").json()["items"] if m["matricula"] == "200")
    assert c.patch(f"/api/admin/authorized/{bia['id']}", json={"is_active": False}).json()["is_active"] is False

    client_for("hnsg").post("/api/auth/register", json={"matricula": "200", "email": "bia@hnsg.org"})
    client_for("hsc").post("/api/auth/register", json={"matricula": "100", "email": "ana@hnsg.org"})
    assert outbox == []
    assert client_for(None).post("/api/auth/register", json={"matricula": "100", "email": "ana@hnsg.org"}).status_code == 400


def test_lista_de_um_hospital_nao_aparece_em_outro(client_for, make_tenant, make_user):
    c1, _, _ = admin_client(client_for, make_tenant, make_user, "hnsg")
    c2, _, _ = admin_client(client_for, make_tenant, make_user, "hsc")
    upload(c1, b"matricula;nome;email\n100;Ana;ana@hnsg.org\n", confirm=True)
    member_id = c1.get("/api/admin/authorized").json()["items"][0]["id"]
    assert c2.get("/api/admin/authorized").json()["total"] == 0
    assert c2.patch(f"/api/admin/authorized/{member_id}", json={"is_active": False}).status_code == 404
    # A mesma matrícula pode existir em outro hospital
    assert upload(c2, b"matricula;nome;email\n100;Ana Outra;ana@hsc.org\n", confirm=True).json()["created"] == 1


def test_inclusao_manual_e_busca(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    body = {"matricula": "100", "name": "Ana Lima", "email": "Ana@hnsg.org", "sector": "UTI", "default_role": "gestor"}
    assert c.post("/api/admin/authorized", json=body).status_code == 201
    assert c.post("/api/admin/authorized", json={**body, "email": "x@hnsg.org"}).status_code == 409
    assert c.post("/api/admin/authorized", json={**body, "matricula": "9", "default_role": "administrador"}).status_code == 422
    assert c.get("/api/admin/authorized", params={"q": "uti"}).json()["total"] == 1
    assert c.get("/api/admin/authorized", params={"q": "zzz"}).json()["total"] == 0
    assert c.get("/api/admin/authorized/modelo.csv").text.startswith("﻿matricula;nome;email")


def test_gestao_de_usuarios(client_for, make_tenant, make_user, outbox, owner):
    c, hnsg, admin = admin_client(client_for, make_tenant, make_user)
    ana = make_user("ana@hnsg.org", hnsg)
    nova = make_user("nova@hnsg.org", hnsg, verified=False)
    make_user("consultor@flash.com", None, Role.consultor)
    outro = make_user("x@hsc.org", make_tenant("hsc"))

    emails = [u["email"] for u in c.get("/api/admin/users").json()]
    assert sorted(emails) == ["admin@hnsg.org", "ana@hnsg.org", "nova@hnsg.org"]  # sem Consultor nem outro hospital
    assert len(c.get("/api/admin/users", params={"situacao": "ativo", "q": "ana"}).json()) == 1

    sessao_ana = client_for("hnsg")
    login(sessao_ana, "ana@hnsg.org")
    r = c.patch(f"/api/admin/users/{ana.id}", json={"role": "membro_comite"})
    assert r.json()["role"] == "membro_comite"
    assert sessao_ana.get("/api/auth/me").json()["role"] == "membro_comite"
    assert c.patch(f"/api/admin/users/{ana.id}", json={"status": "inativo"}).json()["status"] == "inativo"
    assert sessao_ana.get("/api/auth/me").status_code == 401  # sessão derrubada
    assert login(client_for("hnsg"), "ana@hnsg.org").status_code == 403

    assert c.patch(f"/api/admin/users/{admin.id}", json={"status": "inativo"}).status_code == 400
    assert c.patch(f"/api/admin/users/{ana.id}", json={"role": "consultor"}).status_code == 422
    assert c.patch(f"/api/admin/users/{outro.id}", json={"status": "inativo"}).status_code == 404

    assert c.post(f"/api/admin/users/{ana.id}/resend-activation").status_code == 400
    assert c.post(f"/api/admin/users/{nova.id}/resend-activation").status_code == 200
    assert outbox[-1].to == "nova@hnsg.org"
    log = owner.scalars(select(AuditLog).where(AuditLog.action == "usuario_alterado")).all()
    assert len(log) == 2 and all(a.actor_user_id == admin.id for a in log)
    owner.refresh(ana)
    assert ana.status == UserStatus.inativo


def test_consultor_administra_dentro_do_hospital(client_for, make_tenant, make_user):
    make_tenant("hnsg")
    make_user("consultor@flash.com", None, Role.consultor)
    c = client_for("hnsg")
    login(c, "consultor@flash.com")
    assert c.get("/api/admin/users").status_code == 200
    plataforma = client_for(None)
    login(plataforma, "consultor@flash.com")
    assert plataforma.get("/api/admin/users").status_code == 400  # precisa de um hospital
