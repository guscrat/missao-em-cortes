"""_cobertura: agenda do canal e dias cobertos (tudo em tmp, nunca o state/ real)."""
from datetime import date, datetime

import pytest

import _cobertura as cob
from _eventos import upsert_bloco

AGORA = datetime(2026, 10, 22, 12, 0)


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch, banco):
    monkeypatch.setattr(cob, "CANAL_JSON", tmp_path / "canal.json")


def _canal(valor):
    cob.CANAL_JSON.write_text(f'{{"ultimo_longo": "{valor}"}}', encoding="utf-8")


def _bloco(bid, status, publish_at):
    upsert_bloco("v", bid, status=status, publish_at=publish_at, forcar_status=True)


def test_agenda_vazia():
    assert cob.agenda_canal(AGORA) == {"ultimo": None, "futuros": 0}


def test_ultimo_pega_o_maior_entre_canal_e_banco():
    _canal("2026-10-25T18:00:00-03:00")
    assert cob.agenda_canal(AGORA)["ultimo"] == date(2026, 10, 25)
    _bloco(1, "agendado", "2026-10-27T18:00:00-03:00")
    assert cob.agenda_canal(AGORA)["ultimo"] == date(2026, 10, 27)
    _canal("2026-10-30T18:00:00-03:00")
    assert cob.agenda_canal(AGORA)["ultimo"] == date(2026, 10, 30)


def test_canal_json_invalido_cai_pro_banco():
    cob.CANAL_JSON.write_text("lixo", encoding="utf-8")
    _bloco(1, "publicado", "2026-10-20T18:00:00-03:00")
    assert cob.agenda_canal(AGORA) == {"ultimo": date(2026, 10, 20), "futuros": 0}


def test_futuros_so_agendados_no_futuro():
    _bloco(1, "agendado", "2026-10-22T08:00:00-03:00")    # já saiu
    _bloco(2, "agendado", "2026-10-25T18:00:00-03:00")
    _bloco(3, "agendado", "2026-10-24T18:00:00")          # sem fuso = local
    _bloco(4, "publicado", "2026-10-30T18:00:00-03:00")   # publicado não é fila
    _bloco(5, "aprovado", "2026-10-31T18:00:00-03:00")    # status ignorado
    ag = cob.agenda_canal(AGORA)
    assert ag["futuros"] == 2 and ag["ultimo"] == date(2026, 10, 30)


def test_fuso_converte_pra_brasilia():
    _bloco(1, "agendado", "2026-10-23T01:00:00Z")         # 22/10 22:00 em Brasília
    assert cob.agenda_canal(AGORA) == {"ultimo": date(2026, 10, 22), "futuros": 1}


def test_cobertura_passado_conta_zero():
    r = cob.cobertura(0, 1, date(2026, 10, 22), {"ultimo": date(2026, 10, 10), "futuros": 0})
    assert r["dias_agendados"] == 0 and r["dias"] == 0 and r["coberto_ate"] is None


def test_cobertura_ultimo_hoje_cobre_hoje():
    r = cob.cobertura(0, 1, date(2026, 10, 22), {"ultimo": date(2026, 10, 22), "futuros": 0})
    assert r["dias"] == 0 and r["coberto_ate"] == date(2026, 10, 22)


def test_cobertura_agendados_mais_prontos():
    r = cob.cobertura(2, 1, date(2026, 10, 22), {"ultimo": date(2026, 10, 25), "futuros": 3})
    assert r["dias_agendados"] == 3 and r["dias"] == 5.0
    assert r["coberto_ate"] == date(2026, 10, 27)
    assert r["ultimo_agendado"] == date(2026, 10, 25) and r["agendados_futuros"] == 3


def test_cobertura_ceil():
    r = cob.cobertura(3, 2, date(2026, 10, 22), {"ultimo": None, "futuros": 0})
    assert r["dias"] == 1.5 and r["coberto_ate"] == date(2026, 10, 24)


def test_cobertura_nada_none():
    r = cob.cobertura(0, 1, date(2026, 10, 22), {"ultimo": None, "futuros": 0})
    assert r["coberto_ate"] is None and r["ultimo_agendado"] is None


def test_cobertura_le_agenda_do_disco_quando_omitida():
    _canal("2026-10-25T18:00:00-03:00")
    assert cob.cobertura(0, 1, date(2026, 10, 22))["dias_agendados"] == 3
