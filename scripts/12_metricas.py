"""Step 12 (off-pipeline): retenção dos vídeos COM legenda karaokê x média dos antigos, e
retenção + horas assistidas por FAIXA DE DURAÇÃO (curto 5-10, médio 10-20, longo 20-30 min)
pra achar a duração ideal pro nosso público.

Uso:
    uv run py scripts/12_metricas.py              # tabela + resumo (pro resumo semanal)
    uv run py scripts/12_metricas.py --desde=2026-05-01

Projeto do Google SEPARADO do upload (missao-em-cortes-analytics), com credencial e token
próprios em secrets/ (fora do Git): o projeto do upload (publisher) está em auditoria
declarando só upload e NÃO pode ganhar a Analytics API. Passo a passo em .claude/skills/youtube-compliance/references/metricas.md.

Lê (só leitura):
  - YouTube Data API (youtube.readonly): vídeos do canal com título, data e duração
  - YouTube Analytics API (yt-analytics.readonly): views, duração média assistida e % média
    assistida (averageViewPercentage = a "retenção" do Studio) de cada vídeo

Quem é "com legenda": o título do YouTube bate com um título do descricoes.txt de algum
vídeo em outputs/ cujo bloco tem finalizado *_legendado.mp4 (vale pra upload pela API e
pelo Studio). Sem match: antes de LEGENDA_PADRAO_DESDE conta como "sem legenda" (antigo);
depois, fica de fora ("sem info") e é listado pra conferir. Shorts (≤3 min) ficam de fora:
retenção de Short não é comparável com vídeo longo.

Retenção do grupo = média ponderada por views (vídeo com 10 views não pesa igual a um
com 10 mil). Vídeo com menos de MIN_VIEWS views é ignorado (ruído).
Custo: US$ 0 (cota da Data API ~3 unidades por rodada; Analytics tem cota própria).
Resultado também em state/metricas_retencao.json e evento agente="analista" no banco.
"""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date
from pathlib import Path

from _descricoes import ler_descricoes
from _eventos import evento
from _fronteira import FAIXAS, MONTAGEM_S, faixa_do_video
from _google import credenciais
from _paths import OUTPUTS
from _youtube_leitura import (CLIENT_SECRET, ESCOPOS, TOKEN, duracao_iso,  # noqa: F401
                             listar_videos, normalizar)

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "state" / "metricas_retencao.json"
LEGENDA_PADRAO_DESDE = "2026-10-21"   # pipeline passou a legendar por padrão
MAX_SHORT_S = 180
MIN_VIEWS = 20


def titulos_locais(outputs: Path) -> dict[str, bool]:
    """{título normalizado: tem finalizado legendado?} de todos os vídeos processados."""
    mapa = {}
    for pasta in sorted(p for p in outputs.glob("*_*") if p.is_dir()):
        desc = pasta / "descricoes.txt"
        if not desc.exists():
            continue
        for bid, meta in ler_descricoes(desc.read_text(encoding="utf-8")).items():
            legendado = any((pasta / "finalizados").glob(f"video_{bid:02d}_*_legendado.mp4"))
            mapa[normalizar(meta["titulo"])] = legendado
    return mapa


def classificar(video: dict, mapa: dict[str, bool]) -> str:
    """'com_legenda' | 'sem_legenda' | 'sem_info' | 'short'."""
    if video["duracao_s"] <= MAX_SHORT_S:
        return "short"
    legendado = mapa.get(normalizar(video["titulo"]))
    if legendado is not None:
        return "com_legenda" if legendado else "sem_legenda"
    return "sem_legenda" if video["publicado"][:10] < LEGENDA_PADRAO_DESDE else "sem_info"


def resumo_grupo(videos: list[dict]) -> dict | None:
    validos = [v for v in videos if v.get("views", 0) >= MIN_VIEWS]
    if not validos:
        return None
    views = sum(v["views"] for v in validos)
    horas = sum(v["assistido_s"] * v["views"] for v in validos) / 3600
    return {"n": len(validos), "views": views,
            "retencao_pct": round(sum(v["retencao_pct"] * v["views"] for v in validos) / views, 1),
            "assistido_s": round(sum(v["assistido_s"] * v["views"] for v in validos) / views),
            "horas_assistidas": round(horas, 1), "horas_por_video": round(horas / len(validos), 1)}


def por_faixa(videos: list[dict]) -> dict[str, dict | None]:
    """Longos agrupados pela faixa de duração (curto 5-10, médio 10-20, longo 20-30, mais
    abaixo_5/acima_30; _fronteira.faixa_do_video). Pra achar a duração ideal pro nosso público."""
    grupos: dict[str, list] = {nome: [] for nome, _, _ in FAIXAS}
    grupos.update(abaixo_5=[], acima_30=[])
    for v in videos:
        if v["duracao_s"] > MAX_SHORT_S:
            grupos[faixa_do_video(v["duracao_s"])].append(v)
    return {nome: resumo_grupo(vs) for nome, vs in grupos.items()}


# ── API ────────────────────────────────────────────────────────────────────

def videos_do_canal(yt) -> list[dict]:
    """Só os públicos: privado/agendado/teste não tem retenção pra comparar."""
    return [{k: v[k] for k in ("id", "titulo", "publicado", "duracao_s")}
            for v in listar_videos(yt) if v["privacidade"] == "public"]


def metricas(analytics, ids: list[str], inicio: str) -> dict[str, dict]:
    saida = {}
    for i in range(0, len(ids), 50):
        r = analytics.reports().query(
            ids="channel==MINE", startDate=inicio, endDate=date.today().isoformat(),
            metrics="views,averageViewDuration,averageViewPercentage", dimensions="video",
            filters="video==" + ",".join(ids[i:i + 50]), sort="-views", maxResults=50).execute()
        for vid, views, dur, pct in r.get("rows", []):
            saida[vid] = {"views": int(views), "assistido_s": float(dur), "retencao_pct": float(pct)}
    return saida


def main(argv: list[str]) -> int:
    flags = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    inicio = flags.get("desde", "2026-05-01")
    from googleapiclient.discovery import build
    creds = credenciais(ESCOPOS, TOKEN, CLIENT_SECRET)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    videos = videos_do_canal(yt)
    dados = metricas(analytics, [v["id"] for v in videos], inicio)
    mapa = titulos_locais(OUTPUTS)
    grupos: dict[str, list] = {"com_legenda": [], "sem_legenda": [], "sem_info": [], "short": []}
    for v in videos:
        v.update(dados.get(v["id"], {"views": 0, "assistido_s": 0.0, "retencao_pct": 0.0}))
        v["grupo"] = classificar(v, mapa)
        grupos[v["grupo"]].append(v)

    print(f"\nRetenção (% média assistida) · {len(videos)} vídeo(s) públicos desde {inicio}\n")
    for v in sorted(videos, key=lambda v: v["publicado"]):
        if v["grupo"] == "short":
            continue
        print(f"  {v['publicado'][:10]}  {v['grupo']:<11}  {v['retencao_pct']:5.1f}%  "
              f"{v['views']:>6} views  {v['titulo'][:55]}")
    com, sem = resumo_grupo(grupos["com_legenda"]), resumo_grupo(grupos["sem_legenda"])
    fmt = lambda g: (f"{g['retencao_pct']}% ({g['n']} vídeos, {g['views']} views, "   # noqa: E731
                     f"~{g['assistido_s'] // 60}min{g['assistido_s'] % 60:02d}s assistidos)"
                     if g else f"sem dados (precisa de ≥1 vídeo com ≥{MIN_VIEWS} views)")
    print(f"\n  COM legenda: {fmt(com)}\n  SEM legenda: {fmt(sem)}")
    if com and sem:
        print(f"  Diferença: {com['retencao_pct'] - sem['retencao_pct']:+.1f} pontos percentuais")
    if grupos["sem_info"]:
        print(f"\n  [aviso] {len(grupos['sem_info'])} vídeo(s) recente(s) sem match no descricoes.txt "
              f"(título editado no Studio?) — fora da conta")

    faixas = por_faixa(videos)
    print("\n  Por faixa de duração (retenção · horas assistidas):")
    rotulos = {"curto": "curto 5-10min", "medio": "médio 10-20min", "longo": "longo 20-30min",
               "abaixo_5": "abaixo de 5min", "acima_30": "acima de 30min"}
    for nome, g in faixas.items():
        print(f"    {rotulos[nome]:<22} " + (
            f"{g['retencao_pct']}% · {g['horas_assistidas']}h ({g['horas_por_video']}h/vídeo, "
            f"{g['n']} vídeos, ~{g['assistido_s'] // 60}min{g['assistido_s'] % 60:02d}s por view)"
            if g else "sem dados"))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"gerado_em": date.today().isoformat(), "desde": inicio,
                                 "com_legenda": com, "sem_legenda": sem,
                                 "por_faixa": faixas, "videos": videos},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    evento(None, "12_metricas", "ok", agente="analista",
           mensagem=f"retenção com={com and com['retencao_pct']} sem={sem and sem['retencao_pct']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
