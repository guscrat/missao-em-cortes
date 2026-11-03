"""Modo demonstração do 09 pro screencast da auditoria da YouTube Data API (pedido de 03/11/2026).

Roda pelo 09, uma etapa por vez (o scripts/demo_auditoria.ps1 encadeia com pausas e narração):

    uv run py scripts/09_upload.py --demo=preparar [<stem>] [--bloco=N] [--segundos=15]
    uv run py scripts/09_upload.py --demo=plano|login|upload|thumb|update|status [--lang=en] [--agendar]

- preparar: corta um clipe curto (10-20 s) de um vídeo finalizado + copia a thumb pra
  state/demo_auditoria/. Local, não fala com o YouTube.
- plano:    mostra arquivo, título, descrição, tags, thumb e o publishAt do próximo slot real.
- login:    revoga o token do publisher e apaga o arquivo, pra tela de consentimento aparecer.
- upload:   videos.insert do clipe, PRIVADO, título "[TEST]" em inglês (--agendar manda publishAt).
- thumb:    thumbnails.set (coberto pelo escopo youtube.upload).
- update:   videos.update da descrição, SÓ se o token tiver escopo pra isso (youtube.upload não tem).
- status:   confirmação: ID, uploadStatus, privacyStatus e links (das respostas da API).

Não mexe no banco de blocos nem nos youtube*.json: o vídeo de demo não é upload de bloco.
Registro em state/demo_auditoria/demo.json; eventos com agente="publicador".
"""
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASTA = ROOT / "state" / "demo_auditoria"
REGISTRO = PASTA / "demo.json"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# escopos que permitem videos.update (o youtube.upload NÃO está aqui)
ESCOPOS_UPDATE = {"https://www.googleapis.com/auth/youtube",
                  "https://www.googleapis.com/auth/youtube.force-ssl",
                  "https://www.googleapis.com/auth/youtubepartner"}
ETAPAS = ("preparar", "plano", "login", "upload", "thumb", "update", "status")

TITULO = "[TEST] Missão em Cortes - API upload demo (do not publish)"
TAGS = ["test", "API demo", "Missão em Cortes"]

MSG = {
    "pt": {
        "etapa_invalida": "[!] --demo precisa ser uma de: {etapas}",
        "sem_preparo": "[!] Rode antes: uv run py scripts/09_upload.py --demo=preparar [<stem>] [--bloco=N]",
        "sem_upload": "[!] Nenhum vídeo de demo enviado ainda (rode --demo=upload).",
        "sem_fonte": "[!] Sem URL da fonte em inputs/{stem}.url (crédito obrigatório) — escolha outro vídeo.",
        "fonte_nossa": "[!] inputs/{stem}.url aponta pro nosso canal, não pra fonte — escolha outro vídeo.",
        "sem_video": "[!] Nenhum vídeo finalizado com thumb encontrado{onde}.",
        "segundos": "[!] --segundos tem que ficar entre 10 e 20.",
        "agendar_aprovada": ("[!] --agendar recusado: a auditoria já está aprovada, então o vídeo [TEST] "
                             "seria publicado de verdade no horário. Rode sem --agendar."),
        "preparado": "Clipe de demo pronto: {clip} ({seg} s, de {origem})\nThumb: {thumb}\nFonte: {fonte}",
        "plano_titulo": "PLANO DO UPLOAD (nada foi enviado)",
        "arquivo": "Arquivo", "titulo": "Título", "descricao": "Descrição", "tags": "Tags",
        "thumb": "Thumb", "publish_at": "publishAt (próximo slot)",
        "publish_at_nota": ("Em produção o vídeo sobe PRIVADO com status.publishAt e o YouTube "
                            "publica sozinho nesse horário."),
        "corpo": "Corpo do videos.insert em produção:",
        "modo_demo_agenda": "Nesta demo: PRIVADO + publishAt = {quando} (--agendar).",
        "modo_demo_privado": "Nesta demo: PRIVADO, sem publishAt (vídeo de teste, nunca vai ao ar).",
        "revogando": "Revogando o token atual do publisher no Google...",
        "revogado": "Token revogado e apagado ({arquivo}).",
        "revoga_falhou": "[aviso] o Google não confirmou a revogação ({erro}); apagando o arquivo mesmo assim.",
        "sem_token": "Nenhum token salvo: o login vai pedir consentimento.",
        "abrindo_login": "Abrindo o navegador na tela de consentimento OAuth do Google...",
        "login_ok": "Login OK. Escopos concedidos:",
        "cota": "[!] Cota do dia insuficiente ({usadas:,}/{limite:,}). Tente amanhã.",
        "subindo": "Enviando {arquivo} com videos.insert (privado)...",
        "upload_ok": "Upload concluído.",
        "thumb_enviando": "Definindo a thumb com thumbnails.set ({arquivo})...",
        "thumb_ok": "Thumb definida: {url}",
        "update_sem_escopo": ("videos.update PULADO: o token do publisher só tem {escopos}.\n"
                              "videos.update exige youtube, youtube.force-ssl ou youtubepartner, "
                              "que este projeto não pede (escopo mínimo declarado na auditoria).\n"
                              "Os metadados (título, descrição, tags, categoria, idioma) vão no próprio "
                              "videos.insert, e a thumb vai pelo thumbnails.set."),
        "update_enviando": "Atualizando a descrição com videos.update...",
        "update_ok": "Descrição atualizada.",
        "confirmacao": "CONFIRMAÇÃO",
        "video_id": "ID do vídeo", "upload_status": "uploadStatus", "privacy": "privacyStatus",
        "thumb_set": "Thumb definida", "desc_update": "Descrição atualizada", "sim": "sim", "nao": "não",
        "links": "Links", "fonte_conf": ("(dados das respostas da API; o escopo youtube.upload não "
                                         "permite videos.list, então a conferência final é no Studio)"),
        "falhou": "[!] {acao} falhou: HTTP {status}",
    },
    "en": {
        "etapa_invalida": "[!] --demo must be one of: {etapas}",
        "sem_preparo": "[!] Run first: uv run py scripts/09_upload.py --demo=preparar [<stem>] [--bloco=N]",
        "sem_upload": "[!] No demo video uploaded yet (run --demo=upload).",
        "sem_fonte": "[!] No source URL in inputs/{stem}.url (source credit is mandatory) - pick another video.",
        "fonte_nossa": "[!] inputs/{stem}.url points to our own channel, not the source - pick another video.",
        "sem_video": "[!] No finished video with a thumbnail found{onde}.",
        "segundos": "[!] --segundos must be between 10 and 20.",
        "agendar_aprovada": ("[!] --agendar refused: the audit is already approved, so the [TEST] video "
                             "would really go public at that time. Run without --agendar."),
        "preparado": "Demo clip ready: {clip} ({seg} s, from {origem})\nThumbnail: {thumb}\nSource: {fonte}",
        "plano_titulo": "UPLOAD PLAN (nothing has been sent)",
        "arquivo": "File", "titulo": "Title", "descricao": "Description", "tags": "Tags",
        "thumb": "Thumbnail", "publish_at": "publishAt (next slot)",
        "publish_at_nota": ("In production the video is uploaded as PRIVATE with status.publishAt, "
                            "and YouTube publishes it automatically at that time."),
        "corpo": "videos.insert request body in production:",
        "modo_demo_agenda": "In this demo: PRIVATE + publishAt = {quando} (--agendar).",
        "modo_demo_privado": "In this demo: PRIVATE, no publishAt (test video, never goes public).",
        "revogando": "Revoking the current publisher token with Google...",
        "revogado": "Token revoked and deleted ({arquivo}).",
        "revoga_falhou": "[warning] Google did not confirm the revocation ({erro}); deleting the file anyway.",
        "sem_token": "No saved token: the login will ask for consent.",
        "abrindo_login": "Opening the browser on Google's OAuth consent screen...",
        "login_ok": "Login OK. Granted scopes:",
        "cota": "[!] Not enough quota left today ({usadas:,}/{limite:,}). Try again tomorrow.",
        "subindo": "Uploading {arquivo} with videos.insert (private)...",
        "upload_ok": "Upload complete.",
        "thumb_enviando": "Setting the thumbnail with thumbnails.set ({arquivo})...",
        "thumb_ok": "Thumbnail set: {url}",
        "update_sem_escopo": ("videos.update SKIPPED: the publisher token only has {escopos}.\n"
                              "videos.update requires youtube, youtube.force-ssl or youtubepartner, "
                              "which this project does not request (minimum scope declared in the audit).\n"
                              "The metadata (title, description, tags, category, language) is sent in "
                              "videos.insert itself, and the thumbnail via thumbnails.set."),
        "update_enviando": "Updating the description with videos.update...",
        "update_ok": "Description updated.",
        "confirmacao": "CONFIRMATION",
        "video_id": "Video ID", "upload_status": "uploadStatus", "privacy": "privacyStatus",
        "thumb_set": "Thumbnail set", "desc_update": "Description updated", "sim": "yes", "nao": "no",
        "links": "Links", "fonte_conf": ("(data from the API responses; the youtube.upload scope does "
                                         "not allow videos.list, so the final check is in YouTube Studio)"),
        "falhou": "[!] {acao} failed: HTTP {status}",
    },
}


def _up():
    import importlib
    return importlib.import_module("09_upload")


def descricao(fonte: str) -> str:
    return ("TEST UPLOAD - YouTube API Services audit screencast.\n\n"
            "This short private clip was uploaded by the Missão em Cortes tool "
            "(Google Cloud project missao-em-cortes-publisher) to demonstrate the upload, "
            "thumbnail and scheduling flow. It will not be published.\n\n"
            f"Original content: {fonte}")


def ler_registro() -> dict:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salvar_registro(reg: dict) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


# ── preparar (local) ───────────────────────────────────────────────────────

def achar_origem(stem: str | None, bloco: int | None) -> tuple[Path, int, Path, Path] | None:
    """(pasta, bloco, vídeo finalizado, thumb): a do stem/bloco pedido, senão a live mais
    recente que tem os dois."""
    import _paths
    pastas = ([_paths.achar_pasta(stem)] if stem else
              sorted((p for p in _paths.OUTPUTS.iterdir()
                      if p.is_dir() and not p.name.startswith("_")), reverse=True))
    for pasta in pastas:
        for video in sorted((pasta / "finalizados").glob("video_*.mp4")):
            try:
                bid = int(video.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            if bloco is not None and bid != bloco:
                continue
            nn = f"{bid:02d}"
            melhor = _paths.escolher_arquivo(pasta / "finalizados", f"video_{nn}_*.mp4")
            thumb = _paths.escolher_thumb(pasta / "thumbs", nn)
            if melhor and thumb:
                return pasta, bid, melhor, thumb
    return None


def fonte_url(stem: str) -> str | None:
    p = ROOT / "inputs" / f"{stem}.url"
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def preparar(stem: str | None, bloco: int | None, segundos: int, m: dict) -> int:
    import _paths
    from _canal import eh_nosso_canal
    if not 10 <= segundos <= 20:
        print(m["segundos"])
        return 1
    achado = achar_origem(stem, bloco)
    if not achado:
        print(m["sem_video"].format(onde=f" ({stem})" if stem else ""))
        return 1
    pasta, bid, video, thumb = achado
    st = _paths.stem_de(pasta)
    fonte = fonte_url(st)
    if not fonte:
        print(m["sem_fonte"].format(stem=st))
        return 1
    if eh_nosso_canal(fonte):
        print(m["fonte_nossa"].format(stem=st))
        return 1
    PASTA.mkdir(parents=True, exist_ok=True)
    clip = PASTA / "clip_demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-t", str(segundos),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(clip)],
                   check=True)
    thumb_demo = PASTA / f"thumb_demo{thumb.suffix}"
    shutil.copyfile(thumb, thumb_demo)
    salvar_registro({"stem": st, "bloco": bid, "origem": video.name, "segundos": segundos,
                     "clip": clip.name, "thumb": thumb_demo.name, "fonte": fonte})
    print(m["preparado"].format(clip=clip.relative_to(ROOT), seg=segundos,
                                origem=f"{pasta.name}/finalizados/{video.name}",
                                thumb=thumb_demo.relative_to(ROOT), fonte=fonte))
    return 0


# ── plano ──────────────────────────────────────────────────────────────────

def proximo_slot(cfg: dict) -> datetime:
    up = _up()
    import _paths
    return up.proximos_slots(1, up.ultimo_longo(_paths.OUTPUTS, cfg), cfg)[0]


def corpo_insert(meta: dict, publish_at: datetime | None, cfg: dict) -> dict:
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": cfg["feito_para_criancas"]}
    if publish_at:
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"snippet": {"title": meta["titulo"], "description": meta["descricao"],
                        "tags": meta["tags"], "categoryId": cfg["categoria_id"],
                        "defaultLanguage": "en", "defaultAudioLanguage": cfg["idioma"]},
            "status": status}


def _meta(reg: dict) -> dict:
    return _up().preparar_metadados({"titulo": TITULO, "descricao": descricao(reg["fonte"]),
                                     "tags": TAGS})


def plano(reg: dict, cfg: dict, agendar: bool, m: dict) -> int:
    meta, slot = _meta(reg), proximo_slot(cfg)
    linha = "=" * 70
    print(f"{linha}\n{m['plano_titulo']}\n{linha}")
    print(f"{m['arquivo']:<26}{(PASTA / reg['clip']).relative_to(ROOT)} ({reg['segundos']} s)")
    print(f"{m['titulo']:<26}{meta['titulo']}")
    print(f"{m['tags']:<26}{', '.join(meta['tags'])}")
    print(f"{m['thumb']:<26}{(PASTA / reg['thumb']).relative_to(ROOT)}")
    print(f"{m['publish_at']:<26}{slot:%Y-%m-%d %H:%M} ({cfg['fuso']}) = "
          f"{slot.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    print(f"{m['descricao']}:\n" + "\n".join("    " + l for l in meta["descricao"].splitlines()))
    print(f"\n{m['publish_at_nota']}\n{m['corpo']}")
    print(json.dumps(corpo_insert(meta, slot, cfg), ensure_ascii=False, indent=2))
    print("\n" + (m["modo_demo_agenda"].format(quando=f"{slot:%Y-%m-%d %H:%M}") if agendar
                  else m["modo_demo_privado"]))
    return 0


# ── login ──────────────────────────────────────────────────────────────────

def revogar(token: Path, m: dict) -> None:
    """Revoga no Google e apaga o arquivo, pra a próxima chamada abrir o consentimento."""
    if not token.exists():
        print(m["sem_token"])
        return
    print(m["revogando"])
    try:
        dados = json.loads(token.read_text(encoding="utf-8"))
        alvo = dados.get("refresh_token") or dados.get("token")
        req = urllib.request.Request(
            REVOKE_URL, data=urllib.parse.urlencode({"token": alvo}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        urllib.request.urlopen(req, timeout=20).close()
    except Exception as e:   # noqa: BLE001 — token velho/inválido: o login refaz de qualquer jeito
        print(m["revoga_falhou"].format(erro=e))
    token.unlink(missing_ok=True)
    print(m["revogado"].format(arquivo=token.relative_to(ROOT)))


def login(m: dict) -> int:
    up = _up()
    from _google import escopos_gravados
    revogar(up.TOKEN, m)
    print(m["abrindo_login"])
    up.autenticar()
    print(m["login_ok"])
    for e in sorted(escopos_gravados(up.TOKEN)):
        print(f"   - {e}")
    return 0


# ── upload / thumb / update ────────────────────────────────────────────────

def upload(reg: dict, cfg: dict, agendar: bool, m: dict) -> int:
    up = _up()
    from googleapiclient.errors import HttpError
    from _eventos import evento
    cota = up.Cota(cfg["cota_limite_dia"])
    if not cota.cabe(cfg["cota_upload"] + cfg["cota_thumbnail"]):
        print(m["cota"].format(usadas=cota.usadas, limite=cota.limite))
        return 1
    slot = proximo_slot(cfg) if agendar else None
    body = corpo_insert(_meta(reg), slot, cfg)
    clip = PASTA / reg["clip"]
    youtube = up.autenticar()
    print(m["subindo"].format(arquivo=clip.relative_to(ROOT)))
    cota.gastar(cfg["cota_upload"])   # a API cobra mesmo se falhar
    try:
        resp = up.inserir_video(youtube, clip, body)
    except HttpError as e:
        print(m["falhou"].format(acao="videos.insert", status=e.resp.status))
        evento(None, "09_upload", "falha", agente="publicador",
               mensagem=f"DEMO auditoria: http {e.resp.status}")
        return 1
    st = resp.get("status", {})
    reg.update(youtube_id=resp["id"], enviado_em=datetime.now(timezone.utc).isoformat(),
               upload_status=st.get("uploadStatus"), privacy_status=st.get("privacyStatus"),
               publish_at=st.get("publishAt"), thumb_ok=False, update_ok=False)
    salvar_registro(reg)
    evento(None, "09_upload", "ok", agente="publicador",
           mensagem=f"DEMO auditoria youtube_id={resp['id']} (privado, teste)")
    print(m["upload_ok"])
    print(json.dumps({"id": resp["id"], "status": st}, indent=2))
    return 0


def thumb(reg: dict, cfg: dict, m: dict) -> int:
    up = _up()
    from googleapiclient.errors import HttpError
    youtube = up.autenticar()
    arq = PASTA / reg["thumb"]
    print(m["thumb_enviando"].format(arquivo=arq.relative_to(ROOT)))
    up.Cota(cfg["cota_limite_dia"]).gastar(cfg["cota_thumbnail"])
    try:
        resp = up.subir_thumb(youtube, arq, reg["youtube_id"]) or {}
    except HttpError as e:
        print(m["falhou"].format(acao="thumbnails.set", status=e.resp.status))
        return 1
    itens = resp.get("items") or [{}]
    url = (itens[0].get("maxres") or itens[0].get("high") or itens[0].get("default") or {}).get("url", "")
    reg["thumb_ok"] = True
    salvar_registro(reg)
    print(m["thumb_ok"].format(url=url))
    return 0


def update(reg: dict, cfg: dict, m: dict) -> int:
    up = _up()
    from googleapiclient.errors import HttpError
    from _google import escopos_gravados
    escopos = escopos_gravados(up.TOKEN)
    if not escopos & ESCOPOS_UPDATE:
        print(m["update_sem_escopo"].format(escopos=", ".join(sorted(escopos)) or "-"))
        return 0
    youtube = up.autenticar()
    meta = _meta(reg)
    nova = meta["descricao"] + f"\n\nUpdated via videos.update at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC."
    print(m["update_enviando"])
    up.Cota(cfg["cota_limite_dia"]).gastar(50)
    try:
        youtube.videos().update(part="snippet", body={
            "id": reg["youtube_id"],
            "snippet": {"title": meta["titulo"], "description": nova, "tags": meta["tags"],
                        "categoryId": cfg["categoria_id"], "defaultLanguage": "en"}}).execute()
    except HttpError as e:
        print(m["falhou"].format(acao="videos.update", status=e.resp.status))
        return 1
    reg["update_ok"] = True
    salvar_registro(reg)
    print(m["update_ok"])
    return 0


def status(reg: dict, m: dict) -> int:
    vid = reg["youtube_id"]
    linha = "=" * 70
    print(f"{linha}\n{m['confirmacao']}\n{linha}")
    print(f"{m['video_id']:<22}{vid}")
    print(f"{m['upload_status']:<22}{reg.get('upload_status')}")
    print(f"{m['privacy']:<22}{reg.get('privacy_status')}")
    if reg.get("publish_at"):
        print(f"{'publishAt':<22}{reg['publish_at']}")
    print(f"{m['thumb_set']:<22}{m['sim'] if reg.get('thumb_ok') else m['nao']}")
    print(f"{m['desc_update']:<22}{m['sim'] if reg.get('update_ok') else m['nao']}")
    print(f"{m['links']:<22}https://studio.youtube.com/video/{vid}/edit")
    print(f"{'':<22}https://youtu.be/{vid}")
    print(m["fonte_conf"])
    return 0


# ── entrada ────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    pos = [a for a in argv if not a.startswith("--")]
    m = MSG["en" if flags.get("lang") == "en" else "pt"]
    etapa = flags.get("demo")
    if etapa not in ETAPAS:
        print(m["etapa_invalida"].format(etapas=", ".join(ETAPAS)))
        return 2
    if etapa == "preparar":
        return preparar(pos[0] if pos else None,
                        int(flags["bloco"]) if "bloco" in flags else None,
                        int(flags.get("segundos", 15)), m)
    if etapa == "login":
        return login(m)
    reg = ler_registro()
    if not reg.get("clip") or not (PASTA / reg["clip"]).exists():
        print(m["sem_preparo"])
        return 1
    cfg = _up().carregar_config()
    agendar = bool(flags.get("agendar"))
    if agendar and cfg["auditoria_aprovada"]:   # com a auditoria ok, o publishAt publicaria o [TEST]
        print(m["agendar_aprovada"])
        return 1
    if etapa == "plano":
        return plano(reg, cfg, agendar, m)
    if etapa == "upload":
        return upload(reg, cfg, agendar, m)
    if not reg.get("youtube_id"):
        print(m["sem_upload"])
        return 1
    return {"thumb": lambda: thumb(reg, cfg, m), "update": lambda: update(reg, cfg, m),
            "status": lambda: status(reg, m)}[etapa]()
