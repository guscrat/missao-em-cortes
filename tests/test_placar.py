"""Step 15: placar do canal. Clients do Google falsos (nunca rede, nunca state/ real)."""
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "placar", Path(__file__).parent.parent / "scripts" / "15_placar.py")
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)

HOJE = date(2026, 10, 23)


class _Exec:
    def __init__(self, valor):
        self.valor = valor

    def execute(self):
        if isinstance(self.valor, Exception):
            raise self.valor
        return self.valor


class FakeYT:
    def __init__(self, subs="1234"):
        self.subs = subs

    def channels(self):
        return self

    def list(self, **kw):
        self.kw = kw
        return _Exec({"items": [{"statistics": {"subscriberCount": self.subs}}]})


class FakeAnalytics:
    def __init__(self, minutos, views):
        self.respostas = {"estimatedMinutesWatched": minutos, "views": views}
        self.chamadas = []

    def reports(self):
        return self

    def query(self, **kw):
        self.chamadas.append(kw)
        return _Exec({"rows": self.respostas[kw["metrics"]]})


@pytest.mark.parametrize("tipo,esperado", [
    ("shorts", True), ("SHORTS", True), ("videoOnDemand", False),
    ("VIDEO_ON_DEMAND", False), ("liveStream", False)])
def test_e_short(tipo, esperado):
    assert pl.e_short(tipo) is esperado


@pytest.mark.parametrize("longo,short", [("videoOnDemand", "shorts"),
                                         ("VIDEO_ON_DEMAND", "SHORTS")])
def test_medir_horas_sem_shorts_e_views_so_de_shorts(longo, short):
    an = FakeAnalytics([[longo, 6000], ["liveStream", 600], [short, 99999]],
                       [[longo, 500], [short, 7000]])
    r = pl.medir(FakeYT("42"), an, HOJE)
    assert r["inscritos"] == 42
    assert r["horas_12m"] == 110.0          # (6000 + 600) / 60, Shorts fora
    assert r["views_shorts_90d"] == 7000
    assert "atualizado" in r


def test_medir_views_maiusculo():
    an = FakeAnalytics([["VIDEO_ON_DEMAND", 60]], [["VIDEO_ON_DEMAND", 5], ["SHORTS", 123]])
    r = pl.medir(FakeYT(), an, HOJE)
    assert r["views_shorts_90d"] == 123 and r["horas_12m"] == 1.0


def test_medir_datas_365_e_90_dias():
    an = FakeAnalytics([], [])
    pl.medir(FakeYT(), an, HOJE)
    por_metrica = {c["metrics"]: c for c in an.chamadas}
    m, v = por_metrica["estimatedMinutesWatched"], por_metrica["views"]
    assert (m["startDate"], m["endDate"]) == ("2025-10-23", "2026-10-23")
    assert (v["startDate"], v["endDate"]) == ("2026-07-25", "2026-10-23")
    assert m["dimensions"] == v["dimensions"] == "creatorContentType"
    assert m["ids"] == "channel==MINE"


def test_medir_sem_linhas_zera():
    r = pl.medir(FakeYT(), FakeAnalytics([], []), HOJE)
    assert r["horas_12m"] == 0 and r["views_shorts_90d"] == 0


def test_atualizar_grava_arquivo_e_evento(tmp_path, monkeypatch, banco):
    import sys
    import types
    destino = tmp_path / "state" / "placar.json"
    monkeypatch.setattr(pl, "SAIDA", destino)
    visto = {}
    monkeypatch.setattr(pl, "credenciais",
                        lambda esc, tok, cs, interativo: visto.update(interativo=interativo) or "creds")
    an = FakeAnalytics([["videoOnDemand", 120]], [["shorts", 10]])
    yt = FakeYT("7")
    build = lambda nome, ver, **kw: yt if nome == "youtube" else an  # noqa: E731
    for mod in ("googleapiclient", "googleapiclient.discovery"):
        monkeypatch.setitem(sys.modules, mod, types.ModuleType(mod))
    sys.modules["googleapiclient.discovery"].build = build
    p = pl.atualizar(interativo=False)
    assert visto["interativo"] is False
    gravado = json.loads(destino.read_text(encoding="utf-8"))
    assert gravado == p
    assert (gravado["inscritos"], gravado["horas_12m"], gravado["views_shorts_90d"]) == (7, 2.0, 10)
    ev = banco("SELECT status, agente, etapa FROM eventos")
    assert ev == [{"status": "ok", "agente": "analista", "etapa": "15_placar"}]


def test_main_excecao_vira_falha_e_preserva_arquivo(tmp_path, monkeypatch, banco, capsys):
    destino = tmp_path / "placar.json"
    destino.write_text('{"inscritos": 1}', encoding="utf-8")
    monkeypatch.setattr(pl, "SAIDA", destino)

    def quebra(interativo=True):
        raise RuntimeError("token expirado")
    monkeypatch.setattr(pl, "atualizar", quebra)
    assert pl.main([]) == 1
    assert destino.read_text(encoding="utf-8") == '{"inscritos": 1}'
    ev = banco("SELECT status, agente, mensagem FROM eventos")
    assert ev[0]["status"] == "falha" and ev[0]["agente"] == "analista"
    assert "token expirado" in ev[0]["mensagem"]


def test_main_ok_retorna_zero(monkeypatch, capsys):
    monkeypatch.setattr(pl, "atualizar", lambda interativo=True: {
        "inscritos": 1, "horas_12m": 2.0, "views_shorts_90d": 3})
    assert pl.main([]) == 0
    assert "1 inscritos" in capsys.readouterr().out
