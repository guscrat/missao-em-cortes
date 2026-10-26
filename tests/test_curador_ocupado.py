"""Curador (13): trava de concorrência (outro processamento rodando) e alerta no painel. Tudo falso."""
import json
import os
import subprocess

import pandas as pd
import pytest

from test_curador import _av, _item, cu, raiz, rodada  # noqa: F401

import hoje

OUTRO = r"python C:\proj\scripts\02_transcribe.py inputs\x.mp4"


@pytest.mark.parametrize("linha", [
    "py scripts/01_baixar.py https://youtu.be/x kim_x",
    r"py C:\p\scripts\02_transcribe.py inputs\x.mp4",
    "py scripts/04b_polir.py x",
    r"python.exe scripts\pipeline.py x --polir",
    "py scripts/10_shorts.py x",
    r"py scripts\11_revisor.py x",
])
def test_pesados_casa(linha):
    assert cu.PESADOS_RE.search(linha)


@pytest.mark.parametrize("linha", [
    "py scripts/09_upload.py x", "py scripts/13_curador.py", "py scripts/12_metricas.py",
    "py scripts/14_canal.py", "py scripts/curador_oculto.py", "notepad.exe",
])
def test_pesados_nao_casa(linha):
    assert not cu.PESADOS_RE.search(linha)


def test_em_andamento_filtra_e_ignora_proprio_pid():
    procs = [(1, "py scripts/02_transcribe.py a.mp4"), (2, "py scripts/09_upload.py x"),
             (os.getpid(), "py scripts/pipeline.py eu"), (3, "chrome.exe")]
    assert cu.processamento_em_andamento(lambda: procs) == ["py scripts/02_transcribe.py a.mp4"]


@pytest.mark.parametrize("exc", [OSError("x"), subprocess.SubprocessError("y"),
                                 subprocess.TimeoutExpired("ps", 1)])
def test_em_andamento_erro_ao_listar_segue_livre(exc):
    def listar():
        raise exc
    assert cu.processamento_em_andamento(listar) == []


def test_resumir_ocupado_script_e_stem_sem_flags_nem_url():
    assert cu.resumir_ocupado([r"py C:\p\scripts\01_baixar.py --x https://youtu.be/abc renan_x"]) \
        == "01_baixar.py renan_x"
    assert cu.resumir_ocupado(["a", "py scripts/pipeline.py kim_y --polir"]) == "pipeline.py kim_y"
    assert cu.resumir_ocupado(["py scripts/02_transcribe.py"]) == "02_transcribe.py"


def test_esperar_livre_livre_na_hora_nao_dorme():
    dormiu = []
    assert cu.esperar_livre(5, 10, checar=lambda: [], dormir=dormiu.append) == []
    assert dormiu == []


def test_esperar_livre_libera_depois_de_n_checagens(raiz):
    respostas = iter([[OUTRO], [OUTRO], []])
    dormiu = []
    assert cu.esperar_livre(5, 7, checar=lambda: next(respostas), dormir=dormiu.append) == []
    assert dormiu == [7, 7]


def test_esperar_livre_continua_ocupado_devolve_lista(raiz, monkeypatch):
    t = {"v": 0.0}
    monkeypatch.setattr(cu.time, "monotonic", lambda: t["v"])

    def dormir(s):
        t["v"] += s
    r = cu.esperar_livre(1, 30, checar=lambda: [OUTRO], dormir=dormir)
    assert r == [OUTRO] and t["v"] == 60


def test_esperar_livre_espera_zero_nao_dorme():
    dormiu = []
    assert cu.esperar_livre(0, 10, checar=lambda: [OUTRO], dormir=dormiu.append) == [OUTRO]
    assert dormiu == []


def test_rodada_ocupado_pula_sem_processar(raiz, rodada, banco):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 8)}
    rodada["ocupado"] = [OUTRO]
    cu.main([])
    assert rodada["processados"] == []
    estado = json.loads(cu.ESTADO.read_text(encoding="utf-8"))
    assert estado["a"]["decisao"] == "fila" and estado["a"]["tentativas"] == 0
    ev = banco("SELECT status, mensagem FROM eventos WHERE etapa='curador_pulado'")
    assert len(ev) == 1 and ev[0]["status"] == "aviso" and "02_transcribe.py" in ev[0]["mensagem"]
    resumo = cu.RESUMO.read_text(encoding="utf-8")
    assert "pulei o processamento" in resumo and "Live Alfa" in resumo


def test_rodada_livre_nao_gera_pulado(raiz, rodada, banco):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 8)}
    cu.main([])
    assert rodada["processados"] == ["renan_live_alfa"]
    assert banco("SELECT 1 FROM eventos WHERE etapa='curador_pulado'") == []


# --- painel ---------------------------------------------------------------------------------

AGORA = pd.Timestamp("2026-10-26 12:00:00")


def _ev(*linhas):
    """(horas_atras, etapa, status, agente)"""
    return pd.DataFrame([{"ts": AGORA - pd.Timedelta(hours=h), "agente": ag, "etapa": e,
                          "status": st, "mensagem": "pulei: outro rodando", "stem": None}
                         for h, e, st, ag in linhas])


def test_alerta_pulado_aparece():
    (nivel, titulo, det), = hoje._alerta_pulado(_ev((2, "curador_pulado", "aviso", "curador")), AGORA)
    assert nivel == "aviso" and titulo == "Curador pulou o processamento" and "pulei" in det


def test_alerta_pulado_vazio_ou_sem_pulo():
    assert hoje._alerta_pulado(pd.DataFrame(), AGORA) == []
    assert hoje._alerta_pulado(_ev((2, "curador_rodada", "ok", "curador")), AGORA) == []


def test_alerta_pulado_some_com_pipeline_depois():
    ev = _ev((5, "curador_pulado", "aviso", "curador"), (1, "curador_pipeline", "ok", "curador"))
    assert hoje._alerta_pulado(ev, AGORA) == []


def test_alerta_pulado_pipeline_antes_nao_apaga():
    ev = _ev((9, "curador_pipeline", "ok", "curador"), (3, "curador_pulado", "aviso", "curador"))
    assert len(hoje._alerta_pulado(ev, AGORA)) == 1


def test_alerta_pulado_fora_da_janela_de_48h():
    assert hoje._alerta_pulado(_ev((49, "curador_pulado", "aviso", "curador")), AGORA) == []


def test_alertas_curador_inclui_pulado(tmp_path):
    ev = _ev((2, "curador_pulado", "aviso", "curador"))
    saida = hoje.alertas_curador(ev, AGORA, tmp_path / "sem.log")
    assert [t for _, t, _ in saida] == ["Curador pulou o processamento"]
