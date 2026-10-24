"""curador_oculto: lançador sem janela. subprocess falso, paths em tmp_path, banco falso."""
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import curador_oculto as co

INICIO = datetime(2026, 10, 24, 17, 0, 0)


@pytest.fixture
def amb(tmp_path, monkeypatch, banco):
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(co, "LOG", tmp_path / "state" / "curador.log")
    monkeypatch.setattr(co, "ROOT", tmp_path)
    monkeypatch.setattr(co.curador, "PROGRESSO", tmp_path / "state" / "curador_progresso.json")
    return SimpleNamespace(banco=banco, prog=co.curador.PROGRESSO, log=co.LOG)


def _prog(amb, desde, **kw):
    amb.prog.write_text(json.dumps({"desde": desde.isoformat(timespec="seconds"), **kw}),
                        encoding="utf-8")


def _falhas(amb):
    try:
        return amb.banco("SELECT mensagem FROM eventos WHERE etapa='curador_rodada' AND status='falha'")
    except sqlite3.OperationalError:       # banco nem foi criado: nenhum evento
        return []


def test_comando_inclui_args():
    assert co.comando(["--dry-run"])[1:] == ["run", "py", "scripts/13_curador.py", "--dry-run"]


def test_conferir_ok_sem_falha(amb):
    _prog(amb, INICIO + timedelta(seconds=1), rodando=False, codigo=0)
    assert co.conferir(0, INICIO) is None
    assert _falhas(amb) == []


def test_conferir_morreu_no_meio(amb):
    _prog(amb, INICIO + timedelta(seconds=1), rodando=True, etapa="pipeline")
    msg = co.conferir(1, INICIO)
    assert "parou no meio" in msg and "pipeline" in msg
    assert len(_falhas(amb)) == 1
    assert json.loads(amb.prog.read_text(encoding="utf-8"))["rodando"] is False


def test_conferir_nem_comecou(amb):
    _prog(amb, INICIO - timedelta(hours=3), rodando=False)          # progresso de rodada antiga
    msg = co.conferir(2, INICIO)
    assert "nem começou" in msg and len(_falhas(amb)) == 1


def test_conferir_sem_progresso_saida_zero_ou_trava_nao_acusa(amb):
    assert co.conferir(0, INICIO) is None
    assert co.conferir(75, INICIO) is None
    assert _falhas(amb) == []


def test_conferir_usa_erro_de_inicio(amb):
    assert co.conferir(None, INICIO, "não consegui iniciar (x)") == "não consegui iniciar (x)"
    assert len(_falhas(amb)) == 1


def test_main_devolve_codigo_e_escreve_log(amb, monkeypatch):
    chamadas = []

    def run(cmd, **kw):
        chamadas.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(co.subprocess, "run", run)
    assert co.main(["--forcar"]) == 0
    assert chamadas[0][-1] == "--forcar"
    assert "curador_oculto" in amb.log.read_text(encoding="utf-8")
    assert _falhas(amb) == []


def test_main_oserror_vira_falha(amb, monkeypatch):
    def run(*a, **k):
        raise OSError("sem uv")
    monkeypatch.setattr(co.subprocess, "run", run)
    assert co.main([]) == 1
    f = _falhas(amb)
    assert len(f) == 1 and "sem uv" in f[0]["mensagem"]
    assert "sem uv" in amb.log.read_text(encoding="utf-8")


def test_main_codigo_erro_sem_progresso_registra_falha(amb, monkeypatch):
    monkeypatch.setattr(co.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3))
    assert co.main([]) == 3
    assert "exit 3" in _falhas(amb)[0]["mensagem"]
    assert "exit 3" in amb.log.read_text(encoding="utf-8")


def test_main_trava_75_nao_acusa(amb, monkeypatch):
    monkeypatch.setattr(co.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=75))
    assert co.main([]) == 75
    assert _falhas(amb) == []
