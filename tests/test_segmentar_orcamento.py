"""03_segmentar: reaproveitamento por assinatura, cache de 1h só em reprocessamento,
trava de orçamento. Sem API (harness ast + subprocess com bruta assinada)."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import _custo
import test_segmentar_janelas as tj
from test_segmentar_posproc import SCRIPT, bloco, words, DUR

ROOT = Path(__file__).parent.parent
PROMPT_REAL = ROOT / "prompts" / "segmentacao.md"


def _h(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


@pytest.fixture
def ns(tmp_path, monkeypatch):
    """Harness do 03 com decidir_segmentacao carregada."""
    tj.NOMES_FUNC.add("decidir_segmentacao")
    try:
        n, _, _ = tj.carregar(tmp_path, monkeypatch, 5, [{"blocos": [tj.bloco(1, 4)]}])
    finally:
        tj.NOMES_FUNC.discard("decidir_segmentacao")
    return n


def _bruta(tmp_path, ass=None):
    d = {"blocos": []}
    if ass is not None:
        d["_assinatura"] = ass
    (tmp_path / "segmentacao_bruta.json").write_text(json.dumps(d), encoding="utf-8")


def _atual(ns):
    return ns["assinatura"](ns["INPUT"].read_text(encoding="utf-8"), "PROMPT")


# ── decidir_segmentacao ────────────────────────────────────────────────────

def test_assinatura_tem_hash_prompt_e_modelo(ns):
    a = _atual(ns)
    assert a["modelo"] == ns["MODELO"] and a["transcricao"] != a["prompt"]
    assert a == _atual(ns)


def test_decidir_refazer_chama(ns, tmp_path):
    _bruta(tmp_path, _atual(ns))
    assert ns["decidir_segmentacao"](_atual(ns), True) == ("chamar", "--refazer", False)


def test_decidir_sem_bruta_primeira_vez(ns):
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "chamar" and "primeira" in motivo


def test_decidir_sem_bruta_com_parcial_diz_incompleta(ns, tmp_path):
    (tmp_path / "segmentacao_bruta_parcial.json").write_text("{}", encoding="utf-8")
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "chamar" and "incompleta" in motivo


def test_decidir_bruta_ilegivel_chama(ns, tmp_path):
    (tmp_path / "segmentacao_bruta.json").write_text("{quebrado", encoding="utf-8")
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "chamar" and "ilegível" in motivo


def test_decidir_bruta_que_nao_e_objeto_chama(ns, tmp_path):
    (tmp_path / "segmentacao_bruta.json").write_text("[1, 2]", encoding="utf-8")
    acao, motivo, _ = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "chamar" and "ilegível" in motivo


def test_decidir_mesma_assinatura_reaproveita(ns, tmp_path):
    _bruta(tmp_path, _atual(ns))
    acao, _, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "reaproveitar" and not avisar


def test_decidir_transcricao_mudou_chama(ns, tmp_path):
    _bruta(tmp_path, {**_atual(ns), "transcricao": "outra"})
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "chamar" and "transcrição mudou" in motivo


@pytest.mark.parametrize("campo", ["prompt", "modelo"])
def test_decidir_prompt_ou_modelo_mudou_reaproveita_com_aviso(ns, tmp_path, campo):
    _bruta(tmp_path, {**_atual(ns), campo: "antigo"})
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "reaproveitar" and avisar and campo in motivo


def test_decidir_legada_transcricao_mais_nova_chama(ns, tmp_path):
    _bruta(tmp_path)
    os.utime(tmp_path / "segmentacao_bruta.json", (1000, 1000))
    os.utime(tmp_path / "transcricao.txt", (2000, 2000))
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "chamar" and "mais nova" in motivo


def test_decidir_legada_transcricao_mais_velha_reaproveita(ns, tmp_path):
    _bruta(tmp_path)
    os.utime(tmp_path / "segmentacao_bruta.json", (2000, 2000))
    os.utime(tmp_path / "transcricao.txt", (1000, 1000))
    acao, motivo, avisar = ns["decidir_segmentacao"](_atual(ns), False)
    assert acao == "reaproveitar" and "sem assinatura" in motivo


# ── cache de 1h só no --refazer / retomada ─────────────────────────────────

def _roda_llm(tmp_path, monkeypatch, pre_existente=None, cache_1h=False):
    n, msgs, _ = tj.carregar(tmp_path, monkeypatch, 5, [{"blocos": [tj.bloco(1, 4)]}])
    if pre_existente:
        (tmp_path / pre_existente).write_text("{}", encoding="utf-8")
    data = n["chamar_llm"](cache_1h=cache_1h)
    return data, msgs.pedidos[0]


def test_refazer_usa_cache_1h_na_transcricao(tmp_path, monkeypatch):
    _, pedido = _roda_llm(tmp_path, monkeypatch, "segmentacao_bruta.json", cache_1h=True)
    assert pedido["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "<transcricao>" in pedido["system"][0]["text"]
    assert "cache_control" not in pedido["system"][1]


def test_primeira_segmentacao_sem_cache(tmp_path, monkeypatch):
    data, pedido = _roda_llm(tmp_path, monkeypatch)
    assert all("cache_control" not in b for b in pedido["system"])
    assert set(data["_assinatura"]) == {"transcricao", "prompt", "modelo"}


def test_bruta_completa_apaga_a_parcial_e_grava_assinatura(tmp_path, monkeypatch):
    _roda_llm(tmp_path, monkeypatch, "segmentacao_bruta_parcial.json")
    assert not (tmp_path / "segmentacao_bruta_parcial.json").exists()
    bruta = json.loads((tmp_path / "segmentacao_bruta.json").read_text(encoding="utf-8"))
    assert "_assinatura" in bruta


def test_trava_de_orcamento_para_antes_da_api(tmp_path, monkeypatch):
    n, msgs, _ = tj.carregar(tmp_path, monkeypatch, 5, [{"blocos": []}])
    monkeypatch.setattr(_custo, "gasto_live", lambda stem: 99.0)
    n["evento"] = lambda *a, **k: None
    import _eventos
    monkeypatch.setattr(_eventos, "evento", lambda *a, **k: None)
    with pytest.raises(_custo.OrcamentoEstourado):
        n["chamar_llm"]()
    assert msgs.pedidos == []


# ── ponta a ponta (subprocess, sem flag) ───────────────────────────────────

def test_sem_flag_com_bruta_assinada_igual_nao_chama_api(tmp_path):
    pasta = tmp_path / "outputs" / "2026-10-26_fake"
    pasta.mkdir(parents=True)
    transcricao = "[00:00:00] Speaker: texto qualquer.\n"
    (pasta / "transcricao.txt").write_text(transcricao, encoding="utf-8")
    (pasta / "words.json").write_text(json.dumps({"duration": DUR, "words": words()}), encoding="utf-8")
    ass = {"transcricao": _h(transcricao),
           "prompt": _h(PROMPT_REAL.read_text(encoding="utf-8")), "modelo": "claude-sonnet-4-6"}
    (pasta / "segmentacao_bruta.json").write_text(
        json.dumps({"blocos": [bloco(1, 10, 22)], "_assinatura": ass}), encoding="utf-8")
    # proxy inválido: qualquer chamada real falharia
    env = {**os.environ, "MISSAO_DB": str(tmp_path / "t.db"), "ANTHROPIC_API_KEY": "x",
           "HTTPS_PROXY": "http://127.0.0.1:9", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(SCRIPT), str(pasta)], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Segmentando com a API" not in r.stdout and "Reaproveitando" in r.stdout
    d = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    assert d["blocos"] and "_assinatura" not in d
