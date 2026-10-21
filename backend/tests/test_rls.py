"""O banco recusa dados de outro hospital mesmo se a aplicação esquecer um filtro."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.db import get_sessionmaker
from app.models import AuditLog, Campaign, Role, User, utcnow


def app_session(tenant_id=None, all_tenants=False):
    s = get_sessionmaker()()
    s.info["tenant_id"] = tenant_id
    s.info["all_tenants"] = all_tenants
    return s


def test_usuario_da_aplicacao_nao_e_superusuario():
    with app_session() as s:
        assert s.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")) is False


def test_consulta_sem_filtro_so_ve_o_proprio_hospital(make_tenant, make_user):
    hnsg, hsc = make_tenant("hnsg"), make_tenant("hsc")
    make_user("ana@hnsg.org", hnsg)
    make_user("bia@hsc.org", hsc)
    make_user("consultor@flash.com", None, Role.consultor)
    with app_session(hnsg.id) as s:
        emails = set(s.scalars(select(User.email)))
    assert emails == {"ana@hnsg.org", "consultor@flash.com"}
    with app_session(None) as s:
        assert set(s.scalars(select(User.email))) == {"consultor@flash.com"}
    with app_session(None, all_tenants=True) as s:
        assert len(s.scalars(select(User.email)).all()) == 3


def test_nao_grava_usuario_em_outro_hospital(make_tenant):
    hnsg, hsc = make_tenant("hnsg"), make_tenant("hsc")
    with app_session(hnsg.id) as s:
        s.add(User(tenant_id=hsc.id, role=Role.colaborador, name="Intrusa", email="x@hsc.org"))
        with pytest.raises(ProgrammingError, match="row-level security"):
            s.commit()


def test_nao_altera_usuario_de_outro_hospital(make_tenant, make_user, owner):
    hnsg, hsc = make_tenant("hnsg"), make_tenant("hsc")
    bia = make_user("bia@hsc.org", hsc)
    with app_session(hnsg.id) as s:
        s.execute(text("UPDATE users SET name = 'Alterado' WHERE id = :id"), {"id": bia.id})
        s.commit()
    owner.expire_all()
    assert owner.get(User, bia.id).name != "Alterado"


def test_auditoria_isolada(make_tenant, owner):
    hnsg, hsc = make_tenant("hnsg"), make_tenant("hsc")
    owner.add_all([AuditLog(id=uuid.uuid4(), tenant_id=t.id, action="x", created_at=utcnow()) for t in (hnsg, hsc)])
    owner.commit()
    with app_session(hnsg.id) as s:
        assert {a.tenant_id for a in s.scalars(select(AuditLog))} == {hnsg.id}


def test_campanhas_isoladas(make_tenant, owner):
    hnsg, hsc = make_tenant("hnsg"), make_tenant("hsc")
    now = utcnow()
    owner.add_all([Campaign(tenant_id=t.id, title=f"Campanha {t.slug}", submission_start=now,
                            submission_end=now + timedelta(days=1), num_evaluators=3, weight_classify=5,
                            weight_maybe=1, cutoff_score=70) for t in (hnsg, hsc)])
    owner.commit()
    with app_session(hnsg.id) as s:
        assert set(s.scalars(select(Campaign.title))) == {"Campanha hnsg"}
        s.add(Campaign(tenant_id=hsc.id, title="Intrusa", submission_start=now, submission_end=now + timedelta(days=1),
                       num_evaluators=3, weight_classify=5, weight_maybe=1, cutoff_score=70))
        with pytest.raises(ProgrammingError, match="row-level security"):
            s.commit()
