import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.analysis import Evaluator, assign, evaluation_state
from app.models import Assignment, AuditLog, Campaign, Role, User

from .test_admin import admin_client
from .test_campaigns import iso, member_client
from .test_ideas import PDF, add_field, published_campaign


def send_ideas(c, client_for, make_user, hnsg, cid, line, authors):
    """Cada autor envia uma ideia; devolve os ids."""
    ids = []
    for email in authors:
        author = member_client(client_for, make_user, hnsg, email=email)
        iid = author.post("/api/ideas", json={"campaign_id": cid, "title": f"Ideia de {email}", "line_id": line,
                                              "summary": "Resumo"}).json()["id"]
        assert author.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True}).status_code == 200
        ids.append(iid)
    return ids


def close_submissions(c, cid, analysis_start=-0.5, analysis_end=5):
    r = c.patch(f"/api/admin/campaigns/{cid}", json={
        "submission_start": iso(-3), "submission_end": iso(-1), "analysis_start": iso(analysis_start),
        "analysis_end": iso(analysis_end)})
    assert r.status_code == 200, r.text


def committee(client_for, make_user, hnsg, n, first=1):
    return {f"comite{i}@hnsg.org": member_client(client_for, make_user, hnsg, Role.membro_comite,
                                                 f"comite{i}@hnsg.org") for i in range(first, first + n)}


def test_distribuicao(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    ideas = send_ideas(c, client_for, make_user, hnsg, cid, line, ["a@hnsg.org", "b@hnsg.org", "d@hnsg.org"])
    members = committee(client_for, make_user, hnsg, 4)

    # Antes do fim das inscrições: bloqueado, e o comitê não vê nada
    d = c.get(f"/api/admin/campaigns/{cid}/distribution").json()
    assert d["pending"] == 3 and d["committee"] == 4 and "fim das inscrições" in d["blocker"]
    assert c.post(f"/api/admin/campaigns/{cid}/distribution").status_code == 422
    assert members["comite1@hnsg.org"].get("/api/analysis").json()["campaign_id"] is None

    close_submissions(c, cid)
    r = c.post(f"/api/admin/campaigns/{cid}/distribution")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["pending"] == 0 and d["distributed"] == 3 and d["blocker"] is not None
    # 3 ideias × 3 avaliadores = 9 atribuições entre 4 membros: cargas 3, 2, 2, 2
    assert sorted(e["assigned"] for e in d["evaluators"]) == [2, 2, 2, 3]
    assert len(owner.scalars(select(Assignment)).all()) == 9
    assert owner.get(Campaign, cid).current_phase.value == "analise"
    assert owner.scalar(select(AuditLog).where(AuditLog.action == "distribuicao_executada")).details["ideias"] == 3

    # Administrador acompanha tudo no menu Análise: um cartão por ideia e avaliador, filtrável por avaliador
    overview = c.get("/api/analysis").json()
    assert overview["overview"] is True and len(overview["evaluators"]) == 4
    assert sum(len(col["cards"]) for col in overview["columns"]) == 9
    assert all(card["evaluator_name"] for card in overview["columns"][0]["cards"])
    first = overview["evaluators"][0]["id"]
    filtered = c.get("/api/analysis", params={"evaluator_id": first}).json()
    assert {card["evaluator_name"] for col in filtered["columns"] for card in col["cards"]} == \
        {overview["evaluators"][0]["title"]}
    # ...mas não dá parecer nem abre a tela do avaliador
    aid = overview["columns"][0]["cards"][0]["assignment_id"]
    assert c.put(f"/api/analysis/{aid}", json={"verdict": "classificar"}).status_code == 404
    # O avaliador vê só os seus, sem nome de avaliador
    own = members["comite1@hnsg.org"].get("/api/analysis").json()
    assert own["overview"] is False and own["evaluators"] == []
    assert all(card["evaluator_name"] is None for col in own["columns"] for card in col["cards"])

    # Kanban de Classificação: as ideias passam para "Em análise", com o progresso dos pareceres
    board = {col["key"]: col for col in c.get("/api/board").json()["columns"]}
    assert board["recebida"]["cards"] == [] and len(board["em_analise"]["cards"]) == 3
    assert board["em_analise"]["cards"][0]["reviews_total"] == 3
    # O autor vê "Em análise", sem saber quem avalia
    author = member_client(client_for, make_user, hnsg, email="x@hnsg.org")  # outra pessoa: não vê
    assert author.get(f"/api/ideas/{ideas[0]}").status_code == 404


def test_comite_insuficiente_e_conflito(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    c.patch(f"/api/admin/campaigns/{cid}", json={"num_evaluators": 2})
    send_ideas(c, client_for, make_user, hnsg, cid, line, ["a@hnsg.org"])
    close_submissions(c, cid)
    committee(client_for, make_user, hnsg, 1)
    d = c.get(f"/api/admin/campaigns/{cid}/distribution").json()
    assert "2 avaliadores por ideia" in d["blocker"]

    # A autora vira membro do comitê: não pode avaliar a própria ideia
    autora = owner.scalar(select(User).where(User.email == "a@hnsg.org"))
    autora.role = Role.membro_comite
    owner.commit()
    r = c.post(f"/api/admin/campaigns/{cid}/distribution")
    assert r.status_code == 422 and "autores ou coautores" in r.json()["detail"]
    committee(client_for, make_user, hnsg, 1, first=2)
    assert c.post(f"/api/admin/campaigns/{cid}/distribution").status_code == 200
    evaluators = {row.evaluator_id for row in owner.scalars(select(Assignment))}
    assert autora.id not in evaluators


def test_parecer_e_reavaliacao(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    anexo = add_field(c, cid, kind="anexo", label="Apresentação")
    c.patch(f"/api/admin/campaigns/{cid}", json={"num_evaluators": 1})
    autora = member_client(client_for, make_user, hnsg, email="a@hnsg.org")
    iid = autora.post("/api/ideas", json={"campaign_id": cid, "title": "Ideia secreta", "line_id": line,
                                          "summary": "Resumo"}).json()["id"]
    autora.post(f"/api/ideas/{iid}/files/{anexo['id']}", files={"file": ("p.pdf", PDF)})
    autora.post(f"/api/ideas/{iid}/submit", json={"accept_regulation": True})
    close_submissions(c, cid)
    ana = committee(client_for, make_user, hnsg, 1)["comite1@hnsg.org"]
    c.post(f"/api/admin/campaigns/{cid}/distribution")

    board = ana.get("/api/analysis").json()
    assert [col["key"] for col in board["columns"]] == ["para_analise", "classificadas", "nao_classificadas", "talvez"]
    card = board["columns"][0]["cards"][0]
    assert card["title"] == "Ideia secreta" and board["evaluation_state"] == "aberta"
    aid = card["assignment_id"]

    # Duplo-cego: sem autor; o anexo abre pela rota da análise
    detail = ana.get(f"/api/analysis/{aid}").json()
    assert detail["author_name"] is None and detail["coauthors"] is None and detail["can_evaluate"] is True
    assert ana.get(f"/api/analysis/{aid}/files/{anexo['id']}").content == PDF
    assert ana.get(f"/api/ideas/{iid}").status_code == 404  # a rota normal da ideia continua fechada

    # Talvez exige comentário; reavaliar e desfazer são livres no período
    r = ana.put(f"/api/analysis/{aid}", json={"verdict": "talvez", "comment": "  "})
    assert r.status_code == 422 and "Talvez" in r.json()["detail"]
    assert ana.put(f"/api/analysis/{aid}", json={"verdict": "talvez", "comment": "Detalhar custo"}).status_code == 200
    assert [len(col["cards"]) for col in ana.get("/api/analysis").json()["columns"]] == [0, 0, 0, 1]
    assert ana.put(f"/api/analysis/{aid}", json={"verdict": "classificar"}).json()["verdict"] == "classificar"
    assert [len(col["cards"]) for col in ana.get("/api/analysis").json()["columns"]] == [0, 1, 0, 0]
    r = ana.put(f"/api/analysis/{aid}", json={"verdict": None})
    assert r.json()["verdict"] is None and r.json()["evaluated_at"] is None
    ana.put(f"/api/analysis/{aid}", json={"verdict": "nao_classificar"})
    board = {col["key"]: col for col in c.get("/api/board").json()["columns"]}
    assert board["em_analise"]["cards"][0]["reviews_done"] == 1
    actions = [a.action for a in owner.scalars(select(AuditLog).order_by(AuditLog.created_at))]
    assert actions.count("parecer_registrado") == 3 and "parecer_desfeito" in actions

    # Outro membro do comitê não acessa este parecer
    outro = committee(client_for, make_user, hnsg, 1, first=2)["comite2@hnsg.org"]
    assert outro.get(f"/api/analysis/{aid}").status_code == 404
    assert outro.put(f"/api/analysis/{aid}", json={"verdict": "classificar"}).status_code == 404
    assert member_client(client_for, make_user, hnsg, email="col@hnsg.org").get("/api/analysis").status_code == 403

    # Sem duplo-cego, o avaliador vê o autor
    c.patch(f"/api/admin/campaigns/{cid}", json={"blind_review": False})
    assert ana.get(f"/api/analysis/{aid}").json()["author_name"] == "A"

    # Fim do período: só leitura
    c.patch(f"/api/admin/campaigns/{cid}", json={"analysis_start": iso(-0.9), "analysis_end": iso(-0.5)})
    detail = ana.get(f"/api/analysis/{aid}").json()
    assert detail["can_evaluate"] is False and detail["evaluation_state"] == "encerrada"
    r = ana.put(f"/api/analysis/{aid}", json={"verdict": "classificar"})
    assert r.status_code == 409 and "terminou" in r.json()["detail"]


def test_regras_puras():
    ids = [uuid.uuid4() for _ in range(4)]
    now = datetime.now(timezone.utc)
    evaluators = [Evaluator(ids[0], "Ana", 0, None), Evaluator(ids[1], "Bia", 0, now - timedelta(days=1)),
                  Evaluator(ids[2], "Caio", 1, None), Evaluator(ids[3], "Davi", 0, now)]
    ideas = [(uuid.uuid4(), set()) for _ in range(3)]
    plan = assign(ideas, evaluators, 2)
    # 1ª ideia: menor carga (0); entre elas, quem nunca recebeu (Ana), depois quem recebeu há mais tempo (Bia)
    assert plan[ideas[0][0]] == [ids[0], ids[1]]
    # 2ª: Davi (carga 0) e Caio (carga 1, nunca recebeu) antes de Ana/Bia (carga 1, receberam agora)
    assert plan[ideas[1][0]] == [ids[3], ids[2]]
    # 3ª: carga igual (1) para todos; vão primeiro os que receberam há mais tempo (Ana, Bia)
    assert plan[ideas[2][0]] == [ids[0], ids[1]]
    # Autor bloqueado
    blocked = assign([(uuid.uuid4(), {ids[0]})], [Evaluator(ids[0], "Ana", 0, None),
                                                  Evaluator(ids[1], "Bia", 5, None)], 1)
    assert list(blocked.values()) == [[ids[1]]]
    c = Campaign(analysis_start=now + timedelta(hours=1), analysis_end=None)
    assert evaluation_state(c) == "antes"
    c.analysis_start, c.analysis_end = None, now - timedelta(hours=1)
    assert evaluation_state(c) == "encerrada"
