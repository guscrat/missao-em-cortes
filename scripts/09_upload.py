"""Step 9: sobe os vídeos finalizados pro YouTube como PRIVADOS agendados (publishAt).

Uso:
    uv run py scripts/09_upload.py <stem> --dry-run      # mostra o plano, não chama a API
    uv run py scripts/09_upload.py <stem> [--bloco=N] [--max=N]

O que lê (da pasta do vídeo):
  - blocos.json        → quais blocos existem
  - descricoes.txt     → título, descrição e tags (gerado pelo step 8; edição manual no
                         txt é respeitada). Bloco com "[COLAR URL DA LIVE AQUI]" NÃO sobe.
  - finalizados/video_NN_*.mp4 (prefere _polido) e a thumb escolhida (manual > a > b > c)

Agendamento: config/upload.json (horário, intervalo, fuso). O próximo slot vem depois do
último agendado em QUALQUER vídeo (lê outputs/*/youtube.json), então lives diferentes não
disputam o mesmo horário.

Idempotente: bloco com youtube_id (no youtube.json da pasta ou no banco) não sobe de
novo. Se da outra vez só a thumb falhou, tenta só a thumb. O youtube.json é gravado logo
depois de cada upload — é o registro à prova de falha (o banco é best-effort).
Única janela: se o processo morrer entre o fim do upload e essa gravação (segundos),
o próximo run sobe de novo. Depois de um crash no meio do upload, confira o Studio antes.

Cota: a YouTube Data API é grátis (US$ 0), mas tem 10.000 unidades/dia, que zeram à
meia-noite do Pacífico. Upload ≈ 1.600 e thumbnail = 50. O gasto fica em
state/cota_youtube.json e o script para ANTES de estourar.

Credenciais (fora do Git): secrets/youtube_client_secret.json (baixado do Google Cloud)
e secrets/youtube_token.json (criado no 1º login, que abre o navegador).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from _eventos import evento, ler_bloco, upsert_bloco
from _paths import achar_pasta, escolher_arquivo, escolher_thumb, stem_de

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "upload.json"
CLIENT_SECRET = ROOT / "secrets" / "youtube_client_secret.json"
TOKEN = ROOT / "secrets" / "youtube_token.json"
COTA_PATH = ROOT / "state" / "cota_youtube.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

DEFAULTS = {
    "horario": "18:00", "intervalo_dias": 1, "fuso": "America/Sao_Paulo",
    "antecedencia_min_horas": 2, "categoria_id": "25", "idioma": "pt-BR",
    "feito_para_criancas": False,
    "cota_limite_dia": 10_000, "cota_upload": 1_600, "cota_thumbnail": 50,
}
PLACEHOLDER_URL = "[COLAR URL DA LIVE AQUI]"
LIMITE_THUMB_BYTES = 2 * 1024 * 1024     # thumbnails.set recusa acima de 2 MB
LIMITE_TITULO = 100                      # chars
LIMITE_DESCRICAO = 5000                  # bytes
LIMITE_TAGS = 500                        # chars (somando vírgulas e aspas)


def agora() -> datetime:
    return datetime.now(timezone.utc)


def carregar_config(path: Path | None = None) -> dict:
    path = path or CONFIG
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


# ── descricoes.txt (formato do 08_descricao.py) ────────────────────────────

_CABECALHO_BLOCO = re.compile(r"^=+\nVÍDEO (\d+) — [^\n]*\n=+\n", re.M)
_TITULO = re.compile(r"^TÍTULO \(\d+ chars\):\n(.+)$", re.M)
_CORPO = re.compile(r"^-+\nDESCRIÇÃO:\n-+\n(.*?)\n-+\nTAGS[^\n]*\n-+\n([^\n]*)", re.M | re.S)


def ler_descricoes(texto: str) -> dict[int, dict]:
    """{bloco_id: {"titulo", "descricao", "tags"}} a partir do descricoes.txt."""
    partes = _CABECALHO_BLOCO.split(texto.replace("\r\n", "\n"))
    saida = {}
    for bid, corpo in zip(partes[1::2], partes[2::2]):
        titulo, miolo = _TITULO.search(corpo), _CORPO.search(corpo)
        if not (titulo and miolo):
            continue
        saida[int(bid)] = {
            "titulo": titulo.group(1).strip(),
            "descricao": miolo.group(1).strip(),
            "tags": [t.strip() for t in miolo.group(2).split(",") if t.strip()],
        }
    return saida


def _sem_sinais(s: str) -> str:
    # a API rejeita < e > em título/descrição
    return s.replace("<", "‹").replace(">", "›")


def preparar_metadados(meta: dict) -> dict:
    """Aplica os limites da API (título 100 chars, descrição 5000 bytes, tags 500 chars)."""
    titulo = _sem_sinais(meta["titulo"])[:LIMITE_TITULO]
    descricao = _sem_sinais(meta["descricao"])
    descricao = descricao.encode("utf-8")[:LIMITE_DESCRICAO].decode("utf-8", "ignore")
    tags, total = [], 0
    for t in meta["tags"]:
        t = _sem_sinais(t)
        custo = len(t) + (2 if " " in t else 0) + (1 if tags else 0)  # aspas + vírgula
        if total + custo > LIMITE_TAGS:
            break
        tags.append(t)
        total += custo
    return {"titulo": titulo, "descricao": descricao, "tags": tags}


# ── agendamento ────────────────────────────────────────────────────────────

def ultimo_agendado(outputs: Path) -> datetime | None:
    """Maior publish_at registrado em qualquer outputs/*/youtube.json."""
    datas = []
    for reg in outputs.glob("*/youtube.json"):
        try:
            for item in json.loads(reg.read_text(encoding="utf-8")).values():
                if item.get("publish_at"):
                    datas.append(datetime.fromisoformat(item["publish_at"]))
        except (OSError, ValueError, AttributeError) as e:
            print(f"   [aviso] ignorando {reg} ilegível ({e})")
    return max(datas) if datas else None


def proximos_slots(n: int, ultimo: datetime | None, cfg: dict,
                   agora_: datetime | None = None) -> list[datetime]:
    """n horários de publicação, no horário do config, espaçados por intervalo_dias.
    Começa no 1º horário que respeite a antecedência mínima E venha depois do último
    já agendado (+ intervalo)."""
    tz = ZoneInfo(cfg["fuso"])
    h, m = map(int, cfg["horario"].split(":"))
    passo = timedelta(days=cfg["intervalo_dias"])

    minimo = (agora_ or agora()).astimezone(tz) + timedelta(hours=cfg["antecedencia_min_horas"])
    slot = minimo.replace(hour=h, minute=m, second=0, microsecond=0)
    if slot < minimo:
        slot += timedelta(days=1)
    if ultimo:
        depois = (ultimo.astimezone(tz) + passo).replace(hour=h, minute=m, second=0, microsecond=0)
        slot = max(slot, depois)
    return [slot + i * passo for i in range(n)]


# ── registro local (youtube.json) e cota ───────────────────────────────────

def ler_registro(pasta: Path) -> dict:
    p = pasta / "youtube.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def salvar_registro(pasta: Path, registro: dict) -> None:
    p = pasta / "youtube.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)   # atômico: nunca fica um youtube.json pela metade


class Cota:
    """Unidades gastas hoje (dia do Pacífico, que é quando a cota zera)."""

    def __init__(self, limite: int, path: Path | None = None):
        self.limite, self.path = limite, path or COTA_PATH
        self.dia = agora().astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
        dados = {}
        if self.path.exists():
            try:
                dados = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        self.usadas = dados.get("usadas", 0) if dados.get("dia_pacifico") == self.dia else 0

    def cabe(self, unidades: int) -> bool:
        return self.usadas + unidades <= self.limite

    def gastar(self, unidades: int) -> None:
        self.usadas += unidades
        self._salvar()

    def esgotar(self) -> None:
        """A API disse quotaExceeded: alguém mais gastou a cota. Trava até amanhã."""
        self.usadas = self.limite
        self._salvar()

    def _salvar(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"dia_pacifico": self.dia, "usadas": self.usadas}),
                             encoding="utf-8")


# ── API do YouTube ─────────────────────────────────────────────────────────

def autenticar():
    """Cliente da API. 1ª vez abre o navegador pro login; depois reusa o token."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            print("   [aviso] token do YouTube expirou/foi revogado — vai pedir login de novo")
            creds = None
    if not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            sys.exit(f"[!] Falta {CLIENT_SECRET.relative_to(ROOT)} — baixe a credencial OAuth "
                     f"(app de desktop) no Google Cloud e salve com esse nome.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _cota_estourada(e: HttpError) -> bool:
    return e.resp.status == 403 and b"quotaExceeded" in (e.content or b"")


def subir_video(youtube, video: Path, meta: dict, publish_at: datetime, cfg: dict) -> str:
    body = {
        "snippet": {"title": meta["titulo"], "description": meta["descricao"],
                    "tags": meta["tags"], "categoryId": cfg["categoria_id"],
                    "defaultLanguage": cfg["idioma"], "defaultAudioLanguage": cfg["idioma"]},
        "status": {"privacyStatus": "private",
                   "publishAt": publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "selfDeclaredMadeForKids": cfg["feito_para_criancas"]},
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                            resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, tentativas, ultimo_pct = None, 0, -25
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status and status.progress() * 100 >= ultimo_pct + 25:
                ultimo_pct = int(status.progress() * 100)
                print(f"   ... {ultimo_pct}%")
        except HttpError as e:
            if e.resp.status not in (500, 502, 503, 504) or tentativas >= 5:
                raise
            tentativas += 1
            print(f"   [aviso] erro {e.resp.status} no upload, tentativa {tentativas}/5")
            time.sleep(2 ** tentativas)
    return resp["id"]


def subir_thumb(youtube, thumb: Path, video_id: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        if thumb.stat().st_size > LIMITE_THUMB_BYTES:
            from PIL import Image
            jpg = Path(tmp) / f"{thumb.stem}.jpg"
            Image.open(thumb).convert("RGB").save(jpg, "JPEG", quality=90)
            thumb = jpg
        mime = "image/jpeg" if thumb.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        youtube.thumbnails().set(videoId=video_id,
                                 media_body=MediaFileUpload(str(thumb), mimetype=mime)).execute()


# ── orquestração ───────────────────────────────────────────────────────────

def _args(argv: list[str]) -> tuple[str, dict]:
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        sys.exit("Uso: uv run py scripts/09_upload.py <stem> [--bloco=N] [--max=N] [--dry-run]")
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    return pos[0], flags


def main(argv: list[str]) -> int:
    alvo, flags = _args(argv)
    dry = bool(flags.get("dry-run"))
    so_bloco = int(flags["bloco"]) if "bloco" in flags else None
    maximo = int(flags["max"]) if "max" in flags else None

    pasta = achar_pasta(alvo)
    stem = stem_de(pasta)
    cfg = carregar_config()
    desc_txt = pasta / "descricoes.txt"
    if not desc_txt.exists():
        sys.exit(f"[!] {desc_txt} não existe — rode o step 8 (08_descricao.py) antes.")
    descricoes = ler_descricoes(desc_txt.read_text(encoding="utf-8"))
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
    registro = ler_registro(pasta)

    novos, so_thumb = [], []
    for b in blocos:
        bid = b["id"]
        if so_bloco is not None and bid != so_bloco:
            continue
        nn = f"{bid:02d}"
        reg = registro.get(nn, {})
        thumb = escolher_thumb(pasta / "thumbs", nn)
        yt_id = reg.get("youtube_id") or (ler_bloco(stem, bid) or {}).get("youtube_id")
        if yt_id:
            if reg and not reg.get("thumb_ok") and thumb:
                so_thumb.append((bid, nn, thumb, yt_id))
            else:
                print(f"   {nn}: já agendado ({yt_id}) — pulando")
            continue
        video = escolher_arquivo(pasta / "finalizados", f"video_{nn}_*.mp4")
        meta = descricoes.get(bid)
        problema = ("sem vídeo em finalizados/" if not video else
                    "sem entrada no descricoes.txt" if not meta else
                    "URL da fonte faltando na descrição (crédito obrigatório)"
                    if PLACEHOLDER_URL in meta["descricao"] else None)
        if problema:
            print(f"   [!] {nn}: {problema} — não sobe")
            continue
        if not thumb:
            print(f"   [aviso] {nn}: sem thumb — sobe sem (YouTube usa um frame)")
        novos.append((bid, nn, video, thumb, preparar_metadados(meta)))

    if maximo is not None:
        novos = novos[:maximo]
    slots = proximos_slots(len(novos), ultimo_agendado(pasta.parent), cfg)
    custo_un = lambda thumb: cfg["cota_upload"] + (cfg["cota_thumbnail"] if thumb else 0)  # noqa: E731
    estimativa = sum(custo_un(n[3]) for n in novos) + cfg["cota_thumbnail"] * len(so_thumb)

    print(f"\nPlano pra '{stem}': {len(novos)} upload(s), {len(so_thumb)} thumb(s) pendente(s)")
    for (_, nn, video, thumb, meta), slot in zip(novos, slots):
        print(f"   {nn}  {slot:%d/%m %H:%M}  {meta['titulo'][:60]}")
        print(f"       {video.name} · thumb: {thumb.name if thumb else '—'} · {len(meta['tags'])} tags")
    print(f"   Cota estimada: {estimativa:,} unidades (limite {cfg['cota_limite_dia']:,}/dia) · custo US$ 0")
    if dry or not (novos or so_thumb):
        print("\n(dry-run: nada foi enviado)" if dry else "\nNada a fazer.")
        return 0

    cota = Cota(cfg["cota_limite_dia"])
    print(f"   Cota já usada hoje (dia do Pacífico): {cota.usadas:,}")
    youtube = autenticar()
    agendados, falhas, parou = 0, 0, False

    for bid, nn, thumb, yt_id in so_thumb:
        if not cota.cabe(cfg["cota_thumbnail"]):
            parou = True
            break
        cota.gastar(cfg["cota_thumbnail"])
        try:
            subir_thumb(youtube, thumb, yt_id)
            registro[nn]["thumb_ok"] = True
            salvar_registro(pasta, registro)
            print(f"   {nn}: thumb enviada ({yt_id})")
        except HttpError as e:
            print(f"   [!] {nn}: thumb falhou de novo ({e.resp.status})")
            evento(stem, "09_upload", "aviso", agente="publicador", bloco_id=bid,
                   mensagem=f"thumb falhou: {e.resp.status}")

    for (bid, nn, video, thumb, meta), slot in zip(novos, slots):
        if parou or not cota.cabe(custo_un(thumb)):
            print(f"\n[!] Parando antes de estourar a cota: {cota.usadas:,}/{cota.limite:,} usadas. "
                  f"Rode de novo amanhã (zera à meia-noite do Pacífico, ~4h-5h em Brasília).")
            evento(stem, "09_upload", "aviso", agente="publicador",
                   mensagem=f"cota: parou em {cota.usadas}/{cota.limite}")
            break
        print(f"\n>> {nn}: subindo {video.name} (sai {slot:%d/%m %H:%M})")
        t0 = time.time()
        evento(stem, "09_upload", "inicio", agente="publicador", bloco_id=bid)
        cota.gastar(cfg["cota_upload"])   # a API cobra mesmo se falhar
        try:
            yt_id = subir_video(youtube, video, meta, slot, cfg)
        except HttpError as e:
            if _cota_estourada(e):
                cota.esgotar()
                parou = True
            falhas += 1
            print(f"   [!] {nn}: upload falhou ({e.resp.status}{', cota esgotada' if parou else ''})")
            evento(stem, "09_upload", "falha", agente="publicador", bloco_id=bid,
                   mensagem=f"http {e.resp.status}", duracao_s=time.time() - t0)
            if parou:
                break
            continue

        registro[nn] = {"youtube_id": yt_id, "publish_at": slot.isoformat(),
                        "titulo": meta["titulo"], "thumb_ok": False}
        salvar_registro(pasta, registro)   # antes de tudo: é o que garante a idempotência
        upsert_bloco(stem, bid, status="agendado", forcar_status=True,
                     publish_at=slot.isoformat(), youtube_id=yt_id, titulo=meta["titulo"])
        unidades = cfg["cota_upload"]
        if thumb and cota.cabe(cfg["cota_thumbnail"]):
            cota.gastar(cfg["cota_thumbnail"])
            unidades += cfg["cota_thumbnail"]
            try:
                subir_thumb(youtube, thumb, yt_id)
                registro[nn]["thumb_ok"] = True
                salvar_registro(pasta, registro)
            except HttpError as e:
                print(f"   [aviso] {nn}: vídeo subiu mas a thumb falhou ({e.resp.status}) — "
                      f"rode de novo pra tentar só a thumb")
        agendados += 1
        print(f"   OK https://youtu.be/{yt_id} · privado, publica {slot:%d/%m %H:%M}")
        evento(stem, "09_upload", "ok", agente="publicador", bloco_id=bid,
               mensagem=f"youtube_id={yt_id} publishAt={slot.isoformat()} cota={unidades}",
               duracao_s=time.time() - t0)

    print(f"\n{'=' * 60}\nOK {agendados} vídeo(s) agendado(s) · {falhas} falha(s) · "
          f"cota hoje {cota.usadas:,}/{cota.limite:,} · custo US$ 0")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
