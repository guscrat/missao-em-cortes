"""Resolução das pastas de saída do pipeline.

Estrutura: uma pasta por vídeo em outputs/AAAA-MM-DD_<stem>/ (data = processamento).
O prefixo ISO faz a ordenação alfabética coincidir com a cronológica.

Regra de segurança: como os outputs viram input dos passos seguintes, NUNCA
adivinhamos qual pasta usar. O resolvedor falha alto se um stem for ambíguo.
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUTS = ROOT / "outputs"
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def stem_de(pasta: Path) -> str:
    """Stem do vídeo a partir do nome da pasta (tira o prefixo de data)."""
    return _DATE_PREFIX.sub("", pasta.name)


def _matches(stem: str) -> list[Path]:
    return sorted(p for p in OUTPUTS.glob(f"*_{stem}") if p.is_dir())


def achar_pasta(arg: str) -> Path:
    """Resolve o argumento (stem OU nome/caminho da pasta) pra pasta do vídeo.

    Aceita: 'renan_vorcaro' (stem), '2026-06-03_renan_vorcaro' (nome completo)
    ou um caminho. Falha alto se ambíguo ou inexistente — nunca chuta.
    """
    p = Path(arg)
    if p.is_dir():
        return p
    cand = OUTPUTS / p.name
    if cand.is_dir():
        return cand

    stem = p.name
    ms = _matches(stem)
    if len(ms) == 1:
        return ms[0]
    if not ms:
        sys.exit(f"[!] Não achei pasta pra '{stem}' em outputs/. "
                 f"Rode a transcrição (step 2) antes.")
    nomes = "\n".join(f"   - {m.name}" for m in ms)
    sys.exit(f"[!] Ambíguo: há mais de uma pasta pra '{stem}':\n{nomes}\n"
             f"    Passe o nome COMPLETO da pasta (ex: {ms[-1].name}).")


def criar_pasta(stem: str) -> Path:
    """Pra a transcrição (step 2): reusa a pasta do stem se já existir, senão cria
    outputs/<hoje>_<stem>/. Garante no máximo uma pasta por stem."""
    ms = _matches(stem)
    if len(ms) == 1:
        return ms[0]
    if len(ms) > 1:
        nomes = "\n".join(f"   - {m.name}" for m in ms)
        sys.exit(f"[!] Há mais de uma pasta pra '{stem}':\n{nomes}\n"
                 f"    Resolva manualmente (apague/renomeie) antes de reprocessar.")
    pasta = OUTPUTS / f"{date.today().isoformat()}_{stem}"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta
