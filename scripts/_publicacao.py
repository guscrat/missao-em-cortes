"""Lista de publicação manual de uma live: outputs/<pasta>/publicacao.txt.

Só os blocos APROVADOS pelo revisor (revisao.json), em ordem de score, com arquivo final,
as thumbs a/b/c pro "Testar e comparar" do Studio (cada uma marcada template ou colagem; a
manual escolhida pelo revisor sobe sozinha), título/descrição/tags do descricoes.txt (edição manual vale)
e uma sugestão de dia: 1 por dia, ou 2 por dia quando há 3+ aprovados (conteúdo de live
envelhece rápido). As datas continuam DEPOIS do último longo agendado/publicado no canal
(state/canal.json do 14_canal + publish_at do banco), pra não brigar com o que já está na
fila do YouTube (no modo evento do config/canais.json, começam hoje/amanhã: na frente
dos agendados). Enquanto config/upload.json → auditoria_aprovada for false, a lista
mostra só os longos; depois os Shorts aparecem marcados "sobe pela API" (09 --shorts). Usado pelo
Curador (13) no fim de cada vídeo; dá pra rodar à mão:

  uv run py scripts/_publicacao.py <stem> [--grade=12h,19h]

--grade: horários fixos por dia (1 vídeo por horário), em vez de 1-2 por dia às 18h. Horário
de hoje que já passou sai como "publicar JÁ" (o dia continua com os vídeos dele).
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from _cobertura import agenda_canal
from _descricoes import ler_descricoes
from _paths import auditoria_aprovada, modo_evento

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


def thumbs_do_teste(pasta: Path, bid: int, escolhida: Path | None) -> list[tuple[Path, str]]:
    """[(thumb, estilo)] que sobem no "Testar e comparar": as a/b/c do bloco, cada uma
    'template' ou 'colagem' (modo ab: a = template, b/c = colagem). Manual sobe sozinha."""
    if escolhida and escolhida.stem.endswith("_manual"):
        return [(escolhida, "manual")]
    abc = [pasta / "thumbs" / f"thumb_{bid:02d}_{l}.png" for l in "abc"]
    if (pasta / "thumbs" / "colagem" / "colagem.json").exists():
        from _colagem import variante_aplicada      # import pesado (cv2): só com colagem
    else:
        def variante_aplicada(_):
            return None
    lista = [(t, "colagem" if variante_aplicada(t) else "template") for t in abc if t.exists()]
    return lista or ([(escolhida, "template")] if escolhida else [])


def aprovados(pasta: Path) -> list[dict]:
    """[{id, score, duracao, video, thumb, thumbs, titulo, descricao, tags}] em ordem de score."""
    revisao_path = pasta / "revisao.json"
    if not revisao_path.exists():
        return []
    revisao = json.loads(revisao_path.read_text(encoding="utf-8"))
    blocos = {b["id"]: b for b in json.loads(
        (pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]}
    desc_path = pasta / "descricoes.txt"
    descricoes = ler_descricoes(desc_path.read_text(encoding="utf-8")) if desc_path.exists() else {}
    try:
        shorts = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        shorts = {}
    saida = []
    for chave, r in revisao.items():
        bid = int(chave)
        video = _final(pasta, bid)
        if r.get("status") != "aprovado" or bid not in blocos or video is None:
            continue
        b, d = blocos[bid], descricoes.get(bid, {})
        short = shorts.get(f"{bid:02d}", {}).get("arquivo")
        thumb = pasta / "thumbs" / r["thumb"] if r.get("thumb") else None
        saida.append({
            "id": bid,
            "score": b.get("score_potencial") or 0,
            "duracao": b.get("duracao_minutos"),
            "video": video,
            "thumb": thumb,
            "thumbs": thumbs_do_teste(pasta, bid, thumb),
            "short": pasta / "shorts" / short if short else None,
            "titulo": d.get("titulo") or r.get("titulo") or b.get("titulo_sugerido", ""),
            "descricao": d.get("descricao", ""),
            "tags": d.get("tags", []),
        })
    return sorted(saida, key=lambda x: (-x["score"], x["id"]))


def ultimo_agendado() -> date | None:
    """Dia do último longo agendado/publicado (_cobertura.agenda_canal: canal.json do
    14_canal + publish_at do banco), a mesma fonte do Curador e do painel."""
    return agenda_canal()["ultimo"]


def agenda(n: int, agora: datetime | None = None, depois_de: date | None = None) -> list[date]:
    """Dia sugerido pra cada um dos n vídeos (já em ordem de score), começando depois do
    último agendado (depois_de), se houver."""
    agora = agora or datetime.now()
    inicio = agora.date() if agora.hour < CORTE_HOJE else agora.date() + timedelta(days=1)
    if depois_de and depois_de >= inicio:
        inicio = depois_de + timedelta(days=1)
    por_dia = 2 if n >= 3 else 1
    return [inicio + timedelta(days=i // por_dia) for i in range(n)]


def horas(grade: list[str] | None, dias: list[date], agora: datetime | None = None) -> list[str]:
    """Hora de cada vídeo: HORA sem grade; com grade, o i-ésimo vídeo do dia leva o i-ésimo
    horário. Horário de hoje que já passou: 'JÁ (12h passou)'."""
    if not grade:
        return [HORA] * len(dias)
    agora = agora or datetime.now()
    saida, vistos = [], {}
    for d in dias:
        i = vistos.get(d, 0)
        vistos[d] = i + 1
        h = grade[min(i, len(grade) - 1)]
        hh, mm = [int(n) for n in (re.findall(r"\d+", h) + ["0", "0"])[:2]]   # 12h, 19h30, 19:30
        passou = d == agora.date() and (hh, mm) <= (agora.hour, agora.minute)
        saida.append(f"JÁ ({h} passou)" if passou else h)
    return saida


def linhas_thumbs(thumbs: list[tuple[Path, str]]) -> list[str]:
    if not thumbs:
        return ["THUMB:   (sem thumb)"]
    if len(thumbs) == 1:
        return [f"THUMB:   thumbs/{thumbs[0][0].name} ({thumbs[0][1]})"]
    return ["THUMBS (Testar e comparar):"] + [f"  {t.stem[-1]}: thumbs/{t.name} ({estilo})"
                                              for t, estilo in thumbs]


def gerar(pasta: Path, agora: datetime | None = None,
          grade: list[str] | None = None) -> tuple[Path | None, list[dict]]:
    """Grava publicacao.txt. Sem aprovados não grava nada: (None, []). `grade`: horários
    fixos por dia (ex.: ["12h", "19h"]), um vídeo por horário."""
    lista = aprovados(pasta)
    if not lista:
        return None, []
    evento = modo_evento((agora or datetime.now()).date())
    # modo evento: conteúdo novo passa na frente dos agendados (datas a partir de hoje/amanhã)
    depois_de = None if evento else ultimo_agendado()
    if grade:
        inicio = (agora or datetime.now()).date()   # horário de hoje que passou vira "JÁ"
        if depois_de and depois_de >= inicio:
            inicio = depois_de + timedelta(days=1)
        dias = [inicio + timedelta(days=i // len(grade)) for i in range(len(lista))]
    else:
        dias = agenda(len(lista), agora, depois_de)
    hs = horas(grade, dias, agora)
    com_shorts = auditoria_aprovada()
    linhas = [f"# Publicação manual — {pasta.name}",
              f"# {len(lista)} corte(s) aprovado(s) pelo revisor, em ordem de score.",
              "# Thumb: a metade direita preta é o espaço do collage no Canva.",
              "# THUMBS: suba as 3 no \"Testar e comparar\" do Studio (Miniatura → Testar e comparar).",
              "# Resultado do teste: 16_thumb_ab.py registrar <stem> <vídeo> <a|b|c|empate>."]
    if evento:
        linhas += [f"# MODO EVENTO (até {evento['ate']:%d/%m}): datas NA FRENTE dos já agendados.",
                   f"# Se o dia já tem longo agendado às {'/'.join(grade or [HORA])}, empurre o "
                   f"agendado no Studio."]
    if com_shorts:
        linhas += ["# Shorts sobem pela API (09_upload.py <stem> --shorts, 2/dia, depois do longo):",
                   "# NÃO suba à mão. O vídeo relacionado é marcado no Studio (dia_d.py relacionados).", ""]
    else:
        linhas += ["# Só os vídeos LONGOS: os Shorts ficam prontos e sobem pela API quando a",
                   "# auditoria for aprovada (config/upload.json → auditoria_aprovada).", ""]
    for x, dia, hora in zip(lista, dias, hs):
        short = []
        if com_shorts:
            short = [f"SHORT:   shorts/{x['short'].name} (sobe pela API)" if x["short"]
                     else "SHORT:   (sem Short)"]
        linhas +=["=" * 70,
                   f"{DIAS_SEMANA[dia.weekday()]} {dia:%d/%m} {hora} · VÍDEO {x['id']:02d} · "
                   f"score {x['score']} · {x['duracao']} min",
                   "=" * 70,
                   f"ARQUIVO: finalizados/{x['video'].name}",
                   *linhas_thumbs(x["thumbs"]),
                   *short,
                   "", "TÍTULO:", x["titulo"], "", "DESCRIÇÃO:", x["descricao"].strip(), "",
                   "TAGS:", ", ".join(x["tags"]), ""]
    destino = pasta / "publicacao.txt"
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino, lista


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from _paths import achar_pasta
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    grade = next((a.split("=", 1)[1].split(",") for a in sys.argv[1:]
                  if a.startswith("--grade=")), None)
    if not pos:
        sys.exit("Uso: uv run py scripts/_publicacao.py <stem> [--grade=12h,19h]")
    caminho, itens = gerar(achar_pasta(pos[0]), grade=grade)
    print(f"OK {len(itens)} aprovado(s) → {caminho}" if caminho else "Nenhum bloco aprovado.")
