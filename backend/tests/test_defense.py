from sqlalchemy import select

from app.models import AuditLog, Campaign, Idea, Role

from .test_campaigns import iso, member_client
from .test_classification import _setup


def _classified(client_for, make_tenant, make_user):
    """Apuração feita: A classificada com nota 100, B classificada com 40 (Voto de Minerva), D não classificada."""
    c, hnsg, cid, ideas, members = _setup(client_for, make_tenant, make_user)
    c.patch(f"/api/admin/campaigns/{cid}", json={"analysis_start": iso(-0.9), "analysis_end": iso(-0.5)})
    assert c.post(f"/api/admin/campaigns/{cid}/classification").status_code == 200
    return c, hnsg, cid, ideas


def test_fechar_classificacao(client_for, make_tenant, make_user, owner):
    c, hnsg, cid, ideas = _classified(client_for, make_tenant, make_user)
    start = f"/api/admin/campaigns/{cid}/defense/start"

    view = c.get("/api/defense").json()
    assert "Voto de Minerva" in view["start_blocker"] and view["can_manage"] is True
    assert c.post(start, json={"idea_ids": [ideas[0]]}).status_code == 422
    c.put(f"/api/admin/campaigns/{cid}/classification/ideas/{ideas[1]}/minerva",
          json={"verdict": "classificar", "comment": "ok"})

    # Sugestão: todas as Classificadas; com a linha de corte (70), só a de nota 100; com N = 1, só a primeira
    view = c.get("/api/defense").json()
    assert view["start_blocker"] is None
    assert [(x["id"], x["suggested"]) for x in view["candidates"]] == [(ideas[0], True), (ideas[1], True)]
    c.patch(f"/api/admin/campaigns/{cid}", json={"defense_use_cutoff": True})
    assert [x["suggested"] for x in c.get("/api/defense").json()["candidates"]] == [True, False]
    c.patch(f"/api/admin/campaigns/{cid}", json={"defense_use_cutoff": False, "num_defense_finalists": 1})
    assert [x["suggested"] for x in c.get("/api/defense").json()["candidates"]] == [True, False]

    # Só o administrador fecha; só entram ideias do ranking
    make_user("consultor@flash.com", None, Role.consultor)
    consultor = client_for(hnsg.slug)
    consultor.post("/api/auth/login", json={"email": "consultor@flash.com", "password": "senha1234"})
    assert consultor.post(start, json={"idea_ids": [ideas[0]]}).status_code == 403
    assert c.post(start, json={"idea_ids": [ideas[2]]}).status_code == 422  # não classificada
    assert c.post(start, json={"idea_ids": []}).status_code == 422

    # O administrador pode incluir além da sugestão (ex.: desistência de outra)
    r = c.post(start, json={"idea_ids": [ideas[0], ideas[1]]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["current_phase"] == "defesa" and data["candidates"] == []
    assert [(i["id"], i["stage"], i["rank"]) for i in data["ideas"]] == [(ideas[0], "em_defesa", 1),
                                                                         (ideas[1], "em_defesa", 2)]
    assert owner.get(Campaign, cid).current_phase.value == "defesa"
    assert owner.scalar(select(AuditLog).where(AuditLog.action == "classificacao_fechada")).details["ideias"] == [1, 2]
    assert c.post(start, json={"idea_ids": [ideas[0]]}).status_code == 422  # já fechada
    # Fechada a Classificação, o Voto de Minerva não muda mais
    assert c.put(f"/api/admin/campaigns/{cid}/classification/ideas/{ideas[1]}/minerva",
                 json={"verdict": "nao_classificar", "comment": "x"}).status_code == 409
    board = {col["key"]: col for col in c.get("/api/board").json()["columns"]}
    assert len(board["em_defesa"]["cards"]) == 2 and len(board["nao_classificada"]["cards"]) == 1


def test_parecer_da_banca_e_fechar_defesa(client_for, make_tenant, make_user, owner):
    c, hnsg, cid, ideas = _classified(client_for, make_tenant, make_user)
    c.put(f"/api/admin/campaigns/{cid}/classification/ideas/{ideas[1]}/minerva",
          json={"verdict": "classificar", "comment": "ok"})
    close = f"/api/admin/campaigns/{cid}/defense/close"
    assert c.post(close).status_code == 422  # ainda na Classificação
    c.post(f"/api/admin/campaigns/{cid}/defense/start", json={"idea_ids": [ideas[0], ideas[1]]})
    url = lambda i: f"/api/admin/campaigns/{cid}/defense/ideas/{ideas[i]}"  # noqa: E731

    assert "Falta o parecer" in c.get("/api/defense").json()["close_blocker"]
    # Desclassificar exige motivo e comentário
    assert c.put(url(1), json={"viable": False, "comment": "Já existe"}).status_code == 422
    assert c.put(url(1), json={"viable": False, "reasons": ["projeto_em_andamento"], "comment": " "}).status_code == 422
    assert c.put(url(2), json={"viable": True}).status_code == 404  # não está na Defesa
    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    assert gestor.put(url(0), json={"viable": True}).status_code == 403

    r = c.put(url(1), json={"viable": False, "reasons": ["outro", "projeto_em_andamento", "outro"],
                            "comment": "O hospital já implanta algo igual."})
    assert r.status_code == 200, r.text
    b = {i["id"]: i for i in r.json()["ideas"]}[ideas[1]]
    assert (b["stage"], b["reasons"], b["decided_by"]) == ("desclassificada", ["projeto_em_andamento", "outro"], "Admin")
    assert "1 ideia" in r.json()["close_blocker"]
    # Corrigir o parecer é permitido até o fechamento; Viável limpa os motivos
    r = c.put(url(1), json={"viable": True, "reasons": ["outro"]})
    assert {i["id"]: i for i in r.json()["ideas"]}[ideas[1]]["reasons"] == []
    c.put(url(1), json={"viable": False, "reasons": ["viabilidade_financeira"], "comment": "Custo alto."})
    r = c.put(url(0), json={"viable": False, "reasons": ["viabilidade_tecnica"], "comment": "Sem equipe."})
    assert "Nenhuma ideia foi considerada viável" in r.json()["close_blocker"]
    assert c.post(close).status_code == 422
    c.put(url(0), json={"viable": True, "comment": "Banca unânime."})

    # O gestor acompanha, sem lançar parecer
    seen = gestor.get("/api/defense").json()
    assert seen["can_manage"] is False and seen["close_blocker"] is None
    # A autora da desclassificada vê os motivos, não o comentário; quem acompanha vê os dois
    autora = client_for(hnsg.slug)
    autora.post("/api/auth/login", json={"email": "b@hnsg.org", "password": "senha1234"})
    mine = autora.get(f"/api/ideas/{ideas[1]}").json()
    assert (mine["stage_label"], mine["defense_reasons"], mine["defense_comment"]) == (
        "Desclassificada", ["Viabilidade financeira"], None)
    assert c.get(f"/api/ideas/{ideas[1]}").json()["defense_comment"] == "Custo alto."

    r = c.post(close)
    assert r.status_code == 200, r.text
    assert r.json()["current_phase"] == "votacao"
    assert owner.get(Campaign, cid).current_phase.value == "votacao"
    assert owner.get(Idea, ideas[0]).stage.value == "shortlist"
    log = owner.scalar(select(AuditLog).where(AuditLog.action == "defesa_fechada")).details
    assert log == {"shortlist": [1], "desclassificadas": [2]}
    assert c.put(url(0), json={"viable": False, "reasons": ["outro"], "comment": "x"}).status_code == 409
    board = {col["key"]: col for col in c.get("/api/board").json()["columns"]}
    assert len(board["shortlist"]["cards"]) == 1 and len(board["desclassificada"]["cards"]) == 1
    assert owner.get(Idea, ideas[0]).defense_reasons is None and owner.get(Idea, ideas[0]).defense_comment == "Banca unânime."
