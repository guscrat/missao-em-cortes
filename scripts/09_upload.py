"""Step 9: sobe os vídeos finalizados pro YouTube como privados com publishAt (agendamento público).

Uso:
    uv run py scripts/09_upload.py <stem> --dry-run      # mostra o plano, não chama a API
    uv run py scripts/09_upload.py <stem> [--bloco=N] [--max=N]
    uv run py scripts/09_upload.py <stem> --bloco=N --teste   # upload de TESTE (único liberado sem auditoria)
    uv run py scripts/09_upload.py <stem>|todos --shorts [--bloco=N] [--max=N]   # Shorts (shorts/)
    ... --dry-run --como-aprovada   # simula o plano como se a auditoria já estivesse aprovada

O que lê (da pasta do vídeo):
  - blocos.json        → quais blocos existem
  - descricoes.txt     → título, descrição e tags (gerado pelo step 8; edição manual no
                         txt é respeitada). Bloco com "[COLAR URL DA LIVE AQUI]" NÃO sobe.
  - finalizados/video_NN_*.mp4 (prefere _polido) e a thumb escolhida (manual > a > b > c)

Trava da auditoria (config/upload.json → "auditoria_aprovada"):
  - false (padrão): vídeo enviado por projeto de API NÃO auditado fica BLOQUEADO como privado
    no YouTube — não dá pra publicar nem recorrer, só reenviando. Então o script RECUSA subir,
    exceto upload marcado como teste (--teste, exige --bloco=N): sobe privado, sem data, com
    "[TESTE]" no título, registrado à parte em youtube_teste.json (não conta como upload real
    do bloco nem mexe no status dele no banco). Serve pra screencast/validação.
  - true: sobe privado + publishAt (publica sozinho no horário agendado).

Agendamento: config/upload.json (horário, intervalo, fuso). O próximo slot vem depois do
último longo agendado/publicado em QUALQUER vídeo: os outputs/*/youtube.json (API) e o que
foi agendado à mão (_cobertura: canal.json do 14 + banco), então nada disputa o mesmo dia.

Shorts (--shorts): sobe os shorts/short_NN_*.mp4 (do 10_shorts) como privados + publishAt
nos "shorts_horarios" do config (2/dia), só de bloco cujo longo JÁ está no YouTube, no 1º
horário livre a partir da ida do longo ao ar. "todos" = um plano só com todas as lives.
Título = manchete do próprio Short (texto_thumb, até 60 chars; o 14 casa por ela),
descrição do longo com "Vídeo completo: youtu.be/<longo>" no topo. Registro em
youtube_shorts.json e youtube_id/postado no shorts/shorts.json. Short com "revisar" (pouco
rosto) não sobe. O "vídeo relacionado" do Short NÃO existe na API: é marcado à mão no
Studio (lista em `dia_d.py relacionados`).

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
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from _canal import eh_nosso_canal
from _cobertura import agenda_canal
from _descricoes import ler_descricoes
from _eventos import evento, ler_bloco, upsert_bloco
from _google import credenciais
import _paths
from _paths import achar_pasta, escolher_arquivo, escolher_thumb, stem_de

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "upload.json"
TOKEN = ROOT / "secrets" / "youtube_token.json"
COTA_PATH = ROOT / "state" / "cota_youtube.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

DEFAULTS = {
    "auditoria_aprovada": False, "horario": "18:00", "intervalo_dias": 1, "fuso": "America/Sao_Paulo",
    "antecedencia_min_horas": 2, "categoria_id": "25", "idioma": "pt-BR",
    "feito_para_criancas": False,
    "cota_limite_dia": 10_000, "cota_upload": 1_600, "cota_thumbnail": 50,
    "shorts_horarios": ["12:00", "20:00"],
}
PLACEHOLDER_URL = "[COLAR URL DA LIVE AQUI]"
TESTE_JSON = "youtube_teste.json"
SHORTS_JSON = "youtube_shorts.json"
LIMITE_TITULO_SHORT = 60               # manchete curta
NAO_SOBE = {"quarentena", "descartado", "arquivado"}   # decisão do revisor/editor/curadoria
PREFIXO_TESTE = "[TESTE] "
MSG_TRAVA = ("[!] Upload TRAVADO: a auditoria da YouTube Data API ainda não foi aprovada "
             "(config/upload.json → \"auditoria_aprovada\": false).\n"
             "    Vídeo enviado por projeto não auditado fica BLOQUEADO como privado no YouTube: "
             "não dá pra publicar nem recorrer, só reenviando. Subir agora queimaria o vídeo.\n"
             "    Pra um upload de teste: --bloco=N --teste. Quando a auditoria sair, mude a flag pra true.")
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
    if not isinstance(cfg["auditoria_aprovada"], bool):
        sys.exit(f"[!] {path.name}: auditoria_aprovada precisa ser true ou false "
                 f"(veio {cfg['auditoria_aprovada']!r})")
    return cfg


# ── descricoes.txt (parser em _descricoes.py) ──────────────────────────────

def problema_credito(descricao: str) -> str | None:
    """Motivo pra NÃO subir se o crédito da fonte estiver ausente/errado, senão None.

    "Conteúdo original" tem que ser a URL da fonte — nunca o placeholder nem o
    link do nosso próprio canal (esse só vai na linha "Inscreva-se").
    """
    linha = next((l for l in descricao.splitlines() if "Conteúdo original:" in l), None)
    if linha is None or PLACEHOLDER_URL in linha:
        return "URL da fonte faltando na descrição (crédito obrigatório)"
    if eh_nosso_canal(linha):
        return "'Conteúdo original' aponta pro nosso canal, não pra fonte (crédito obrigatório)"
    return None


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


def ultimo_longo(outputs: Path, cfg: dict) -> datetime | None:
    """Último longo no YouTube: o maior entre os uploads da API (youtube.json) e o que foi
    agendado/publicado à mão (_cobertura.agenda_canal, a mesma fonte do Curador)."""
    datas = [d for d in (ultimo_agendado(outputs),) if d]
    dia = agenda_canal()["ultimo"]
    if dia:
        h, m = map(int, cfg["horario"].split(":"))
        datas.append(datetime(dia.year, dia.month, dia.day, h, m, tzinfo=ZoneInfo(cfg["fuso"])))
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


def _data(iso: str, cfg: dict) -> datetime:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=ZoneInfo(cfg["fuso"]))


def slots_shorts(minimos: list[datetime | None], ocupados: set[datetime], cfg: dict,
                 agora_: datetime | None = None) -> list[datetime]:
    """Um horário por Short, na ordem dada: o 1º dos shorts_horarios do config (2/dia) que
    respeite a antecedência, não esteja ocupado por outro Short e não venha antes do
    `minimo` do item (o publish_at do longo: o "Vídeo completo" aponta pra vídeo público)."""
    tz = ZoneInfo(cfg["fuso"])
    horas = sorted(tuple(map(int, h.split(":"))) for h in cfg["shorts_horarios"])
    piso = (agora_ or agora()).astimezone(tz) + timedelta(hours=cfg["antecedencia_min_horas"])
    tomados = {o.astimezone(tz) for o in ocupados}
    saida = []
    for minimo in minimos:
        desde = max(piso, minimo.astimezone(tz)) if minimo else piso
        dia, slot = desde.date(), None
        while slot is None:
            slot = next((x for h, m in horas
                         if (x := datetime(dia.year, dia.month, dia.day, h, m, tzinfo=tz)) >= desde
                         and x not in tomados), None)
            dia += timedelta(days=1)
        tomados.add(slot)
        saida.append(slot)
    return saida


def shorts_ocupados(outputs: Path, cfg: dict) -> set[datetime]:
    """publish_at de todos os Shorts já agendados (outputs/*/youtube_shorts.json)."""
    datas = set()
    for reg in outputs.glob(f"*/{SHORTS_JSON}"):
        try:
            datas |= {_data(i["publish_at"], cfg)
                      for i in json.loads(reg.read_text(encoding="utf-8")).values()
                      if i.get("publish_at")}
        except (OSError, ValueError, AttributeError, TypeError) as e:
            print(f"   [aviso] ignorando {reg} ilegível ({e})")
    return datas


# ── registro local (youtube.json) e cota ───────────────────────────────────

def ler_registro(pasta: Path, nome: str = "youtube.json") -> dict:
    p = pasta / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def salvar_registro(pasta: Path, registro: dict, nome: str = "youtube.json") -> None:
    p = pasta / nome
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
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credenciais(SCOPES, TOKEN), cache_discovery=False)


def _cota_estourada(e: HttpError) -> bool:
    return e.resp.status == 403 and b"quotaExceeded" in (e.content or b"")


def _quando(slot: datetime | None) -> str:
    return f"publica {slot:%d/%m %H:%M}" if slot else "TESTE: fica privado pra sempre (não dá pra publicar)"


def subir_video(youtube, video: Path, meta: dict, publish_at: datetime | None, cfg: dict) -> str:
    body = {
        "snippet": {"title": meta["titulo"], "description": meta["descricao"],
                    "tags": meta["tags"], "categoryId": cfg["categoria_id"],
                    "defaultLanguage": cfg["idioma"], "defaultAudioLanguage": cfg["idioma"]},
        "status": {"privacyStatus": "private",
                   "selfDeclaredMadeForKids": cfg["feito_para_criancas"]},
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
        sys.exit("Uso: uv run py scripts/09_upload.py <stem> [--bloco=N] [--max=N] [--dry-run] [--teste]")
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    return pos[0], flags


def main(argv: list[str]) -> int:
    alvo, flags = _args(argv)
    dry = bool(flags.get("dry-run"))
    so_bloco = int(flags["bloco"]) if "bloco" in flags else None
    maximo = int(flags["max"]) if "max" in flags else None
    teste = bool(flags.get("teste"))
    if teste and so_bloco is None:
        sys.exit("[!] --teste exige --bloco=N (sobe um vídeo só, não a live inteira).")
    simulado = bool(flags.get("como-aprovada"))
    if simulado and not dry:
        sys.exit("[!] --como-aprovada só vale com --dry-run (é simulação).")
    if teste and flags.get("shorts"):
        sys.exit("[!] --teste não vale pra Shorts (sem auditoria, nada de Short).")

    cfg = carregar_config()
    if simulado:
        cfg["auditoria_aprovada"] = True
    if flags.get("shorts"):
        if alvo == "todos" and so_bloco is not None:
            sys.exit("[!] --bloco=N precisa de um stem, não de 'todos'.")
        pastas = (sorted(p.parent.parent for p in _paths.OUTPUTS.glob("*/shorts/shorts.json"))
                  if alvo == "todos" else [achar_pasta(alvo)])
        return main_shorts(pastas, cfg, so_bloco, maximo, dry, simulado)
    pasta = achar_pasta(alvo)
    stem = stem_de(pasta)
    desc_txt = pasta / "descricoes.txt"
    if not desc_txt.exists():
        sys.exit(f"[!] {desc_txt} não existe — rode o step 8 (08_descricao.py) antes.")
    descricoes = ler_descricoes(desc_txt.read_text(encoding="utf-8"))
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
    registro = ler_registro(pasta)
    registro_teste = ler_registro(pasta, TESTE_JSON) if teste else {}

    novos, so_thumb = [], []
    for b in blocos:
        bid = b["id"]
        if so_bloco is not None and bid != so_bloco:
            continue
        nn = f"{bid:02d}"
        reg = registro.get(nn, {})
        thumb = escolher_thumb(pasta / "thumbs", nn)
        yt_id = reg.get("youtube_id") or (ler_bloco(stem, bid) or {}).get("youtube_id")
        if yt_id and not teste:   # teste não conta como upload real: pode repetir
            if reg and not reg.get("thumb_ok") and thumb:
                so_thumb.append((bid, nn, thumb, yt_id))
            else:
                print(f"   {nn}: já agendado ({yt_id}) — pulando")
            continue
        status = (ler_bloco(stem, bid) or {}).get("status")
        if status in NAO_SOBE and not teste:
            print(f"   [!] {nn}: bloco em {status} no painel — não sobe")
            continue
        video = escolher_arquivo(pasta / "finalizados", f"video_{nn}_*.mp4")
        meta = descricoes.get(bid)
        problema = ("sem vídeo em finalizados/" if not video else
                    "sem entrada no descricoes.txt" if not meta else
                    problema_credito(meta["descricao"]))
        if problema:
            print(f"   [!] {nn}: {problema} — não sobe")
            continue
        if not thumb:
            print(f"   [aviso] {nn}: sem thumb — sobe sem (YouTube usa um frame)")
        if teste:
            meta = {**meta, "titulo": PREFIXO_TESTE + meta["titulo"]}
        novos.append((bid, nn, video, thumb, preparar_metadados(meta)))

    if maximo is not None:
        novos = novos[:maximo]
    if teste:
        so_thumb = []   # retentativa de thumb é do upload real, não do teste
    travado = not cfg["auditoria_aprovada"] and not teste
    slots = ([None] * len(novos) if teste
             else proximos_slots(len(novos), ultimo_longo(pasta.parent, cfg), cfg))
    custo_un = lambda thumb: cfg["cota_upload"] + (cfg["cota_thumbnail"] if thumb else 0)  # noqa: E731
    estimativa = sum(custo_un(n[3]) for n in novos) + cfg["cota_thumbnail"] * len(so_thumb)

    modo = ("TESTE" if teste else "SIMULAÇÃO como se a auditoria estivesse aprovada" if simulado
            else "agendado" if cfg["auditoria_aprovada"] else "TRAVADO, auditoria pendente")
    print(f"\nPlano pra '{stem}' ({modo}): {len(novos)} upload(s), "
          f"{len(so_thumb)} thumb(s) pendente(s)")
    for (_, nn, video, thumb, meta), slot in zip(novos, slots):
        quando = f"{slot:%d/%m %H:%M}" if slot else "teste"
        print(f"   {nn}  {quando:<11}  {meta['titulo'][:60]}")
        print(f"       {video.name} · thumb: {thumb.name if thumb else '—'} · {len(meta['tags'])} tags")
    print(f"   Cota estimada: {estimativa:,} unidades (limite {cfg['cota_limite_dia']:,}/dia) · custo US$ 0")
    if travado and (novos or so_thumb):
        print("\n" + MSG_TRAVA)
        if not dry:
            evento(stem, "09_upload", "aviso", agente="publicador",
                   mensagem="recusado: auditoria da API pendente")
            return 1
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
        print(f"\n>> {nn}: subindo {video.name} ({_quando(slot)})")
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

        if teste:
            registro_teste.setdefault(nn, []).append(
                {"youtube_id": yt_id, "enviado_em": agora().isoformat(), "titulo": meta["titulo"]})
            salvar_registro(pasta, registro_teste, TESTE_JSON)
            if thumb and cota.cabe(cfg["cota_thumbnail"]):
                cota.gastar(cfg["cota_thumbnail"])
                try:
                    subir_thumb(youtube, thumb, yt_id)
                except HttpError as e:
                    print(f"   [aviso] {nn}: thumb do teste falhou ({e.resp.status})")
            agendados += 1
            print(f"   OK https://youtu.be/{yt_id} · {_quando(slot)}")
            evento(stem, "09_upload", "ok", agente="publicador", bloco_id=bid,
                   mensagem=f"TESTE youtube_id={yt_id}", duracao_s=time.time() - t0)
            continue

        publish_at = slot.isoformat()
        registro[nn] = {"youtube_id": yt_id, "publish_at": publish_at,
                        "titulo": meta["titulo"], "arquivo": video.name, "thumb_ok": False}
        salvar_registro(pasta, registro)   # antes de tudo: é o que garante a idempotência
        upsert_bloco(stem, bid, status="agendado", forcar_status=True,
                     publish_at=publish_at, youtube_id=yt_id, titulo=meta["titulo"])
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
        print(f"   OK https://youtu.be/{yt_id} · privado, {_quando(slot)}")
        evento(stem, "09_upload", "ok", agente="publicador", bloco_id=bid,
               mensagem=f"youtube_id={yt_id} publishAt={publish_at} cota={unidades}",
               duracao_s=time.time() - t0)

    print(f"\n{'=' * 60}\nOK {agendados} vídeo(s) enviado(s) · {falhas} falha(s) · "
          f"cota hoje {cota.usadas:,}/{cota.limite:,} · custo US$ 0")
    return 1 if falhas else 0


# ── Shorts ─────────────────────────────────────────────────────────────────

def manchete(bloco: dict) -> str:
    """A manchete queimada no topo do Short (mesma regra do 10_shorts: texto_thumb, senão o
    tema), cortada em palavra inteira se passar de LIMITE_TITULO_SHORT."""
    texto = " ".join((bloco.get("texto_thumb") or bloco.get("tema") or "").split())
    if len(texto) <= LIMITE_TITULO_SHORT:
        return texto
    return texto[:LIMITE_TITULO_SHORT + 1].rsplit(" ", 1)[0].rstrip(" ,;:—-")


def meta_short(meta: dict, longo_id: str, titulo: str) -> dict:
    """Título = manchete do próprio Short (o 14 casa Short pelo texto_thumb exato) e a
    descrição do longo com o link dele no topo — o crédito da fonte vem junto."""
    descricao = f"▶️ Vídeo completo: https://youtu.be/{longo_id}\n\n{meta['descricao']}"
    return preparar_metadados({"titulo": titulo, "descricao": descricao, "tags": meta["tags"]})


def planejar_shorts(pasta: Path, cfg: dict, so_bloco: int | None) -> list[dict]:
    """Shorts da pasta prontos pra subir (o longo do bloco já está no YouTube)."""
    stem = stem_de(pasta)
    try:
        shorts = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
        descricoes = ler_descricoes((pasta / "descricoes.txt").read_text(encoding="utf-8"))
        blocos = {b["id"]: b for b in json.loads(
            (pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"   [!] {stem}: sem shorts.json/descricoes.txt/blocos.json legível ({e}) — pulando")
        return []
    longos, feitos = ler_registro(pasta), ler_registro(pasta, SHORTS_JSON)
    itens = []
    for nn, sh in sorted(shorts.items()):
        bid = int(nn)
        if so_bloco is not None and bid != so_bloco:
            continue
        if nn in feitos or sh.get("youtube_id"):
            continue   # já está no YouTube (pela API ou à mão, marcado pelo 14)
        bloco = ler_bloco(stem, bid) or {}
        longo = longos.get(nn, {})
        longo_id = longo.get("youtube_id") or bloco.get("youtube_id")
        publish_at = longo.get("publish_at") or bloco.get("publish_at")
        video = pasta / "shorts" / sh.get("arquivo", "")
        meta = descricoes.get(bid)
        titulo = manchete(blocos.get(bid, {}))
        problema = (f"bloco em {bloco['status']} no painel" if bloco.get("status") in NAO_SOBE else
                    "longo ainda não está no YouTube — o Short espera" if not longo_id else
                    "pouco rosto (revisar: true no shorts.json) — confira e libere à mão"
                    if sh.get("revisar") else
                    "arquivo do Short não existe" if not sh.get("arquivo") or not video.exists() else
                    "sem entrada no descricoes.txt" if not meta else
                    "sem manchete (texto_thumb/tema) no blocos.json" if not titulo else
                    problema_credito(meta["descricao"]))
        if problema:
            print(f"   [!] {stem} {nn}: {problema} — não sobe")
            continue
        itens.append({"pasta": pasta, "stem": stem, "bid": bid, "nn": nn, "video": video,
                      "longo_id": longo_id,
                      "minimo": _data(publish_at, cfg) if publish_at else None,
                      "meta": meta_short(meta, longo_id, titulo)})
    return itens


def main_shorts(pastas: list[Path], cfg: dict, so_bloco: int | None, maximo: int | None,
                dry: bool, simulado: bool) -> int:
    itens = [x for pasta in pastas for x in planejar_shorts(pasta, cfg, so_bloco)]
    longe = datetime.max.replace(tzinfo=timezone.utc)
    itens.sort(key=lambda x: (x["minimo"] or longe, x["stem"], x["bid"]))
    if maximo is not None:
        itens = itens[:maximo]
    outputs = pastas[0].parent if pastas else _paths.OUTPUTS
    slots = slots_shorts([x["minimo"] for x in itens], shorts_ocupados(outputs, cfg), cfg)
    modo = ("SIMULAÇÃO como se a auditoria estivesse aprovada" if simulado
            else "agendado" if cfg["auditoria_aprovada"] else "TRAVADO, auditoria pendente")
    print(f"\nShorts ({modo}): {len(itens)} upload(s) em {len(pastas)} live(s)")
    for x, slot in sorted(zip(itens, slots), key=lambda par: par[1]):
        print(f"   {slot:%d/%m %H:%M}  {x['stem'][:24]:<24} {x['nn']}  {x['meta']['titulo'][:50]}")
        print(f"       {x['video'].name} · longo youtu.be/{x['longo_id']}")
    print(f"   Cota estimada: {cfg['cota_upload'] * len(itens):,} unidades "
          f"(limite {cfg['cota_limite_dia']:,}/dia) · custo US$ 0")
    if itens and not cfg["auditoria_aprovada"]:
        print("\n" + MSG_TRAVA)
        if not dry:
            evento(None, "09_upload", "aviso", agente="publicador",
                   mensagem="Shorts recusados: auditoria da API pendente")
            return 1
    if dry or not itens:
        print("\n(dry-run: nada foi enviado)" if dry else "\nNada a fazer.")
        return 0

    cota = Cota(cfg["cota_limite_dia"])
    print(f"   Cota já usada hoje (dia do Pacífico): {cota.usadas:,}")
    youtube = autenticar()
    enviados, falhas = 0, 0
    for x, slot in zip(itens, slots):
        pasta, stem, nn, bid = x["pasta"], x["stem"], x["nn"], x["bid"]
        if not cota.cabe(cfg["cota_upload"]):
            print(f"\n[!] Parando antes de estourar a cota: {cota.usadas:,}/{cota.limite:,} usadas. "
                  f"Rode de novo amanhã (os que faltam pegam os horários livres).")
            evento(stem, "09_upload", "aviso", agente="publicador",
                   mensagem=f"Shorts, cota: parou em {cota.usadas}/{cota.limite}")
            break
        print(f"\n>> Short {stem} {nn}: subindo {x['video'].name} ({_quando(slot)})")
        t0 = time.time()
        cota.gastar(cfg["cota_upload"])   # a API cobra mesmo se falhar
        try:
            yt_id = subir_video(youtube, x["video"], x["meta"], slot, cfg)
        except HttpError as e:
            falhas += 1
            print(f"   [!] Short {nn}: upload falhou ({e.resp.status})")
            evento(stem, "09_upload", "falha", agente="publicador", bloco_id=bid,
                   mensagem=f"Short http {e.resp.status}", duracao_s=time.time() - t0)
            if _cota_estourada(e):
                cota.esgotar()
                break
            continue
        feitos = ler_registro(pasta, SHORTS_JSON)
        feitos[nn] = {"youtube_id": yt_id, "publish_at": slot.isoformat(), "longo_id": x["longo_id"],
                      "titulo": x["meta"]["titulo"], "arquivo": x["video"].name,
                      "relacionado_ok": False}
        salvar_registro(pasta, feitos, SHORTS_JSON)   # antes de tudo: idempotência
        shorts_path = pasta / "shorts" / "shorts.json"
        try:   # mesmo formato do 14_canal: tira o Short do estoque e do publicacao.txt
            shorts = json.loads(shorts_path.read_text(encoding="utf-8"))
            shorts[nn].update(youtube_id=yt_id, postado=slot.date().isoformat())
            shorts_path.write_text(json.dumps(shorts, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError, KeyError) as e:
            print(f"   [aviso] não atualizei o shorts.json ({e}); o 14_canal acerta depois")
        enviados += 1
        print(f"   OK https://youtu.be/{yt_id} · privado, {_quando(slot)}")
        evento(stem, "09_upload", "ok", agente="publicador", bloco_id=bid,
               mensagem=f"Short youtube_id={yt_id} publishAt={slot.isoformat()} "
                        f"longo={x['longo_id']} cota={cfg['cota_upload']}",
               duracao_s=time.time() - t0)

    print(f"\n{'=' * 60}\nOK {enviados} Short(s) agendado(s) · {falhas} falha(s) · "
          f"cota hoje {cota.usadas:,}/{cota.limite:,} · custo US$ 0")
    if enviados:
        print("Falta o VÍDEO RELACIONADO de cada um no Studio: uv run py scripts/dia_d.py relacionados")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
