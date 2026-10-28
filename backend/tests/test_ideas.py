from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from app.models import AuditLog, AuthorizedMember, Idea, IdeaStage, RegulationVersion, Role, utcnow

from .conftest import login
from .test_admin import admin_client
from .test_campaigns import iso, member_client, new_campaign
from .test_rls import app_session

PDF = b"%PDF-1.7\n" + b"0" * 64


def published_campaign(c, start=-1, end=10, regulation="1. Quem participa\n2. Cessão de direitos"):
    camp = new_campaign(c, start=start, end=end)
    cid = camp["id"]
    line = c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Segurança do paciente"}).json()["lines"][0]
    body = {"is_published": True}
    if regulation:
        body["regulation_text"] = regulation
    assert c.patch(f"/api/admin/campaigns/{cid}", json=body).status_code == 200
    return cid, line["id"]


def add_field(c, cid, **body):
    r = c.post(f"/api/admin/campaigns/{cid}/fields", json=body)
    assert r.status_code == 201, r.text
    return r.json()["fields"][-1]


def setup_form(c, cid):
    problema = add_field(c, cid, kind="texto_longo", label="Problema", required=True)
    setor = add_field(c, cid, kind="lista", label="Área", options=["Assistencial", "Administrativa"])
    custo = add_field(c, cid, kind="sim_nao", label="Tem custo?", required=True)
    anexo = add_field(c, cid, kind="anexo", label="Apresentação", help_text="PDF ou PowerPoint")
    return problema, setor, custo, anexo


def test_campos_do_formulario(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    cid = new_campaign(c)["id"]
    # Lista exige ao menos duas opções, sem repetir
    r = c.post(f"/api/admin/campaigns/{cid}/fields", json={"kind": "lista", "label": "Área", "options": ["Só uma"]})
    assert r.status_code == 422 and "duas opções" in r.json()["detail"]
    r = c.post(f"/api/admin/campaigns/{cid}/fields", json={"kind": "lista", "label": "Área", "options": ["A", " a "]})
    assert r.status_code == 422 and "repetida" in r.json()["detail"]
    assert c.post(f"/api/admin/campaigns/{cid}/fields", json={"kind": "foto", "label": "X"}).status_code == 422

    campos = setup_form(c, cid)
    assert [f["position"] for f in c.get(f"/api/admin/campaigns/{cid}").json()["fields"]] == [1, 2, 3, 4]
    assert campos[1]["options"] == ["Assistencial", "Administrativa"]
    assert campos[0]["options"] is None

    r = c.patch(f"/api/admin/campaign-fields/{campos[0]['id']}", json={"label": "Qual o problema?", "help_text": ""})
    assert r.json()["fields"][0]["label"] == "Qual o problema?" and r.json()["fields"][0]["help_text"] is None
    ids = [f["id"] for f in campos]
    r = c.put(f"/api/admin/campaigns/{cid}/fields/order", json={"ids": list(reversed(ids))})
    assert [f["id"] for f in r.json()["fields"]] == list(reversed(ids))
    r = c.patch(f"/api/admin/campaign-fields/{ids[1]}", json={"is_active": False})
    assert [f["is_active"] for f in r.json()["fields"] if f["id"] == ids[1]] == [False]
    r = c.delete(f"/api/admin/campaign-fields/{ids[1]}")
    assert r.status_code == 200 and len(r.json()["fields"]) == 3


def test_versoes_do_regulamento(client_for, make_tenant, make_user, owner):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    cid = new_campaign(c)["id"]
    assert c.get(f"/api/admin/campaigns/{cid}").json()["regulation_version"] is None
    c.patch(f"/api/admin/campaigns/{cid}", json={"regulation_text": "Versão A"})
    c.patch(f"/api/admin/campaigns/{cid}", json={"regulation_text": "Versão A", "home_text": "Oi"})  # mesmo texto
    assert c.get(f"/api/admin/campaigns/{cid}").json()["regulation_version"] == 1
    c.patch(f"/api/admin/campaigns/{cid}", json={"regulation_text": "Versão B"})
    assert c.get(f"/api/campaigns/{cid}").json()["regulation_version"] == 2
    assert [v.text for v in owner.scalars(select(RegulationVersion).order_by(RegulationVersion.version))] == \
        ["Versão A", "Versão B"]


def test_rascunho_envio_e_minhas_ideias(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    problema, setor, custo, _ = setup_form(c, cid)
    ana = member_client(client_for, make_user, hnsg, email="ana@hnsg.org")
    bia_user = make_user("bia@hnsg.org", hnsg)
    owner.add_all([
        AuthorizedMember(tenant_id=hnsg.id, matricula="10", name="Bia Souza", email="bia@hnsg.org", sector="UTI",
                         user_id=bia_user.id),
        AuthorizedMember(tenant_id=hnsg.id, matricula="20", name="Bruno Sem Conta", email="bruno@hnsg.org"),
        AuthorizedMember(tenant_id=hnsg.id, matricula="30", name="Beto Inativo", email="beto@hnsg.org", is_active=False),
    ])
    owner.commit()

    form = ana.get(f"/api/campaigns/{cid}/form").json()
    assert form["submission_state"] == "aberta" and form["regulation_version"] == 1
    assert [f["label"] for f in form["fields"]] == ["Problema", "Área", "Tem custo?", "Apresentação"]

    # Busca de coautores: só ativos, sem e-mail nem matrícula na resposta
    people = ana.get("/api/ideas/people", params={"q": "b"}).json()
    assert people == []
    people = ana.get("/api/ideas/people", params={"q": "br"}).json()
    assert [p["name"] for p in people] == ["Bruno Sem Conta"] and set(people[0]) == {"id", "name", "sector"}
    bia = ana.get("/api/ideas/people", params={"q": "10"}).json()[0]

    # Rascunho incompleto é aceito
    r = ana.post("/api/ideas", json={"campaign_id": cid, "title": "Checklist de alta", "coauthor_ids": [bia["id"]],
                                     "answers": {setor["id"]: "Assistencial"}})
    assert r.status_code == 201, r.text
    idea = r.json()
    assert idea["stage"] == "rascunho" and idea["number"] is None and idea["can_edit"] is True
    assert [p["name"] for p in idea["coauthors"]] == ["Bia Souza"]
    iid = idea["id"]

    # Opção que não existe na lista e resposta com tipo errado são recusadas
    r = ana.put(f"/api/ideas/{iid}", json={"title": "Checklist de alta", "answers": {setor["id"]: "Outra"}})
    assert r.status_code == 422 and "Área" in r.json()["detail"]
    r = ana.put(f"/api/ideas/{iid}", json={"title": "Checklist de alta", "answers": {custo["id"]: "talvez"}})
    assert r.status_code == 422

    # Coautora não vê o rascunho; outra pessoa nunca vê
    bia_c = client_for("hnsg")
    login(bia_c, "bia@hnsg.org")
    assert bia_c.get("/api/ideas/mine").json() == []
    assert bia_c.get(f"/api/ideas/{iid}").status_code == 404

    # Envio: exige aceite e campos obrigatórios
    r = ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": False})
    assert r.status_code == 422 and "regulamento" in r.json()["detail"]
    r = ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True})
    assert r.status_code == 422
    assert "Linha de ideias" in r.json()["detail"] and "Resumo" in r.json()["detail"]
    assert "Problema" in r.json()["detail"] and "Tem custo?" in r.json()["detail"] and "Área" not in r.json()["detail"]

    full = {"title": "Checklist de alta segura", "line_id": line, "summary": "Reduz reinternações.",
            "coauthor_ids": [bia["id"]], "answers": {problema["id"]: "Altas sem orientação", custo["id"]: False,
                                                     setor["id"]: "Assistencial"}}
    assert ana.put(f"/api/ideas/{iid}", json=full).status_code == 200
    r = ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True})
    assert r.status_code == 200, r.text
    sent = r.json()
    assert sent["stage"] == "recebida" and sent["number"] == 1 and sent["regulation_version"] == 1
    assert sent["regulation_accepted_at"] and sent["can_edit"] is True
    assert ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True}).status_code == 409

    log = owner.scalar(select(AuditLog).where(AuditLog.action == "ideia_enviada"))
    assert log.details["regulamento_versao"] == 1 and log.details["numero"] == 1
    stored = owner.get(Idea, iid)
    assert owner.get(RegulationVersion, stored.regulation_version_id).text.startswith("1. Quem participa")

    # Ideia enviada pode ser editada, mas não pode ficar incompleta
    r = ana.put(f"/api/ideas/{iid}", json=full | {"summary": "  "})
    assert r.status_code == 422 and "Resumo" in r.json()["detail"]
    r = ana.put(f"/api/ideas/{iid}", json=full | {"title": "Checklist de alta segura 2.0"})
    assert r.status_code == 200 and r.json()["stage"] == "recebida"
    assert ana.delete(f"/api/ideas/{iid}").status_code == 409  # enviada não se exclui

    # Coautora vê a ideia enviada, mas não edita
    mine = bia_c.get("/api/ideas/mine").json()
    assert [(i["title"], i["role"], i["can_edit"]) for i in mine] == [("Checklist de alta segura 2.0", "coautor", False)]
    assert bia_c.put(f"/api/ideas/{iid}", json=full).status_code == 403

    # Segunda ideia recebe o número 2; rascunho pode ser excluído
    second = ana.post("/api/ideas", json=full | {"campaign_id": cid, "title": "Outra ideia"}).json()
    assert ana.post(f"/api/ideas/{second['id']}/submit", json={"accept_regulation": True}).json()["number"] == 2
    draft = ana.post("/api/ideas", json={"campaign_id": cid, "title": "Rascunho"}).json()
    assert [i["stage_label"] for i in ana.get("/api/ideas/mine").json()] == ["Rascunho", "Recebida", "Recebida"]
    assert ana.delete(f"/api/ideas/{draft['id']}").status_code == 204

    # Coautor inativo, a própria autora e linha de outra campanha são recusados
    beto = owner.scalar(select(AuthorizedMember).where(AuthorizedMember.matricula == "30"))
    assert ana.put(f"/api/ideas/{iid}", json=full | {"coauthor_ids": [str(beto.id)]}).status_code == 422
    other_cid, other_line = published_campaign(c)
    assert ana.put(f"/api/ideas/{iid}", json=full | {"line_id": other_line}).status_code == 422


def test_periodo_de_inscricao(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    ana = member_client(client_for, make_user, hnsg)
    full = lambda line: {"title": "Ideia", "line_id": line, "summary": "Resumo"}  # noqa: E731

    # Antes de abrir: dá para guardar rascunho, não para enviar
    futura, line = published_campaign(c, start=2, end=10)
    iid = ana.post("/api/ideas", json=full(line) | {"campaign_id": futura}).json()["id"]
    r = ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True})
    assert r.status_code == 409 and "período de inscrição" in r.json()["detail"]

    # Campanha sem regulamento não recebe envio
    sem_reg, line2 = published_campaign(c, regulation=None)
    iid2 = ana.post("/api/ideas", json=full(line2) | {"campaign_id": sem_reg}).json()["id"]
    r = ana.post(f"/api/ideas/{iid2}/submit", json={"accept_regulation": True})
    assert r.status_code == 422 and "regulamento" in r.json()["detail"]

    # Depois do fim: nada muda
    aberta, line3 = published_campaign(c)
    iid3 = ana.post("/api/ideas", json=full(line3) | {"campaign_id": aberta}).json()["id"]
    assert ana.post(f"/api/ideas/{iid3}/submit", json={"accept_regulation": True}).status_code == 200
    c.patch(f"/api/admin/campaigns/{aberta}", json={"submission_start": iso(-10), "submission_end": iso(-1)})
    assert ana.put(f"/api/ideas/{iid3}", json=full(line3)).status_code == 409
    assert ana.get(f"/api/ideas/{iid3}").json()["can_edit"] is False
    assert ana.post("/api/ideas", json=full(line3) | {"campaign_id": aberta}).status_code == 409

    # Rascunho de campanha não publicada: a campanha não existe para quem envia
    rascunho = new_campaign(c)["id"]
    assert ana.post("/api/ideas", json={"campaign_id": rascunho, "title": "X" * 5}).status_code == 404


def test_anexos(client_for, make_tenant, make_user):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    anexo = add_field(c, cid, kind="anexo", label="Apresentação", required=True)
    ana = member_client(client_for, make_user, hnsg)
    outra = member_client(client_for, make_user, hnsg, email="outra@hnsg.org")
    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    iid = ana.post("/api/ideas", json={"campaign_id": cid, "title": "Ideia com anexo", "line_id": line,
                                       "summary": "Resumo"}).json()["id"]
    url = f"/api/ideas/{iid}/files/{anexo['id']}"

    assert ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True}).status_code == 422
    assert ana.post(url, files={"file": ("x.html", b"<script>alert(1)</script>")}).status_code == 422
    assert ana.post(url, files={"file": ("planilha.docx", b"PK\x03\x04" + b"0" * 20)}).status_code == 200
    r = ana.post(url, files={"file": ("C:\\Users\\ana\\proposta.pdf", PDF)})
    assert r.status_code == 200
    assert r.json()["answers"][0]["file_name"] == "proposta.pdf" and r.json()["answers"][0]["file_size"] == len(PDF)

    # Rascunho: só a autora baixa
    assert gestor.get(url).status_code == 404 and outra.get(url).status_code == 404
    got = ana.get(url)
    assert got.status_code == 200 and got.content == PDF and "attachment" in got.headers["content-disposition"]

    assert ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True}).status_code == 200
    assert gestor.get(url).status_code == 200 and outra.get(url).status_code == 404
    # Anexo obrigatório de ideia enviada só pode ser trocado, não removido
    assert ana.delete(url).status_code == 422
    assert outra.post(url, files={"file": ("x.pdf", PDF)}).status_code == 404


def test_kanban(client_for, make_tenant, make_user):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    ana = member_client(client_for, make_user, hnsg)
    body = {"campaign_id": cid, "title": "Ideia enviada", "line_id": line, "summary": "Resumo"}
    iid = ana.post("/api/ideas", json=body).json()["id"]
    ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True})
    ana.post("/api/ideas", json=body | {"title": "Só rascunho"})

    for role in (Role.colaborador, Role.membro_comite):
        other = member_client(client_for, make_user, hnsg, role, f"{role.value}@hnsg.org")
        assert other.get("/api/board").status_code == 403
    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    for client in (c, gestor):
        board = client.get("/api/board").json()
        assert board["campaign_id"] == cid
        columns = {col["key"]: col for col in board["columns"]}
        assert list(columns)[:3] == ["recebida", "em_analise", "empate"] and len(columns) == 10
        assert [(x["number"], x["title"], x["line_name"], x["author_name"]) for x in columns["recebida"]["cards"]] == \
            [(1, "Ideia enviada", "Segurança do paciente", "Ana")]
        assert sum(len(col["cards"]) for col in board["columns"]) == 1
    # O gestor abre a ideia enviada (sem editar)
    detail = gestor.get(f"/api/ideas/{iid}").json()
    assert detail["role"] == "acompanha" and detail["can_edit"] is False and detail["author_name"] == "Ana"

    # Campanha com ideias não volta a rascunho; linha com ideias não pode ser excluída
    r = c.patch(f"/api/admin/campaigns/{cid}", json={"is_published": False})
    assert r.status_code == 422 and "ideias" in r.json()["detail"]
    assert c.delete(f"/api/admin/campaigns/{cid}").status_code == 409
    c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Outra"})
    assert c.delete(f"/api/admin/campaign-lines/{line}").status_code == 409


def test_campo_com_respostas_so_desativa(client_for, make_tenant, make_user):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    campo = add_field(c, cid, kind="texto_curto", label="Setor envolvido")
    ana = member_client(client_for, make_user, hnsg)
    ana.post("/api/ideas", json={"campaign_id": cid, "title": "Ideia", "answers": {campo["id"]: "UTI"}})
    assert c.get(f"/api/admin/campaigns/{cid}").json()["fields"][0]["answers"] == 1
    r = c.delete(f"/api/admin/campaign-fields/{campo['id']}")
    assert r.status_code == 409 and "desative" in r.json()["detail"]
    c.patch(f"/api/admin/campaign-fields/{campo['id']}", json={"is_active": False})
    assert ana.get(f"/api/campaigns/{cid}/form").json()["fields"] == []


def test_ideia_de_outro_hospital(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    ana = member_client(client_for, make_user, hnsg)
    iid = ana.post("/api/ideas", json={"campaign_id": cid, "title": "Ideia", "line_id": line,
                                       "summary": "Resumo"}).json()["id"]
    ana.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True})
    outro, hsc, _ = admin_client(client_for, make_tenant, make_user, slug="hsc")
    assert outro.get(f"/api/ideas/{iid}").status_code == 404
    assert outro.post("/api/ideas", json={"campaign_id": cid, "title": "Invasão"}).status_code == 404
    assert outro.get("/api/board").json()["columns"][0]["cards"] == []

    # No banco: o RLS esconde e recusa ideias de outro hospital
    with app_session(hsc.id) as s:
        assert s.scalars(select(Idea)).all() == []
        s.add(Idea(tenant_id=hnsg.id, campaign_id=cid, author_id=owner.get(Idea, iid).author_id, title="Intrusa",
                   stage=IdeaStage.rascunho, created_at=utcnow() - timedelta(seconds=1)))
        with pytest.raises(ProgrammingError, match="row-level security"):
            s.commit()
