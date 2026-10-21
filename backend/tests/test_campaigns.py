from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.campaigns import date_order_problem, youtube_id
from app.models import AuditLog, Campaign, Role

from .conftest import login
from .test_admin import admin_client

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
NOW = datetime.now(timezone.utc)


def iso(days: float) -> str:
    return (NOW + timedelta(days=days)).isoformat()


def new_campaign(c, title="2º Prêmio Ir. Lourdes", start=-1, end=10):
    r = c.post("/api/admin/campaigns", json={"title": title, "submission_start": iso(start), "submission_end": iso(end)})
    assert r.status_code == 201, r.text
    return r.json()


def member_client(client_for, make_user, tenant, role=Role.colaborador, email="ana@hnsg.org"):
    make_user(email, tenant, role)
    c = client_for(tenant.slug)
    login(c, email)
    return c


def test_campanhas_exigem_administrador(client_for, make_tenant, make_user):
    hnsg = make_tenant("hnsg")
    assert client_for("hnsg").get("/api/admin/campaigns").status_code == 401
    for role in (Role.gestor, Role.membro_comite, Role.colaborador):
        c = member_client(client_for, make_user, hnsg, role, f"{role.value}@hnsg.org")
        assert c.get("/api/admin/campaigns").status_code == 403, role
        assert c.post("/api/admin/campaigns", json={"title": "X", "submission_start": iso(0),
                                                     "submission_end": iso(1)}).status_code == 403


def test_criar_campanha_copia_regras_do_hospital(client_for, make_tenant, make_user, owner):
    c, hnsg, admin = admin_client(client_for, make_tenant, make_user)
    camp = new_campaign(c)
    assert camp["num_evaluators"] == 3 and camp["weight_classify"] == 5 and camp["cutoff_score"] == 70
    assert camp["is_published"] is False and camp["current_phase"] == "recepcao"
    assert camp["submission_state"] == "aberta" and camp["lines"] == []
    assert owner.get(Campaign, camp["id"]).created_by == admin.id
    r = c.post("/api/admin/campaigns", json={"title": "Datas trocadas", "submission_start": iso(5),
                                             "submission_end": iso(1)})
    assert r.status_code == 422
    # Data sem fuso é recusada (o navegador sempre manda com fuso)
    r = c.post("/api/admin/campaigns", json={"title": "Sem fuso", "submission_start": "2026-11-01T08:00:00",
                                             "submission_end": iso(30)})
    assert r.status_code == 422
    assert [x["title"] for x in c.get("/api/admin/campaigns").json()] == ["2º Prêmio Ir. Lourdes"]


def test_editar_datas_textos_video_e_regras(client_for, make_tenant, make_user, owner):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    cid = new_campaign(c)["id"]
    body = {
        "analysis_start": iso(11), "analysis_end": iso(20), "classification_end": iso(25), "defense_date": iso(30),
        "voting_start": iso(40), "voting_end": iso(40.5), "home_headline": "Sua ideia transforma o hospital",
        "home_text": "Participe!", "tips_text": "Seja claro.\nMostre o impacto.", "regulation_text": "1. Quem participa",
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "num_defense_finalists": 10,
        "num_voting_finalists": 5, "num_winners": 3, "cutoff_score": 60,
    }
    r = c.patch(f"/api/admin/campaigns/{cid}", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["cutoff_score"] == 60 and r.json()["tips_text"] == "Seja claro.\nMostre o impacto."

    # Datas fora de ordem, vídeo que não é do YouTube e números incoerentes são recusados com mensagem clara
    r = c.patch(f"/api/admin/campaigns/{cid}", json={"analysis_start": iso(5)})
    assert r.status_code == 422 and "início da análise" in r.json()["detail"]
    r = c.patch(f"/api/admin/campaigns/{cid}", json={"voting_end": iso(40)})
    assert r.status_code == 422 and "fechamento da votação" in r.json()["detail"]
    assert c.patch(f"/api/admin/campaigns/{cid}", json={"video_url": "https://vimeo.com/123"}).status_code == 422
    assert c.patch(f"/api/admin/campaigns/{cid}", json={"num_voting_finalists": 11}).status_code == 422
    assert c.patch(f"/api/admin/campaigns/{cid}", json={"num_winners": 6}).status_code == 422
    assert c.patch(f"/api/admin/campaigns/{cid}", json={"title": None}).status_code == 422

    # Campo vazio limpa o valor; datas opcionais podem ser apagadas
    r = c.patch(f"/api/admin/campaigns/{cid}", json={"video_url": "  ", "defense_date": None})
    assert r.status_code == 200 and r.json()["video_url"] is None and r.json()["defense_date"] is None

    actions = {a.action for a in owner.scalars(select(AuditLog))}
    assert {"campanha_criada", "campanha_alterada"} <= actions


def test_linhas_de_ideias(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    cid = new_campaign(c)["id"]
    for name in ("Segurança do paciente", "Sustentabilidade", "Experiência do paciente", "Processos", "Tecnologia"):
        assert c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": name}).status_code == 201
        if name != "Tecnologia":  # nome repetido, sem diferenciar maiúsculas
            assert c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": name.upper()}).status_code == 409
    # Máximo de 5 ativas
    r = c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Sexta"})
    assert r.status_code == 422 and "no máximo 5" in r.json()["detail"]
    lines = c.get(f"/api/admin/campaigns/{cid}").json()["lines"]
    assert [x["position"] for x in lines] == [1, 2, 3, 4, 5]

    # Desativar libera vaga; reativar com 5 ativas é recusado
    r = c.patch(f"/api/admin/campaign-lines/{lines[4]['id']}", json={"is_active": False})
    assert r.json()["active_lines"] == 4
    assert c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Inovação aberta"}).status_code == 201
    assert c.patch(f"/api/admin/campaign-lines/{lines[4]['id']}", json={"is_active": True}).status_code == 422

    assert c.patch(f"/api/admin/campaign-lines/{lines[0]['id']}", json={"name": "processos"}).status_code == 409

    # Reordenar e excluir
    all_ids = [x["id"] for x in c.get(f"/api/admin/campaigns/{cid}").json()["lines"]]
    r = c.put(f"/api/admin/campaigns/{cid}/lines/order", json={"ids": list(reversed(all_ids))})
    assert [x["id"] for x in r.json()["lines"]] == list(reversed(all_ids))
    assert c.put(f"/api/admin/campaigns/{cid}/lines/order", json={"ids": all_ids[:2]}).status_code == 422
    r = c.delete(f"/api/admin/campaign-lines/{lines[4]['id']}")
    assert r.status_code == 200 and len(r.json()["lines"]) == 5


def test_publicar_e_pagina_inicial(client_for, make_tenant, make_user):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    colaboradora = member_client(client_for, make_user, hnsg)
    assert colaboradora.get("/api/campaigns/current").json() is None

    cid = new_campaign(c)["id"]
    # Sem linha de ideias não publica
    r = c.patch(f"/api/admin/campaigns/{cid}", json={"is_published": True})
    assert r.status_code == 422 and "linha de ideias" in r.json()["detail"]
    c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Segurança do paciente", "description": "Menos riscos"})
    c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Antiga"})
    antiga = c.get(f"/api/admin/campaigns/{cid}").json()["lines"][1]["id"]
    c.patch(f"/api/admin/campaign-lines/{antiga}", json={"is_active": False})

    # Rascunho: a colaboradora não vê; o administrador pré-visualiza
    assert colaboradora.get(f"/api/campaigns/{cid}").status_code == 404
    assert c.get(f"/api/campaigns/{cid}").json()["is_published"] is False

    c.patch(f"/api/admin/campaigns/{cid}", json={"is_published": True, "video_url": "https://youtu.be/dQw4w9WgXcQ",
                                                 "voting_start": iso(40), "voting_end": iso(40.4)})
    c.post(f"/api/admin/campaigns/{cid}/banner", files={"file": ("banner.png", PNG, "image/png")})
    page = colaboradora.get("/api/campaigns/current").json()
    assert page["id"] == cid and page["submission_state"] == "aberta"
    assert page["video_embed_url"] == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert page["banner_url"].startswith("/files/tenants/hnsg/campaigns/")
    assert [x["name"] for x in page["lines"]] == ["Segurança do paciente"]  # só as ativas
    assert [p["key"] for p in page["phases"]] == ["recepcao", "analise", "classificacao", "defesa", "votacao"]

    # Campanha publicada não pode ficar sem linha ativa nem ser excluída
    seg = page["lines"][0]["id"]
    assert c.patch(f"/api/admin/campaign-lines/{seg}", json={"is_active": False}).status_code == 422
    assert c.delete(f"/api/admin/campaign-lines/{seg}").status_code == 422
    assert c.delete(f"/api/admin/campaigns/{cid}").status_code == 409


def test_periodo_de_inscricao(client_for, make_tenant, make_user, owner):
    c, hnsg, _ = admin_client(client_for, make_tenant, make_user)
    colaboradora = member_client(client_for, make_user, hnsg)
    for title, start, end in (("Futura", 5, 10), ("Encerrada", -10, -1)):
        cid = new_campaign(c, title, start, end)["id"]
        c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Geral"})
        c.patch(f"/api/admin/campaigns/{cid}", json={"is_published": True})
    states = {x["title"]: x["submission_state"] for x in c.get("/api/admin/campaigns").json()}
    assert states == {"Futura": "antes", "Encerrada": "encerrada"}
    # A página inicial mostra a mais recente que não foi encerrada
    assert colaboradora.get("/api/campaigns/current").json()["title"] == "Futura"


def test_banner_e_exclusao_de_rascunho(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    cid = new_campaign(c)["id"]
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    assert c.post(f"/api/admin/campaigns/{cid}/banner", files={"file": ("b.svg", svg)}).status_code == 422
    assert c.post(f"/api/admin/campaigns/{cid}/banner", files={"file": ("b.png", PNG)}).json()["banner_url"]
    assert c.delete(f"/api/admin/campaigns/{cid}/banner").json()["banner_url"] is None
    c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Geral"})
    assert c.delete(f"/api/admin/campaigns/{cid}").status_code == 204
    assert c.get(f"/api/admin/campaigns/{cid}").status_code == 404


def test_campanha_de_outro_hospital_nao_aparece(client_for, make_tenant, make_user):
    c, _, _ = admin_client(client_for, make_tenant, make_user)
    cid = new_campaign(c)["id"]
    lid = c.post(f"/api/admin/campaigns/{cid}/lines", json={"name": "Geral"}).json()["lines"][0]["id"]
    c.patch(f"/api/admin/campaigns/{cid}", json={"is_published": True})
    outro, hsc, _ = admin_client(client_for, make_tenant, make_user, slug="hsc")
    assert outro.get("/api/admin/campaigns").json() == []
    assert outro.get(f"/api/admin/campaigns/{cid}").status_code == 404
    assert outro.patch(f"/api/admin/campaigns/{cid}", json={"title": "Invadida"}).status_code == 404
    assert outro.patch(f"/api/admin/campaign-lines/{lid}", json={"name": "Invadida"}).status_code == 404
    assert outro.get(f"/api/campaigns/{cid}").status_code == 404
    assert outro.get("/api/campaigns/current").json() is None


def test_regras_puras():
    assert youtube_id("https://youtu.be/dQw4w9WgXcQ?si=abc") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("https://evil.com/watch?v=dQw4w9WgXcQ") is None
    assert youtube_id("javascript:alert(1)") is None
    d = lambda days: NOW + timedelta(days=days)  # noqa: E731
    assert date_order_problem({"submission_start": d(0), "submission_end": d(1), "voting_start": d(5)}) is None
    assert "defesa" in date_order_problem({"submission_end": d(10), "defense_date": d(3)})
