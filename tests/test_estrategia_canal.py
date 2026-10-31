"""Estratégia do canal (31/10): cortes de terceiros no Curador (13), cortado_por e tabelas novas
no banco, views dos 7 primeiros dias / minutos por faixa / resumo semanal no 17, painel.
Tudo mockado: sem rede, sem yt-dlp, sem API, banco temporário."""
import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import _eventos as ev
import _fronteira as fr
import hoje

_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("curador13_estr", _ROOT / "scripts" / "13_curador.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)
_spec = importlib.util.spec_from_file_location("analytics17_estr", _ROOT / "scripts" / "17_analytics.py")
an = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(an)

MONT = fr.MONTAGEM_S


# ── 13_curador: cortes_publicados ──────────────────────────────────────────

@pytest.fixture
def cache(tmp_path, monkeypatch):
    p = tmp_path / "state" / "cortes_terceiros.json"
    monkeypatch.setattr(cu, "CORTES_CACHE", p)
    return p


class Fontes:
    def __init__(self, mapa, falham=()):
        self.mapa, self.falham, self.lidos = mapa, set(falham), []

    def __call__(self, vid):
        self.lidos.append(vid)
        if vid in self.falham:
            raise RuntimeError("descrição indisponível")
        return self.mapa[vid]


CANAL_A, CANAL_B = {"nome": "Canal A", "url": "https://yt/@a"}, {"nome": "Canal B", "url": "https://yt/@b"}


def test_cortes_publicados_conta_por_canal_e_le_descricao_uma_vez(cache):
    listas = {"Canal A": ["a1", "a2"], "Canal B": ["b1"]}
    fontes = Fontes({"a1": ["liveX"], "a2": ["liveX", "liveY"], "b1": ["liveX"]})
    achados = cu.cortes_publicados([CANAL_A, CANAL_B], 30, listar=lambda c, n: listas[c["nome"]],
                                   fontes=fontes)
    assert achados == {"liveX": {"Canal A": 2, "Canal B": 1}, "liveY": {"Canal A": 1}}
    assert sorted(fontes.lidos) == ["a1", "a2", "b1"]
    fontes.lidos.clear()                                   # 2ª rodada: tudo do cache
    again = cu.cortes_publicados([CANAL_A, CANAL_B], 30, listar=lambda c, n: listas[c["nome"]],
                                 fontes=fontes)
    assert again == achados and fontes.lidos == []


def test_cortes_publicados_passa_n_pro_listar(cache):
    vistos = []
    cu.cortes_publicados([CANAL_A], 7, listar=lambda c, n: vistos.append(n) or [], fontes=Fontes({}))
    assert vistos == [7]


def test_cortes_publicados_canal_que_falha_e_pulado(cache, capsys):
    def listar(c, n):
        if c["nome"] == "Canal A":
            raise RuntimeError("yt-dlp caiu")
        return ["b1"]
    achados = cu.cortes_publicados([CANAL_A, CANAL_B], 30, listar=listar,
                                   fontes=Fontes({"b1": ["liveX"]}))
    assert achados == {"liveX": {"Canal B": 1}}
    assert "Canal A" in capsys.readouterr().out


def test_cortes_publicados_descricao_que_falha_nao_entra_no_cache(cache):
    f = Fontes({"a1": ["liveX"], "a2": ["liveY"]}, falham=["a2"])
    achados = cu.cortes_publicados([CANAL_A], 30, listar=lambda c, n: ["a1", "a2"], fontes=f)
    assert achados == {"liveX": {"Canal A": 1}}
    assert list(json.loads(cache.read_text(encoding="utf-8"))) == ["a1"]
    f.falham.clear()                                       # volta a tentar na rodada seguinte
    achados = cu.cortes_publicados([CANAL_A], 30, listar=lambda c, n: ["a1", "a2"], fontes=f)
    assert achados == {"liveX": {"Canal A": 1}, "liveY": {"Canal A": 1}}


def test_cortes_publicados_corte_fora_da_listagem_sai_do_cache(cache):
    f = Fontes({"a1": ["liveX"], "a2": ["liveY"]})
    cu.cortes_publicados([CANAL_A], 30, listar=lambda c, n: ["a1", "a2"], fontes=f)
    assert set(json.loads(cache.read_text(encoding="utf-8"))) == {"a1", "a2"}
    achados = cu.cortes_publicados([CANAL_A], 30, listar=lambda c, n: ["a2"], fontes=f)
    assert set(json.loads(cache.read_text(encoding="utf-8"))) == {"a2"}
    assert achados == {"liveY": {"Canal A": 1}}


def test_cortes_publicados_cache_corrompido_recomeca(cache):
    cache.parent.mkdir(parents=True)
    cache.write_text("{quebrado", encoding="utf-8")
    achados = cu.cortes_publicados([CANAL_A], 30, listar=lambda c, n: ["a1"],
                                   fontes=Fontes({"a1": ["liveX"]}))
    assert achados == {"liveX": {"Canal A": 1}}


def test_cortes_publicados_sem_canais_nao_faz_nada(cache):
    assert cu.cortes_publicados([], 30, listar=None, fontes=None) == {}


# ── 13_curador: marcar_cortados ────────────────────────────────────────────

def _fila(**prios):
    return {k: {"decisao": "fila", "prioridade": p} for k, p in prios.items()}


def test_marcar_cortados_penaliza_e_guarda_base():
    est = _fila(a=8, b=8)
    cortados = cu.marcar_cortados(est, {"a": {"Canal B": 1, "Canal A": 2}})
    assert cortados == ["a"]
    assert est["a"]["cortado_por"] == "Canal A (2), Canal B (1)"       # ordem alfabética
    assert est["a"]["prioridade"] == 8 - cu.PENALIDADE_CORTADO and est["a"]["prioridade_llm"] == 8
    assert est["b"]["cortado_por"] == "" and est["b"]["prioridade"] == 8


def test_marcar_cortados_minimo_1():
    est = _fila(a=2, b=1)
    cu.marcar_cortados(est, {"a": {"X": 1}, "b": {"X": 1}})
    assert est["a"]["prioridade"] == 1 and est["b"]["prioridade"] == 1


def test_marcar_cortados_volta_pra_base_quando_some_e_nao_penaliza_duas_vezes():
    est = _fila(a=8)
    cu.marcar_cortados(est, {"a": {"X": 1}})
    cu.marcar_cortados(est, {"a": {"X": 2}})                           # 2ª rodada: não acumula
    assert est["a"]["prioridade"] == 5 and est["a"]["cortado_por"] == "X (2)"
    cu.marcar_cortados(est, {})                                        # corte sumiu da listagem
    assert est["a"]["prioridade"] == 8 and est["a"]["cortado_por"] == ""


def test_marcar_cortados_so_decisao_fila():
    est = {"p": {"decisao": "processado", "prioridade": 8}, "r": {"decisao": "recusado"}}
    assert cu.marcar_cortados(est, {"p": {"X": 1}, "r": {"X": 1}}) == []
    assert est["p"] == {"decisao": "processado", "prioridade": 8}
    assert est["r"] == {"decisao": "recusado"}


# ── _eventos ───────────────────────────────────────────────────────────────

def test_gravar_sugestao_com_cortado_por(banco):
    ev.gravar_sugestao("v1", titulo="Live", cortado_por="Canal A (2)")
    ev.gravar_sugestao("v2", titulo="Outra", cortado_por="")
    ev.gravar_sugestao("v3", titulo="Sem checagem")
    por_id = {s["video_id"]: s["cortado_por"] for s in ev.listar_sugestoes()}
    assert por_id == {"v1": "Canal A (2)", "v2": "", "v3": None}
    ev.gravar_sugestao("v1", cortado_por="")                           # corte sumiu: atualiza
    assert {s["video_id"]: s["cortado_por"] for s in ev.listar_sugestoes()}["v1"] == ""


def test_espelhar_fila_leva_cortado_por(banco):
    cu.espelhar_fila({"a": {"decisao": "fila", "titulo": "T", "prioridade": 4,
                            "cortado_por": "X (1)"}})
    assert ev.listar_sugestoes()[0]["cortado_por"] == "X (1)"


def test_migracao_sugestoes_ganha_cortado_por(tmp_path):
    db = tmp_path / "velho.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sugestoes (video_id TEXT PRIMARY KEY, titulo TEXT, status TEXT "
                "NOT NULL DEFAULT 'sugerida', sugerida_em TEXT, atualizado_em TEXT)")
    con.execute("INSERT INTO sugestoes (video_id, titulo) VALUES ('x', 'Antiga')")
    con.commit()
    con.close()
    con = ev.conectar(db)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(sugestoes)")}
    linha = con.execute("SELECT titulo, cortado_por FROM sugestoes").fetchone()
    con.close()
    assert "cortado_por" in cols and linha["titulo"] == "Antiga" and linha["cortado_por"] is None


def test_views_7d_grava_substitui_e_ordena(banco):
    assert ev.views_7d() == []
    ev.gravar_views_7d([{"youtube_id": "a", "titulo": "A", "publicado": "2026-10-01", "duracao_s": 900,
                         "views": 10},
                        {"youtube_id": "b", "titulo": "B", "publicado": "2026-10-05", "duracao_s": 900,
                         "views": 20}])
    ev.gravar_views_7d([{"youtube_id": "a", "titulo": "A", "publicado": "2026-10-01", "duracao_s": 900,
                         "views": 99}])
    r = ev.views_7d()
    assert [x["youtube_id"] for x in r] == ["b", "a"] and r[1]["views"] == 99
    assert banco("SELECT COUNT(*) n FROM views_7d")[0]["n"] == 2


def test_gravar_analytics_trafego_canal_idempotente(banco):
    m = [{"youtube_id": "a", "views": 1}]
    ev.gravar_analytics("2026-10-28", m, [], [], [], [{"origem": "YT_SEARCH", "views": 5}])
    ev.gravar_analytics("2026-10-28", m, [], [], [], [{"origem": "YT_SEARCH", "views": 7},
                                                      {"origem": "SUBSCRIBER", "views": 3}])
    assert {r["origem"]: r["views"] for r in banco("SELECT * FROM trafego_canal")} == {
        "YT_SEARCH": 7, "SUBSCRIBER": 3}
    ev.gravar_analytics("2026-10-29", m, [], [], [])                   # chamada antiga sem o campo
    assert banco("SELECT COUNT(*) n FROM trafego_canal WHERE data='2026-10-29'")[0]["n"] == 0


def test_ultima_coleta_traz_semana_e_semana_antes(banco):
    m = [{"youtube_id": "a", "views": 1}]
    for dia, tc in (("2026-10-14", [{"origem": "YT_SEARCH", "views": 1}]),   # antiga demais
                    ("2026-10-21", [{"origem": "YT_SEARCH", "views": 40},
                                    {"origem": "SUBSCRIBER", "views": 10}]),
                    ("2026-10-25", [{"origem": "YT_SEARCH", "views": 99}]),  # < 7 dias: não conta
                    ("2026-10-28", [{"origem": "YT_SEARCH", "views": 30},
                                    {"origem": "RELATED_VIDEO", "views": 70}])):
        ev.gravar_analytics(dia, m, [], [], [], tc)
    c = ev.ultima_coleta()
    assert c["data"] == "2026-10-28"
    assert c["trafego_semana"] == {"YT_SEARCH": 30, "RELATED_VIDEO": 70}
    assert c["trafego_semana_antes"] == {"YT_SEARCH": 40, "SUBSCRIBER": 10}


def test_ultima_coleta_sem_coleta_de_7_dias_antes(banco):
    ev.gravar_analytics("2026-10-28", [{"youtube_id": "a", "views": 1}], [], [], [],
                        [{"origem": "YT_SEARCH", "views": 30}])
    c = ev.ultima_coleta()
    assert c["trafego_semana"] == {"YT_SEARCH": 30} and c["trafego_semana_antes"] == {}


# ── 17_analytics ───────────────────────────────────────────────────────────

class FakeAn:
    def __init__(self, views=None):
        self.chamadas, self.views = [], views or {}

    def reports(self):
        return self

    def query(self, **kw):
        self.chamadas.append(kw)
        vid = kw["filters"].split("==")[1]
        rows = [[vid, self.views[vid], 100.0, 40.0]] if vid in self.views else []
        return type("E", (), {"execute": lambda s: {"rows": rows}})()


def _vid(i, pub, dur=1200):
    return {"id": i, "titulo": f"T {i}", "publicado": f"{pub}T10:00:00Z", "duracao_s": dur}


def test_views_primeiros_7d_janela_idade_e_feitos():
    hoje_ = date(2026, 10, 28)
    videos = [_vid("ok", "2026-10-19"),          # 9 dias: entra
              _vid("novo", "2026-10-20"),        # 8 dias: ainda não
              _vid("feito", "2026-10-01"),       # já calculado
              _vid("zero", "2026-10-10")]        # sem linha no Analytics: 0 views
    fake = FakeAn({"ok": 55, "feito": 9})
    r = an.views_primeiros_7d(fake, videos, hoje_, {"feito"})
    assert [x["youtube_id"] for x in r] == ["ok", "zero"]
    assert r[0]["views"] == 55 and r[1]["views"] == 0
    assert r[0]["titulo"] == "T ok" and r[0]["duracao_s"] == 1200
    c = fake.chamadas[0]
    assert (c["startDate"], c["endDate"]) == ("2026-10-19", "2026-10-25")    # pub .. pub+6
    assert len(fake.chamadas) == 2


def test_views_primeiros_7d_sem_candidatos_nao_consulta():
    fake = FakeAn()
    assert an.views_primeiros_7d(fake, [_vid("a", "2026-10-27")], date(2026, 10, 28), set()) == []
    assert fake.chamadas == []


def test_fora_da_busca():
    assert an.fora_da_busca({}) is None
    r = an.fora_da_busca({"YT_SEARCH": 25, "SUBSCRIBER": 25, "RELATED_VIDEO": 25, "SHORTS": 25})
    assert r == {"total": 100, "fora_pct": 75.0, "recomendacao_pct": 75.0}
    r = an.fora_da_busca({"YT_SEARCH": 50, "EXT_URL": 50})             # fora da busca, mas não recomendação
    assert r["fora_pct"] == 50.0 and r["recomendacao_pct"] == 0.0
    assert an.fora_da_busca({"YT_SEARCH": 10})["fora_pct"] == 0.0


def _m(dur_min, views, assistido_s, ret=50.0):
    return {"duracao_s": dur_min * 60 + MONT, "views": views, "assistido_s": assistido_s,
            "retencao_pct": ret}


def test_minutos_por_faixa_ponderado_e_ignora_shorts_e_sem_view():
    metricas = [_m(7, 100, 300, 40), _m(7, 300, 180, 60),              # curto: 2 vídeos
                _m(15, 50, 600, 30),                                   # medio
                {"duracao_s": 120, "views": 999, "assistido_s": 100, "retencao_pct": 90},   # Short
                _m(25, 0, 500),                                        # sem view
                {**_m(25, 10, 500), "assistido_s": None}]              # sem dado de tempo
    r = {x["faixa"]: x for x in an.minutos_por_faixa(metricas)}
    assert set(r) == {"curto", "medio", "todos"}
    assert r["curto"]["n"] == 2 and r["curto"]["views"] == 400
    assert r["curto"]["min_por_view"] == round((300 * 100 + 180 * 300) / 400 / 60, 1)   # 1.4
    assert r["curto"]["retencao_pct"] == 55.0
    assert r["todos"]["n"] == 3 and r["todos"]["views"] == 450
    assert [x["faixa"] for x in an.minutos_por_faixa(metricas)][-1] == "todos"


def test_minutos_por_faixa_vazio():
    assert an.minutos_por_faixa([]) == []
    assert an.minutos_por_faixa([{"duracao_s": 100, "views": 5, "assistido_s": 10}]) == []


def test_minutos_por_faixa_faixas_de_borda():
    r = {x["faixa"] for x in an.minutos_por_faixa([_m(4, 10, 100), _m(31, 10, 100)])}
    assert r == {"abaixo_5", "acima_30", "todos"}


def test_media_7d_janela_e_deslocamento():
    h = date(2026, 10, 28)
    v7 = [{"publicado": "2026-10-20", "duracao_s": 900, "views": 10},     # dentro de 4 semanas
          {"publicado": "2026-10-10", "duracao_s": 900, "views": 30},
          {"publicado": "2026-10-20", "duracao_s": 100, "views": 999},    # Short: fora
          {"publicado": "2026-09-15", "duracao_s": 900, "views": 100},    # 8 a 4 semanas atrás
          {"publicado": "2026-06-01", "duracao_s": 900, "views": 5}]      # velho demais
    assert an.media_7d(v7, h, 4) == (2, 20.0)
    assert an.media_7d(v7, h, 4, desloc=4) == (1, 100.0)
    assert an.media_7d([], h, 4) == (0, None)


def test_resumo_semanal_secoes_novas_no_topo():
    metricas = [{"titulo": "Live A", "duracao_s": 7 * 60 + MONT, "views": 100, "assistido_s": 240.0,
                 "retencao_pct": 45.0, "impressoes": None, "ctr_pct": None}]
    v7 = [{"youtube_id": "a", "titulo": "Live A", "publicado": "2026-10-10", "duracao_s": 900,
           "views": 120}]
    txt = an.resumo_semanal([{"termo": "renan", "views": 9}], metricas, {"YT_SEARCH": 5},
                            "2026-10-28", None,
                            {"YT_SEARCH": 30, "SUBSCRIBER": 70}, {"YT_SEARCH": 80, "SUBSCRIBER": 20}, v7)
    assert "Minutos assistidos por view" in txt and "curto 5-10 min" in txt and "| 4.0 |" in txt
    assert "**70%**" in txt and "Semana anterior: 20%" in txt
    assert "**120.0**" in txt and "Live A" in txt
    assert txt.index("Minutos assistidos") < txt.index("Views que não vêm da busca") \
        < txt.index("Vídeos novos") < txt.index("Termos de pesquisa")


def test_resumo_semanal_sem_dados_novos_nao_quebra():
    txt = an.resumo_semanal([], [], {}, "sem coleta")
    assert "nenhum longo com views ainda" in txt
    assert "sem as origens de tráfego" in txt
    assert "dias publicado" in txt
    assert "nenhuma view vinda da busca" in txt


def test_resumo_semanal_sem_semana_anterior():
    txt = an.resumo_semanal([], [], {}, "2026-10-28", None, {"YT_SEARCH": 10}, {}, [])
    assert "Semana anterior: sem coleta pra comparar" in txt and "**0%**" in txt


def test_semanal_ponta_a_ponta_com_banco(banco, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "SEMANAL", tmp_path / "state" / "analytics_semanal.md")
    m = [{"youtube_id": "a", "titulo": "Live A", "publicado": "2026-10-10", "duracao_s": 600 + MONT,
          "views": 100, "assistido_s": 120.0, "retencao_pct": 50.0}]
    ev.gravar_analytics("2026-10-21", m, [], [], [], [{"origem": "YT_SEARCH", "views": 50},
                                                      {"origem": "SUBSCRIBER", "views": 50}])
    ev.gravar_analytics("2026-10-28", m, [], [], [], [{"origem": "YT_SEARCH", "views": 20},
                                                      {"origem": "SUBSCRIBER", "views": 80}])
    txt = an.semanal()
    assert "**80%**" in txt and "Semana anterior: 50%" in txt and "médio 10-20 min" in txt


# ── painel: secao_sugestoes ────────────────────────────────────────────────

def _render(tmp_path, linhas):
    from streamlit.testing.v1 import AppTest
    cols = ["video_id", "titulo", "canal", "url", "duracao_min", "data", "prioridade",
            "motivo", "status", "mensagem", "cortado_por"]
    pd.DataFrame(linhas, columns=cols).to_pickle(tmp_path / "s.pkl")
    src = "\n".join(["import sys", f"sys.path.insert(0, {str(Path(hoje.__file__).parent)!r})",
                     "import pandas as pd", "import hoje",
                     f"hoje.secao_sugestoes(pd.read_pickle({str(tmp_path / 's.pkl')!r}), False)"])
    return AppTest.from_string(src).run()


def test_secao_sugestoes_mostra_cortado_por(tmp_path):
    at = _render(tmp_path, [
        ("a", "Live A", "Kim", "u", 90.0, "2026-10-29", 8, "m", "sugerida", None, "Canal X (2)"),
        ("b", "Live B", "Kim", "u", 90.0, "2026-10-29", 7, "m", "sugerida", None, ""),
        ("c", "Live C", "Kim", "u", 90.0, "2026-10-29", 6, "m", "sugerida", None, None)])
    assert not at.exception
    html_ = " ".join(m.value for m in at.markdown)
    assert html_.count("já cortado por Canal X (2)") == 1
    assert html_.count("ninguém cortou ainda") == 1                    # None = não conferiu: nada
