"""Falha da API/ffmpeg não pode passar calada: descrever_erro + saída com erro no 04b e 06.

04b/06 rodam no nível do módulo; extraímos (ast) só o bloco final `if falhas:` e o
executamos num namespace isolado. Sem API, sem ffmpeg.
"""
import ast
import sys
from pathlib import Path

import pytest

import _custo

SCRIPTS = Path(__file__).parent.parent / "scripts"
MSG_LIMITE = ("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
              "'message': 'You have reached your specified API usage limits. You will regain "
              "access on 2026-11-01 at 00:00 UTC.'}}")


def test_descrever_erro_limite_de_uso():
    assert "limite de uso" in _custo.descrever_erro(Exception(MSG_LIMITE))


def test_descrever_erro_sem_credito():
    e = Exception("Your credit balance is too low to access the Anthropic API")
    assert "sem crédito" in _custo.descrever_erro(e)


def test_descrever_erro_generico_usa_nome_da_excecao():
    assert _custo.descrever_erro(ValueError("qualquer coisa")) == "ValueError"


def _bloco_falhas(arquivo):
    arvore = ast.parse((SCRIPTS / arquivo).read_text(encoding="utf-8"))
    nos = [n for n in arvore.body if isinstance(n, ast.If)
           and isinstance(n.test, ast.Name) and n.test.id == "falhas"]
    assert nos, f"{arquivo}: sem `if falhas:` no nível do módulo"
    return ast.Module(body=[nos[-1]], type_ignores=[])


def _rodar(arquivo, falhas):
    eventos = []
    ns = {"sys": sys, "falhas": falhas, "stem": "x",
          "evento": lambda *a, **k: eventos.append((a, k))}
    exec(compile(_bloco_falhas(arquivo), arquivo, "exec"), ns)
    return eventos


def test_04b_sai_com_erro():
    with pytest.raises(SystemExit) as exc:
        _rodar("04b_polir.py", [(3, "limite de uso da API atingido")])
    assert "bloco 3" in str(exc.value.code)


def test_04b_sem_falhas_nao_sai():
    assert _rodar("04b_polir.py", []) == []


def test_06_sai_com_erro_listando_blocos():
    with pytest.raises(SystemExit) as exc:
        _rodar("06_montar.py", [2, 5])
    assert "2, 5" in str(exc.value.code)


def test_06_sem_falhas_nao_sai():
    _rodar("06_montar.py", [])
