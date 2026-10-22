"""Lista de publicação manual de uma live: outputs/<pasta>/publicacao.txt.

Só os blocos APROVADOS pelo revisor (revisao.json), em ordem de score, com arquivo final,
thumb escolhida pelo revisor, título/descrição/tags do descricoes.txt (edição manual vale)
e uma sugestão de dia: 1 por dia, ou 2 por dia quando há 3+ aprovados (conteúdo de live
envelhece rápido). Usado pelo Curador (13) no fim de cada vídeo; dá pra rodar à mão:

  uv run py scripts/_publicacao.py <stem>
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from _descricoes import ler_descricoes

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
HORA = "18h"
CORTE_HOJE = 16          # processou antes das 16h: o 1º já pode sair hoje às 18h


def _final(pasta: Path, bid: int) -> Path | None:
    """Vídeo final do bloco: prefere _polido_legendado > _legendado > _polido > original."""
    cands = sorted((pasta / "finalizados").glob(f"video_{bid:02d}_*.mp4"))
    for sufixo in ("_polido_legendado", "_legendado", "_polido"):
        for c in cands:
            if c.stem.endswith(sufixo):
                return c
    return next((c for c in cands if not c.stem.endswith(("_polido", "_legendado"))), None)


def aprovados(pasta: Path) -> list[dict]:
    """[{id, score, duracao, video, thumb, titulo, descricao, tags}] em ordem de score."""
    revisao_path = pasta / "revisao.json"
    if not revisao_path.exists():
        return []
    revisao = json.loads(revisao_path.read_text(encoding="utf-8"))
    blocos = {b["id"]: b for b in json.loads(
        (pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]}
    desc_path = pasta / "descricoes.txt"
    descricoes = ler_descricoes(desc_path.read_text(encoding="utf-8")) if desc_path.exists() else {}
    saida = []
    for chave, r in revisao.items():
        bid = int(chave)
        video = _final(pasta, bid)
        if r.get("status") != "aprovado" or bid not in blocos or video is None:
            continue
        b, d = blocos[bid], descricoes.get(bid, {})
        saida.append({
            "id": bid,
            "score": b.get("score_potencial") or 0,
            "duracao": b.get("duracao_minutos"),
            "video": video,
            "thumb": pasta / "thumbs" / r["thumb"] if r.get("thumb") else None,
            "titulo": d.get("titulo") or r.get("titulo") or b.get("titulo_sugerido", ""),
            "descricao": d.get("descricao", ""),
            "tags": d.get("tags", []),
        })
    return sorted(saida, key=lambda x: (-x["score"], x["id"]))


def agenda(n: int, agora: datetime | None = None) -> list[date]:
    """Dia sugerido pra cada um dos n vídeos (já em ordem de score)."""
    agora = agora or datetime.now()
    inicio = agora.date() if agora.hour < CORTE_HOJE else agora.date() + timedelta(days=1)
    por_dia = 2 if n >= 3 else 1
    return [inicio + timedelta(days=i // por_dia) for i in range(n)]


def gerar(pasta: Path, agora: datetime | None = None) -> tuple[Path | None, list[dict]]:
    """Grava publicacao.txt. Sem aprovados não grava nada: (None, [])."""
    lista = aprovados(pasta)
    if not lista:
        return None, []
    dias = agenda(len(lista), agora)
    linhas = [f"# Publicação manual — {pasta.name}",
              f"# {len(lista)} corte(s) aprovado(s) pelo revisor, em ordem de score.",
              "# Thumb: a metade direita preta é o espaço do collage no Canva.", ""]
    for x, dia in zip(lista, dias):
        linhas +=["=" * 70,
                   f"{DIAS_SEMANA[dia.weekday()]} {dia:%d/%m} {HORA} · VÍDEO {x['id']:02d} · "
                   f"score {x['score']} · {x['duracao']} min",
                   "=" * 70,
                   f"ARQUIVO: finalizados/{x['video'].name}",
                   f"THUMB:   thumbs/{x['thumb'].name}" if x["thumb"] else "THUMB:   (sem thumb)",
                   "", "TÍTULO:", x["titulo"], "", "DESCRIÇÃO:", x["descricao"].strip(), "",
                   "TAGS:", ", ".join(x["tags"]), ""]
    destino = pasta / "publicacao.txt"
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino, lista


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from _paths import achar_pasta
    if len(sys.argv) < 2:
        sys.exit("Uso: uv run py scripts/_publicacao.py <stem>")
    caminho, itens = gerar(achar_pasta(sys.argv[1]))
    print(f"OK {len(itens)} aprovado(s) → {caminho}" if caminho else "Nenhum bloco aprovado.")
