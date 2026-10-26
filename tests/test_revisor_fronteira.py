"""11_revisor: checagem de fronteira ($0, antes do LLM) e flags do pipeline --bloco.
refazer_bloco, Claude e ffmpeg sempre mockados."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

import _paths

_spec = importlib.util.spec_from_file_location(
    "revisor_fr", Path(__file__).parent.parent / "scripts" / "11_revisor.py")
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def W(*itens):
    return [{"word": w, "start": s, "end": e} for w, s, e in itens]


# Bloco 10s-20s. Ponta final cai no meio da frase ("c4" não fecha; "fim." vem em 20.1-20.5)
MEIO = W(("c1", 10.0, 10.5), ("c2", 11.0, 11.5), ("c3", 19.0, 19.5), ("c4", 19.6, 20.0),
         ("fim.", 20.1, 20.5), ("Outra", 25.0, 25.5))
# Sem nenhum ponto natural por perto: só vírgulas
SEM_PONTO = W(("c1", 10.0, 10.5), ("c2,", 11.0, 11.5), ("c3,", 19.0, 19.5), ("c4,", 19.6, 20.0),
              ("fim,", 20.1, 20.5), ("Outra,", 25.0, 25.5))
NATURAL = W(("c1", 10.0, 10.5), ("c2", 11.0, 11.5), ("c3", 19.0, 19.5), ("fim.", 19.6, 20.0),
            ("Outra", 25.0, 25.5))


@pytest.fixture
def cenario(projeto, monkeypatch):
    pasta = projeto.video("v", blocos=[1])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    b = blocos["blocos"][0]
    b["timestamp_inicio"], b["timestamp_fim"] = "00:00:10", "00:00:20"
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    refeitos = []
    monkeypatch.setattr(rv, "refazer_bloco", lambda p, bid: refeitos.append(bid) or True)
    return pasta, b, refeitos, projeto.banco


def _ts(pasta):
    b = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"][0]
    return b["timestamp_inicio"], b["timestamp_fim"], b


def test_fronteira_ok_nao_mexe_nem_refaz(cenario):
    pasta, b, refeitos, _ = cenario
    reg, motivo = rv.conferir_fronteira("v", pasta, b, NATURAL)
    assert motivo is None and reg["inicio_ok"] and reg["fim_ok"] and "reajuste_s" not in reg
    assert refeitos == [] and _ts(pasta)[:2] == ("00:00:10", "00:00:20")


def test_fronteira_reajusta_grava_blocos_json_e_refaz(cenario):
    pasta, b, refeitos, banco = cenario
    reg, motivo = rv.conferir_fronteira("v", pasta, b, MEIO)
    assert motivo is None and refeitos == [1]
    ini, fim, salvo = _ts(pasta)
    assert ini == "00:00:10" or ini == "00:00:10.00"
    assert fim == "00:00:20.50"
    assert salvo["duracao_minutos"] == round(10.5 / 60, 1)
    assert salvo["faixa_duracao"] == "fora"
    assert reg["reajuste_s"] == [0.0, 0.5] and reg["fim_ok"] is True
    assert b["timestamp_fim"] == "00:00:20.50"            # o dict do chamador também muda
    assert banco("SELECT faixa_duracao FROM blocos WHERE bloco_id=1")[0]["faixa_duracao"] == "fora"


def test_fronteira_sem_ponto_natural_vai_pra_quarentena_sem_mexer(cenario):
    pasta, b, refeitos, _ = cenario
    reg, motivo = rv.conferir_fronteira("v", pasta, b, SEM_PONTO)
    assert motivo and "não há ponto natural" in motivo
    assert refeitos == [] and _ts(pasta)[:2] == ("00:00:10", "00:00:20")


def test_fronteira_reajuste_sem_mudanca_vai_pra_quarentena_sem_refazer(cenario, monkeypatch):
    # a checagem reprova, mas o ponto natural mais perto é o próprio tempo: refazer daria o
    # mesmo vídeo (live do Renan, bloco 07, antes do fix da palavra de duração zero)
    pasta, b, refeitos, _ = cenario
    monkeypatch.setattr(rv._fronteira, "checar", lambda *a, **k: {
        "inicio_ok": True, "fim_ok": False, "primeiras": "c1", "ultimas": "c3",
        "pausa_depois_s": 0.7})
    monkeypatch.setattr(rv._fronteira, "encaixar", lambda p, ini, fim, *a: {
        "inicio": ini, "fim": fim, "inicio_ok": True, "fim_ok": True})
    _, motivo = rv.conferir_fronteira("v", pasta, b, NATURAL)
    assert motivo and "tempo atual" in motivo
    assert refeitos == [] and _ts(pasta)[:2] == ("00:00:10", "00:00:20")


def test_fronteira_refazer_falhou_vira_quarentena(cenario, monkeypatch):
    pasta, b, _, _ = cenario
    monkeypatch.setattr(rv, "refazer_bloco", lambda p, bid: False)
    _, motivo = rv.conferir_fronteira("v", pasta, b, MEIO)
    assert motivo and "falhou ao refazer" in motivo


def test_fronteira_dry_run_so_mostra(cenario, capsys):
    pasta, b, refeitos, _ = cenario
    reg, motivo = rv.conferir_fronteira("v", pasta, b, MEIO, reajustar=False)
    assert motivo and "meio de frase" in motivo and "reajuste_s" not in reg
    assert refeitos == [] and _ts(pasta)[:2] == ("00:00:10", "00:00:20")
    assert "fronteira reprovada" in capsys.readouterr().out


def test_fronteira_respeita_dur_max_de_30min(cenario):
    # bloco de 29:50 -> o fim não pode passar de 30min a partir do início
    pasta, b, _, _ = cenario
    b["timestamp_inicio"], b["timestamp_fim"] = "00:00:10", "00:30:00"
    p = W(("a", 10.0, 10.5), ("m", 1799.0, 1799.5), ("z", 1799.6, 1800.0),
          ("ok.", 1800.1, 1801.0), ("Outra", 1805.0, 1805.5))
    reg, motivo = rv.conferir_fronteira("v", pasta, b, p, reajustar=False)
    assert motivo  # meio de frase
    # com reajuste: 1801.0 - 10 = 1791s <= 1800 (ok, dentro do máximo)
    reg, motivo = rv.conferir_fronteira("v", pasta, b, p)
    assert motivo is None and _ts(pasta)[1] == "00:30:01.00"


# ── main: grava "fronteira" no revisao.json e quarentena antes do LLM ───────

class _NaoChamar:
    def __init__(self):
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._boom))

    def _boom(self, **k):
        raise AssertionError("API não deveria ser chamada")


def _preparar_main(cenario, monkeypatch, palavras):
    pasta, b, refeitos, banco = cenario
    (pasta / "words.json").write_text(json.dumps({"words": palavras}), encoding="utf-8")
    (pasta / "cortes" / "corte_01_slug.mp4").touch()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(
        Anthropic=_NaoChamar, APIError=RuntimeError))
    return pasta, refeitos, banco


def test_main_quarentena_por_fronteira_sem_chamar_llm(cenario, monkeypatch):
    pasta, refeitos, banco = _preparar_main(cenario, monkeypatch, SEM_PONTO)
    assert rv.main([str(pasta)]) == 0
    rev = json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))
    assert rev["01"]["status"] == "quarentena" and rev["01"]["custo_usd"] == 0.0
    assert rev["01"]["fronteira"]["fim_ok"] is False
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "quarentena"
    assert refeitos == []


def test_main_dry_run_nao_reajusta(cenario, monkeypatch, capsys):
    pasta, refeitos, _ = _preparar_main(cenario, monkeypatch, MEIO)
    assert rv.main([str(pasta), "--dry-run"]) == 0
    assert refeitos == [] and _ts(pasta)[:2] == ("00:00:10", "00:00:20")
    assert "dry-run" in capsys.readouterr().out


# ── flags_refazer ──────────────────────────────────────────────────────────

def test_flags_refazer_polido_e_legendado(tmp_path):
    c = tmp_path / "cortes"
    (c / "legendados").mkdir(parents=True)
    (c / "corte_01_x_polido.mp4").touch()
    (c / "legendados" / "corte_01_x_polido.mp4").touch()
    assert rv.flags_refazer(tmp_path, "01") == ["--polir"]


def test_flags_refazer_simples_sem_legenda(tmp_path):
    (tmp_path / "cortes").mkdir()
    (tmp_path / "cortes" / "corte_01_x.mp4").touch()
    assert rv.flags_refazer(tmp_path, "01") == ["--sem-legendas"]


def test_flags_refazer_outro_bloco_nao_conta(tmp_path):
    (tmp_path / "cortes").mkdir()
    (tmp_path / "cortes" / "corte_02_x_polido.mp4").touch()
    assert rv.flags_refazer(tmp_path, "01") == ["--sem-legendas"]


def test_refazer_bloco_monta_comando_do_pipeline(tmp_path, monkeypatch):
    pasta = tmp_path / "2026-10-26_v"
    (pasta / "cortes").mkdir(parents=True)
    vistos = []
    monkeypatch.setattr(rv.subprocess, "run",
                        lambda cmd, **k: vistos.append(cmd) or types.SimpleNamespace(returncode=0))
    assert rv.refazer_bloco(pasta, 3) is True
    cmd = vistos[0]
    assert cmd[1].endswith("pipeline.py") and "2026-10-26_v" in cmd and "--bloco=3" in cmd
    assert "--sem-legendas" in cmd
