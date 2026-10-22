"""Step 14 (off-pipeline): lê o NOSSO canal e marca sozinho o que já foi publicado ou agendado.

Uso:
    uv run py scripts/14_canal.py [--dry-run]

Substitui o registro manual: o Gu sobe no Studio e este script descobre. Também roda
sozinho no começo de cada rodada do Curador (13), antes da conta do estoque.

Lê todos os uploads do canal (inclusive privados e agendados) com o token do projeto de
MÉTRICAS (missao-em-cortes-analytics, youtube.readonly, só leitura; nunca o do publisher)
e casa cada vídeo com um bloco local pelo TÍTULO (descricoes.txt e blocos.json, normalizado,
sem #hashtags; aceita edição pequena no Studio por similaridade):
  - longo (> 3 min) público    → bloco "publicado" (+ youtube_id, publish_at)
  - longo privado com publishAt → bloco "agendado"
  - Short (≤ 3 min), público ou agendado → "postado" no shorts/shorts.json do bloco
    (sai do estoque de Shorts). Suba o Short com o mesmo título do vídeo longo.
Rascunho privado sem data e não listado são ignorados. Vídeo sem match fica listado pra
conferir (título muito editado no Studio quebra o casamento).

Grava state/canal.json com a data do último longo agendado/publicado: é dali que o
publicacao.txt continua a sugestão de datas. Custo: US$ 0 (cota de leitura, ~5 unidades).
Eventos com agente="publicador".
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from _eventos import evento, ler_bloco, upsert_bloco
from _paths import OUTPUTS, stem_de
from _youtube_leitura import listar_videos, normalizar, youtube

ROOT = Path(__file__).parent.parent
ESTADO = ROOT / "state" / "canal.json"
MAX_SHORT_S = 180
SIMILARIDADE = 0.85         # título editado de leve no Studio ainda casa
DIAS_SEM_MATCH = 15         # só lista sem-match recente (o canal tem vídeos antigos à mão)
BRT = timezone(timedelta(hours=-3))


def chave(titulo: str) -> str:
    return normalizar(re.sub(r"#\w+", " ", titulo or ""))


def titulos_locais(outputs: Path) -> list[dict]:
    """[{chave, pasta, stem, bloco, tipo}] de todos os vídeos processados. tipo 'titulo'
    casa por similaridade; 'thumb' (texto_thumb, curto) só casa exato."""
    from _descricoes import ler_descricoes
    locais = []
    for pasta in sorted(p for p in outputs.glob("*_*") if p.is_dir()):
        vistos = set()
        def add(bid, texto, tipo="titulo"):
            k = chave(texto)
            if k and (k, bid) not in vistos:
                vistos.add((k, bid))
                locais.append({"chave": k, "pasta": pasta, "stem": stem_de(pasta),
                               "bloco": bid, "tipo": tipo})
        desc = pasta / "descricoes.txt"
        if desc.exists():
            for bid, meta in ler_descricoes(desc.read_text(encoding="utf-8")).items():
                add(bid, meta["titulo"])
        try:
            blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
        except (OSError, ValueError, KeyError):
            blocos = []
        for b in blocos:
            for campo in ("titulo_sugerido", "titulo_original"):
                add(b["id"], b.get(campo))
            for campo in ("texto_thumb", "texto_thumb_original"):
                add(b["id"], b.get(campo), "thumb")
    return locais


def casar(titulo: str, locais: list[dict]) -> dict | None:
    """Bloco local do título: exato primeiro; senão o mais parecido, se passar do limiar
    e não empatar com outro bloco."""
    k = chave(titulo)
    exatos = {(x["pasta"], x["bloco"]): x for x in locais if x["chave"] == k}
    if len(exatos) == 1:
        return next(iter(exatos.values()))
    if exatos:
        return None                         # mesmo título em 2 blocos: não chuta
    notas = sorted(((SequenceMatcher(None, k, x["chave"]).ratio(), x) for x in locais
                    if x["tipo"] == "titulo"), key=lambda n: -n[0])
    if not notas or notas[0][0] < SIMILARIDADE:
        return None
    melhor = notas[0][1]
    if len(notas) > 1 and notas[1][0] == notas[0][0] and \
            (notas[1][1]["pasta"], notas[1][1]["bloco"]) != (melhor["pasta"], melhor["bloco"]):
        return None
    return melhor


def para_brt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BRT)


def situacao(v: dict) -> tuple[str, datetime] | None:
    """('publicado'|'agendado', quando) ou None (rascunho privado, não listado)."""
    if v["privacidade"] == "public":
        return "publicado", para_brt(v.get("publish_at") or v["publicado"])
    if v["privacidade"] == "private" and v.get("publish_at"):
        return "agendado", para_brt(v["publish_at"])
    return None


def marcar_short(pasta: Path, bloco: int, vid: str, quando: datetime, dry: bool) -> bool:
    """postado + youtube_id no shorts.json. True se mudou algo."""
    caminho = pasta / "shorts" / "shorts.json"
    try:
        registro = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    item = registro.get(f"{bloco:02d}") if isinstance(registro, dict) else None
    if not isinstance(item, dict) or item.get("youtube_id") == vid:
        return False
    item.update(postado=quando.date().isoformat(), youtube_id=vid)
    if not dry:
        caminho.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def marcar_longo(stem: str, bloco: int, vid: str, status: str, quando: datetime,
                 dry: bool) -> bool:
    atual = ler_bloco(stem, bloco) or {}
    publish_at = quando.isoformat(timespec="seconds")
    if (atual.get("status"), atual.get("youtube_id"), atual.get("publish_at")) == \
            (status, vid, publish_at):
        return False
    if not dry:
        upsert_bloco(stem, bloco, status=status, youtube_id=vid, publish_at=publish_at,
                     forcar_status=True)
    return True


def aplicar(videos: list[dict], locais: list[dict], agora: datetime | None = None,
            dry: bool = False) -> dict:
    agora = agora or datetime.now(BRT)
    res = {"longos": [], "shorts": [], "sem_match": [], "ultimo_longo": None}
    for v in videos:
        s = situacao(v)
        if s is None:
            continue
        status, quando = s
        short = v["duracao_s"] <= MAX_SHORT_S
        if not short and (res["ultimo_longo"] is None or quando.isoformat() > res["ultimo_longo"]):
            res["ultimo_longo"] = quando.isoformat(timespec="seconds")
        m = casar(v["titulo"], locais if short else [x for x in locais if x["tipo"] == "titulo"])
        if m is None:
            if (agora - quando).days <= DIAS_SEM_MATCH:
                res["sem_match"].append({"id": v["id"], "titulo": v["titulo"], "status": status,
                                         "short": short})
            continue
        linha = {"stem": m["stem"], "bloco": m["bloco"], "id": v["id"], "status": status,
                 "quando": quando.strftime("%d/%m %H:%M"), "titulo": v["titulo"]}
        if short:
            if marcar_short(m["pasta"], m["bloco"], v["id"], quando, dry):
                res["shorts"].append(linha)
                if not dry:
                    evento(m["stem"], "14_canal", "ok", bloco_id=m["bloco"], agente="publicador",
                           mensagem=f"Short {status} no canal: {v['id']} em {linha['quando']}")
        elif marcar_longo(m["stem"], m["bloco"], v["id"], status, quando, dry):
            res["longos"].append(linha)
            if not dry:
                evento(m["stem"], "14_canal", "ok", bloco_id=m["bloco"], agente="publicador",
                       mensagem=f"longo {status} no canal: {v['id']} em {linha['quando']}")
    if not dry:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps({"atualizado": agora.isoformat(timespec="seconds"),
                                      "ultimo_longo": res["ultimo_longo"],
                                      "sem_match": res["sem_match"]},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def sincronizar(interativo: bool = True, dry: bool = False) -> dict:
    """Lê o canal e aplica. interativo=False (Curador agendado) nunca abre o navegador:
    sem login válido levanta _google.LoginNecessario."""
    return aplicar(listar_videos(youtube(interativo)), titulos_locais(OUTPUTS), dry=dry)


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry-run" in argv
    res = sincronizar(dry=dry)
    print(f"\nCanal{' (dry-run: nada gravado)' if dry else ''}: "
          f"{len(res['longos'])} longo(s) e {len(res['shorts'])} Short(s) atualizados")
    for x in res["longos"] + res["shorts"]:
        print(f"  {x['status']:<9} {x['quando']}  {x['stem']} bloco {x['bloco']:02d}  {x['titulo'][:60]}")
    if res["ultimo_longo"]:
        print(f"Último longo no canal: {para_brt(res['ultimo_longo']):%d/%m %H:%M}")
    for x in res["sem_match"]:
        print(f"  [sem match] {'Short' if x['short'] else 'longo'} {x['status']}: {x['titulo'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
