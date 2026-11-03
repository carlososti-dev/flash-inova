import re
import uuid

from sqlalchemy import func, inspect, select

from app.models import AuditLog, AuthorizedMember, Ballot, Campaign, Idea, Role, Voter
from app.voting import Standing, email_hint, podium

from .conftest import login
from .test_campaigns import iso, member_client
from .test_defense import _classified


def _in_voting(client_for, make_tenant, make_user, owner):
    """Campanha na Votação com as ideias A (nota 100) e B (nota 40) na Shortlist; D não classificada."""
    c, hnsg, cid, ideas = _classified(client_for, make_tenant, make_user)
    c.put(f"/api/admin/campaigns/{cid}/classification/ideas/{ideas[1]}/minerva",
          json={"verdict": "classificar", "comment": "ok"})
    c.post(f"/api/admin/campaigns/{cid}/defense/start", json={"idea_ids": [ideas[0], ideas[1]]})
    for i in (0, 1):
        assert c.put(f"/api/admin/campaigns/{cid}/defense/ideas/{ideas[i]}", json={"viable": True}).status_code == 200
    assert c.post(f"/api/admin/campaigns/{cid}/defense/close").status_code == 200
    # Maria tem conta (ligada à lista de autorizados); João só está na lista
    maria = make_user("maria@hnsg.org", hnsg)
    owner.add_all([
        AuthorizedMember(tenant_id=hnsg.id, matricula="1001", name="Maria Lima", email="maria@hnsg.org", user_id=maria.id),
        AuthorizedMember(tenant_id=hnsg.id, matricula="2002", name="João Souza", email="joao@hnsg.org"),
        AuthorizedMember(tenant_id=hnsg.id, matricula="3003", name="Ex-colaborador", email="ex@hnsg.org", is_active=False),
    ])
    owner.commit()
    return c, hnsg, cid, ideas


def _open(c, cid):
    r = c.patch(f"/api/admin/campaigns/{cid}", json={"voting_start": iso(-0.1), "voting_end": iso(1)})
    assert r.status_code == 200, r.text


def _code(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)


def test_regras_do_podio():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    ordered, winners = podium([Standing(a, 5, 40, 3, 3), Standing(b, 5, 90, 1, 1), Standing(c, 7, 10, 4, 4),
                               Standing(d, 0, 100, 2, 2)], 3)
    assert [s.id for s in ordered] == [c, b, a, d]  # empate em 5 votos: vence a maior nota da Classificação
    assert winners == {c, b, a}
    # Quem não teve voto não é premiada, mesmo com vaga no pódio
    assert podium([Standing(a, 2, 0, 1, 1), Standing(b, 0, 0, 2, 2)], 3)[1] == {a}
    assert email_hint("maria.lima@hospital.org.br") == "ma•••@hospital.org.br"


def test_votacao_por_codigo_e_por_login(client_for, make_tenant, make_user, owner, outbox):
    c, hnsg, cid, ideas = _in_voting(client_for, make_tenant, make_user, owner)
    visitor = client_for(hnsg.slug)  # celular de quem leu o QR code: sem login

    page = visitor.get("/api/vote").json()
    assert (page["campaign_id"], page["state"], page["ideas"], page["voter"]) == (cid, "antes", [], None)
    assert visitor.post("/api/vote/code", json={"campaign_id": cid, "matricula": "2002"}).status_code == 409
    _open(c, cid)
    page = visitor.get(f"/api/vote?campaign_id={cid}").json()
    assert page["state"] == "aberta" and page["voter"] is None
    assert [(i["id"], i["author_name"], i["summary"]) for i in page["ideas"]] == [
        (ideas[0], "A", "Resumo"), (ideas[1], "B", "Resumo")]
    assert visitor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[0]}).status_code == 401

    # Matrícula → código por e-mail
    send = lambda m: visitor.post("/api/vote/code", json={"campaign_id": cid, "matricula": m})  # noqa: E731
    assert send("9999").status_code == 404
    assert send("3003").status_code == 404  # inativo na lista
    r = send(" 2002 ")
    assert r.status_code == 200, r.text
    assert r.json()["email_hint"] == "jo•••@hnsg.org" and outbox[-1].to == "joao@hnsg.org"
    code = _code(outbox)
    assert send("2002").status_code == 429  # pediu de novo logo em seguida
    verify = lambda m, k: visitor.post("/api/vote/verify", json={"campaign_id": cid, "matricula": m, "code": k})  # noqa: E731
    wrong = "000000" if code != "000000" else "111111"
    r = verify("2002", wrong)
    assert r.status_code == 422 and "Restam 4" in r.json()["detail"]
    assert verify("1001", code).status_code == 422  # código de outra pessoa
    r = verify("2002", code)
    assert r.status_code == 200, r.text
    assert r.json()["voter"] == {"name": "João Souza", "method": "codigo", "voted": False}
    assert verify("2002", code).status_code == 422  # código já usado

    # Vota; não pode votar de novo nem em ideia fora da Shortlist
    assert visitor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[2]}).status_code == 404
    r = visitor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[0]})
    assert r.status_code == 200, r.text
    assert r.json()["voter"]["voted"] is True
    assert visitor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]}).status_code == 409
    assert visitor.post("/api/vote/exit").status_code == 200
    assert visitor.get("/api/vote").json()["voter"] is None

    # Maria vota pelo código e depois tenta de novo pelo login: é a mesma pessoa
    send("1001")
    verify("1001", _code(outbox))
    assert visitor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]}).status_code == 200
    maria = client_for(hnsg.slug)
    login(maria, "maria@hnsg.org")
    assert maria.get("/api/vote").json()["voter"] == {"name": "Maria", "method": "login", "voted": True}
    assert maria.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[0]}).status_code == 409

    # Quem tem conta vota pelo login (o administrador também); o Consultor não é do hospital
    assert c.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]}).status_code == 200
    make_user("consultor@flash.com", None, Role.consultor)
    consultor = client_for(hnsg.slug)
    login(consultor, "consultor@flash.com")
    assert consultor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]}).status_code == 401

    # Quem votou fica registrado; em quem votou, não (a tabela de votos não tem o eleitor)
    assert owner.scalar(select(func.count()).select_from(Voter)) == 3
    assert {col.name for col in inspect(Ballot).columns} == {"id", "tenant_id", "campaign_id", "idea_id"}
    assert owner.scalar(select(func.count()).select_from(Ballot).where(Ballot.idea_id == ideas[1])) == 2

    # Muitas tentativas erradas derrubam o código
    owner.add(AuthorizedMember(tenant_id=hnsg.id, matricula="4004", name="Ana", email="ana4@hnsg.org"))
    owner.commit()
    send("4004")
    good = _code(outbox)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        verify("4004", bad)
    assert verify("4004", good).json()["detail"].startswith("Código inválido")


def test_apuracao_e_premiacao(client_for, make_tenant, make_user, owner, outbox):
    c, hnsg, cid, ideas = _in_voting(client_for, make_tenant, make_user, owner)
    close = f"/api/admin/campaigns/{cid}/voting/close"
    assert "Defina a abertura" in c.get("/api/voting").json()["close_blocker"]
    _open(c, cid)
    view = c.get("/api/voting").json()
    assert view["close_blocker"] == "Nenhum voto registrado ainda."
    assert view["vote_url"].endswith(f"/votacao?campanha={cid}&tenant=hnsg")
    assert view["qr_svg"].startswith("data:image/svg+xml")
    # Podem votar: 2 ativos na lista (a conta da Maria é a mesma pessoa) + 6 contas fora dela (admin, 3 autores, 2 do comitê)
    assert (view["eligible"], view["voters"]) == (8, 0)

    # Empate em 1 voto: A fica na frente pela nota da Classificação (100 contra 40)
    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    gestor.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]})
    c.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[0]})
    view = gestor.get("/api/voting").json()
    assert view["can_manage"] is False and view["voters"] == 2
    assert [(i["id"], i["votes"], i["position"], i["tied"], i["winner"]) for i in view["ideas"]] == [
        (ideas[0], 1, 1, True, True), (ideas[1], 1, 2, True, True)]
    assert gestor.post(close).status_code == 403

    # Um voto a mais para B: B passa à frente. Só 1 premiada nesta campanha.
    c.patch(f"/api/admin/campaigns/{cid}", json={"num_winners": 1})
    member_client(client_for, make_user, hnsg, email="x@hnsg.org").post(
        "/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]})
    r = c.post(close)  # antes do fechamento: o administrador pode encerrar
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["current_phase"], data["state"], data["close_blocker"]) == (
        "encerrada", "encerrada", "A votação desta campanha já foi apurada.")
    assert [(i["id"], i["votes"], i["award_position"], i["winner"]) for i in data["ideas"]] == [
        (ideas[1], 2, 1, True), (ideas[0], 1, None, False)]
    b, a = owner.get(Idea, ideas[1]), owner.get(Idea, ideas[0])
    assert (b.stage.value, b.award_position, b.vote_count) == ("premiada", 1, 2)
    assert (a.stage.value, a.award_position, a.vote_count) == ("shortlist", None, 1)
    assert owner.get(Campaign, cid).voting_closed_at is not None
    log = owner.scalar(select(AuditLog).where(AuditLog.action == "votacao_apurada")).details
    assert log["premiadas"] == [{"lugar": 1, "ideia": 2, "votos": 2}] and log["antes_do_fechamento"] is True
    assert c.post(close).status_code == 422

    # Depois da apuração ninguém mais vota; o kanban e a autora mostram o lugar
    late = member_client(client_for, make_user, hnsg, email="y@hnsg.org")
    assert late.post("/api/vote", json={"campaign_id": cid, "idea_id": ideas[1]}).status_code == 409
    assert late.get("/api/vote").json()["state"] == "encerrada"
    board = {col["key"]: col for col in c.get("/api/board").json()["columns"]}
    assert [(x["id"], x["award_position"], x["votes"]) for x in board["premiada"]["cards"]] == [(ideas[1], 1, 2)]
    autora = client_for(hnsg.slug)
    login(autora, "b@hnsg.org")
    assert autora.get(f"/api/ideas/{ideas[1]}").json()["stage_label"] == "Premiada · 1º lugar"
