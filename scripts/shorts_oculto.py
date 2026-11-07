"""Sobe a fila de Shorts escondido, sem janela de CMD: é o que o Agendador do Windows chama
todo dia (tarefa "MissaoEmCortes-Shorts", 17:50, depois do Curador).

Uso (Agendador): .venv\\Scripts\\pythonw.exe scripts\\shorts_oculto.py

Roda `09_upload.py todos --shorts`: sobe o que couber na cota do dia, cada Short passando
antes pela checagem de atualidade, e para sozinho quando a fila zera (rodada sem nada a
subir não gasta nada). Saída no state/shorts.log. O 09 grava o resumo da rodada
(state/shorts_fila.json + evento 09_shorts_rodada, que o painel mostra). Se o 09 quebrar
antes de gravar o resumo (token, rede, Traceback), a falha é registrada aqui → alerta.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOG = Path(os.environ.get("MISSAO_SHORTS_LOG") or ROOT / "state" / "shorts.log")
FILA = ROOT / "state" / "shorts_fila.json"

# pythonw não tem stdout/stderr (None): manda os dois pro log (ver curador_oculto)
if sys.stdout is None or sys.stderr is None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
sys.stdout.reconfigure(encoding="utf-8")

from _eventos import evento  # noqa: E402 — depois do stdout acima
CREATE_NO_WINDOW = 0x08000000


def comando() -> list[str]:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
    return [uv, "run", "py", "scripts/09_upload.py", "todos", "--shorts"]


def resumo_gravado(inicio: datetime, fila: Path | None = None) -> bool:
    """O 09 gravou o resumo desta rodada (shorts_fila.json com atualizado >= início)?"""
    import json
    try:
        atualizado = json.loads((fila or FILA).read_text(encoding="utf-8")).get("atualizado") or ""
        quando = datetime.fromisoformat(atualizado)
        if quando.tzinfo:   # o 09 grava em UTC; início é hora local sem fuso
            quando = quando.astimezone().replace(tzinfo=None)
        return quando >= inicio.replace(microsecond=0)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def ultima_linha(log: Path, desde: int) -> str:
    """Última linha não vazia que o 09 escreveu nesta rodada (o erro, quando quebra)."""
    try:
        with open(log, "rb") as f:
            f.seek(desde)
            linhas = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return next((x.strip() for x in reversed(linhas) if x.strip()), "")


def conferir(codigo: int | None, inicio: datetime, erro: str = "", detalhe: str = "") -> str | None:
    """Saiu com erro e o 09 não gravou o resumo = quebrou antes: registra a falha."""
    if codigo == 0 or (codigo is not None and resumo_gravado(inicio)):
        return None   # ok, ou o 09 já registrou a rodada (com as falhas dela)
    msg = erro or f"upload de Shorts quebrou (exit {codigo}): {detalhe or 'veja o state/shorts.log'}"
    evento(None, "09_shorts_rodada", "falha", agente="publicador", mensagem=msg[:300])
    return msg


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    inicio = datetime.now()
    codigo, erro = None, ""
    with open(LOG, "ab") as log:
        log.write(f"\n=== {inicio:%d/%m %H:%M} shorts_oculto (sem janela) ===\n".encode("utf-8"))
        log.flush()
        desde = log.tell()
        try:
            codigo = subprocess.run(comando(), cwd=ROOT, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=CREATE_NO_WINDOW if sys.platform == "win32"
                                    else 0).returncode
        except OSError as e:
            erro = f"não consegui iniciar o upload de Shorts ({e})"
            log.write(f"[!] {erro}\n".encode("utf-8"))
    msg = conferir(codigo, inicio, erro, ultima_linha(LOG, desde))
    if msg:
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(f"[!] {msg}\n")
    return 1 if codigo is None else codigo


if __name__ == "__main__":
    sys.exit(main())
