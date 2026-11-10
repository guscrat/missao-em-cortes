"""Contas do diagnóstico do canal, puras (sem rede, sem banco): usadas pelo resumo semanal do
17_analytics e pela aba Analytics do painel, pra os dois mostrarem o mesmo número."""
from datetime import date, timedelta

from _fronteira import FAIXAS, faixa_do_video
from _youtube_leitura import MAX_SHORT_S

SEMANAS_7D = 4           # média das views em 7 dias dos publicados nas últimas N semanas
RECOMENDACAO = ("SUBSCRIBER", "RELATED_VIDEO", "SHORTS")   # início/feed + sugeridos + Shorts
ROTULO_FAIXA = {"curto": "curto 3-10 min", "medio": "médio 10-20 min", "longo": "longo 20-30 min",
                "abaixo_3": "abaixo de 3 min", "acima_30": "acima de 30 min"}


def minutos_por_faixa(metricas: list[dict]) -> list[dict]:
    """[{faixa, n, views, min_por_view, retencao_pct}] dos longos com view, por faixa de duração
    do corte (só as que têm vídeo) + 'todos' no fim. Médias ponderadas pelas views."""
    longos = [m for m in metricas if (m.get("duracao_s") or 0) > MAX_SHORT_S and m.get("views")
              and m.get("assistido_s") is not None]
    grupos = {nome: [] for nome in ("abaixo_3", *(f[0] for f in FAIXAS), "acima_30")}
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
