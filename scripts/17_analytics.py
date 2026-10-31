"""Step 17 (off-pipeline): coleta diária do YouTube Analytics por vídeo → banco (agente="analista").

Uso:
    uv run py scripts/17_analytics.py            # coleta (o Curador chama 1x/dia, depois do placar)
    uv run py scripts/17_analytics.py semanal    # resumo da semana → state/analytics_semanal.md

Por vídeo PÚBLICO do canal, acumulado desde a publicação (o Analytics atrasa ~2 dias):
  - views; impressões e CTR da miniatura (relatório Reach da Reporting API, ver abaixo)
  - retenção média (% média assistida) e duração média assistida
  - origens de tráfego (insightTrafficSourceType: busca, sugeridos, inscritos, Shorts...)
  - termos de pesquisa do YouTube que trouxeram views (até 25 por vídeo)
Do canal inteiro, nos últimos 7 dias: os termos de pesquisa (a lista que o Editor recebe pra
usar nos títulos) e as origens de tráfego (tabela trafego_canal: % das views que NÃO vem da
busca, o sinal de que o algoritmo começou a recomendar).
Por vídeo novo: as views dos 7 primeiros dias depois de publicado (tabela views_7d, 1 consulta
por vídeo, 1 vez só, quando ele faz DIAS_7D_PRONTO dias: o Analytics atrasa ~2).

Resumo semanal (sexta, pelo Curador): a métrica principal é MINUTOS ASSISTIDOS POR VIEW, com
a retenção ao lado, por faixa de duração do corte (_fronteira.faixa_do_video); depois o % que
não vem da busca (semana x semana anterior), as views dos 7 primeiros dias dos vídeos novos,
os termos de busca, os antigos em alta, as origens e o CTR das miniaturas.

Vídeos EM ALTA: publicados há mais de DIAS_ANTIGO dias cujas views dos últimos 7 dias
passaram de MIN_VIEWS_SEMANA e de FATOR_ALTA x a média semanal de antes (o assunto voltou a
ser buscado). Saem com o tema do bloco (blocos.tema; Short/sem bloco = título) na tabela
em_alta: painel (aba Analytics), resumo de sexta e Curador, que prioriza lives desses temas.

Grava a foto do dia nas tabelas metricas_video / trafego_video / termos_busca / termos_canal
(_eventos.gravar_analytics) e em_alta (_eventos.gravar_em_alta); o painel mostra na aba
"Analytics".

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

from _eventos import (em_alta_atual, evento, gravar_analytics, gravar_em_alta, gravar_reach,
                      gravar_views_7d, reach_importados, reach_por_video, temas_por_youtube,
                      termos_semana, ultima_coleta, views_7d)
from _fronteira import FAIXAS, faixa_do_video
from _google import credenciais
from _youtube_leitura import (CLIENT_SECRET, ESCOPOS, MAX_SHORT_S, TOKEN, listar_videos,
                              nome_origem)

ROOT = Path(__file__).parent.parent
SEMANAL = ROOT / "state" / "analytics_semanal.md"
MAX_TERMOS = 25          # limite da API pra insightTrafficSourceDetail
REACH_TIPO = "channel_reach_basic_a1"
REACH_JOB = "missao-em-cortes-reach"
DIAS_ANTIGO = 30         # "vídeo antigo": publicado há mais que isso
MIN_VIEWS_SEMANA = 50    # abaixo disso é ruído, não alta
FATOR_ALTA = 3.0         # views da semana >= isso x a média semanal de antes
DIAS_7D_PRONTO = 9       # idade em que os 7 primeiros dias já estão no Analytics (atrasa ~2)
SEMANAS_7D = 4           # resumo: média das views em 7 dias dos publicados nas últimas N semanas
RECOMENDACAO = ("SUBSCRIBER", "RELATED_VIDEO", "SHORTS")   # início/feed + sugeridos + Shorts
ROTULO_FAIXA = {"curto": "curto 5-10 min", "medio": "médio 10-20 min", "longo": "longo 20-30 min",
                "abaixo_5": "abaixo de 5 min", "acima_30": "acima de 30 min"}


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


def trafego_canal(analytics, inicio: str, fim: str) -> list[dict]:
    """Origens de tráfego do canal inteiro no período."""
    return [{"origem": origem, "views": int(views)} for origem, views in _query(
        analytics, startDate=inicio, endDate=fim, dimensions="insightTrafficSourceType",
        metrics="views", sort="-views")]


def views_primeiros_7d(analytics, videos: list[dict], hoje: date, feitos: set[str]) -> list[dict]:
    """Views dos 7 primeiros dias (dia da publicação + 6) dos vídeos com DIAS_7D_PRONTO+ dias
    que ainda não estão em `feitos`. 1 consulta por vídeo."""
    saida = []
    for v in videos:
        if v["id"] in feitos or _idade(v["publicado"], hoje) < DIAS_7D_PRONTO:
            continue
        ini = date.fromisoformat(v["publicado"][:10])
        base = basicas(analytics, [v["id"]], ini.isoformat(), (ini + timedelta(days=6)).isoformat())
        saida.append({"youtube_id": v["id"], "titulo": v["titulo"], "publicado": v["publicado"],
                      "duracao_s": v["duracao_s"], "views": base.get(v["id"], {}).get("views", 0)})
    return saida


def _idade(publicado: str, hoje: date) -> int:
    return (hoje - date.fromisoformat(publicado[:10])).days


def em_alta(metricas: list[dict], semana: dict[str, int], hoje: date) -> list[dict]:
    """Vídeos antigos (> DIAS_ANTIGO dias) cujas views da semana (semana: {id: views nos
    últimos 7 dias}) bateram MIN_VIEWS_SEMANA e FATOR_ALTA x a média semanal de antes.
    Maior fator primeiro. Sem `tema` (quem tem banco completa)."""
    saida = []
    for m in metricas:
        idade, views_semana = _idade(m["publicado"], hoje), semana.get(m["youtube_id"], 0)
        if idade <= DIAS_ANTIGO or views_semana < MIN_VIEWS_SEMANA:
            continue
        media_antes = max(0, (m["views"] or 0) - views_semana) / ((idade - 7) / 7)
        fator = views_semana / max(media_antes, 1)
        if fator >= FATOR_ALTA:
            saida.append({"youtube_id": m["youtube_id"], "titulo": m["titulo"],
                          "publicado": m["publicado"], "views_semana": views_semana,
                          "views_total": m["views"], "fator": round(fator, 1)})
    return sorted(saida, key=lambda x: (-x["fator"], -x["views_semana"]))


def coletar_dados(yt, analytics, hoje: date | None = None, reach: dict | None = None,
                  feitos_7d: set[str] = frozenset()) -> dict:
    """Lê o canal e devolve {data, metricas, trafego, termos, termos_canal, trafego_canal,
    views_7d, em_alta, avisos}. reach: {youtube_id: {impressoes, ctr_pct}} já somado do
    relatório Reach (reach_por_video); feitos_7d: ids que já têm as views dos 7 primeiros dias."""
    hoje = hoje or date.today()
    fim = hoje.isoformat()
    videos = [v for v in listar_videos(yt) if v["privacidade"] == "public"]
    avisos = []
    if not videos:
        return {"data": fim, "metricas": [], "trafego": [], "termos": [], "termos_canal": [],
                "trafego_canal": [], "views_7d": [], "em_alta": [],
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
    semana_ini = (hoje - timedelta(days=7)).isoformat()
    canal = termos(analytics, semana_ini, fim)
    antigos = [v["id"] for v in videos if _idade(v["publicado"], hoje) > DIAS_ANTIGO
               and base.get(v["id"], {}).get("views")]
    try:
        semana = {vid: x["views"] for vid, x in basicas(analytics, antigos, semana_ini, fim).items()}
    except Exception as e:  # noqa: BLE001 — sem a semana, a foto do dia vale sem os "em alta"
        semana = {}
        avisos.append(f"vídeos antigos em alta não calculados ({str(e)[:150]})")
    try:
        traf_canal = trafego_canal(analytics, semana_ini, fim)
        v7 = views_primeiros_7d(analytics, videos, hoje, feitos_7d)
    except Exception as e:  # noqa: BLE001 — sem eles, a foto do dia vale; tenta de novo amanhã
        traf_canal, v7 = [], []
        avisos.append(f"origens do canal / views dos 7 primeiros dias não lidas ({str(e)[:150]})")
    return {"data": fim, "metricas": metricas, "trafego": traf, "termos": ters,
            "termos_canal": canal, "trafego_canal": traf_canal, "views_7d": v7,
            "em_alta": em_alta(metricas, semana, hoje), "avisos": avisos}


def coletar(interativo: bool = True) -> dict:
    """Coleta e grava no banco. interativo=False (Curador) nunca abre o navegador."""
    from googleapiclient.discovery import build
    from google.auth.transport.requests import AuthorizedSession
    creds = credenciais(ESCOPOS, TOKEN, CLIENT_SECRET, interativo=interativo)
    sessao = AuthorizedSession(creds)

    def baixar(url: str) -> str:
        r = sessao.get(url, timeout=60)
        r.raise_for_status()
        return r.content.decode("utf-8-sig")   # BOM no CSV não suja o 1º cabeçalho

    aviso_reach = None
    try:
        dias = importar_reach(build("youtubereporting", "v1", credentials=creds,
                                    cache_discovery=False), baixar)
    except Exception as e:  # noqa: BLE001 — sem o Reach do dia, valem as impressões já importadas
        dias, aviso_reach = 0, f"relatório Reach (impressões/CTR) não lido ({str(e)[:150]})"
    desde, reach = reach_por_video()
    dados = coletar_dados(build("youtube", "v3", credentials=creds, cache_discovery=False),
                          build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False),
                          reach=reach, feitos_7d={x["youtube_id"] for x in views_7d()})
    if aviso_reach:
        dados["avisos"].append(aviso_reach)
    dados["reach_desde"] = desde
    gravar_analytics(dados["data"], dados["metricas"], dados["trafego"], dados["termos"],
                     dados["termos_canal"], dados["trafego_canal"])
    gravar_views_7d(dados["views_7d"])
    temas = temas_por_youtube([x["youtube_id"] for x in dados["em_alta"]])
    for x in dados["em_alta"]:
        x["tema"] = temas.get(x["youtube_id"])
    gravar_em_alta(dados["data"], dados["em_alta"])
    msg = (f"{len(dados['metricas'])} vídeo(s) · {len(dados['termos'])} termo(s) por vídeo · "
           f"{len(dados['termos_canal'])} termo(s) do canal (7 dias) · "
           f"{len(dados['em_alta'])} antigo(s) em alta · Reach: {dias} dia(s) novo(s)"
           + (f", impressões desde {desde}" if desde else ", ainda sem relatório"))
    for aviso in dados["avisos"]:
        evento(None, "17_analytics", "aviso", agente="analista", mensagem=aviso[:300])
    evento(None, "17_analytics", "ok", agente="analista", mensagem=msg)
    return dados


# ── resumo semanal ─────────────────────────────────────────────────────────

def linha_em_alta(x: dict) -> str:
    """Uma linha do vídeo em alta (resumo semanal e do Curador)."""
    return (f"**{x['tema']}** — {x['views_semana']} views na semana ({x['fator']:.0f}x o ritmo de "
            f"antes) · \"{x['titulo'][:60]}\", de {x['publicado'][8:10]}/{x['publicado'][5:7]}")


def minutos_por_faixa(metricas: list[dict]) -> list[dict]:
    """[{faixa, n, views, min_por_view, retencao_pct}] dos longos com view, por faixa de duração
    do corte (só as que têm vídeo) + 'todos' no fim. Médias ponderadas pelas views."""
    longos = [m for m in metricas if (m.get("duracao_s") or 0) > MAX_SHORT_S and m.get("views")
              and m.get("assistido_s") is not None]
    grupos = {nome: [] for nome in ("abaixo_5", *(f[0] for f in FAIXAS), "acima_30")}
    for m in longos:
        grupos[faixa_do_video(m["duracao_s"])].append(m)

    def linha(nome, ms):
        views = sum(m["views"] for m in ms)
        return {"faixa": nome, "n": len(ms), "views": views,
                "min_por_view": round(sum(m["assistido_s"] * m["views"] for m in ms) / views / 60, 1),
                "retencao_pct": round(sum((m["retencao_pct"] or 0) * m["views"] for m in ms) / views, 1)}
    saida = [linha(nome, ms) for nome, ms in grupos.items() if ms]
    return saida + [linha("todos", longos)] if longos else []


def fora_da_busca(trafego: dict[str, int]) -> dict | None:
    """{total, fora_pct, recomendacao_pct} das views de um período (None sem views)."""
    total = sum(trafego.values())
    if not total:
        return None
    return {"total": total, "fora_pct": round(100 * (total - trafego.get("YT_SEARCH", 0)) / total, 1),
            "recomendacao_pct": round(100 * sum(trafego.get(o, 0) for o in RECOMENDACAO) / total, 1)}


def media_7d(v7: list[dict], hoje: date, semanas: int, desloc: int = 0) -> tuple[int, float | None]:
    """(n, média de views em 7 dias) dos longos publicados entre (semanas + desloc) e desloc
    semanas atrás."""
    ini, fim = hoje - timedelta(weeks=semanas + desloc), hoje - timedelta(weeks=desloc)
    vs = [x["views"] for x in v7 if (x.get("duracao_s") or 0) > MAX_SHORT_S
          and ini < date.fromisoformat(x["publicado"][:10]) <= fim]
    return len(vs), (round(sum(vs) / len(vs), 1) if vs else None)


def resumo_semanal(termos_top: list[dict], metricas: list[dict], trafego_canal: dict[str, int],
                   data: str, em_alta_top: list[dict] | None = None,
                   trafego_semana: dict[str, int] | None = None,
                   trafego_antes: dict[str, int] | None = None,
                   v7: list[dict] | None = None) -> str:
    """Markdown do resumo semanal. Abre com a métrica principal (minutos assistidos por view,
    com a retenção, por faixa de duração), depois o sinal de recomendação (% fora da busca) e
    as views dos vídeos novos nos 7 primeiros dias; os termos de pesquisa (insumo do Editor) vêm
    em seguida."""
    linhas = [f"# Analytics da semana ({data})", "",
              "## Minutos assistidos por view (métrica principal), por faixa de duração",
              "Longos públicos, acumulado desde a publicação; a duração é a do corte (sem cold open, "
              "intro, card e outro).", ""]
    faixas = minutos_por_faixa(metricas)
    if faixas:
        linhas += ["| Faixa | Vídeos | Views | Min/view | Retenção |", "|---|---|---|---|---|"]
        linhas += [f"| {ROTULO_FAIXA.get(f['faixa'], '**todos**')} | {f['n']} | {f['views']} | "
                   f"{f['min_por_view']:.1f} | {f['retencao_pct']:.0f}% |" for f in faixas]
    else:
        linhas.append("- (nenhum longo com views ainda)")
    linhas += ["", "## Views que não vêm da busca (sinal de que o algoritmo começou a recomendar)", ""]
    agora, antes = fora_da_busca(trafego_semana or {}), fora_da_busca(trafego_antes or {})
    if agora:
        linhas.append(f"- Últimos 7 dias: **{agora['fora_pct']:.0f}%** das {agora['total']} views "
                      f"(recomendação — início/feed, sugeridos e Shorts: {agora['recomendacao_pct']:.0f}%)")
        linhas.append(f"- Semana anterior: {antes['fora_pct']:.0f}% das {antes['total']} views "
                      f"(recomendação: {antes['recomendacao_pct']:.0f}%)" if antes
                      else "- Semana anterior: sem coleta pra comparar")
    else:
        linhas.append("- (sem as origens de tráfego do canal nos últimos 7 dias)")
    hoje = date.fromisoformat(data) if data[:4].isdigit() else date.today()
    linhas += ["", "## Vídeos novos: views nos 7 primeiros dias", ""]
    n, media = media_7d(v7 or [], hoje, SEMANAS_7D)
    n_antes, media_antes = media_7d(v7 or [], hoje, SEMANAS_7D, desloc=SEMANAS_7D)
    if media is not None:
        linhas.append(f"- Média dos longos publicados nas últimas {SEMANAS_7D} semanas: **{media:.1f}** "
                      f"views ({n} vídeos)" + (f" · {SEMANAS_7D} semanas antes: {media_antes:.1f} "
                                                f"({n_antes} vídeos)" if media_antes is not None else ""))
        linhas += [f"- {x['views']} · {x['titulo'][:70]} ({x['publicado'][8:10]}/{x['publicado'][5:7]})"
                   for x in [x for x in v7 or [] if (x.get("duracao_s") or 0) > MAX_SHORT_S][:5]]
    else:
        linhas.append(f"- (nenhum longo com {DIAS_7D_PRONTO}+ dias publicado nas últimas "
                      f"{SEMANAS_7D} semanas)")
    linhas += ["", "## Termos de pesquisa que mais trouxeram views (busca do YouTube, 7 dias)",
              "O Editor recebe esta lista ao reescrever títulos: usar um termo só se a fala sustentar.", ""]
    linhas += ([f"{i}. **{t['termo']}** — {t['views']} views" for i, t in enumerate(termos_top, 1)]
               or ["- (nenhuma view vinda da busca nos últimos 7 dias)"])
    linhas += ["", f"## Vídeos antigos em alta (publicados há {DIAS_ANTIGO}+ dias)",
               "O assunto voltou a ser procurado: o Curador prioriza lives novas sobre esses temas.", ""]
    linhas += ([f"- {linha_em_alta(x)}" for x in em_alta_top or []]
               or ["- (nenhum vídeo antigo disparou nesta semana)"])
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
                           coleta["data"] or "sem coleta", em_alta_atual(),
                           coleta.get("trafego_semana"), coleta.get("trafego_semana_antes"),
                           views_7d())
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
    for x in dados["em_alta"]:
        print(f"  [em alta] {x['views_semana']} views na semana ({x['fator']:.0f}x) · "
              f"{(x['tema'] or x['titulo'])[:55]}")
    if dados["termos_canal"]:
        print("\n  Termos de busca (canal, 7 dias): "
              + ", ".join(f"{t['termo']} ({t['views']})" for t in dados["termos_canal"][:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
