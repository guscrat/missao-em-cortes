"""Roda o Curador (13) escondido, sem janela de CMD: é o que o Agendador do Windows chama.

Uso (Agendador): .venv\\Scripts\\pythonw.exe scripts\\curador_oculto.py [args do 13]

pythonw não abre console, e o 13 roda com CREATE_NO_WINDOW: ganha um console invisível que
uv/ffmpeg/yt-dlp herdam, então nenhum filho pisca janela. Saída vai pro state/curador.log.
O progresso aparece no painel (state/curador_progresso.json, gravado pelo próprio 13). Se o
Curador morrer no meio ou nem começar, registra falha no banco → alerta no painel.
"""
import importlib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOG = Path(os.environ.get("MISSAO_CURADOR_LOG") or ROOT / "state" / "curador.log")

# pythonw não tem stdout/stderr (None): os imports abaixo fazem sys.stdout.reconfigure e
# quebravam antes de tudo. Manda os dois pro log: erro do próprio lançador vira Traceback
# lá (alerta "Curador quebrou" no painel) em vez de sumir.
if sys.stdout is None or sys.stderr is None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
sys.stdout.reconfigure(encoding="utf-8")

from _eventos import evento  # noqa: E402 — depois do stdout acima
CREATE_NO_WINDOW = 0x08000000
curador = importlib.import_module("13_curador")


def comando(argv: list[str]) -> list[str]:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
    return [uv, "run", "py", "scripts/13_curador.py", *argv]


def conferir(codigo: int | None, inicio: datetime, erro: str = "") -> str | None:
    """Depois que o 13 saiu: rodada desta vez ainda "rodando" = morreu no meio; nem gravou
    progresso e saiu com erro = nem começou. Registra a falha e devolve a mensagem."""
    prog = curador.ler_progresso()
    desta_vez = (prog.get("desde") or "") >= inicio.isoformat(timespec="seconds")
    if desta_vez and prog.get("rodando"):
        msg = f"Curador parou no meio (etapa \"{prog.get('etapa', '?')}\", exit {codigo})"
        curador.encerrar_progresso(codigo)
    elif not desta_vez and codigo not in (0, curador.SAIDA_TRAVADO):
        msg = erro or f"Curador nem começou (exit {codigo}) — veja o state/curador.log"
    else:
        return None
    evento(None, "curador_rodada", "falha", agente="curador", mensagem=msg[:300])
    return msg


def main(argv: list[str]) -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    inicio = datetime.now()
    codigo, erro = None, ""
    with open(LOG, "ab") as log:
        log.write(f"\n=== {inicio:%d/%m %H:%M} curador_oculto (sem janela) ===\n".encode("utf-8"))
        log.flush()
        try:
            codigo = subprocess.run(comando(argv), cwd=ROOT, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=CREATE_NO_WINDOW if sys.platform == "win32"
                                    else 0).returncode
        except OSError as e:
            erro = f"não consegui iniciar o Curador ({e})"
            log.write(f"[!] {erro}\n".encode("utf-8"))
    msg = conferir(codigo, inicio, erro)
    if msg:
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(f"[!] {msg}\n")
    return 1 if codigo is None else codigo


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
