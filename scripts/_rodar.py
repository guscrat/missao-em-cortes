"""Roda um script filho repassando o stderr ao vivo e guardando a última linha dele
(o detalhe da falha que o pipeline grava no banco e o painel mostra)."""
import os
import subprocess
import sys


def _repassar(pedaco: bytes) -> None:
    saida = getattr(sys.stderr, "buffer", None)   # pythonw: sys.stderr é None
    if saida is None:
        return
    saida.write(pedaco)
    sys.stderr.flush()


def rodar(cmd: list[str]) -> tuple[int, str]:
    """(exit code, última linha não vazia do stderr, até 200 caracteres)."""
    # utf-8 no filho: no Windows o stderr em pipe sairia em cp1252 ("inv�lido")
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    cauda = b""
    for pedaco in iter(lambda: proc.stderr.read1(4096), b""):
        _repassar(pedaco)
        cauda = (cauda + pedaco)[-4000:]
    codigo = proc.wait()
    linhas = [l.strip() for l in cauda.decode("utf-8", "replace").replace("\r", "\n").splitlines()]
    return codigo, next((l for l in reversed(linhas) if l), "")[:200]
