"""Resolução das pastas de saída do pipeline.

Estrutura: uma pasta por vídeo em outputs/AAAA-MM-DD_<stem>/ (data = processamento).
O prefixo ISO faz a ordenação alfabética coincidir com a cronológica.

Regra de segurança: como os outputs viram input dos passos seguintes, NUNCA
adivinhamos qual pasta usar. O resolvedor falha alto se um stem for ambíguo.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUTS = ROOT / "outputs"
UPLOAD_JSON = ROOT / "config" / "upload.json"
CANAIS_JSON = ROOT / "config" / "canais.json"
THUMB_JSON = ROOT / "config" / "thumb.json"
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def auditoria_aprovada() -> bool:
    """Flag "auditoria_aprovada" do config/upload.json. Enquanto for false, os Shorts não
    sobem (nem pela API, nem à mão): estoque do Curador e publicacao.txt contam só longos.
    Arquivo ausente/ilegível ou valor que não seja true = travado."""
    try:
        return json.loads(UPLOAD_JSON.read_text(encoding="utf-8")).get("auditoria_aprovada") is True
    except (OSError, ValueError, AttributeError):
        return False


def modo_thumb() -> str:
    """config/thumb.json → "modo": 'ab' (a/b/c = 3 versões da clássica com frames e textos
    diferentes, pro "Testar e comparar") ou 'classica' (a/b/c = 3 frames, mesmo texto).
    Arquivo ausente/ilegível ou outro valor = 'classica'."""
    try:
        modo = json.loads(THUMB_JSON.read_text(encoding="utf-8")).get("modo")
    except (OSError, ValueError, AttributeError):
        return "classica"
    return "ab" if modo == "ab" else "classica"


def modo_evento(hoje: date | None = None, cfg: dict | None = None) -> dict | None:
    """Modo evento do config/canais.json (ex.: 2º turno): {"desde", "ate", "tema"} enquanto
    "modo_evento" for true e hoje estiver entre modo_evento_desde e modo_evento_ate
    (inclusive). Depois do "ate" desliga sozinho, mesmo com a flag ainda true. Sem config,
    flag false ou data ilegível = None (desligado). cfg = canais.json já lido (o Curador)."""
    hoje = hoje or date.today()
    try:
        cfg = cfg if cfg is not None else json.loads(CANAIS_JSON.read_text(encoding="utf-8"))
        if cfg.get("modo_evento") is not True:
            return None
        ate = date.fromisoformat(cfg["modo_evento_ate"])
        desde = date.fromisoformat(cfg.get("modo_evento_desde") or hoje.isoformat())
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    if not desde <= hoje <= ate:
        return None
    return {"desde": desde, "ate": ate, "tema": cfg.get("modo_evento_tema") or "evento"}


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


def escolher_arquivo(pasta: Path, padrao: str, preferir_polido: bool = True) -> Path | None:
    """Primeiro arquivo que casa com o glob, preferindo a versão mais trabalhada:
    _polido_legendado > _legendado > _polido > original."""
    achados = sorted(pasta.glob(padrao)) if pasta.is_dir() else []
    if not achados:
        return None
    if preferir_polido:
        return min(achados, key=lambda a: (not a.stem.endswith("_legendado"),
                                           "_polido" not in a.stem))
    return achados[0]


def escolher_thumb(pasta_thumbs: Path, nn: str) -> Path | None:
    """Thumb escolhida do bloco: manual > a > b > c > sem sufixo.
    Na prática você apaga as variantes descartadas, então sobra só a escolhida."""
    for padrao in (f"thumb_{nn}_manual.png", f"thumb_{nn}_a.png", f"thumb_{nn}_b.png",
                   f"thumb_{nn}_c.png", f"thumb_{nn}.png"):
        p = pasta_thumbs / padrao
        if p.exists():
            return p
    return None
