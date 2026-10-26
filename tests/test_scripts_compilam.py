"""Todo script compila. Os scripts de pipeline rodam no nível do módulo e muitos não têm
teste que os importe: um erro de sintaxe passaria no CI (aconteceu no 06, PR #85)."""
import py_compile
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).parent.parent / "scripts").glob("*.py"))
PAINEL = sorted((Path(__file__).parent.parent / "painel").glob("*.py"))


@pytest.mark.parametrize("script", SCRIPTS + PAINEL, ids=lambda p: p.name)
def test_compila(script, tmp_path):
    py_compile.compile(str(script), cfile=str(tmp_path / "x.pyc"), doraise=True)
