"""Curador (13): progresso em state/curador_progresso.json e evento curador_rodada. Tudo falso."""
import sqlite3
from types import SimpleNamespace

import pytest

# reaproveita o módulo carregado e as fixtures (projeto falso em tmp_path, fakes da rodada)
from test_curador import cu, raiz, rodada  # noqa: F401


def _rodadas(banco):
    try:
        return banco("SELECT 1 FROM eventos WHERE etapa='curador_rodada'")
    except sqlite3.OperationalError:       # banco nem foi criado: nenhum evento
        return []


def test_progresso_inicio_etapas_e_encerrar(raiz):
    assert cu.ler_progresso() == {}
    cu.marcar_etapa("lendo", inicio=True)
    p = cu.ler_progresso()
    assert p["rodando"] is True and p["etapa"] == "lendo" and p["desde"] and p["pid"] > 0
    desde = p["desde"]
    cu.marcar_etapa("pipeline", stem="abc")
    cu.marcar_etapa("revisor")                                      # stem fica até a troca
    p = cu.ler_progresso()
    assert (p["etapa"], p["stem"], p["desde"]) == ("revisor", "abc", desde)
    cu.marcar_etapa("nova", inicio=True)                            # inicio zera tudo
    assert "stem" not in cu.ler_progresso()
    cu.encerrar_progresso(0)
    p = cu.ler_progresso()
    assert p["rodando"] is False and p["codigo"] == 0 and p["fim"]


def test_progresso_corrompido_vira_vazio(raiz):
    cu.PROGRESSO.parent.mkdir(parents=True, exist_ok=True)
    cu.PROGRESSO.write_text("{quebrado", encoding="utf-8")
    assert cu.ler_progresso() == {}
    cu.PROGRESSO.write_text("[1]", encoding="utf-8")
    assert cu.ler_progresso() == {}


def test_rodada_ok_registra_evento_e_encerra_progresso(raiz, rodada, banco):
    assert cu.main([]) == 0
    ev = banco("SELECT status FROM eventos WHERE etapa='curador_rodada' ORDER BY id")
    assert [e["status"] for e in ev] == ["inicio", "ok"]
    p = cu.ler_progresso()
    assert p["rodando"] is False and p["codigo"] == 0
    assert not cu.TRAVA.exists()


def test_rodada_excecao_registra_falha_e_repropaga(raiz, rodada, banco, monkeypatch):
    def estoura(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(cu, "sincronizar_canal", estoura)
    with pytest.raises(RuntimeError):
        cu.main([])
    ev = banco("SELECT status, mensagem FROM eventos WHERE etapa='curador_rodada' ORDER BY id")
    assert [e["status"] for e in ev] == ["inicio", "falha"]
    assert "RuntimeError: boom" in ev[1]["mensagem"]
    p = cu.ler_progresso()
    assert p["rodando"] is False and p["codigo"] is None
    assert not cu.TRAVA.exists()


def test_trava_ocupada_sai_75_sem_progresso_nem_evento(raiz, rodada, banco):
    cu.TRAVA.parent.mkdir(parents=True, exist_ok=True)
    cu.TRAVA.write_text("123", encoding="utf-8")
    assert cu.main([]) == cu.SAIDA_TRAVADO == 75
    assert not cu.PROGRESSO.exists()
    assert _rodadas(banco) == []


def test_dry_run_nao_cria_progresso_trava_nem_evento(raiz, rodada, banco):
    assert cu.main(["--dry-run"]) == 0
    assert not cu.PROGRESSO.exists() and not cu.TRAVA.exists()
    assert _rodadas(banco) == []


def test_rodar_marca_etapa_com_rotulo(raiz, monkeypatch):
    monkeypatch.setattr(cu.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert cu.rodar("01_baixar.py", "u") is True
    assert cu.ler_progresso()["etapa"] == "baixando"
    cu.rodar("outro.py")
    assert cu.ler_progresso()["etapa"] == "outro.py"
