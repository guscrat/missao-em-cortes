"""Leitura do NOSSO canal pelo projeto de métricas (missao-em-cortes-analytics, só leitura).

Compartilhado pelo 12 (retenção) e pelo 14 (o que já foi publicado/agendado). Usa o client e
o token próprios do projeto analytics, nunca os do publisher (upload). Como dono do canal, o
youtube.readonly enxerga também os vídeos privados e o publishAt dos agendados.
"""
import re
import unicodedata
from pathlib import Path

from _google import credenciais

ROOT = Path(__file__).parent.parent
CLIENT_SECRET = ROOT / "secrets" / "analytics_client_secret.json"   # projeto missao-em-cortes-analytics
TOKEN = ROOT / "secrets" / "analytics_token.json"
ESCOPOS = ["https://www.googleapis.com/auth/yt-analytics.readonly",
           "https://www.googleapis.com/auth/youtube.readonly"]
MAX_SHORT_S = 180   # até 3 min = Short

# insightTrafficSourceType → nome no painel/resumo (17_analytics)
ORIGENS = {"YT_SEARCH": "busca do YouTube", "RELATED_VIDEO": "vídeos sugeridos",
           "SUBSCRIBER": "inscritos (feed/início)", "YT_CHANNEL": "página do canal",
           "SHORTS": "feed de Shorts", "EXT_URL": "sites externos", "NOTIFICATION": "notificações",
           "PLAYLIST": "playlists", "YT_OTHER_PAGE": "outras páginas do YouTube",
           "NO_LINK_OTHER": "direto/desconhecido", "END_SCREEN": "tela final",
           "ANNOTATION": "cards/anotações", "HASHTAGS": "hashtags"}


def nome_origem(origem: str) -> str:
    return ORIGENS.get(origem, origem.lower().replace("_", " "))


def normalizar(titulo: str) -> str:
    t = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def duracao_iso(d: str) -> int:
    """'PT1H2M3S' → segundos."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s


def youtube(interativo: bool = True):
    """Cliente da Data API v3 com o token de métricas."""
    from googleapiclient.discovery import build
    creds = credenciais(ESCOPOS, TOKEN, CLIENT_SECRET, interativo=interativo)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def listar_videos(yt) -> list[dict]:
    """Todos os uploads do canal, inclusive privados e agendados:
    [{id, titulo, privacidade, publish_at, publicado, duracao_s}]."""
    canal = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = canal["contentDetails"]["relatedPlaylists"]["uploads"]
    itens, pagina = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails,snippet", playlistId=uploads,
                                    maxResults=50, pageToken=pagina).execute()
        itens += r["items"]
        pagina = r.get("nextPageToken")
        if not pagina:
            break
    videos = []
    for i in range(0, len(itens), 50):
        ids = [it["contentDetails"]["videoId"] for it in itens[i:i + 50]]
        r = yt.videos().list(part="contentDetails,snippet,status", id=",".join(ids)).execute()
        for v in r["items"]:
            videos.append({"id": v["id"], "titulo": v["snippet"]["title"],
                           "privacidade": v["status"]["privacyStatus"],
                           "publish_at": v["status"].get("publishAt"),
                           "publicado": v["snippet"]["publishedAt"],
                           "duracao_s": duracao_iso(v["contentDetails"]["duration"])})
    return videos
