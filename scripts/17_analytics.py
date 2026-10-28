"""Step 17 (off-pipeline): coleta diária do YouTube Analytics por vídeo → banco (agente="analista").

Uso:
    uv run py scripts/17_analytics.py            # coleta (o Curador chama 1x/dia, depois do placar)
    uv run py scripts/17_analytics.py semanal    # resumo da semana → state/analytics_semanal.md

Por vídeo PÚBLICO do canal, acumulado desde a publicação (o Analytics atrasa ~2 dias):
  - views, impressões da miniatura e CTR da miniatura (videoThumbnailImpressions*)
  - retenção média (% média assistida) e duração média assistida
  - origens de tráfego (insightTrafficSourceType: busca, sugeridos, inscritos, Shorts...)
  - termos de pesquisa do YouTube que trouxeram views (até 25 por vídeo)
Do canal inteiro: os termos de pesquisa dos últimos 7 dias — é deles que sai o destaque do
resumo semanal e a lista que o Editor (_editor) recebe pra usar nos títulos.

Grava a foto do dia nas tabelas metricas_video / trafego_video / termos_busca / termos_canal
(_eventos.gravar_analytics); o painel mostra na aba "Analytics".
Projeto missao-em-cortes-analytics (token próprio, só leitura, nunca o do publisher).
Custo: US$ 0 (Data API ~3 unidades por rodada; o resto é Analytics API, cota própria e grátis).
Se a API recusar as métricas de impressão, a coleta segue sem elas (impressões/CTR vazios).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, timedelta
from pathlib import Path

from _eventos import evento, gravar_analytics, termos_semana, ultima_coleta
from _google import credenciais
from _youtube_leitura import (CLIENT_SECRET, ESCOPOS, MAX_SHORT_S, TOKEN, listar_videos,
                              nome_origem)

ROOT = Path(__file__).parent.parent
SEMANAL = ROOT / "state" / "analytics_semanal.md"
MAX_TERMOS = 25          # limite da API pra insightTrafficSourceDetail


def _query(analytics, **kw) -> list[list]:
    return analytics.reports().query(ids="channel==MINE", **kw).execute().get("rows", [])


def basicas(analytics, ids: list[str], inicio: str, fim: str) -> dict[str, dict]:
    """{id: {views, retencao_pct, assistido_s}} em lotes de 50."""
    saida = {}
    for i in range(0, len(ids), 50):
        for vid, views, dur, pct in _query(
                analytics, startDate=inicio, endDate=fim, dimensions="video",
                metrics="views,averageViewDuration,averageViewPercentage",
                filters="video==" + ",".join(ids[i:i + 50]), maxResults=50, sort="-views"):
            saida[vid] = {"views": int(views), "assistido_s": round(float(dur), 1),
                          "retencao_pct": round(float(pct), 1)}
    return saida


def impressoes(analytics, ids: list[str], inicio: str, fim: str) -> dict[str, dict]:
    """{id: {impressoes, ctr_pct}}. O CTR vem como razão (cliques ÷ impressões) → %. Se algum
    valor passar de 1, a API já mandou em %: o lote inteiro fica como veio."""
    saida = {}
    for i in range(0, len(ids), 50):
        saida.update({vid: (int(imp), float(ctr)) for vid, imp, ctr in _query(
            analytics, startDate=inicio, endDate=fim, dimensions="video",
            metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
            filters="video==" + ",".join(ids[i:i + 50]), maxResults=50,
            sort="-videoThumbnailImpressions")})
    fator = 1 if any(ctr > 1 for _, ctr in saida.values()) else 100
    return {vid: {"impressoes": imp, "ctr_pct": round(ctr * fator, 2)}
            for vid, (imp, ctr) in saida.items()}


def trafego(analytics, vid: str, inicio: str, fim: str) -> list[dict]:
    return [{"youtube_id": vid, "origem": origem, "views": int(views), "minutos": round(float(m), 1)}
            for origem, views, m in _query(
                analytics, startDate=inicio, endDate=fim, dimensions="insightTrafficSourceType",
                metrics="views,estimatedMinutesWatched", filters=f"video=={vid}", sort="-views")]


def termos(analytics, inicio: str, fim: str, vid: str | None = None) -> list[dict]:
    """Termos da busca do YouTube que trouxeram views (do vídeo, ou do canal sem `vid`)."""
    filtro = "insightTrafficSourceType==YT_SEARCH" + (f";video=={vid}" if vid else "")
    return [{"termo": termo, "views": int(views)} for termo, views in _query(
        analytics, startDate=inicio, endDate=fim, dimensions="insightTrafficSourceDetail",
        metrics="views", filters=filtro, sort="-views", maxResults=MAX_TERMOS)]


def coletar_dados(yt, analytics, hoje: date | None = None) -> dict:
    """Lê o canal e devolve {data, metricas, trafego, termos, termos_canal, avisos}."""
    hoje = hoje or date.today()
    fim = hoje.isoformat()
    videos = [v for v in listar_videos(yt) if v["privacidade"] == "public"]
    avisos = []
    if not videos:
        return {"data": fim, "metricas": [], "trafego": [], "termos": [], "termos_canal": [],
                "avisos": ["nenhum vídeo público no canal"]}
    inicio = min(v["publicado"][:10] for v in videos)
    ids = [v["id"] for v in videos]
    base = basicas(analytics, ids, inicio, fim)
    try:
        imp = impressoes(analytics, ids, inicio, fim)
    except Exception as e:  # noqa: BLE001 — métrica nova da API; sem ela o resto vale
        imp = {}
        avisos.append(f"impressões/CTR não lidos ({str(e)[:150]})")
    metricas, traf, ters = [], [], []
    for v in videos:
        vid, desde = v["id"], v["publicado"][:10]
        metricas.append({"youtube_id": vid, "titulo": v["titulo"], "publicado": v["publicado"],
                         "duracao_s": v["duracao_s"],
                         **base.get(vid, {"views": 0, "assistido_s": None, "retencao_pct": None}),
                         **imp.get(vid, {"impressoes": None, "ctr_pct": None})})
        if not base.get(vid, {}).get("views"):
            continue                                  # sem view, sem tráfego nem termo
        traf += trafego(analytics, vid, desde, fim)
        ters += [{"youtube_id": vid, **t} for t in termos(analytics, desde, fim, vid)]
    canal = termos(analytics, (hoje - timedelta(days=7)).isoformat(), fim)
    return {"data": fim, "metricas": metricas, "trafego": traf, "termos": ters,
            "termos_canal": canal, "avisos": avisos}


def coletar(interativo: bool = True) -> dict:
    """Coleta e grava no banco. interativo=False (Curador) nunca abre o navegador."""
    from googleapiclient.discovery import build
    creds = credenciais(ESCOPOS, TOKEN, CLIENT_SECRET, interativo=interativo)
    dados = coletar_dados(build("youtube", "v3", credentials=creds, cache_discovery=False),
                          build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False))
    gravar_analytics(dados["data"], dados["metricas"], dados["trafego"], dados["termos"],
                     dados["termos_canal"])
    msg = (f"{len(dados['metricas'])} vídeo(s) · {len(dados['termos'])} termo(s) por vídeo · "
           f"{len(dados['termos_canal'])} termo(s) do canal (7 dias)")
    for aviso in dados["avisos"]:
        evento(None, "17_analytics", "aviso", agente="analista", mensagem=aviso[:300])
    evento(None, "17_analytics", "ok", agente="analista", mensagem=msg)
    return dados


# ── resumo semanal ─────────────────────────────────────────────────────────

def resumo_semanal(termos_top: list[dict], metricas: list[dict], trafego_canal: dict[str, int],
                   data: str) -> str:
    """Markdown do resumo semanal. Os termos de pesquisa vêm primeiro: é o insumo do Editor."""
    linhas = [f"# Analytics da semana ({data})", "",
              "## Termos de pesquisa que mais trouxeram views (busca do YouTube, 7 dias)",
              "O Editor recebe esta lista ao reescrever títulos: usar um termo só se a fala sustentar.", ""]
    linhas += ([f"{i}. **{t['termo']}** — {t['views']} views" for i, t in enumerate(termos_top, 1)]
               or ["- (nenhuma view vinda da busca nos últimos 7 dias)"])
    total = sum(trafego_canal.values())
    if total:
        linhas += ["", "## De onde vieram as views (acumulado dos vídeos públicos)"]
        linhas += [f"- {nome_origem(o)}: {v} ({v / total:.0%})"
                   for o, v in sorted(trafego_canal.items(), key=lambda x: -x[1])[:6]]
    longos = [m for m in metricas if (m.get("duracao_s") or 0) > MAX_SHORT_S and m.get("impressoes")]
    if longos:
        imp = sum(m["impressoes"] for m in longos)
        ctr = sum(m["ctr_pct"] * m["impressoes"] for m in longos) / imp
        linhas += ["", "## Miniaturas (vídeos longos)",
                   f"- CTR médio: {ctr:.1f}% em {imp} impressões"]
        melhores = sorted((m for m in longos if m["impressoes"] >= 100), key=lambda m: -m["ctr_pct"])
        linhas += [f"- {m['ctr_pct']:.1f}% · {m['titulo'][:70]}" for m in melhores[:3]]
    return "\n".join(linhas) + "\n"


def semanal() -> str:
    """Lê a coleta mais recente do banco e grava state/analytics_semanal.md."""
    coleta = ultima_coleta()
    texto = resumo_semanal(termos_semana(), coleta["metricas"], coleta["trafego"],
                           coleta["data"] or "sem coleta")
    SEMANAL.parent.mkdir(parents=True, exist_ok=True)
    SEMANAL.write_text(texto, encoding="utf-8")
    return texto


def main(argv: list[str]) -> int:
    if argv[:1] == ["semanal"]:
        print(semanal())
        print(f"→ {SEMANAL}")
        return 0
    try:
        dados = coletar()
    except Exception as e:  # noqa: BLE001 — falha vira evento; a coleta anterior fica no banco
        evento(None, "17_analytics", "falha", agente="analista", mensagem=str(e)[:300])
        print(f"[!] Não coletei o Analytics: {e}", file=sys.stderr)
        return 1
    for aviso in dados["avisos"]:
        print(f"[aviso] {aviso}")
    print(f"Analytics {dados['data']}: {len(dados['metricas'])} vídeo(s) públicos")
    for m in sorted(dados["metricas"], key=lambda m: -(m["views"] or 0))[:10]:
        ctr = f"{m['ctr_pct']:.1f}%" if m["ctr_pct"] is not None else "—"
        ret = f"{m['retencao_pct']:.0f}%" if m["retencao_pct"] is not None else "—"
        print(f"  {m['views']:>6} views · CTR {ctr:>5} · retenção {ret:>4} · {m['titulo'][:55]}")
    if dados["termos_canal"]:
        print("\n  Termos de busca (canal, 7 dias): "
              + ", ".join(f"{t['termo']} ({t['views']})" for t in dados["termos_canal"][:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
