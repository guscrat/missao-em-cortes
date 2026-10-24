"""hoje.curador_rodando: faixa "Curador rodando" / "parou no meio". Arquivo em tmp_path, pid falso."""
import json
import os

import pandas as pd

import hoje

AGORA = pd.Timestamp("2026-10-22 12:00:00")


def _ev(*linhas):
    """(horas_atras, etapa, stem)"""
    return pd.DataFrame([{"ts": AGORA - pd.Timedelta(hours=h), "agente": "pipeline", "etapa": e,
                          "status": "inicio", "mensagem": "", "stem": s} for h, e, s in linhas])


def _prog(tmp_path, **kw):
    p = tmp_path / "curador_progresso.json"
    p.write_text(json.dumps(kw), encoding="utf-8")
    return p


def _vivo(pid):
    return True


def test_nao_rodando(tmp_path):
    assert hoje.curador_rodando(pd.DataFrame(), AGORA, tmp_path / "nada.json") == []
    p = _prog(tmp_path, rodando=False, desde="2026-10-22T11:00:00", etapa="x", pid=1)
    assert hoje.curador_rodando(pd.DataFrame(), AGORA, p, vivo=_vivo) == []


def test_rodando_hoje_mostra_so_hora(tmp_path):
    p = _prog(tmp_path, rodando=True, desde="2026-10-22T11:00:00", etapa="revisor", pid=1,
              atualizado="2026-10-22T11:30:00")
    (nivel, titulo, det), = hoje.curador_rodando(pd.DataFrame(), AGORA, p, vivo=_vivo)
    assert nivel == "info" and titulo == "Curador rodando desde 11:00 — etapa revisor"
    assert "11:30" in det


def test_rodando_de_outro_dia_mostra_data(tmp_path):
    p = _prog(tmp_path, rodando=True, desde="2026-10-21T17:00:00", etapa="baixando", pid=1)
    (_, titulo, _), = hoje.curador_rodando(pd.DataFrame(), AGORA, p, vivo=_vivo)
    assert titulo == "Curador rodando desde 21/10 17:00 — etapa baixando"


def test_junta_step_do_pipeline(tmp_path):
    p = _prog(tmp_path, rodando=True, desde="2026-10-22T10:00:00", etapa="pipeline", pid=1,
              stem="live")
    ev = _ev((1.5, "04_cortar", "live"), (1.0, "06_montar", "live"),
             (1.0, "99_outro", "outro"),           # outro stem: ignora
             (5.0, "02_transcribe", "live"))       # antes da rodada: ignora
    (_, titulo, det), = hoje.curador_rodando(ev, AGORA, p, vivo=_vivo)
    assert titulo.endswith("etapa pipeline · 06_montar") and "live" in det


def test_pipeline_sem_evento_fica_pipeline(tmp_path):
    p = _prog(tmp_path, rodando=True, desde="2026-10-22T10:00:00", etapa="pipeline", pid=1,
              stem="live")
    (_, titulo, _), = hoje.curador_rodando(_ev(), AGORA, p, vivo=_vivo)
    assert titulo.endswith("etapa pipeline")


def test_pid_morto_e_erro(tmp_path):
    p = _prog(tmp_path, rodando=True, desde="2026-10-22T10:00:00", etapa="baixando", pid=999999)
    (nivel, titulo, det), = hoje.curador_rodando(pd.DataFrame(), AGORA, p, vivo=lambda pid: False)
    assert nivel == "erro" and titulo == "Curador parou no meio" and "baixando" in det


def test_pid_vivo_real():
    assert hoje._pid_vivo(os.getpid()) is True
    assert hoje._pid_vivo(None) is True                 # sem pid: não alarma
