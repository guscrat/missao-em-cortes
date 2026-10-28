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
    def __init__(self):
        self.chamadas = []

    def reports(self):
        return self

    def query(self, **kw):
        self.chamadas.append(kw)
        m, d = kw["metrics"], kw["dimensions"]
        assert not m.startswith("videoThumbnail")      # a Analytics API recusa (400)
        if d == "video":
            return _Exec({"rows": [["a", 300, 410.55, 37.44]]})
        if d == "insightTrafficSourceType":
            return _Exec({"rows": [["YT_SEARCH", 100, 50.0], ["SUBSCRIBER", 200, 80.5]]})
        return _Exec({"rows": [["renan santos", 40], ["missão", 10]]})


def _coletar(**kw):
    an_ = FakeAnalytics(**kw)
    return an.coletar_dados(FakeYT(VIDS), an_, HOJE), an_


# --- coletar_dados -------------------------------------------------------------------

REACH = {"a": {"impressoes": 1000, "ctr_pct": 5.2}}


def test_coletar_ignora_privado_e_usa_reach_pronto():
    d = an.coletar_dados(FakeYT(VIDS), FakeAnalytics(), HOJE, reach=REACH)
    assert [m["youtube_id"] for m in d["metricas"]] == ["a", "b"]
    a, b = d["metricas"]
    assert a["ctr_pct"] == 5.2 and a["impressoes"] == 1000
    assert a["views"] == 300 and a["retencao_pct"] == 37.4 and a["assistido_s"] == 410.6
    assert a["duracao_s"] == 1200 and d["avisos"] == []
    assert b["impressoes"] is None and b["ctr_pct"] is None


def test_coletar_dados_sem_reach_deixa_impressoes_nulas():
    d, an_ = _coletar()
    assert d["metricas"][0]["impressoes"] is None and d["metricas"][0]["ctr_pct"] is None
    assert not any(c["metrics"].startswith("videoThumbnail") for c in an_.chamadas)


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


def test_montar_pedido_corta_termo_longo():
    pedido = _editor.montar_pedido("t", "x", "p", "trans", [], ["a" * 200])
    assert "a" * _editor.MAX_TERMO in pedido and "a" * (_editor.MAX_TERMO + 1) not in pedido


# --- Reach (Reporting API) -----------------------------------------------------------

class FakeReporting:
    """jobs().list / jobs().create / jobs().reports().list com páginas fixas."""
    def __init__(self, jobs_paginas=None, reports_paginas=None):
        self.jobs_paginas = jobs_paginas or [{}]
        self.reports_paginas = reports_paginas or [{}]
        self.criados, self.tokens_jobs, self.tokens_reports = [], [], []

    def jobs(self):
        return self

    def reports(self):
        return _Rep(self)

    def list(self, pageToken=None, **kw):
        self.tokens_jobs.append(pageToken)
        return _Exec(self.jobs_paginas[0 if pageToken is None else int(pageToken)])

    def create(self, body):
        self.criados.append(body)
        return _Exec({"id": "novo"})


class _Rep:
    def __init__(self, pai):
        self.pai = pai

    def list(self, jobId=None, pageToken=None):
        self.pai.tokens_reports.append(pageToken)
        return _Exec(self.pai.reports_paginas[0 if pageToken is None else int(pageToken)])


def _rel(dia, criado, url=None):
    return {"startTime": f"{dia}T08:00:00Z", "createTime": criado,
            "downloadUrl": url or f"u-{dia}-{criado}"}


CSV = ("date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
       "2026-10-20,c,a,100,0.10\n2026-10-20,c,a,300,0.02\n2026-10-20,c,b,0,0\n")


def test_job_reach_acha_o_existente():
    r = FakeReporting(jobs_paginas=[{"jobs": [{"id": "j0", "reportTypeId": "outro"},
                                               {"id": "j1", "reportTypeId": an.REACH_TIPO}]}])
    assert an.job_reach(r) == "j1" and r.criados == []


def test_job_reach_pagina():
    r = FakeReporting(jobs_paginas=[{"jobs": [{"id": "j0", "reportTypeId": "outro"}],
                                     "nextPageToken": "1"},
                                    {"jobs": [{"id": "j9", "reportTypeId": an.REACH_TIPO}]}])
    assert an.job_reach(r) == "j9" and r.tokens_jobs == [None, "1"] and r.criados == []


def test_job_reach_cria_quando_nao_existe():
    r = FakeReporting(jobs_paginas=[{}])
    assert an.job_reach(r) == "novo"
    assert r.criados == [{"reportTypeId": an.REACH_TIPO, "name": an.REACH_JOB}]


def test_relatorios_novos_backfill_mais_novo_vence():
    r = FakeReporting(reports_paginas=[{"reports": [
        _rel("2026-10-20", "2026-10-22T01:00:00Z", "velho"),
        _rel("2026-10-20", "2026-10-25T01:00:00Z", "backfill"),
        _rel("2026-10-21", "2026-10-22T02:00:00Z", "d21")]}])
    novos = an.relatorios_novos(r, "j", {})
    assert [(x["dia"], x["url"]) for x in novos] == [("2026-10-20", "backfill"), ("2026-10-21", "d21")]


def test_relatorios_novos_ja_importado_nao_volta_e_backfill_posterior_volta():
    r = FakeReporting(reports_paginas=[
        {"reports": [_rel("2026-10-20", "2026-10-22T01:00:00Z"),
                     _rel("2026-10-21", "2026-10-22T02:00:00Z", "novo21")], "nextPageToken": "1"},
        {"reports": [_rel("2026-10-21", "2026-10-26T00:00:00Z", "back21")]}])
    novos = an.relatorios_novos(r, "j", {"2026-10-20": "2026-10-22T01:00:00Z",
                                         "2026-10-21": "2026-10-22T02:00:00Z"})
    assert [(x["dia"], x["url"]) for x in novos] == [("2026-10-21", "back21")]
    assert r.tokens_reports == [None, "1"]
    r2 = FakeReporting(reports_paginas=[{"reports": [_rel("2026-10-20", "2026-10-22T01:00:00Z")]}])
    assert an.relatorios_novos(r2, "j", {"2026-10-20": "2026-10-22T01:00:00Z"}) == []


def test_ler_reach_soma_e_pondera_razao():
    r = {x["youtube_id"]: x for x in an.ler_reach(CSV)}
    assert r["a"] == {"youtube_id": "a", "impressoes": 400, "ctr_pct": 4.0}   # (10+6)/400
    assert r["b"]["impressoes"] == 0 and r["b"]["ctr_pct"] == 0.0


def test_ler_reach_ctr_ja_em_porcentagem():
    csv_ = CSV.split("\n")[0] + "\n2026-10-20,c,a,100,10\n2026-10-20,c,a,300,2\n"
    assert an.ler_reach(csv_)[0]["ctr_pct"] == 4.0


def test_ler_reach_campos_vazios():
    csv_ = CSV.split("\n")[0] + "\n2026-10-20,c,a,,\n"
    assert an.ler_reach(csv_) == [{"youtube_id": "a", "impressoes": 0, "ctr_pct": 0.0}]


def test_gravar_reach_substitui_o_dia_e_reach_por_video(banco):
    assert _eventos.reach_por_video() == (None, {})
    _eventos.gravar_reach("2026-10-20", "t1", [{"youtube_id": "a", "impressoes": 100, "ctr_pct": 10.0},
                                               {"youtube_id": "z", "impressoes": 5, "ctr_pct": 0.0}])
    _eventos.gravar_reach("2026-10-21", "t2", [{"youtube_id": "a", "impressoes": 300, "ctr_pct": 2.0}])
    desde, r = _eventos.reach_por_video()
    assert desde == "2026-10-20" and r["a"] == {"impressoes": 400, "ctr_pct": 4.0}
    for _ in range(2):          # backfill do dia 20 (idempotente): z some, a muda
        _eventos.gravar_reach("2026-10-20", "t3", [{"youtube_id": "a", "impressoes": 100, "ctr_pct": 2.0}])
    _, r = _eventos.reach_por_video()
    assert "z" not in r and r["a"] == {"impressoes": 400, "ctr_pct": 2.0}
    assert len(banco("SELECT * FROM reach_dia")) == 2
    assert _eventos.reach_importados() == {"2026-10-20": "t3", "2026-10-21": "t2"}


def test_importar_reach_ponta_a_ponta(banco):
    r = FakeReporting(jobs_paginas=[{"jobs": [{"id": "j", "reportTypeId": an.REACH_TIPO}]}],
                      reports_paginas=[{"reports": [_rel("2026-10-20", "t1", "url20")]}])
    baixados = []

    def baixar(url):
        baixados.append(url)
        return CSV

    assert an.importar_reach(r, baixar) == 1 and baixados == ["url20"]
    desde, reach = _eventos.reach_por_video()
    assert desde == "2026-10-20" and reach["a"]["impressoes"] == 400
    assert an.importar_reach(r, baixar) == 0 and baixados == ["url20"]    # nada novo, não rebaixa


def _mock_google(monkeypatch, reporting_falha=None):
    import google.auth.transport.requests as req
    import googleapiclient.discovery as disc
    monkeypatch.setattr(an, "credenciais", lambda *a, **k: object())
    monkeypatch.setattr(req, "AuthorizedSession", lambda creds: MagicMock())

    def build(nome, versao, **kw):
        if nome == "youtubereporting":
            if reporting_falha:
                raise reporting_falha
            return FakeReporting(jobs_paginas=[{"jobs": [{"id": "j", "reportTypeId": an.REACH_TIPO}]}])
        return FakeYT(VIDS) if nome == "youtube" else FakeAnalytics()
    monkeypatch.setattr(disc, "build", build)


def test_coletar_reach_falhando_vira_aviso_e_segue(banco, monkeypatch):
    _mock_google(monkeypatch, RuntimeError("API desativada"))
    _eventos.gravar_reach("2026-10-20", "t1", [{"youtube_id": "a", "impressoes": 100, "ctr_pct": 3.0}])
    d = an.coletar(interativo=False)
    assert any("Reach" in a and "API desativada" in a for a in d["avisos"])
    assert d["reach_desde"] == "2026-10-20"
    assert d["metricas"][0]["impressoes"] == 100 and d["metricas"][0]["ctr_pct"] == 3.0
    assert banco("SELECT COUNT(*) AS n FROM metricas_video")[0]["n"] == 2
    status = [e["status"] for e in banco("SELECT status FROM eventos WHERE etapa='17_analytics'")]
    assert "aviso" in status and "ok" in status


def test_coletar_sem_nenhum_relatorio(banco, monkeypatch):
    _mock_google(monkeypatch)
    d = an.coletar(interativo=False)
    assert d["reach_desde"] is None and d["avisos"] == []
    assert d["metricas"][0]["impressoes"] is None


def test_painel_carregar_reach_desde(banco):
    _eventos.gravar_analytics("2026-10-28", [{"youtube_id": "a", "views": 1}], [], [], [])
    assert painel.carregar(_eventos.DB_PATH)["reach_desde"] is None      # tabela vazia
    _eventos.gravar_reach("2026-10-20", "t", [{"youtube_id": "a", "impressoes": 1, "ctr_pct": 1.0}])
    assert painel.carregar(_eventos.DB_PATH)["reach_desde"] == "2026-10-20"


def test_painel_carregar_banco_sem_reach_dia(tmp_path):
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE metricas_video (data TEXT, youtube_id TEXT, views INT)")
    con.execute("CREATE TABLE termos_canal (data TEXT, termo TEXT, views INT)")
    con.execute("CREATE TABLE trafego_video (data TEXT, youtube_id TEXT, origem TEXT, views INT)")
    con.execute("CREATE TABLE termos_busca (data TEXT, youtube_id TEXT, termo TEXT, views INT)")
    con.execute("INSERT INTO metricas_video VALUES ('2026-10-28', 'a', 1)")
    con.commit()
    con.close()
    d = painel.carregar(db)
    assert d["data"] == "2026-10-28" and d["reach_desde"] is None


def test_painel_caption_reach(monkeypatch, banco):
    d, _ = _coletar()
    _eventos.gravar_analytics(d["data"], d["metricas"], d["trafego"], d["termos"], d["termos_canal"])
    cap = _captura(monkeypatch)
    painel.aba_analytics(_eventos.DB_PATH)
    assert "1º relatório Reach" in " ".join(cap)
    _eventos.gravar_reach("2026-10-20", "t", [{"youtube_id": "a", "impressoes": 1, "ctr_pct": 1.0}])
    cap = _captura(monkeypatch)
    painel.aba_analytics(_eventos.DB_PATH)
    assert "desde 20/10" in " ".join(cap)
