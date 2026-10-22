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

Conteúdo antigo: live com mais de DIAS_ARQUIVAR dias (pela data da pasta) cujos blocos
ainda não foram pro YouTube vira 'arquivado' (motivo "conteúdo antigo"). Somem do
kanban e das métricas. Agendado, publicado e descartado não são tocados. Os Shorts
ainda não postados dessa live ganham "arquivado" no shorts/shorts.json (saem do estoque).
"""
import json
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date
from pathlib import Path

from _eventos import arquivar_blocos, evento, upsert_bloco, upsert_video, DB_PATH
from _paths import OUTPUTS, ROOT, escolher_arquivo, escolher_thumb, stem_de

INPUTS = ROOT / "inputs"
_PASTA_VIDEO = re.compile(r"^\d{4}-\d{2}-\d{2}_.+")
DIAS_ARQUIVAR = 15
MOTIVO_ANTIGO = "conteúdo antigo"


def arquivar_se_antigo(pasta: Path, stem: str, hoje: date | None = None) -> list[int]:
    """Arquiva os blocos não publicados se a live tem mais de DIAS_ARQUIVAR dias."""
    try:
        data = date.fromisoformat(pasta.name[:10])
    except ValueError:
        return []
    if ((hoje or date.today()) - data).days <= DIAS_ARQUIVAR:
        return []
    ids = arquivar_blocos(stem, MOTIVO_ANTIGO)
    if ids:
        evento(stem, "arquivar", "ok", mensagem=f"{MOTIVO_ANTIGO}: blocos {ids} "
               f"(live de {data:%d/%m/%Y}, >{DIAS_ARQUIVAR} dias sem publicar)")
    shorts = arquivar_shorts(pasta)
    if shorts:
        evento(stem, "arquivar", "ok", mensagem=f"{MOTIVO_ANTIGO}: Shorts {shorts} "
               f"(live de {data:%d/%m/%Y}, >{DIAS_ARQUIVAR} dias sem postar)")
    return ids


def arquivar_shorts(pasta: Path) -> list[str]:
    """Marca "arquivado" no shorts.json os Shorts ainda não postados (o 10_shorts preserva
    a marca ao regerar). Short arquivado sai do estoque e não sobe. Só é chamado pra live
    velha (arquivar_se_antigo)."""
    caminho = pasta / "shorts" / "shorts.json"
    try:
        registro = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(registro, dict):
        return []
    nns = [nn for nn, sh in registro.items() if isinstance(sh, dict)
           and not sh.get("postado") and not sh.get("arquivado")]
    if nns:
        for nn in nns:
            registro[nn]["arquivado"] = MOTIVO_ANTIGO
        caminho.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return sorted(nns)


def sincronizar_pasta(pasta: Path, hoje: date | None = None) -> tuple[str, int]:
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
        corte = escolher_arquivo(pasta / "cortes", f"corte_{nn}_*.mp4")
        final = escolher_arquivo(pasta / "finalizados", f"video_{nn}_*.mp4")
        thumb = escolher_thumb(pasta / "thumbs", nn)

        status = "montado" if final else "cortado" if corte else "segmentado"
        upsert_bloco(
            stem, b["id"],
            status=status,
            tema=b.get("tema"),
            titulo=b.get("titulo_sugerido"),
            texto_thumb=b.get("texto_thumb"),
            score=b.get("score_potencial"),
            duracao_min=b.get("duracao_minutos"),
            # posix (/) pra o banco valer em qualquer SO — Path aceita / no Windows
            video_path=final.relative_to(ROOT).as_posix() if final else None,
            thumb_path=thumb.relative_to(ROOT).as_posix() if thumb else None,
        )
    arquivados = arquivar_se_antigo(pasta, stem, hoje)
    if arquivados:
        print(f"  {pasta.name}: arquivados por {MOTIVO_ANTIGO} → blocos {arquivados}")
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
