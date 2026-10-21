"""Varre outputs/ e inputs/ e (re)popula o banco do painel a partir dos arquivos.

Uso: uv run py scripts/sincronizar_estado.py

Idempotente: pode rodar quantas vezes quiser. Serve pra:
  - backfill dos vídeos processados antes do painel existir
  - "consertar" o banco se algo saiu do ar no meio

Status derivado dos arquivos (só sobrescreve status AUTO — decisões de
revisor/publicador como 'agendado' ou 'quarentena' nunca são rebaixadas):
  blocos.json com o bloco      -> segmentado
  cortes/corte_NN_*.mp4        -> cortado
  finalizados/video_NN_*.mp4   -> montado
"""
import json
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

from _eventos import upsert_bloco, upsert_video, DB_PATH
from _paths import OUTPUTS, ROOT, stem_de

INPUTS = ROOT / "inputs"
_PASTA_VIDEO = re.compile(r"^\d{4}-\d{2}-\d{2}_.+")


def _primeiro(pasta: Path, padrao: str, preferir_polido: bool = True) -> Path | None:
    achados = sorted(pasta.glob(padrao)) if pasta.is_dir() else []
    if not achados:
        return None
    if preferir_polido:
        polidos = [a for a in achados if a.stem.endswith("_polido")]
        if polidos:
            return polidos[0]
    return achados[0]


def _thumb(pasta_thumbs: Path, nn: str) -> Path | None:
    # manual > a/b/c > sem sufixo — o painel mostra a "melhor" disponível
    for padrao in (f"thumb_{nn}_manual.png", f"thumb_{nn}_a.png", f"thumb_{nn}.png"):
        p = pasta_thumbs / padrao
        if p.exists():
            return p
    return None


def sincronizar_pasta(pasta: Path) -> tuple[str, int]:
    stem = stem_de(pasta)
    url_file = INPUTS / f"{stem}.url"
    fonte_url = url_file.read_text(encoding="utf-8").strip() if url_file.exists() else None

    blocos_json = pasta / "blocos.json"
    if blocos_json.exists():
        status_video = "segmentado"
    elif (pasta / "transcricao.txt").exists():
        status_video = "transcrito"
    elif (INPUTS / f"{stem}.mp4").exists():
        status_video = "baixado"
    else:
        status_video = None

    upsert_video(stem, pasta=pasta.name, fonte_url=fonte_url, status=status_video)
    if not blocos_json.exists():
        return stem, 0

    blocos = json.loads(blocos_json.read_text(encoding="utf-8")).get("blocos", [])
    for b in blocos:
        nn = f"{b['id']:02d}"
        corte = _primeiro(pasta / "cortes", f"corte_{nn}_*.mp4")
        final = _primeiro(pasta / "finalizados", f"video_{nn}_*.mp4")
        thumb = _thumb(pasta / "thumbs", nn)

        status = "montado" if final else "cortado" if corte else "segmentado"
        upsert_bloco(
            stem, b["id"],
            status=status,
            tema=b.get("tema"),
            titulo=b.get("titulo_sugerido"),
            texto_thumb=b.get("texto_thumb"),
            score=b.get("score_potencial"),
            duracao_min=b.get("duracao_minutos"),
            video_path=str(final.relative_to(ROOT)) if final else None,
            thumb_path=str(thumb.relative_to(ROOT)) if thumb else None,
        )
    return stem, len(blocos)


def main() -> None:
    if not OUTPUTS.is_dir():
        sys.exit(f"[!] {OUTPUTS} não existe — nada pra sincronizar.")
    pastas = sorted(p for p in OUTPUTS.iterdir() if p.is_dir() and _PASTA_VIDEO.match(p.name))
    total = 0
    for pasta in pastas:
        stem, n = sincronizar_pasta(pasta)
        total += n
        print(f"  {pasta.name}: {n} blocos")
    print(f"\nOK {len(pastas)} vídeos · {total} blocos sincronizados em {DB_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
