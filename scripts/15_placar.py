"""Step 15 (off-pipeline): placar do canal rumo ao YPP → state/placar.json (agente="analista").

Uso: uv run py scripts/15_placar.py      (o Curador chama 1x/dia, no começo da rodada das 17h)

Grava o que o painel (aba Hoje → "Placar do canal") mostra contra as metas do YPP:
  - inscritos         Data API channels.list statistics (youtube.readonly)
  - horas_12m         horas assistidas nos últimos 365 dias SEM Shorts (o YPP conta só
                      vídeo longo): Analytics estimatedMinutesWatched por creatorContentType
  - views_shorts_90d  views de Shorts nos últimos 90 dias (creatorContentType = shorts)

Aproximação: o YPP conta só horas/views PÚBLICAS válidas; a Analytics não separa isso, então
o número daqui pode ficar um pouco acima do Studio. O Analytics atrasa ~2 dias.
Projeto missao-em-cortes-analytics (token próprio, só leitura, nunca o do publisher).
Custo: US$ 0 (1 unidade da cota da Data API; Analytics tem cota própria).
Falhou? O placar.json anterior fica como está e vira evento de falha no painel.
"""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, datetime, timedelta
from pathlib import Path

from _eventos import evento
from _google import credenciais
from _youtube_leitura import CLIENT_SECRET, ESCOPOS, TOKEN

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "state" / "placar.json"


def e_short(tipo: str) -> bool:
    """creatorContentType vem como "shorts"/"videoOnDemand" (a doc fala SHORTS/VIDEO_ON_DEMAND)."""
    return tipo.replace("_", "").lower() == "shorts"


def inscritos(yt) -> int:
    canal = yt.channels().list(part="statistics", mine=True).execute()["items"][0]
    return int(canal["statistics"].get("subscriberCount") or 0)


def por_tipo(analytics, metrica: str, dias: int, hoje: date) -> dict[str, float]:
    """{creatorContentType: soma da métrica} nos últimos `dias` dias."""
    r = analytics.reports().query(
        ids="channel==MINE", startDate=(hoje - timedelta(days=dias)).isoformat(),
        endDate=hoje.isoformat(), metrics=metrica, dimensions="creatorContentType").execute()
    return {tipo: float(valor) for tipo, valor in r.get("rows", [])}


def medir(yt, analytics, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    minutos = por_tipo(analytics, "estimatedMinutesWatched", 365, hoje)
    views = por_tipo(analytics, "views", 90, hoje)
    return {"atualizado": datetime.now().astimezone().isoformat(timespec="seconds"),
            "inscritos": inscritos(yt),
            "horas_12m": round(sum(v for t, v in minutos.items() if not e_short(t)) / 60, 1),
            "views_shorts_90d": int(sum(v for t, v in views.items() if e_short(t)))}


def atualizar(interativo: bool = True) -> dict:
    """Lê o canal e grava state/placar.json. interativo=False (Curador) nunca abre navegador."""
    from googleapiclient.discovery import build
    creds = credenciais(ESCOPOS, TOKEN, CLIENT_SECRET, interativo=interativo)
    placar = medir(build("youtube", "v3", credentials=creds, cache_discovery=False),
                   build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(placar, ensure_ascii=False, indent=2), encoding="utf-8")
    evento(None, "15_placar", "ok", agente="analista",
           mensagem=f"{placar['inscritos']} inscritos · {placar['horas_12m']} h (12m) · "
                    f"{placar['views_shorts_90d']} views de Shorts (90d)")
    return placar


def main(argv: list[str]) -> int:
    try:
        p = atualizar()
    except Exception as e:  # noqa: BLE001 — falha vira evento; o placar anterior fica
        evento(None, "15_placar", "falha", agente="analista", mensagem=str(e)[:300])
        print(f"[!] Não li o placar do canal: {e}", file=sys.stderr)
        return 1
    print(f"Placar: {p['inscritos']} inscritos / 1.000 · {p['horas_12m']} h / 4.000 (12 meses) · "
          f"{p['views_shorts_90d']} views de Shorts / 10 mi (90 dias) → {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
