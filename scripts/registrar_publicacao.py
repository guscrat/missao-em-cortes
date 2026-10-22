"""Registra o que foi publicado À MÃO (Studio), pra o painel e o estoque do Curador.

Enquanto o upload pela API (09) está travado pela auditoria, o Gu sobe os vídeos no Studio.
Sem registrar, o bloco continua "Pronto para publicar" e o Curador acha que tem estoque.

Uso:
  uv run py scripts/registrar_publicacao.py <stem> --bloco=N --video=<URL ou id> [--quando=AAAA-MM-DD[THH:MM]]
  uv run py scripts/registrar_publicacao.py <stem> --bloco=N --short [--quando=AAAA-MM-DD]

  --video   longo subiu: bloco vira "agendado" (publicação no futuro) ou "publicado"
            (já no ar), com youtube_id e publish_at. --quando padrão: agora.
  --short   o Short do bloco foi postado: marca "postado" no shorts/shorts.json
            (sai do estoque de Shorts). --quando padrão: hoje.

Custo: $0. Eventos com agente="publicador".
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from _eventos import evento, upsert_bloco
from _paths import achar_pasta, stem_de

FUSO = "-03:00"      # Brasília (como o 09_upload grava o publish_at)
ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/)?([\w-]{11})(?:[?&#].*)?$")


def youtube_id(valor: str) -> str | None:
    m = ID_RE.search(valor.strip())
    return m.group(1) if m else None


def quando_iso(valor: str | None, agora: datetime | None = None) -> datetime:
    agora = agora or datetime.now()
    if not valor:
        return agora.replace(second=0, microsecond=0)
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        raise SystemExit(f"[!] --quando inválido: '{valor}' (use AAAA-MM-DD ou AAAA-MM-DDTHH:MM)")


def registrar_video(stem: str, bloco: int, vid: str, quando: datetime,
                    agora: datetime | None = None) -> str:
    status = "agendado" if quando > (agora or datetime.now()) else "publicado"
    upsert_bloco(stem, bloco, status=status, youtube_id=vid,
                 publish_at=quando.strftime("%Y-%m-%dT%H:%M:%S") + FUSO, forcar_status=True)
    evento(stem, "publicacao_manual", "ok", bloco_id=bloco, agente="publicador",
           mensagem=f"longo {status} à mão: youtube {vid} em {quando:%d/%m/%Y %H:%M}")
    return status


def registrar_short(pasta: Path, stem: str, bloco: int, quando: datetime) -> None:
    caminho = pasta / "shorts" / "shorts.json"
    try:
        registro = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registro = {}
    nn = f"{bloco:02d}"
    if nn not in registro:
        raise SystemExit(f"[!] bloco {bloco} não tem Short em {caminho} (gere com 10_shorts.py)")
    registro[nn]["postado"] = quando.date().isoformat()
    caminho.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    evento(stem, "publicacao_manual", "ok", bloco_id=bloco, agente="publicador",
           mensagem=f"Short postado à mão em {quando:%d/%m/%Y}")


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in argv if not a.startswith("--")]
    opcoes = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "") for a in argv if a.startswith("--"))
    if not args or "bloco" not in opcoes or ("video" in opcoes) == ("short" in opcoes):
        print(__doc__)
        return 1
    pasta = achar_pasta(args[0])
    stem, bloco = stem_de(pasta), int(opcoes["bloco"])
    quando = quando_iso(opcoes.get("quando"))
    if "short" in opcoes:
        registrar_short(pasta, stem, bloco, quando)
        print(f"OK Short do bloco {bloco} de {stem} marcado como postado ({quando:%d/%m})")
        return 0
    vid = youtube_id(opcoes["video"])
    if not vid:
        raise SystemExit(f"[!] não achei o id do YouTube em '{opcoes['video']}'")
    status = registrar_video(stem, bloco, vid, quando)
    print(f"OK bloco {bloco} de {stem}: {status} ({vid}, {quando:%d/%m %H:%M})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
