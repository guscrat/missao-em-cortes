"""Rodada 2: 04b intervalos_fixos (campo remover), revisor (remover + maioria de momentos fora),
_publicacao.horas com minutos, propaganda.json. Tudo mockado."""
import ast
import json
from datetime import date, datetime
from pathlib import Path

import pytest

import _fronteira as fr
import _publicacao as pub
from test_abertura_momentos import (  # noqa: F401  (cenario e a fixture usada pelos testes)
    OKC, _Cli, _desc, _main_pronto, _sem_prop, cenario, cheio, rv, seq)


# ── 04b: intervalos_fixos ──────────────────────────────────────────────────

def _polir_ns(tmp_path, words):
    fonte = Path(__file__).parent.parent / "scripts" / "04b_polir.py"
    arvore = ast.parse(fonte.read_text(encoding="utf-8"))
    corpo = [n for n in arvore.body if isinstance(n, ast.FunctionDef)
             and n.name in {"intervalos_fixos", "hhmmss_para_segundos", "mesclar_intervalos"}]
    wj = tmp_path / "words.json"
    wj.write_text(json.dumps({"words": words}), encoding="utf-8")
    ns = {"json": json, "fr": fr, "WORDS_JSON": wj}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), str(fonte), "exec"), ns)
    return ns


def test_intervalos_fixos_relativos_ao_inicio_do_corte(tmp_path):
    words = seq("a b c d", t0=100.0, passo=1.0)
    ns = _polir_ns(tmp_path, words)
    b = {"timestamp_inicio": "00:01:40", "timestamp_fim": "00:11:40",
         "remover": [{"inicio": "00:03:20", "fim": "00:03:50", "motivo": "propaganda"},
                     {"inicio": "00:05:00", "fim": "00:05:10"}]}
    ini_s, _ = fr.janela(words, 100.0, 700.0)
    r = ns["intervalos_fixos"](b)
    assert r[0]["t_inicio"] == pytest.approx(200 - ini_s)
    assert r[1]["t_inicio"] == pytest.approx(300 - ini_s)
    assert r[0]["t_fim"] - r[0]["t_inicio"] == pytest.approx(30)
    assert r[0]["motivo"] == "propaganda" and r[0]["fixo"] is True
    assert "remover" in r[1]["motivo"]


def test_intervalos_fixos_sem_remover_e_vazio(tmp_path):
    ns = _polir_ns(tmp_path, [])
    assert ns["intervalos_fixos"]({"timestamp_inicio": "00:00:10", "timestamp_fim": "00:09:00"}) == []
    assert ns["intervalos_fixos"]({"remover": []}) == []


def test_intervalos_fixos_funde_com_silencio(tmp_path):
    ns = _polir_ns(tmp_path, [])
    fixo = {"t_inicio": 10.0, "t_fim": 40.0, "motivo": "x", "fixo": True}
    sil = {"t_inicio": 38.0, "t_fim": 45.0, "motivo": "silencio"}
    r = ns["mesclar_intervalos"]([sil, fixo])
    assert len(r) == 1 and (r[0]["t_inicio"], r[0]["t_fim"]) == (10.0, 45.0)


# ── revisor main ───────────────────────────────────────────────────────────

def _status_apos(cenario, monkeypatch, n, fora):
    cli = _Cli({**OKC, "momentos_fora": [f"Momento {i}" for i in fora]})
    pasta, _, _ = _main_pronto(cenario, monkeypatch, _sem_prop(), cli)
    _desc(pasta, [f"Momento {i}" for i in range(n)])
    assert rv.main([str(pasta)]) == 0
    return json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))["01"]


def test_main_maioria_dos_momentos_fora_vai_pra_quarentena(cenario, monkeypatch):
    rev = _status_apos(cenario, monkeypatch, 3, [0, 1])
    assert rev["status"] == "quarentena"
    assert "confira se os tempos do bloco estão certos" in rev["motivo"]
    assert len(rev["momentos_removidos"]) == 2


def test_main_um_de_tres_continua_aprovado(cenario, monkeypatch):
    assert _status_apos(cenario, monkeypatch, 3, [0])["status"] == "aprovado"


def test_main_dois_de_quatro_nao_e_maioria(cenario, monkeypatch):
    assert _status_apos(cenario, monkeypatch, 4, [0, 1])["status"] == "aprovado"


def test_main_transcricao_exclui_palavras_do_remover(cenario, monkeypatch):
    pasta0 = cenario[0]
    blocos = json.loads((pasta0 / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0]["remover"] = [{"inicio": "00:02:00", "fim": "00:02:10"}]
    (pasta0 / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    palavras = [{"word": "DENTRO", "start": 110.0, "end": 110.4},
                {"word": "PROPAGANDA", "start": 125.0, "end": 125.4},
                {"word": "DEPOIS", "start": 130.0, "end": 130.4},
                {"word": "FIM.", "start": 690.0, "end": 690.4}]
    cli = _Cli(OKC)
    pasta, _, _ = _main_pronto(cenario, monkeypatch, palavras, cli)
    assert rv.main([str(pasta)]) == 0
    texto = cli.chamadas[0]["messages"][0]["content"][-1]["text"]
    assert "DENTRO" in texto and "DEPOIS" in texto and "PROPAGANDA" not in texto


# ── horas com minutos ──────────────────────────────────────────────────────

def test_horas_com_minutos_19h30_e_19_30():
    hoje = date(2026, 10, 26)
    assert pub.horas(["19h30", "20:30"], [hoje, hoje], datetime(2026, 10, 26, 19, 45)) == [
        "JÁ (19h30 passou)", "20:30"]
    assert pub.horas(["19:30"], [hoje], datetime(2026, 10, 26, 19, 29)) == ["19:30"]
    assert pub.horas(["19:30"], [hoje], datetime(2026, 10, 26, 19, 30)) == ["JÁ (19:30 passou)"]


# ── propaganda.json ────────────────────────────────────────────────────────

def test_patrocinio_solto_nao_e_termo_e_max_150():
    termos, _ = fr.termos_propaganda()
    assert ["patrocinio"] not in termos and ["nosso", "patrocinio"] in termos
    assert fr.MAX_PROPAGANDA_S == 150
    p = seq("O patrocinio da campanha foi debatido. " + cheio(30))
    assert fr.pular_propaganda(p, 100.0, termos) is None
