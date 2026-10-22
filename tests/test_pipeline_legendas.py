"""pipeline.py: legenda karaokê (04c) ligada por padrão. subprocess/evento mockados."""
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _eventos

PIPELINE = Path(__file__).parent.parent / "scripts" / "pipeline.py"


def _rodar(monkeypatch, argv, falha_em=None):
    """Roda pipeline.py como módulo. Retorna (comandos [(script, args)], SystemExit|None)."""
    cmds = []

    def fake_run(cmd, *a, **k):
        script = Path(cmd[1]).name
        cmds.append((script, list(cmd[2:])))
        return SimpleNamespace(returncode=1 if script == falha_em else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(_eventos, "evento", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "stem_x", "--desde=3", *argv])
    saida = None
    try:
        runpy.run_path(str(PIPELINE), run_name="__main__")
    except SystemExit as e:
        saida = e
    return cmds, saida


def _por_script(cmds):
    return {s: a for s, a in cmds}


def test_padrao_inclui_legendas_e_montar_legendado(monkeypatch):
    cmds, _ = _rodar(monkeypatch, [])
    d = _por_script(cmds)
    assert "04c_legendas.py" in d
    assert "--legendado" in d["06_montar.py"]
    scripts = [s for s, _ in cmds]
    assert scripts.index("04_cortar.py") < scripts.index("04c_legendas.py") < scripts.index("05_cards.py")


def test_sem_legendas_remove_04c_e_legendado(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--sem-legendas"])
    d = _por_script(cmds)
    assert "04c_legendas.py" not in d
    assert "--legendado" not in d["06_montar.py"]


def test_polir_passa_polido_ao_04c(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--polir"])
    d = _por_script(cmds)
    assert "--polido" in d["04c_legendas.py"]
    assert "--polido" in d["06_montar.py"] and "--legendado" in d["06_montar.py"]
    assert "--polido" not in _por_script(_rodar(monkeypatch, [])[0])["04c_legendas.py"]


def test_retomada_inclui_sem_legendas(monkeypatch):
    _, saida = _rodar(monkeypatch, ["--sem-legendas"], falha_em="04_cortar.py")
    assert saida is not None and "--sem-legendas" in str(saida.code)
    assert "--desde=4" in str(saida.code)


def test_retomada_padrao_nao_menciona_sem_legendas(monkeypatch):
    _, saida = _rodar(monkeypatch, [], falha_em="04c_legendas.py")
    assert "--sem-legendas" not in str(saida.code)
    assert "--desde=4c" in str(saida.code)


def test_desde_depois_do_04c_sem_legendados_falha_alto(monkeypatch):
    # stem_x não tem pasta em outputs/: nenhum corte legendado
    cmds, saida = _rodar(monkeypatch, ["--desde=5"])
    assert saida is not None and "--desde=4c" in str(saida.code)
    assert cmds == []                                   # nenhum step rodou


def test_desde_depois_do_04c_com_sem_legendas_segue(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--desde=5", "--sem-legendas"])
    assert [s for s, _ in cmds][0] == "05_cards.py"
