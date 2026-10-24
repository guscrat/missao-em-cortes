"""Prompt caching e custo com cache. Tudo mockado: nenhuma chamada de API."""
import importlib.util
import json
import sqlite3
import types
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

import _colagem
import _custo
import _eventos
import hoje

SCRIPTS = Path(__file__).parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("revisor_c", SCRIPTS / "11_revisor.py")
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def _resp(modelo="claude-opus-5-5", i=0, o=0, esc=None, lei=None, **extra):
    u = types.SimpleNamespace(input_tokens=i, output_tokens=o,
                              cache_creation_input_tokens=esc, cache_read_input_tokens=lei)
    return types.SimpleNamespace(model=modelo, usage=u, **extra)


# ── _custo ─────────────────────────────────────────────────────────────────

def test_modelo_fora_da_tabela_avisa_e_usa_opus(capsys):
    u = _custo.uso(_resp(modelo="claude-novo", i=1_000_000), "claude-novo")
    assert u["custo_usd"] == pytest.approx(4.0)
    assert "fora da tabela" in capsys.readouterr().err


def test_sem_cache_usd_reprecifica_escrita_e_leitura():
    # opus: 1M lidos (0.20) + 1M escritos (5.00) custaram 5.20; sem cache seriam 8.00
    ev = {"mensagem": "claude-opus-5-5 (thumb)", "custo_usd": 5.20,
          "cache_escrita": 1_000_000, "cache_leitura": 1_000_000}
    assert _custo.sem_cache_usd(ev) == pytest.approx(8.0)
    assert _custo.sem_cache_usd({"mensagem": "", "custo_usd": 0.3, "cache_leitura": 10}) == 0.3


def test_economia_por_etapa_e_total():
    evs = [{"etapa": "11_revisor", "mensagem": "claude-opus-5-5", "custo_usd": 0.20,
            "tokens_in": 2_000_000, "cache_escrita": 0, "cache_leitura": 1_000_000},
           {"etapa": "04b_polir", "mensagem": None, "custo_usd": 0.10, "tokens_in": 1000}]
    e = _custo.economia(evs)
    assert e["11_revisor"]["sem_cache"] == pytest.approx(4.0)
    assert e["11_revisor"]["taxa"] == pytest.approx(0.5)
    assert e["_total"]["chamadas"] == 2
    assert e["_total"]["sem_cache"] - e["_total"]["custo"] == pytest.approx(3.8)


def test_uso_sem_cache_opus():
    u = _custo.uso(_resp(i=1_000_000, o=100_000), "claude-opus-5-5")
    assert u["custo_usd"] == pytest.approx(4.0 + 2.0)
    assert u["tokens_in"] == 1_000_000 and u["cache_escrita"] == u["cache_leitura"] == 0


@pytest.mark.parametrize("modelo,esperado", [
    ("claude-opus-5-5", 4 + 5 + 0.20 + 20),
    ("claude-sonnet-4-6", 3 + 3.75 + 0.30 + 15),
    ("claude-haiku-5-5", 0.10 + 0.125 + 0.01 + 0.50),
])
def test_uso_com_cache_por_modelo(modelo, esperado):
    # 1M de cada tipo (resp.model == modelo; o Haiku fica na faixa curta por resposta)
    pedacos = [_resp(modelo, i=1_000_000 if modelo != "claude-haiku-5-5" else 90_000),
               _resp(modelo, esc=1_000_000 if modelo != "claude-haiku-5-5" else 90_000),
               _resp(modelo, lei=1_000_000 if modelo != "claude-haiku-5-5" else 90_000),
               _resp(modelo, o=1_000_000)]
    usos = [_custo.uso(p, modelo) for p in pedacos]
    if modelo == "claude-haiku-5-5":
        esperado = (90_000 * (0.10 + 0.125 + 0.01) / 1e6) + 0.50
    assert _custo.somar(usos)["custo_usd"] == pytest.approx(esperado)


def test_tokens_in_e_total():
    u = _custo.uso(_resp(i=10, esc=20, lei=30, o=5), "claude-opus-5-5")
    assert (u["tokens_in"], u["tokens_out"], u["cache_escrita"], u["cache_leitura"]) == (60, 5, 20, 30)


def test_haiku_faixa_longa():
    curto = _custo.uso(_resp("claude-haiku-5-5", i=100_000, o=1_000_000), "claude-haiku-5-5")
    longo = _custo.uso(_resp("claude-haiku-5-5", i=100_001, o=1_000_000), "claude-haiku-5-5")
    assert curto["custo_usd"] == pytest.approx(100_000 * 0.10 / 1e6 + 0.50)
    assert longo["custo_usd"] == pytest.approx(100_001 * 0.50 / 1e6 + 2.50)


def test_haiku_faixa_longa_conta_cache_no_total():
    u = _custo.uso(_resp("claude-haiku-5-5", i=1000, esc=50_000, lei=60_000), "claude-haiku-5-5")
    assert u["custo_usd"] == pytest.approx((1000 * 0.50 + 50_000 * 0.625 + 60_000 * 0.05) / 1e6)


def test_resp_model_vence_quando_na_tabela():
    r = _resp("claude-sonnet-4-6", i=1_000_000)
    assert _custo.uso(r, "claude-opus-5-5")["custo_usd"] == pytest.approx(3.0)


def test_resp_model_desconhecido_usa_o_pedido():
    r = _resp("claude-xyz", i=1_000_000)
    assert _custo.uso(r, "claude-opus-5-5")["custo_usd"] == pytest.approx(4.0)


def test_campos_none_ou_ausentes_viram_zero():
    r = types.SimpleNamespace(model="claude-opus-5-5",
                              usage=types.SimpleNamespace(input_tokens=None, output_tokens=7))
    u = _custo.uso(r, "claude-opus-5-5")
    assert u["tokens_in"] == 0 and u["tokens_out"] == 7 and u["cache_leitura"] == 0
    assert _custo.cache(r) == {"cache_escrita": 0, "cache_leitura": 0}


def test_cache_devolve_kwargs_do_evento():
    assert _custo.cache(_resp(esc=5, lei=9)) == {"cache_escrita": 5, "cache_leitura": 9}


def test_somar_e_taxa_acerto():
    a = _custo.uso(_resp(i=100, lei=300, o=1), "claude-opus-5-5")
    b = _custo.uso(_resp(i=100, esc=100, o=2), "claude-opus-5-5")
    s = _custo.somar([a, b])
    assert s["tokens_in"] == 600 and s["tokens_out"] == 3
    assert s["cache_leitura"] == 300 and s["cache_escrita"] == 100
    assert s["custo_usd"] == pytest.approx(a["custo_usd"] + b["custo_usd"])
    assert _custo.taxa_acerto(s["cache_leitura"], s["tokens_in"]) == pytest.approx(0.5)
    assert _custo.taxa_acerto(0, 0) == 0.0


def test_resumo_vazio_sem_cache_e_preenchido_com():
    assert _custo.resumo(_custo.uso(_resp(i=10), "claude-opus-5-5")) == ""
    r = _custo.resumo(_custo.uso(_resp(i=0, lei=100), "claude-opus-5-5"))
    assert "100" in r and "100%" in r


# ── _eventos: colunas cache_* ──────────────────────────────────────────────

def test_evento_grava_cache(banco):
    _eventos.evento("v", "11_revisor", "llm", tokens_in=100, cache_escrita=30, cache_leitura=40)
    r = banco("SELECT cache_escrita, cache_leitura FROM eventos")[0]
    assert r == {"cache_escrita": 30, "cache_leitura": 40}


def test_evento_cache_default_zero(banco):
    _eventos.evento("v", "x", "ok")
    assert banco("SELECT cache_escrita, cache_leitura FROM eventos")[0] == {
        "cache_escrita": 0, "cache_leitura": 0}


def test_migracao_banco_antigo_sem_colunas_cache(tmp_path, monkeypatch):
    db = tmp_path / "antigo" / "pipeline.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, stem TEXT,
        bloco_id INTEGER, agente TEXT, etapa TEXT, status TEXT, mensagem TEXT,
        tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, custo_usd REAL DEFAULT 0,
        duracao_s REAL)""")
    con.execute("INSERT INTO eventos (ts, etapa, status, tokens_in) VALUES ('t','e','llm',5)")
    con.commit()
    con.close()
    monkeypatch.setattr(_eventos, "DB_PATH", db)
    _eventos.evento("v", "11_revisor", "llm", cache_leitura=7)
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(eventos)")}
    linhas = con.execute("SELECT tokens_in, cache_leitura FROM eventos ORDER BY id").fetchall()
    con.close()
    assert {"cache_escrita", "cache_leitura"} <= cols
    assert linhas[0] == (5, 0) and linhas[1][1] == 7   # linha antiga ganha 0


# ── revisor ────────────────────────────────────────────────────────────────

def test_sistema_revisor_grafias_com_cache_no_ultimo_bloco(monkeypatch):
    monkeypatch.setattr(rv._grafias, "para_prompt", lambda *a, **k: "- Nikolas Ferreira")
    s = rv.sistema_revisor()
    assert isinstance(s, list) and len(s) == 2
    assert s[0]["text"] == rv.SISTEMA and "cache_control" not in s[0]
    assert s[1]["text"].startswith("GRAFIAS OFICIAIS:") and "Nikolas Ferreira" in s[1]["text"]
    assert s[1]["cache_control"] == {"type": "ephemeral"}


def test_montar_conteudo_sem_grafias(monkeypatch):
    monkeypatch.setattr(rv._grafias, "para_prompt", lambda *a, **k: "- MARCADOR_GRAFIA")
    c = rv.montar_conteudo("Título", "THUMB", "fala do trecho", None, [])
    texto = " ".join(b.get("text", "") for b in c)
    assert "GRAFIAS OFICIAIS" not in texto and "MARCADOR_GRAFIA" not in texto
    assert "fala do trecho" in texto


class _Client:
    def __init__(self):
        self.kw = None
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.kw = kw
        return _resp(stop_reason="end_turn",
                     content=[types.SimpleNamespace(type="text", text=json.dumps({}))])


def test_chamar_claude_padrao_manda_system_em_lista():
    c = _Client()
    rv.chamar_claude(c, [{"type": "text", "text": "x"}])
    assert isinstance(c.kw["system"], list)
    assert c.kw["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_chamar_claude_sistema_string_do_thumb_fica_string():
    c = _Client()
    rv.chamar_claude(c, [{"type": "text", "text": "x"}], sistema=rv.SISTEMA_THUMB)
    assert c.kw["system"] == rv.SISTEMA_THUMB and isinstance(c.kw["system"], str)


def test_revisor_custo_usa_cache():
    tin, tout, usd = rv.custo(_resp(i=1_000_000))
    assert (tin, tout) == (1_000_000, 0) and usd == pytest.approx(4.0)
    assert rv.custo(_resp(lei=1_000_000))[2] == pytest.approx(0.20)


# ── _colagem.escolher ──────────────────────────────────────────────────────

def test_colagem_escolher_system_com_cache_control(monkeypatch):
    monkeypatch.setattr(_colagem, "montar_conteudo_visao", lambda *a, **k: [])
    monkeypatch.setattr(_colagem, "validar_escolha", lambda d, nr, nc: d)
    visto = {}

    def create(**kw):
        visto.update(kw)
        return _resp("claude-haiku-5-5", stop_reason="end_turn",
                     content=[types.SimpleNamespace(type="text", text="{}")])

    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    escolha, _ = _colagem.escolher(client, [Image.new("RGB", (4, 4))], [], "tema")
    assert escolha == {}
    assert visto["system"] == [{"type": "text", "text": _colagem.SISTEMA_VISAO,
                                "cache_control": {"type": "ephemeral"}}]


def test_colagem_custo_com_cache_haiku():
    tin, tout, usd = _colagem.custo(_resp("claude-haiku-5-5", i=1000, esc=2000, lei=3000, o=100))
    assert tin == 6000 and tout == 100
    assert usd == pytest.approx((1000 * 0.10 + 2000 * 0.125 + 3000 * 0.01 + 100 * 0.50) / 1e6)


# ── painel/hoje.custo_cache ────────────────────────────────────────────────

def test_hoje_custo_cache():
    df = pd.DataFrame({"tokens_in": [1000, 3000, 0], "cache_leitura": [0, 2000, 0],
                       "cache_escrita": [500, 0, 0]})
    assert hoje.custo_cache(df) == {"tokens_in": 4000, "leitura": 2000, "escrita": 500, "taxa": 0.5}


def test_hoje_custo_cache_banco_sem_colunas():
    df = pd.DataFrame({"tokens_in": [1000, 2000]})
    assert hoje.custo_cache(df) == {"tokens_in": 3000, "leitura": 0, "escrita": 0, "taxa": 0.0}


def test_hoje_custo_cache_vazio():
    assert hoje.custo_cache(pd.DataFrame()) == {"tokens_in": 0, "leitura": 0, "escrita": 0, "taxa": 0.0}
