"""Fontes de terceiros no Curador (31/10): filtro por grupo no título, nunca processa sozinho,
risco no painel, 'possivelmente já cortado' pelo título, cache com título/data, migração do banco.
Tudo mockado: sem rede, sem yt-dlp, sem API, banco temporário."""
import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import _capitulos as cap
import _eventos as ev
import hoje

_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("curador13_terc", _ROOT / "scripts" / "13_curador.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)

CFG = {"duracao_min": 20, "duracao_max": 300, "dias": 30}
HOJE = date(2026, 10, 31)


def item(titulo="Renan Santos fala sobre economia", **kw):
    return {"id": "v1", "titulo": titulo, "duracao_s": 3600, "data": "2026-10-30",
            "live_status": "was_live", **kw}


# ── 1. tem_grupo / motivo_filtro ───────────────────────────────────────────

@pytest.mark.parametrize("titulo,esperado", [
    ("Renan Santos no Flow", True),
    ("RENAN SANTOS NO FLOW", True),
    ("Arthur do Val e Mamãe Falei", True),
    ("Mamae Falei comenta", True),
    ("Kim Kataguiri responde", True),
    ("Guto Zacarias debate", True),
    ("Amanda Vettorazzo em entrevista", True),
    ("O MBL decide", True),
    ("Partido Missão lança candidato", True),
    ("Partido Missao lança candidato", True),
    ("MISSÃO IMPOSSÍVEL: o filme", False),
    ("Gombl e outros", False),                  # palavra inteira: 'mbl' dentro de outra não conta
    ("Fulano fala sobre economia", False),
    ("", False),
])
def test_tem_grupo(titulo, esperado):
    assert cu.tem_grupo(titulo) is esperado


def test_motivo_filtro_terceiros_sem_grupo_barra():
    m = cu.motivo_filtro(item("Fulano fala de economia", terceiros=True), CFG, HOJE, set())
    assert m and "terceiros" in m


def test_motivo_filtro_terceiros_com_grupo_passa():
    assert cu.motivo_filtro(item(terceiros=True), CFG, HOJE, set()) is None


def test_motivo_filtro_normal_sem_grupo_nao_e_afetado():
    assert cu.motivo_filtro(item("Fulano fala de economia"), CFG, HOJE, set()) is None


# ── 2. proximo_da_fila ─────────────────────────────────────────────────────

def test_proximo_da_fila_ignora_terceiros_mesmo_com_prioridade_maior():
    estado = {"t": {"decisao": "fila", "prioridade": 10, "data": "2026-10-30", "terceiros": True},
              "n": {"decisao": "fila", "prioridade": 3, "data": "2026-10-20"}}
    assert cu.proximo_da_fila(estado) == "n"


def test_proximo_da_fila_so_terceiros_devolve_none():
    estado = {"t": {"decisao": "fila", "prioridade": 10, "data": "2026-10-30", "terceiros": True}}
    assert cu.proximo_da_fila(estado) is None


def test_proximo_da_fila_modo_evento_ignora_terceiros():
    estado = {"t": {"decisao": "fila", "prioridade": 10, "data": "2026-10-30", "terceiros": True},
              "n": {"decisao": "fila", "prioridade": 9, "data": "2026-10-29"}}
    assert cu.proximo_da_fila(estado, date(2026, 10, 28), 9) == "n"
    estado.pop("n")
    assert cu.proximo_da_fila(estado, date(2026, 10, 28), 9) is None


def _corpo_rodada():
    src = (_ROOT / "scripts" / "13_curador.py").read_text(encoding="utf-8")
    corpo = src[src.index("def _rodada("):]
    return corpo[:corpo.index("\ndef ", 10)] if "\ndef " in corpo[10:] else corpo


def test_rodada_so_escolhe_automatico_via_proximo_da_fila():
    """Todo caminho automático da _rodada (evento, estoque baixo, rede) passa por proximo_da_fila;
    processar_escolhido só é chamado com o vid dela ou por processar_pedidos (clique do Gu)."""
    corpo = _corpo_rodada()
    assert corpo.count("vid = proximo_da_fila(") == 3
    assert corpo.count("processar_escolhido(") == 1
    assert "processar_pedidos(cfg, estado, rodada)" in corpo


# ── 3. montar_pedido / registro / listar_canal ─────────────────────────────

def test_montar_pedido_marca_terceiros():
    base = {"id": "a", "canal": "Flow", "data": "2026-10-30", "duracao_s": 3600, "titulo": "T"}
    txt = cu.montar_pedido([{**base, "terceiros": True}, {**base, "id": "b", "canal": "Kim"}])
    flow = next(ln for ln in txt.splitlines() if "id=a" in ln)
    kim = next(ln for ln in txt.splitlines() if "id=b" in ln)
    assert "canal: Flow (terceiros)" in flow
    assert "terceiros" not in kim


def test_listar_canal_propaga_terceiros(monkeypatch):
    class Y:
        def extract_info(self, url, download=False):
            if url.endswith("/videos"):
                raise RuntimeError("does not have a videos tab")
            return {"entries": [{"id": "x1", "title": "Renan", "duration": 3600,
                                 "timestamp": 1761800000, "live_status": "was_live"}]}
    monkeypatch.setattr(cu, "_ydl", lambda opcoes: Y())
    base = {"nome": "Flow", "url": "https://yt/@flow", "prefixo": "flow"}
    com = cu.listar_canal({**base, "terceiros": True}, 5)
    sem = cu.listar_canal(base, 5)
    assert com[0]["terceiros"] is True
    assert "terceiros" not in sem[0]


def test_registro_do_estado_guarda_terceiros():
    """O registro montado na _rodada inclui terceiros: True só pra item de terceiros."""
    corpo = _corpo_rodada()
    corpo = corpo[corpo.index("registro = {"):corpo.index('estado[c["id"]] = registro')]
    assert '**({"terceiros": True} if c.get("terceiros") else {})' in corpo


# ── 4. espelhar_fila ───────────────────────────────────────────────────────

def test_espelhar_fila_risco_so_pra_terceiros(banco):
    base = {"decisao": "fila", "titulo": "T", "canal": "C", "prioridade": 5, "url": "u",
            "data": "2026-10-30", "motivo": "m"}
    cu.espelhar_fila({"t": {**base, "terceiros": True, "talvez_cortado_por": "Canal X (1)"},
                      "n": {**base, "talvez_cortado_por": ""},
                      "x": {**base, "decisao": "recusado", "terceiros": True}})
    por_id = {s["video_id"]: s for s in ev.listar_sugestoes()}
    assert set(por_id) == {"t", "n"}
    assert por_id["t"]["risco"] == cu.RISCO_TERCEIROS
    assert por_id["t"]["talvez_cortado_por"] == "Canal X (1)"
    assert por_id["n"]["risco"] is None
    assert por_id["n"]["talvez_cortado_por"] == ""


# ── 5. palavras_chave / talvez_cortado / cortes_sem_link ───────────────────

def test_palavras_chave_tira_genericas_curtas_e_acento():
    assert cu.palavras_chave("Renan Santos ao vivo: Lula e a Reforma Tributária da Câmara") == \
        {"reforma", "tributaria", "camara"}                      # lula é genérica (PALAVRAS_GENERICAS)
    assert cu.palavras_chave("Debate sobre o STF") == set()      # genéricas / <4 letras


LIVE = {"titulo": "Reforma tributária e o Congresso", "data": "2026-10-20"}


def corte(titulo="Reforma tributária no Congresso", data="2026-10-22", canal="Canal X"):
    return {"canal": canal, "titulo": titulo, "data": data}


def test_talvez_cortado_conta_com_palavras_em_comum():
    assert cu.talvez_cortado(LIVE, [corte(), corte(canal="Canal Y")]) == {"Canal X": 1, "Canal Y": 1}


def test_talvez_cortado_uma_palavra_so_nao_basta():
    assert cu.MIN_PALAVRAS_TALVEZ == 2
    assert cu.talvez_cortado(LIVE, [corte("Reforma e outras coisas")]) == {}


def test_talvez_cortado_janela_de_dias():
    assert cu.talvez_cortado(LIVE, [corte(data="2026-10-20")]) == {"Canal X": 1}     # mesmo dia
    assert cu.talvez_cortado(LIVE, [corte(data="2026-10-30")]) == {"Canal X": 1}     # +DIAS_TALVEZ
    assert cu.talvez_cortado(LIVE, [corte(data="2026-10-31")]) == {}                 # depois da janela
    assert cu.talvez_cortado(LIVE, [corte(data="2026-10-19")]) == {}                 # antes da live


def test_talvez_cortado_sem_data():
    assert cu.talvez_cortado(LIVE, [corte(data=None)]) == {}
    assert cu.talvez_cortado({"titulo": LIVE["titulo"], "data": None}, [corte()]) == {}
    assert cu.talvez_cortado({"titulo": "", "data": "2026-10-20"}, [corte()]) == {}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    p = tmp_path / "state" / "cortes_terceiros.json"
    monkeypatch.setattr(cu, "CORTES_CACHE", p)
    return p


def test_cortes_sem_link_so_sem_fontes_e_com_titulo(cache):
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({
        "a": {"canal": "X", "fontes": [], "titulo": "Sem link", "data": "2026-10-22"},
        "b": {"canal": "X", "fontes": ["live1"], "titulo": "Com link", "data": "2026-10-22"},
        "c": {"canal": "X", "fontes": []},                       # entrada antiga, sem título
        "d": {"canal": "X", "fontes": [], "titulo": ""}}), encoding="utf-8")
    assert [c["titulo"] for c in cu.cortes_sem_link()] == ["Sem link"]


def test_cortes_sem_link_cache_ausente_ou_corrompido(cache):
    assert cu.cortes_sem_link() == []
    cache.parent.mkdir(parents=True)
    cache.write_text("{quebrado", encoding="utf-8")
    assert cu.cortes_sem_link() == []


# ── 6. marcar_cortados ─────────────────────────────────────────────────────

def _fila(**kw):
    return {"decisao": "fila", "prioridade": 8, **LIVE, **kw}


def test_marcar_cortados_com_link_penaliza_forte_e_ignora_talvez():
    est = {"l": _fila()}
    assert cu.marcar_cortados(est, {"l": {"Canal A": 2}}, [corte()]) == ["l"]
    assert est["l"]["prioridade"] == 8 - cu.PENALIDADE_CORTADO
    assert est["l"]["cortado_por"] == "Canal A (2)"
    assert est["l"]["talvez_cortado_por"] == ""


def test_marcar_cortados_sem_link_mas_titulo_bate():
    est = {"l": _fila()}
    assert cu.marcar_cortados(est, {}, [corte()]) == []
    assert est["l"]["prioridade"] == 8 - cu.PENALIDADE_TALVEZ
    assert est["l"]["cortado_por"] == ""
    assert est["l"]["talvez_cortado_por"] == "Canal X (1)"


def test_marcar_cortados_nada_fica_na_base():
    est = {"l": _fila()}
    cu.marcar_cortados(est, {}, [corte("Outro assunto totalmente diferente")])
    assert est["l"]["prioridade"] == 8
    assert est["l"]["cortado_por"] == est["l"]["talvez_cortado_por"] == ""


def test_marcar_cortados_minimo_1():
    est = {"l": _fila(prioridade=2)}
    cu.marcar_cortados(est, {"l": {"A": 1}})
    assert est["l"]["prioridade"] == 1


def test_marcar_cortados_nao_acumula_entre_rodadas():
    est = {"l": _fila()}
    cu.marcar_cortados(est, {"l": {"A": 1}})
    cu.marcar_cortados(est, {"l": {"A": 1}})
    assert est["l"]["prioridade"] == 5 and est["l"]["prioridade_llm"] == 8
    cu.marcar_cortados(est, {}, [corte()])                  # cai pra "talvez"
    assert est["l"]["prioridade"] == 7
    cu.marcar_cortados(est, {}, [])                         # sumiu: volta pra base
    assert est["l"]["prioridade"] == 8


def test_marcar_cortados_ignora_quem_nao_esta_na_fila():
    est = {"l": {**_fila(), "decisao": "recusado"}}
    cu.marcar_cortados(est, {"l": {"A": 1}})
    assert est["l"]["prioridade"] == 8 and "cortado_por" not in est["l"]


# ── 7. cortes_publicados (cache com título/data) ───────────────────────────

class Fontes:
    def __init__(self, mapa):
        self.mapa, self.lidos = mapa, []

    def __call__(self, vid):
        self.lidos.append(vid)
        return self.mapa[vid]


CANAL = {"nome": "Canal A", "url": "https://yt/@a"}


def test_cortes_publicados_guarda_dict_inteiro(cache):
    f = Fontes({"a1": {"fontes": ["liveX"], "titulo": "T1", "data": "2026-10-22"},
                "a2": {"fontes": [], "titulo": "T2", "data": "2026-10-23"}})
    achados = cu.cortes_publicados([CANAL], 30, listar=lambda c, n: ["a1", "a2"], fontes=f)
    assert achados == {"liveX": {"Canal A": 1}}
    salvo = json.loads(cache.read_text(encoding="utf-8"))
    assert salvo["a1"] == {"canal": "Canal A", "fontes": ["liveX"], "titulo": "T1", "data": "2026-10-22"}
    assert salvo["a2"]["titulo"] == "T2" and salvo["a2"]["fontes"] == []


def test_cortes_publicados_aceita_lista_compat(cache):
    f = Fontes({"a1": ["liveX"]})
    assert cu.cortes_publicados([CANAL], 30, listar=lambda c, n: ["a1"], fontes=f) == \
        {"liveX": {"Canal A": 1}}
    assert json.loads(cache.read_text(encoding="utf-8"))["a1"] == {"canal": "Canal A", "fontes": ["liveX"]}


def test_cortes_publicados_antigo_sem_fontes_e_sem_titulo_relido_uma_vez(cache):
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"a1": {"canal": "Canal A", "fontes": []}}), encoding="utf-8")
    f = Fontes({"a1": {"fontes": [], "titulo": "Novo", "data": "2026-10-22"}})
    cu.cortes_publicados([CANAL], 30, listar=lambda c, n: ["a1"], fontes=f)
    assert f.lidos == ["a1"]
    assert json.loads(cache.read_text(encoding="utf-8"))["a1"]["titulo"] == "Novo"
    cu.cortes_publicados([CANAL], 30, listar=lambda c, n: ["a1"], fontes=f)
    assert f.lidos == ["a1"]                                # 2ª rodada: do cache


def test_cortes_publicados_antigo_com_fontes_sem_titulo_nao_e_relido(cache):
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"a1": {"canal": "Canal A", "fontes": ["liveX"]}}), encoding="utf-8")
    f = Fontes({})
    achados = cu.cortes_publicados([CANAL], 30, listar=lambda c, n: ["a1"], fontes=f)
    assert f.lidos == [] and achados == {"liveX": {"Canal A": 1}}


# ── 8. _eventos: migração e gravar_sugestao ────────────────────────────────

def test_migracao_adiciona_colunas_em_banco_antigo(tmp_path):
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sugestoes (video_id TEXT PRIMARY KEY, titulo TEXT, cortado_por TEXT, "
                "status TEXT NOT NULL DEFAULT 'sugerida', sugerida_em TEXT, atualizado_em TEXT)")
    con.commit()
    con.close()
    ev.conectar(db).close()
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sugestoes)")}
    con.close()
    assert {"talvez_cortado_por", "risco"} <= cols


def test_gravar_sugestao_aceita_talvez_e_risco(banco):
    ev.gravar_sugestao("v1", titulo="T", talvez_cortado_por="Canal X (1)", risco="r")
    s = ev.listar_sugestoes()[0]
    assert s["talvez_cortado_por"] == "Canal X (1)" and s["risco"] == "r"


# ── 9. painel: secao_sugestoes ─────────────────────────────────────────────

def _render(tmp_path, linhas, extras=("cortado_por", "talvez_cortado_por", "risco")):
    from streamlit.testing.v1 import AppTest
    cols = ["video_id", "titulo", "canal", "url", "duracao_min", "data", "prioridade",
            "motivo", "status", "mensagem", *extras]
    pd.DataFrame(linhas, columns=cols).to_pickle(tmp_path / "s.pkl")
    src = "\n".join(["import sys", f"sys.path.insert(0, {str(Path(hoje.__file__).parent)!r})",
                     "import pandas as pd", "import hoje",
                     f"hoje.secao_sugestoes(pd.read_pickle({str(tmp_path / 's.pkl')!r}), False)"])
    return AppTest.from_string(src).run()


def _html(at):
    return " ".join(m.value for m in at.markdown)


def _linha(vid, cortado, talvez, risco):
    return (vid, f"Live {vid}", "Kim", "u", 90.0, "2026-10-29", 8, "m", "sugerida", None,
            cortado, talvez, risco)


def test_painel_mostra_possivelmente_cortado(tmp_path):
    at = _render(tmp_path, [_linha("a", "", "Canal X (1)", None)])
    assert not at.exception
    h = _html(at)
    assert "possivelmente já cortado (pelo título) por Canal X (1)" in h
    assert "ninguém cortou ainda" not in h


def test_painel_cortado_por_tem_precedencia(tmp_path):
    h = _html(_render(tmp_path, [_linha("a", "Canal A (2)", "Canal X (1)", None)]))
    assert "já cortado por Canal A (2)" in h and "possivelmente" not in h


def test_painel_ninguem_cortou_e_risco(tmp_path):
    h = _html(_render(tmp_path, [_linha("a", "", "", cu.RISCO_TERCEIROS)]))
    assert "ninguém cortou ainda" in h
    assert "⚠ " + cu.RISCO_TERCEIROS in h


def test_painel_sem_risco_nao_mostra_aviso(tmp_path):
    assert "⚠" not in _html(_render(tmp_path, [_linha("a", "", "", None)]))


def test_painel_sugestao_sem_as_colunas_novas_nao_quebra(tmp_path):
    at = _render(tmp_path, [("a", "Live a", "Kim", "u", 90.0, "2026-10-29", 8, "m", "sugerida",
                             None, "Canal A (1)")], extras=("cortado_por",))
    assert not at.exception
    h = _html(at)
    assert "já cortado por Canal A (1)" in h and "⚠" not in h


# ── 10. capítulos a partir de 5 min ────────────────────────────────────────

def test_min_corte_capitulos_e_5_min():
    assert cap.MIN_CORTE_MIN == 5.0
