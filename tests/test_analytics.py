"""Step 17: coleta do Analytics, banco, resumo semanal, Curador, Editor e aba do painel.
Clients do Google falsos (nunca rede, nunca state/ real)."""
import importlib.util
import sqlite3
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import streamlit as st

import _editor
import _eventos

_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("analytics17", _ROOT / "scripts" / "17_analytics.py")
an = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(an)
_spec = importlib.util.spec_from_file_location("curador13", _ROOT / "scripts" / "13_curador.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)

import analytics as painel  # noqa: E402  (painel/analytics.py)

HOJE = date(2026, 10, 28)          # quarta
SEXTA = date(2026, 10, 30)


class _Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        if isinstance(self.v, Exception):
            raise self.v
        return self.v


class FakeYT:
    """Uploads do canal: lista de (id, titulo, privacidade, publicado, duracao ISO)."""
    def __init__(self, vids):
        self.vids = vids

    def channels(self):
        return self

    def playlistItems(self):
        return self

    def videos(self):
        return self

    def list(self, **kw):
        if "mine" in kw:
            return _Exec({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UP"}}}]})
        if "playlistId" in kw:
            return _Exec({"items": [{"contentDetails": {"videoId": v[0]}} for v in self.vids]})
        return _Exec({"items": [
            {"id": i, "snippet": {"title": t, "publishedAt": f"{pub}T10:00:00Z"},
             "status": {"privacyStatus": priv}, "contentDetails": {"duration": dur}}
            for i, t, priv, pub, dur in self.vids]})


VIDS = [("a", "Live A", "public", "2026-10-10", "PT20M"),
        ("b", "Live B sem view", "public", "2026-10-15", "PT10M"),
        ("p", "Privado", "private", "2026-10-01", "PT10M")]


class FakeAnalytics:
    def __init__(self, falha_impressoes=False):
        self.falha_impressoes = falha_impressoes
        self.chamadas = []

    def reports(self):
        return self

    def query(self, **kw):
        self.chamadas.append(kw)
        m, d = kw["metrics"], kw["dimensions"]
        if m.startswith("videoThumbnail"):
            if self.falha_impressoes:
                return _Exec(Exception("metrica invalida"))
            return _Exec({"rows": [["a", 1000, 0.052]]})
        if d == "video":
            return _Exec({"rows": [["a", 300, 410.55, 37.44]]})
        if d == "insightTrafficSourceType":
            return _Exec({"rows": [["YT_SEARCH", 100, 50.0], ["SUBSCRIBER", 200, 80.5]]})
        return _Exec({"rows": [["renan santos", 40], ["missão", 10]]})


def _coletar(**kw):
    an_ = FakeAnalytics(**kw)
    return an.coletar_dados(FakeYT(VIDS), an_, HOJE), an_


# --- coletar_dados -------------------------------------------------------------------

def test_coletar_ignora_privado_e_converte_ctr():
    d, _ = _coletar()
    assert [m["youtube_id"] for m in d["metricas"]] == ["a", "b"]
    a = d["metricas"][0]
    assert a["ctr_pct"] == 5.2 and a["impressoes"] == 1000
    assert a["views"] == 300 and a["retencao_pct"] == 37.4 and a["assistido_s"] == 410.6
    assert a["duracao_s"] == 1200 and d["avisos"] == []


def test_coletar_falha_de_impressoes_vira_aviso():
    d, _ = _coletar(falha_impressoes=True)
    assert len(d["avisos"]) == 1 and "impressões" in d["avisos"][0]
    a = d["metricas"][0]
    assert a["impressoes"] is None and a["ctr_pct"] is None and a["views"] == 300


def test_coletar_video_sem_view_nao_tem_trafego_nem_termos():
    d, _ = _coletar()
    b = d["metricas"][1]
    assert b["views"] == 0 and b["retencao_pct"] is None
    assert {t["youtube_id"] for t in d["trafego"]} == {"a"}
    assert {t["youtube_id"] for t in d["termos"]} == {"a"}


def test_coletar_termos_do_canal_janela_de_7_dias():
    d, an_ = _coletar()
    canal = [c for c in an_.chamadas if c["dimensions"] == "insightTrafficSourceDetail"
             and "video==" not in c["filters"]]
    assert len(canal) == 1
    assert canal[0]["startDate"] == "2026-10-21" and canal[0]["endDate"] == "2026-10-28"
    assert d["termos_canal"][0] == {"termo": "renan santos", "views": 40}
    base = an_.chamadas[0]                       # início = publicação do público mais antigo
    assert base["startDate"] == "2026-10-10" and base["filters"] == "video==a,b"


def test_coletar_sem_video_publico():
    d = an.coletar_dados(FakeYT([VIDS[2]]), FakeAnalytics(), HOJE)
    assert d["metricas"] == [] and d["avisos"] == ["nenhum vídeo público no canal"]


# --- banco ---------------------------------------------------------------------------

def test_gravar_analytics_idempotente_e_ultima_coleta(banco):
    d, _ = _coletar()
    for _i in range(2):
        _eventos.gravar_analytics(d["data"], d["metricas"], d["trafego"], d["termos"],
                                  d["termos_canal"])
    assert len(banco("SELECT * FROM metricas_video")) == 2
    assert len(banco("SELECT * FROM trafego_video")) == 2
    assert len(banco("SELECT * FROM termos_canal")) == 2
    u = _eventos.ultima_coleta()
    assert u["data"] == "2026-10-28" and len(u["metricas"]) == 2
    assert u["trafego"] == {"YT_SEARCH": 100, "SUBSCRIBER": 200}


def test_ultima_coleta_pega_o_dia_mais_recente(banco):
    m = [{"youtube_id": "a", "views": 1}]
    _eventos.gravar_analytics("2026-10-27", m, [], [], [{"termo": "velho", "views": 9}])
    _eventos.gravar_analytics("2026-10-28", m, [], [], [{"termo": "x", "views": 1},
                                                        {"termo": "y", "views": 5}])
    assert _eventos.ultima_coleta()["data"] == "2026-10-28"
    assert _eventos.termos_semana() == [{"termo": "y", "views": 5}, {"termo": "x", "views": 1}]
    assert _eventos.termos_semana(limite=1) == [{"termo": "y", "views": 5}]


def test_sem_coleta_devolve_vazio(banco):
    assert _eventos.termos_semana() == []
    assert _eventos.ultima_coleta() == {"data": None, "metricas": [], "trafego": {}}


# --- resumo semanal ------------------------------------------------------------------

def test_resumo_semanal_termos_primeiro():
    metr = [{"titulo": "Live A", "duracao_s": 1200, "impressoes": 1000, "ctr_pct": 5.0},
            {"titulo": "Short", "duracao_s": 30, "impressoes": 9999, "ctr_pct": 1.0}]
    t = an.resumo_semanal([{"termo": "renan", "views": 40}], metr,
                          {"YT_SEARCH": 100, "SUBSCRIBER": 300}, "2026-10-30")
    assert t.index("Termos de pesquisa") < t.index("De onde vieram") < t.index("Miniaturas")
    assert "1. **renan** — 40 views" in t
    assert "busca do YouTube: 100 (25%)" in t
    assert "CTR médio: 5.0% em 1000 impressões" in t     # Short fora da conta


def test_resumo_semanal_sem_termos():
    t = an.resumo_semanal([], [], {}, "2026-10-30")
    assert "nenhuma view vinda da busca" in t and "De onde vieram" not in t


def test_semanal_grava_arquivo(banco, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "SEMANAL", tmp_path / "state" / "analytics_semanal.md")
    _eventos.gravar_analytics("2026-10-28", [{"youtube_id": "a", "views": 1, "duracao_s": 900}],
                              [], [], [{"termo": "kim", "views": 3}])
    texto = an.semanal()
    assert an.SEMANAL.read_text(encoding="utf-8") == texto and "kim" in texto


def test_semanal_sem_coleta(banco, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "SEMANAL", tmp_path / "s" / "a.md")
    assert "sem coleta" in an.semanal()


# --- Curador -------------------------------------------------------------------------

class _FakeAn:
    def __init__(self, falha=None):
        self.falha, self.semanal_chamado, self.interativo = falha, False, None

    def coletar(self, interativo=True):
        self.interativo = interativo
        if self.falha:
            raise self.falha

    def semanal(self):
        self.semanal_chamado = True


def test_curador_coleta_falha_vira_aviso(banco, monkeypatch):
    fake = _FakeAn(RuntimeError("token vencido"))
    monkeypatch.setitem(sys.modules, "17_analytics", fake)
    aviso, termos = cu.coletar_analytics(SEXTA)
    assert "token vencido" in aviso and termos == [] and not fake.semanal_chamado
    assert banco("SELECT status FROM eventos WHERE etapa='17_analytics'")[0]["status"] == "falha"


def test_curador_dia_comum_nao_gera_semanal(banco, monkeypatch):
    fake = _FakeAn()
    monkeypatch.setitem(sys.modules, "17_analytics", fake)
    assert cu.coletar_analytics(HOJE) == (None, [])
    assert fake.interativo is False and not fake.semanal_chamado


def test_curador_sexta_gera_semanal_e_devolve_termos(banco, monkeypatch):
    fake = _FakeAn()
    monkeypatch.setitem(sys.modules, "17_analytics", fake)
    _eventos.gravar_analytics("2026-10-30", [{"youtube_id": "a", "views": 1}], [], [],
                              [{"termo": "kim", "views": 3}])
    aviso, termos = cu.coletar_analytics(SEXTA)
    assert aviso is None and fake.semanal_chamado and termos == [{"termo": "kim", "views": 3}]


def _rod(**kw):
    return {"quando": "x", "custo": 0, "escolhidos": [], "fila": [], "recusados": [],
            "processados": [], **kw}


@pytest.fixture
def resumo_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(cu, "RESUMO", tmp_path / "state" / "curador_resumo.md")


def test_resumo_curador_com_termos_e_aviso(resumo_tmp):
    t = cu.escrever_resumo(_rod(termos_semana=[{"termo": "renan", "views": 40}],
                                aviso_analytics="Analytics não coletado"))
    assert "## Termos de pesquisa da semana" in t and "**renan** — 40 views" in t
    assert "Analytics não coletado" in t and "## Avisos" in t


def test_resumo_curador_sem_termos(resumo_tmp):
    t = cu.escrever_resumo(_rod(termos_semana=[]))
    assert "Termos de pesquisa" not in t


# --- Editor --------------------------------------------------------------------------

def test_montar_pedido_com_e_sem_termos():
    com = _editor.montar_pedido("T", "TT", "p", "transc", [], ["renan santos", "missão 14"])
    assert "TERMOS QUE O PÚBLICO BUSCA" in com and "renan santos; missão 14" in com
    assert com.endswith("transc")
    for sem in (_editor.montar_pedido("T", "TT", "p", "transc", []),
                _editor.montar_pedido("T", "TT", "p", "transc", [], [])):
        assert "\nTERMOS QUE O PÚBLICO BUSCA" not in sem


# --- painel --------------------------------------------------------------------------

def _df_metricas():
    return pd.DataFrame([
        {"youtube_id": "a", "titulo": "Live A", "publicado": "2026-10-10T10:00:00Z", "duracao_s": 1200,
         "views": 300, "impressoes": 1000, "ctr_pct": 5.0, "retencao_pct": 40.0, "assistido_s": 400.0},
        {"youtube_id": "c", "titulo": "Live C", "publicado": "2026-10-11T10:00:00Z", "duracao_s": 900,
         "views": 100, "impressoes": 3000, "ctr_pct": 3.0, "retencao_pct": 20.0, "assistido_s": 100.0},
        {"youtube_id": "s", "titulo": "Short", "publicado": "2026-10-12T10:00:00Z", "duracao_s": 30,
         "views": 9999, "impressoes": 99999, "ctr_pct": 1.0, "retencao_pct": 90.0, "assistido_s": 20.0}])


def test_painel_resumo_ponderado_so_longos():
    r = painel.resumo(_df_metricas())
    assert r["videos"] == 2 and r["views"] == 400 and r["impressoes"] == 4000
    assert r["ctr_pct"] == pytest.approx((5 * 1000 + 3 * 3000) / 4000)
    assert r["retencao_pct"] == pytest.approx((40 * 300 + 20 * 100) / 400)


def test_painel_resumo_vazio_e_sem_impressoes():
    assert painel.resumo(pd.DataFrame())["videos"] == 0
    df = _df_metricas().assign(impressoes=None, ctr_pct=None)
    r = painel.resumo(df)
    assert r["impressoes"] is None and r["ctr_pct"] is None and r["views"] == 400


def test_painel_origens_nomes_e_ordem():
    tr = pd.DataFrame([{"origem": "SUBSCRIBER", "views": 5}, {"origem": "YT_SEARCH", "views": 7},
                       {"origem": "YT_SEARCH", "views": 3}, {"origem": "ALGO_NOVO", "views": 1}])
    s = painel.origens(tr)
    assert list(s.index) == ["busca do YouTube", "inscritos (feed/início)", "algo novo"]
    assert s.iloc[0] == 10 and painel.origens(pd.DataFrame()).empty


def test_painel_tabela_videos():
    termos = pd.DataFrame([{"youtube_id": "a", "termo": "pouco", "views": 1},
                           {"youtube_id": "a", "termo": "muito", "views": 9}])
    df = painel.tabela_videos(_df_metricas(), termos)
    assert list(df["titulo"]) == ["Short", "Live A", "Live C"]       # por views
    assert list(df["tipo"]) == ["Short", "longo", "longo"]
    linha = df[df["titulo"] == "Live A"].iloc[0]
    assert linha["termo_top"] == "muito" and linha["ctr"] == pytest.approx(0.05)
    assert pd.isna(df[df["titulo"] == "Live C"].iloc[0]["termo_top"])
    assert painel.tabela_videos(_df_metricas(), pd.DataFrame()).shape[0] == 3
    assert painel.tabela_videos(pd.DataFrame(), pd.DataFrame()).empty


def _captura(monkeypatch):
    cap = []
    monkeypatch.setattr(st, "info", lambda t, **k: cap.append(f"INFO:{t}"))
    monkeypatch.setattr(st, "markdown", lambda t, **k: cap.append(t))
    monkeypatch.setattr(st, "caption", lambda t, **k: cap.append(f"CAP:{t}"))
    monkeypatch.setattr(st, "columns", lambda *a, **k: [MagicMock(), MagicMock()])
    monkeypatch.setattr(st, "text_input", lambda *a, **k: "")
    monkeypatch.setattr(st, "dataframe", lambda df, **k: cap.append(f"DF:{len(df)}"))
    monkeypatch.setattr(painel.visual, "grade", lambda c, **k: cap.extend(c))
    monkeypatch.setattr(painel.visual, "barras", lambda s, **k: cap.append(f"BARRAS:{list(s.index)}"))
    return cap


def test_painel_render_sem_coleta(monkeypatch, tmp_path):
    cap = _captura(monkeypatch)
    painel.aba_analytics(tmp_path / "nao_existe.db")
    assert len(cap) == 1 and "Sem coleta do Analytics" in cap[0]


def test_painel_render_banco_sem_tabelas(monkeypatch, tmp_path):
    db = tmp_path / "velho.db"
    sqlite3.connect(db).close()
    cap = _captura(monkeypatch)
    painel.aba_analytics(db)
    assert "Sem coleta do Analytics" in cap[0]


def test_painel_render_com_coleta(monkeypatch, banco):
    d, _ = _coletar()
    _eventos.gravar_analytics(d["data"], d["metricas"], d["trafego"], d["termos"],
                              d["termos_canal"])
    cap = _captura(monkeypatch)
    painel.aba_analytics(_eventos.DB_PATH)
    txt = " ".join(cap)
    assert "Sem coleta" not in txt and "28/10/2026" in txt
    assert "BARRAS:['renan santos', 'missão']" in txt
    assert "BARRAS:['inscritos (feed/início)', 'busca do YouTube']" in txt
    assert "DF:2" in txt
