"""Step 17 (off-pipeline): coleta diária do YouTube Analytics por vídeo → banco (agente="analista").

Uso:
    uv run py scripts/17_analytics.py            # coleta (o Curador chama 1x/dia, depois do placar)
    uv run py scripts/17_analytics.py semanal    # resumo da semana → state/analytics_semanal.md

Por vídeo PÚBLICO do canal, acumulado desde a publicação (o Analytics atrasa ~2 dias):
  - views; impressões e CTR da miniatura (relatório Reach da Reporting API, ver abaixo)
  - retenção média (% média assistida) e duração média assistida
  - origens de tráfego (insightTrafficSourceType: busca, sugeridos, inscritos, Shorts...)
  - termos de pesquisa do YouTube que trouxeram views (até 25 por vídeo)
Do canal inteiro: os termos de pesquisa dos últimos 7 dias — é deles que sai o destaque do
resumo semanal e a lista que o Editor (_editor) recebe pra usar nos títulos.

Grava a foto do dia nas tabelas metricas_video / trafego_video / termos_busca / termos_canal
(_eventos.gravar_analytics); o painel mostra na aba "Analytics".

Impressões/CTR não saem pela Analytics API (400 "query is not supported"): só pela YouTube
Reporting API, num job diário do relatório channel_reach_basic_a1 (criado sozinho na 1ª vez).
O YouTube gera 1 CSV por dia (o 1º sai ~48h depois de criar o job, junto com os 30 dias
anteriores); cada dia novo é importado em reach_dia, e backfill do mesmo dia (createTime mais
novo) substitui o anterior. O total do vídeo soma os dias importados (desde o 1º relatório).
Se a Reporting API falhar, a coleta segue com as impressões já importadas e um aviso.

Projeto missao-em-cortes-analytics (token próprio, só leitura, nunca o do publisher).
Custo: US$ 0 (Data API ~3 unidades por rodada; Analytics e Reporting API, cota própria e grátis).
"""
import csv
import io
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, timedelta
from pathlib import Path

from _eventos import (evento, gravar_analytics, gravar_reach, reach_importados, reach_por_video,
                     termos_semana, ultima_coleta)
from _google import credenciais
from _youtube_leitura import (CLIENT_SECRET, ESCOPOS, MAX_SHORT_S, TOKEN, listar_videos,
                              nome_origem)

ROOT = Path(__file__).parent.parent
SEMANAL = ROOT / "state" / "analytics_semanal.md"
MAX_TERMOS = 25          # limite da API pra insightTrafficSourceDetail
REACH_TIPO = "channel_reach_basic_a1"
REACH_JOB = "missao-em-cortes-reach"


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


def job_reach(reporting) -> str:
    """Id do job do relatório Reach; cria na 1ª vez (o YouTube passa a gerar 1 CSV por dia)."""
    pagina = None
    while True:
        r = reporting.jobs().list(pageToken=pagina).execute()
        for job in r.get("jobs", []):
            if job["reportTypeId"] == REACH_TIPO:
                return job["id"]
        pagina = r.get("nextPageToken")
        if not pagina:
            break
    return reporting.jobs().create(body={"reportTypeId": REACH_TIPO, "name": REACH_JOB}).execute()["id"]


def relatorios_novos(reporting, job_id: str, importados: dict[str, str]) -> list[dict]:
    """Relatórios a importar: por dia, o de createTime mais novo (backfill substitui), só se
    ainda não foi importado com esse createTime ou um mais novo. [{dia, create_time, url}]."""
    por_dia, pagina = {}, None
    while True:
        r = reporting.jobs().reports().list(jobId=job_id, pageToken=pagina).execute()
        for rel in r.get("reports", []):
            dia = rel["startTime"][:10]
            if dia not in por_dia or rel["createTime"] > por_dia[dia]["create_time"]:
                por_dia[dia] = {"dia": dia, "create_time": rel["createTime"],
                                "url": rel["downloadUrl"]}
        pagina = r.get("nextPageToken")
        if not pagina:
            break
    return sorted((x for x in por_dia.values() if x["create_time"] > importados.get(x["dia"], "")),
                  key=lambda x: x["dia"])


def ler_reach(texto: str) -> list[dict]:
    """CSV do Reach (date, channel_id, video_id, video_thumbnail_impressions,
    video_thumbnail_impressions_ctr) → [{youtube_id, impressoes, ctr_pct}] somando por vídeo.
    O CTR vem como razão (cliques ÷ impressões) → %; se algum passar de 1, já veio em %."""
    soma: dict[str, list[float]] = {}
    for linha in csv.DictReader(io.StringIO(texto)):
        imp = int(float(linha["video_thumbnail_impressions"] or 0))
        ctr = float(linha["video_thumbnail_impressions_ctr"] or 0)
        acc = soma.setdefault(linha["video_id"], [0, 0.0, 0.0])
        acc[0] += imp
        acc[1] += imp * ctr
        acc[2] = max(acc[2], ctr)
    fator = 1 if any(acc[2] > 1 for acc in soma.values()) else 100
    return [{"youtube_id": vid, "impressoes": imp,
             "ctr_pct": round(cliques / imp * fator, 2) if imp else 0.0}
            for vid, (imp, cliques, _) in soma.items()]


def importar_reach(reporting, baixar) -> int:
    """Baixa e grava os relatórios Reach novos. baixar(url) → texto do CSV. Devolve quantos dias."""
    novos = relatorios_novos(reporting, job_reach(reporting), reach_importados())
    for rel in novos:
        gravar_reach(rel["dia"], rel["create_time"], ler_reach(baixar(rel["url"])))
    return len(novos)


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


def coletar_dados(yt, analytics, hoje: date | None = None, reach: dict | None = None) -> dict:
    """Lê o canal e devolve {data, metricas, trafego, termos, termos_canal, avisos}.
    reach: {youtube_id: {impressoes, ctr_pct}} já somado do relatório Reach (reach_por_video)."""
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
    imp = reach or {}
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
    from google.auth.transport.requests import AuthorizedSession
    creds = credenciais(ESCOPOS, TOKEN, CLIENT_SECRET, interativo=interativo)
    sessao = AuthorizedSession(creds)

    def baixar(url: str) -> str:
        r = sessao.get(url, timeout=60)
        r.raise_for_status()
        return r.content.decode("utf-8")

    aviso_reach = None
    try:
        dias = importar_reach(build("youtubereporting", "v1", credentials=creds,
                                    cache_discovery=False), baixar)
    except Exception as e:  # noqa: BLE001 — sem o Reach do dia, valem as impressões já importadas
        dias, aviso_reach = 0, f"relatório Reach (impressões/CTR) não lido ({str(e)[:150]})"
    desde, reach = reach_por_video()
    dados = coletar_dados(build("youtube", "v3", credentials=creds, cache_discovery=False),
                          build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False),
                          reach=reach)
    if aviso_reach:
        dados["avisos"].append(aviso_reach)
    dados["reach_desde"] = desde
    gravar_analytics(dados["data"], dados["metricas"], dados["trafego"], dados["termos"],
                     dados["termos_canal"])
    msg = (f"{len(dados['metricas'])} vídeo(s) · {len(dados['termos'])} termo(s) por vídeo · "
           f"{len(dados['termos_canal'])} termo(s) do canal (7 dias) · Reach: {dias} dia(s) novo(s)"
           + (f", impressões desde {desde}" if desde else ", ainda sem relatório"))
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
    print(f"Analytics {dados['data']}: {len(dados['metricas'])} vídeo(s) públicos · impressões/CTR "
          + (f"desde {dados['reach_desde']}" if dados.get("reach_desde")
             else "ainda sem relatório Reach (o 1º sai ~48h depois de criar o job)"))
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
