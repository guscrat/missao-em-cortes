"""Diagnóstico do canal na aba Analytics (painel/analytics.py): contas puras, leitura e render."""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent / "painel"))
import analytics as pa  # noqa: E402
import _eventos  # noqa: E402

COLS = ["data", "youtube_id", "views"]


def _hist(*linhas):
    """linhas: (data, youtube_id, views)."""
    return pd.DataFrame(list(linhas), columns=COLS)


# --- views_semana --------------------------------------------------------------------

def test_views_semana_diferenca_de_acumulado():
    h = _hist(("2026-10-14", "a", 10), ("2026-10-21", "a", 30), ("2026-10-28", "a", 100))
    assert pa.views_semana(h, "2026-10-28") == (70, 20)


def test_views_semana_video_novo_conta_do_zero():
    h = _hist(("2026-10-14", "a", 10), ("2026-10-21", "a", 30), ("2026-10-28", "a", 40),
              ("2026-10-28", "novo", 25))
    atual, antes = pa.views_semana(h, "2026-10-28")
    assert atual == 10 + 25 and antes == 20


def test_views_semana_sem_coleta_antiga_none():
    assert pa.views_semana(_hist(("2026-10-28", "a", 40)), "2026-10-28") == (None, None)
    h2 = _hist(("2026-10-21", "a", 30), ("2026-10-28", "a", 40))
    assert pa.views_semana(h2, "2026-10-28") == (10, None)
    assert pa.views_semana(pd.DataFrame(columns=COLS), "2026-10-28") == (None, None)


def test_views_semana_usa_coleta_mais_recente_ate_o_dia():
    h = _hist(("2026-10-20", "a", 30), ("2026-10-28", "a", 40))   # sem coleta exata de 21/10
    assert pa.views_semana(h, "2026-10-28")[0] == 10


# --- views_por_dia -------------------------------------------------------------------

def test_views_por_dia_pula_buraco_de_coleta():
    h = _hist(("2026-10-01", "a", 10), ("2026-10-02", "a", 15),
              ("2026-10-05", "a", 100), ("2026-10-06", "a", 108))
    s = pa.views_por_dia(h)
    assert list(s.index) == ["02/10", "06/10"] and list(s) == [5, 8]


def test_views_por_dia_vazio_limite_e_negativo():
    assert pa.views_por_dia(pd.DataFrame(columns=COLS)).empty
    assert pa.views_por_dia(_hist(("2026-10-01", "a", 10))).empty
    h = _hist(*[(f"2026-10-{d:02d}", "a", d * 10) for d in range(1, 8)])
    assert len(pa.views_por_dia(h, dias=3)) == 3
    assert list(pa.views_por_dia(_hist(("2026-10-01", "a", 10), ("2026-10-02", "a", 4)))) == [0]


# --- concentracao --------------------------------------------------------------------

def test_concentracao_vazia_e_sem_views():
    assert pa.concentracao(pd.DataFrame()) is None
    assert pa.concentracao(pd.DataFrame([{"titulo": "x", "views": 0}])) is None
    assert pa.concentracao(pd.DataFrame([{"titulo": "x", "views": None}])) is None


def test_concentracao_top():
    m = pd.DataFrame([{"titulo": "A", "views": 75}, {"titulo": "B", "views": 25}])
    frac, tit = pa.concentracao(m)
    assert frac == pytest.approx(0.75) and tit == "A"


# --- publicados_por_semana -----------------------------------------------------------

AGORA = pd.Timestamp("2026-11-10 12:00", tz="America/Sao_Paulo")


def _pub(*iso):
    return pd.DataFrame({"publish_at": list(iso)})


def test_publicados_agendado_futuro_nao_conta():
    p = pa.publicados_por_semana(_pub("2026-11-09T20:00:00Z", "2026-11-15T20:00:00Z"), AGORA)
    assert p.iloc[-1] == 1 and p.sum() == 1


def test_publicados_fuso_naive_e_sao_paulo():
    naive = pd.Timestamp("2026-11-10 12:00")          # 12:00 SP = 15:00 UTC
    a = pa.publicados_por_semana(_pub("2026-11-09T20:00:00Z"), naive)
    b = pa.publicados_por_semana(_pub("2026-11-09T20:00:00Z"), AGORA)
    assert list(a.index) == list(b.index) and list(a) == list(b)
    assert pa.publicados_por_semana(_pub("2026-11-10T16:00:00Z"), naive).sum() == 0   # futuro
    assert pa.publicados_por_semana(_pub("2026-11-10T14:00:00Z"), naive).sum() == 1
    assert a.index[-1] == "03/11"                      # rótulo no fuso de SP


def test_publicados_corta_semanas_zeradas_iniciais_mas_mantem_ultimas_duas():
    p = pa.publicados_por_semana(_pub("2026-10-28T20:00:00Z"), AGORA)
    assert len(p) == 2 and list(p) == [1, 0]
    assert list(pa.publicados_por_semana(pd.DataFrame(), AGORA)) == [0, 0]
    antigos = _pub(*[(AGORA.tz_convert("UTC") - pd.Timedelta(days=7 * i + 1)).isoformat()
                     for i in range(8)])
    assert len(pa.publicados_por_semana(antigos, AGORA)) == 8


# --- leitura -------------------------------------------------------------------------

def _d(**kw):
    base = {"data": "2026-11-10", "dias_coleta": 0, "views_semana": None, "views_semana_antes": None,
            "busca": None, "busca_antes": None, "concentracao": None,
            "longos_semana": pa.LONGOS_MIN_SEMANA, "longos_semana_antes": None,
            "novos_n": 0, "novos_media": None, "novos_media_antes": None,
            "faixas": pd.DataFrame()}
    base.update(kw)
    return base


def _tons(d):
    return [t for t, _ in pa.leitura(d)]


def test_leitura_neutra_sem_frases():
    assert pa.leitura(_d()) == []


def test_leitura_coleta_velha():
    assert _tons(_d(dias_coleta=pa.DIAS_COLETA_VELHA)) == []
    f = pa.leitura(_d(dias_coleta=pa.DIAS_COLETA_VELHA + 1, data="2026-11-08"))
    assert f[0][0] == "erro" and "08/11" in f[0][1]


def test_leitura_poucos_longos():
    assert _tons(_d(longos_semana=pa.LONGOS_MIN_SEMANA)) == []
    f = pa.leitura(_d(longos_semana=pa.LONGOS_MIN_SEMANA - 1, longos_semana_antes=7))
    assert f[0][0] == "alerta" and "semana anterior: 7" in f[0][1]


def test_leitura_variacao_de_views():
    assert _tons(_d(views_semana=81, views_semana_antes=100)) == []        # -19%
    assert _tons(_d(views_semana=119, views_semana_antes=100)) == []       # +19%
    assert _tons(_d(views_semana=80, views_semana_antes=100)) == ["alerta"]
    assert _tons(_d(views_semana=120, views_semana_antes=100)) == ["ok"]
    assert _tons(_d(views_semana=50, views_semana_antes=0)) == []          # sem base
    assert _tons(_d(views_semana=50, views_semana_antes=None)) == []


def test_leitura_concentracao():
    assert _tons(_d(concentracao=(0.49, "T"))) == []
    f = pa.leitura(_d(concentracao=(0.5, "Título X")))
    assert f[0][0] == "alerta" and "Título X" in f[0][1]


def test_leitura_fora_da_busca():
    assert _tons(_d(busca={"fora_pct": 25.0, "recomendacao_pct": 10})) == []
    f = pa.leitura(_d(busca={"fora_pct": 24.9, "recomendacao_pct": 10}))
    assert f[0][0] == "" and "25%" in f[0][1]


def _faixas(*linhas):
    return pd.DataFrame(linhas, columns=["faixa", "n", "views", "min_por_view", "retencao"])


def test_leitura_faixas():
    dois = _faixas(("curto 3-10 min", 3, 100, 2.0, 0.40), ("médio 10-20 min", 3, 100, 5.0, 0.30),
                   ("todos", 6, 200, 3.5, 0.35))
    f = pa.leitura(_d(faixas=dois))
    assert len(f) == 1 and "curto 3-10 min" in f[0][1] and "médio 10-20 min" in f[0][1]
    mesma = _faixas(("curto 3-10 min", 3, 100, 5.0, 0.40), ("médio 10-20 min", 3, 100, 2.0, 0.30))
    assert pa.leitura(_d(faixas=mesma))[0][1].endswith("retenção).")
    pouca = _faixas(("curto 3-10 min", pa.MIN_VIDEOS_FAIXA - 1, 100, 2.0, 0.4),
                    ("médio 10-20 min", 3, 100, 5.0, 0.3))
    assert pa.leitura(_d(faixas=pouca)) == []          # sobra uma só: sem comparação


def test_leitura_novos():
    f = pa.leitura(_d(novos_media=12.5, novos_n=4, novos_media_antes=10.0))
    assert f[0][0] == "" and "12,5" in f[0][1] and "10,0" in f[0][1]
    assert "semanas antes" not in pa.leitura(_d(novos_media=12.5, novos_n=4))[0][1]


# --- tabela_faixas -------------------------------------------------------------------

def test_tabela_faixas():
    assert pa.tabela_faixas(pd.DataFrame()).empty
    m = pd.DataFrame([{"duracao_s": 300, "views": 10, "assistido_s": 120.0, "retencao_pct": 40.0}])
    t = pa.tabela_faixas(m)
    assert list(t["faixa"]) == ["curto 3-10 min", "todos"]
    assert t.iloc[0]["retencao"] == pytest.approx(0.4)


# --- carregar / render ---------------------------------------------------------------

def _gravar(data="2026-11-10"):
    met = [{"youtube_id": "a", "titulo": "Live A", "publicado": "2026-10-10T10:00:00Z",
            "duracao_s": 1200, "views": 300, "impressoes": 1000, "ctr_pct": 5.0,
            "retencao_pct": 40.0, "assistido_s": 400.0}]
    tr = [{"youtube_id": "a", "origem": "YT_SEARCH", "views": 5, "minutos": 1.0}]
    _eventos.gravar_analytics(data, met, tr, [{"youtube_id": "a", "termo": "x", "views": 2}],
                              [{"termo": "x", "views": 2}], [{"origem": "YT_SEARCH", "views": 5}])


def test_carregar_banco_sem_tabelas_novas(tmp_path):
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE metricas_video (data TEXT, youtube_id TEXT, titulo TEXT, publicado TEXT,
            duracao_s INT, views INT, impressoes INT, ctr_pct REAL, retencao_pct REAL, assistido_s REAL);
        CREATE TABLE trafego_video (data TEXT, youtube_id TEXT, origem TEXT, views INT, minutos REAL);
        CREATE TABLE termos_busca (data TEXT, youtube_id TEXT, termo TEXT, views INT);
        CREATE TABLE termos_canal (data TEXT, termo TEXT, views INT);
        INSERT INTO metricas_video VALUES ('2026-11-10','a','A','2026-10-10',1200,10,NULL,NULL,40,100);
    """)
    con.commit()
    con.close()
    d = pa.carregar(db)
    assert d["data"] == "2026-11-10" and len(d["metricas"]) == 1
    assert d["trafego_semana"] == {} and d["trafego_semana_antes"] == {}
    assert d["v7"] == [] and d["publicacoes"].empty and len(d["historico"]) == 1
    assert pa.diagnostico(d, AGORA)["views_semana"] is None


def test_carregar_banco_completo(banco):
    _gravar()
    d = pa.carregar(_eventos.DB_PATH)
    assert d["trafego_semana"] == {"YT_SEARCH": 5}
    assert set(d) >= {"historico", "trafego_semana", "trafego_semana_antes", "v7", "publicacoes"}


def _captura(monkeypatch):
    cap = []
    monkeypatch.setattr(st, "info", lambda t, **k: cap.append(f"INFO:{t}"))
    monkeypatch.setattr(st, "markdown", lambda t, **k: cap.append(t))
    monkeypatch.setattr(st, "caption", lambda t, **k: cap.append(f"CAP:{t}"))
    monkeypatch.setattr(st, "columns", lambda *a, **k: [MagicMock(), MagicMock()])
    monkeypatch.setattr(st, "text_input", lambda *a, **k: "")
    monkeypatch.setattr(st, "dataframe", lambda df, **k: cap.append(f"DF:{len(df)}"))
    monkeypatch.setattr(pa.visual, "grade", lambda c, **k: cap.extend(c))
    monkeypatch.setattr(pa.visual, "barras", lambda s, **k: cap.append(f"BARRAS:{list(s.index)}"))
    monkeypatch.setattr(pa.visual, "colunas", lambda s, **k: cap.append(f"COLUNAS:{list(s.index)}"))
    return cap


def test_aba_renderiza_diagnostico(monkeypatch, banco):
    _gravar()
    cap = _captura(monkeypatch)
    pa.aba_analytics(_eventos.DB_PATH)
    txt = " ".join(map(str, cap))
    assert "Diagnóstico do canal" in txt and "COLUNAS:" in txt
    assert "Precisa de pelo menos 2 coletas" in txt      # 1 coleta: sem views por dia
    assert "Por faixa de duração" in txt


def test_aba_diagnostico_com_historico(monkeypatch, banco):
    _gravar("2026-11-09")
    _gravar("2026-11-10")
    cap = _captura(monkeypatch)
    pa.aba_analytics(_eventos.DB_PATH)
    assert "COLUNAS:['10/11']" in " ".join(map(str, cap))


def test_secao_diagnostico_sem_dados_opcionais(monkeypatch):
    cap = _captura(monkeypatch)
    pa.secao_diagnostico({**pa.VAZIO, "data": "2026-11-10"}, AGORA)
    assert any("Diagnóstico" in str(c) for c in cap)
