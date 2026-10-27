from sqlalchemy import select

from app.classification import score, tally
from app.models import AuditLog, Campaign, Idea, IdeaStage, Role, Verdict

from .test_admin import admin_client
from .test_analysis import close_submissions, committee, send_ideas
from .test_campaigns import iso, member_client
from .test_ideas import published_campaign

C, T, NC = Verdict.classificar, Verdict.talvez, Verdict.nao_classificar


def test_regras_da_apuracao():
    assert tally([C, C, C], 3, 5, 1) == tally([C, C, C], 3, 5, 1)
    r = tally([C, C, C], 3, 5, 1)
    assert (r.outcome, r.score, r.weighted) == (IdeaStage.classificada, 100, 15)
    assert tally([C, C], 3, 5, 1).score == 67  # todos C, abaixo do quórum
    assert tally([C, C, T], 3, 5, 1).score == 70
    assert tally([C, T, T], 3, 5, 1).outcome == IdeaStage.talvez  # T ≥ C
    assert tally([C, T, T], 3, 5, 1).score == 50
    assert tally([T, T, T], 3, 5, 1).score == 20
    assert tally([C, NC, None], 3, 5, 1).outcome == IdeaStage.empate  # parecer em branco não conta
    assert tally([C, NC, NC], 3, 5, 1).outcome == IdeaStage.nao_classificada
    assert tally([C, NC, NC], 3, 5, 1).score == 0
    assert tally([], 3, 5, 1).outcome == IdeaStage.empate
    # Outros casos com Nc: (100·C − 30·T − 80·Nc) ÷ máx(total, quórum), de 5 em 5
    assert score(3, 0, 1, 3) == 55  # 220 / 4
    assert score(2, 1, 1, 3) == 25  # 90 / 4 = 22,5 → 25 (meio para cima)
    # Voto de Minerva: um parecer a mais desfaz o empate
    r = tally([C, NC], 2, 5, 1, minerva=C)
    assert (r.outcome, r.score) == (IdeaStage.classificada, 40)
    assert tally([C, NC], 2, 5, 1, minerva=NC).outcome == IdeaStage.nao_classificada


def _setup(client_for, make_tenant, make_user):
    """3 ideias, 2 avaliadores por ideia; A recebe C+C, B recebe C+Nc (empate), D recebe Nc e um em branco."""
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    cid, line = published_campaign(c)
    c.patch(f"/api/admin/campaigns/{cid}", json={"num_evaluators": 2, "cutoff_score": 70})
    ideas = send_ideas(c, client_for, make_user, hnsg, cid, line, ["a@hnsg.org", "b@hnsg.org", "d@hnsg.org"])
    close_submissions(c, cid)
    members = committee(client_for, make_user, hnsg, 2)
    assert c.post(f"/api/admin/campaigns/{cid}/distribution").status_code == 200

    def give(member, idea_id, verdict):
        board = members[member].get("/api/analysis").json()
        aid = next(card["assignment_id"] for col in board["columns"] for card in col["cards"]
                   if card["idea_id"] == idea_id)
        assert members[member].put(f"/api/analysis/{aid}", json={"verdict": verdict}).status_code == 200

    give("comite1@hnsg.org", ideas[0], "classificar")
    give("comite2@hnsg.org", ideas[0], "classificar")
    give("comite1@hnsg.org", ideas[1], "classificar")
    give("comite2@hnsg.org", ideas[1], "nao_classificar")
    give("comite1@hnsg.org", ideas[2], "nao_classificar")
    return c, hnsg, cid, ideas, members


def test_alerta_e_relatorio_de_avaliadores(client_for, make_tenant, make_user, owner, outbox):
    c, hnsg, cid, ideas, members = _setup(client_for, make_tenant, make_user)
    report = c.get("/api/dashboard/evaluators").json()
    assert report["campaign_id"] == cid and report["can_remind"] is True
    assert (report["reviews_done"], report["reviews_total"]) == (5, 6)
    first = report["evaluators"][0]  # quem tem mais pendências vem primeiro
    assert (first["name"], first["assigned"], first["evaluated"], first["pending"]) == ("Comite2", 3, 2, 1)
    assert report["evaluators"][1]["pending"] == 0
    assert report["ideas"][0]["pending_evaluators"] == ["Comite2"] and report["ideas"][0]["id"] == ideas[2]

    # Só administrador e consultor veem o relatório
    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    assert gestor.get("/api/dashboard/evaluators").status_code == 403
    assert members["comite1@hnsg.org"].post(f"/api/admin/campaigns/{cid}/reminders", json={}).status_code == 403

    outbox.clear()
    r = c.post(f"/api/admin/campaigns/{cid}/reminders", json={"message": "Faltam poucos dias!"})
    assert r.status_code == 200 and r.json() == {"sent": 1, "recipients": ["Comite2"]}
    assert len(outbox) == 1 and outbox[0].to == "comite2@hnsg.org"
    assert "1 ideia aguardando" in outbox[0].subject and "Faltam poucos dias!" in outbox[0].body
    assert "/analise" in outbox[0].body and "O prazo" in outbox[0].body
    assert c.get("/api/dashboard/evaluators").json()["evaluators"][0]["last_reminder_at"] is not None
    # Escolher só quem não tem pendência: nada a enviar
    quem_terminou = report["evaluators"][1]["id"]
    r = c.post(f"/api/admin/campaigns/{cid}/reminders", json={"evaluator_ids": [quem_terminou]})
    assert r.status_code == 422
    assert owner.scalar(select(AuditLog).where(AuditLog.action == "lembrete_avaliacao")).details["pendentes"] == 1

    # Depois do fim da análise, não há mais alerta
    c.patch(f"/api/admin/campaigns/{cid}", json={"analysis_start": iso(-0.9), "analysis_end": iso(-0.5)})
    assert c.get("/api/dashboard/evaluators").json()["can_remind"] is False
    assert c.post(f"/api/admin/campaigns/{cid}/reminders", json={}).status_code == 409


def test_apuracao_ranking_e_minerva(client_for, make_tenant, make_user, owner):
    c, hnsg, cid, ideas, members = _setup(client_for, make_tenant, make_user)

    # Durante a análise: só a prévia, e a apuração fica bloqueada
    view = c.get("/api/classification").json()
    assert "depois do fim" in view["blocker"] and view["classified_at"] is None and view["pending_reviews"] == 1
    preview = {i["id"]: i for i in view["ideas"]}
    assert preview[ideas[0]]["outcome"] == "classificada" and preview[ideas[0]]["stage"] == "em_analise"
    assert preview[ideas[1]]["outcome"] == "empate"
    assert c.post(f"/api/admin/campaigns/{cid}/classification").status_code == 422

    c.patch(f"/api/admin/campaigns/{cid}", json={"analysis_start": iso(-0.9), "analysis_end": iso(-0.5)})
    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    assert gestor.post(f"/api/admin/campaigns/{cid}/classification").status_code == 403
    assert c.get("/api/classification").json()["blocker"] is None

    r = c.post(f"/api/admin/campaigns/{cid}/classification")
    assert r.status_code == 200, r.text
    data = r.json()
    result = {i["id"]: i for i in data["ideas"]}
    assert (result[ideas[0]]["stage"], result[ideas[0]]["score"], result[ideas[0]]["rank"]) == ("classificada", 100, 1)
    assert result[ideas[0]]["above_cutoff"] is True
    assert (result[ideas[1]]["stage"], result[ideas[1]]["score"], result[ideas[1]]["rank"]) == ("empate", None, None)
    assert (result[ideas[2]]["stage"], result[ideas[2]]["score"]) == ("nao_classificada", 0)
    assert [i["id"] for i in data["ideas"]] == ideas  # classificadas, depois empate, depois não classificadas
    camp = owner.get(Campaign, cid)
    assert camp.current_phase.value == "classificacao" and camp.classified_at is not None
    assert owner.scalar(select(AuditLog).where(AuditLog.action == "classificacao_apurada")).details["empate"] == 1
    assert c.post(f"/api/admin/campaigns/{cid}/classification").status_code == 422  # só uma vez

    board = {col["key"]: col for col in gestor.get("/api/board").json()["columns"]}
    assert len(board["empate"]["cards"]) == 1 and board["classificada"]["cards"][0]["score"] == 100
    # O gestor acompanha, sem nome de avaliador nem poder de decidir
    seen = gestor.get("/api/classification").json()
    assert seen["can_manage"] is False and seen["can_minerva"] is False
    assert all(r["evaluator_name"] is None for i in seen["ideas"] for r in i["reviews"])
    # O autor não vê o empate
    autora = client_for(hnsg.slug)
    autora.post("/api/auth/login", json={"email": "b@hnsg.org", "password": "senha1234"})
    assert autora.get(f"/api/ideas/{ideas[1]}").json()["stage_label"] == "Em classificação"

    # Voto de Minerva: só o administrador, com justificativa, e só em ideia empatada
    url = f"/api/admin/campaigns/{cid}/classification/ideas/{ideas[1]}/minerva"
    make_user("consultor@flash.com", None, Role.consultor)
    consultor = client_for(hnsg.slug)
    consultor.post("/api/auth/login", json={"email": "consultor@flash.com", "password": "senha1234"})
    assert consultor.put(url, json={"verdict": "classificar", "comment": "x"}).status_code == 403
    assert c.put(url, json={"verdict": "classificar", "comment": "  "}).status_code == 422
    other = f"/api/admin/campaigns/{cid}/classification/ideas/{ideas[0]}/minerva"
    assert c.put(other, json={"verdict": "classificar", "comment": "x"}).status_code == 409
    r = c.put(url, json={"verdict": "classificar", "comment": "Alinhada à meta de segurança do paciente."})
    assert r.status_code == 200, r.text
    result = {i["id"]: i for i in r.json()["ideas"]}
    decided = result[ideas[1]]
    assert (decided["stage"], decided["score"], decided["rank"], decided["above_cutoff"]) == ("classificada", 40, 2, False)
    assert decided["minerva_verdict"] == "classificar" and decided["minerva_by"] == "Admin"
    assert owner.scalar(select(AuditLog).where(AuditLog.action == "voto_de_minerva")).details["nota"] == 40
    # Dá para rever o voto enquanto a campanha está na Classificação
    r = c.put(url, json={"verdict": "nao_classificar", "comment": "Revisto"})
    assert {i["id"]: i for i in r.json()["ideas"]}[ideas[1]]["stage"] == "nao_classificada"
    c.put(url, json={"verdict": "classificar", "comment": "Voltei atrás"})

    # Linha de corte: mudar a nota mínima muda quem fica acima
    c.patch(f"/api/admin/campaigns/{cid}", json={"cutoff_score": 40})
    assert {i["id"]: i for i in c.get("/api/classification").json()["ideas"]}[ideas[1]]["above_cutoff"] is True

    csv = c.get("/api/classification.csv").content.decode("utf-8-sig")
    lines = csv.strip().splitlines()
    assert lines[0].startswith("Posição;Nº;Título")
    assert lines[1].startswith("1;1;Ideia de a@hnsg.org") and ";Sim;" in lines[1]
    assert "Voltei atrás" in lines[2]
    assert owner.get(Idea, ideas[1]).minerva_comment == "Voltei atrás"
    assert client_for(hnsg.slug).get("/api/classification").status_code == 401
