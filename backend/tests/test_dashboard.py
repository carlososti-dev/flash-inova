from app.models import Role

from .test_campaigns import member_client
from .test_ideas import published_campaign
from .test_voting import _in_voting


def test_comparacao_entre_campanhas(client_for, make_tenant, make_user, owner):
    c, hnsg, cid, ideas = _in_voting(client_for, make_tenant, make_user, owner)
    novo, _ = published_campaign(c, start=1, end=10)  # próximo ciclo, ainda sem ideias
    c.post("/api/admin/campaigns", json={"title": "Rascunho", "submission_start": "2027-01-01T00:00:00Z",
                                         "submission_end": "2027-02-01T00:00:00Z"})  # não publicada: fica de fora

    r = c.get("/api/dashboard/campaigns")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["eligible"] == 2  # ativos na lista de autorizados
    assert [x["id"] for x in out["campaigns"]] == [cid, novo]  # da mais antiga para a mais recente
    first, second = out["campaigns"]
    # A (C+C), B (C+Nc, Voto de Minerva) e D (Nc + em branco); A e B viáveis na Defesa
    assert (first["ideas_sent"], first["participants"], first["phase"]) == (3, 3, "votacao")
    assert (first["classified"], first["defense"], first["shortlist"], first["awarded"]) == (2, 2, 2, 0)
    assert (first["evaluators"], first["reviews_done"], first["reviews_total"]) == (2, 5, 6)
    assert first["divergence_pct"] == 50.0  # A concorda, B diverge; D tem um só parecer
    assert first["ties"] == 1
    assert first["by_line"] == [{"name": "Segurança do paciente", "count": 3}]
    assert first["submission_days"] == 2 and first["cycle_days"] is None
    assert (second["ideas_sent"], second["divergence_pct"], second["avg_score"]) == (0, None, None)

    gestor = member_client(client_for, make_user, hnsg, Role.gestor, "gestor@hnsg.org")
    assert gestor.get("/api/dashboard/campaigns").status_code == 200  # o gestor acompanha
    colaborador = member_client(client_for, make_user, hnsg, Role.colaborador, "colab@hnsg.org")
    assert colaborador.get("/api/dashboard/campaigns").status_code == 403
