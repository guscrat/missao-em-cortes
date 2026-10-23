"""Dia D da auditoria da YouTube Data API: checagem, verificação e checklist do Studio.

Runbook completo: .claude/skills/youtube-compliance/references/dia-d.md

Uso:
    uv run py scripts/dia_d.py checar               # SIMULAÇÃO: nada é enviado, nada muda
    uv run py scripts/dia_d.py verificar <id> [<id>...]   # status real no YouTube (só leitura)
    uv run py scripts/dia_d.py relacionados [--feito=ID,ID]   # Shorts sem vídeo relacionado

checar: credenciais do publisher (projeto certo, token com escopo de upload), cota de hoje,
o candidato ao teste (1 longo aprovado que ainda não está no YouTube) e o plano dos Shorts —
os dois pelo 09 com --dry-run --como-aprovada, ou seja, exatamente o que vai subir quando a
flag virar. Sai 1 se faltar algo que impede o dia D.

verificar: lê o status do vídeo com o token do projeto de MÉTRICAS (youtube.readonly, o
dono do canal enxerga privado/agendado). Privado sem data depois de um upload real = a trava
da auditoria continua (vídeo bloqueado como privado).

relacionados: a API não tem o campo "vídeo relacionado" do Short; ele é marcado à mão no
Studio. Lista os Shorts agendados pelo 09 que ainda não foram marcados; --feito=ID marca.
Custo: US$ 0 (Data API, leitura ≈1 unidade por chamada).
"""
import importlib
import json
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

import _paths
from _eventos import evento, ler_bloco
from _google import client_id_do_secret, escopos_gravados
from _paths import auditoria_aprovada, stem_de

ROOT = Path(__file__).parent.parent
SCRIPTS = Path(__file__).parent
SECRETS = ROOT / "secrets"
PROJETO_PUBLISHER = "missao-em-cortes-publisher"
ESCOPO_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
JA_NO_YOUTUBE = {"agendado", "publicado"}

up = importlib.import_module("09_upload")


# ── checar ─────────────────────────────────────────────────────────────────

def _json(caminho: Path) -> dict:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def checar_credenciais(secrets: Path | None = None) -> list[tuple[bool, str]]:
    """[(ok, mensagem)] do OAuth do publisher e do token de leitura (pra verificar)."""
    secrets = secrets or SECRETS
    client, token = secrets / "youtube_client_secret.json", secrets / "youtube_token.json"
    res = []
    projeto = (_json(client).get("installed") or _json(client).get("web") or {}).get("project_id")
    if not client.exists():
        res.append((False, f"falta {client.name} (projeto {PROJETO_PUBLISHER})"))
    elif projeto != PROJETO_PUBLISHER:
        res.append((False, f"{client.name} é do projeto {projeto!r}, não do {PROJETO_PUBLISHER}"))
    else:
        res.append((True, f"{client.name} do projeto {PROJETO_PUBLISHER}"))
    if not token.exists():
        res.append((False, f"falta {token.name}: o 1º upload abre o navegador pro login"))
    elif _json(token).get("client_id") != client_id_do_secret(client):
        res.append((False, f"{token.name} foi feito com outro client: o upload refaz o login"))
    elif ESCOPO_UPLOAD not in escopos_gravados(token):
        res.append((False, f"{token.name} sem o escopo youtube.upload"))
    else:
        res.append((True, f"{token.name} com escopo de upload (validade só se testa no upload)"))
    leitura = secrets / "analytics_token.json"
    res.append((leitura.exists(), f"{leitura.name} (o `verificar` e o 14_canal usam)"
                if leitura.exists() else f"falta {leitura.name}: sem ele não dá pra verificar"))
    return res


def candidato_teste() -> dict | None:
    """1º longo aprovado (pasta mais recente, maior score) que ainda não está no YouTube e
    tem crédito da fonte: {stem, id, titulo}."""
    from _publicacao import aprovados
    for pasta in sorted(_paths.OUTPUTS.glob("*_*"), reverse=True):
        if not (pasta / "revisao.json").exists():
            continue
        stem, registro = stem_de(pasta), up.ler_registro(pasta)
        for x in aprovados(pasta):
            bloco = ler_bloco(stem, x["id"]) or {}
            if (bloco.get("youtube_id") or registro.get(f"{x['id']:02d}")
                    or bloco.get("status") in JA_NO_YOUTUBE | up.NAO_SOBE
                    or up.problema_credito(x["descricao"])):
                continue
            return {"stem": stem, "id": x["id"], "titulo": x["titulo"]}
    return None


def _rodar_09(*args: str) -> int:
    sys.stdout.flush()   # senão a saída do 09 passa na frente da nossa
    return subprocess.run([sys.executable, str(SCRIPTS / "09_upload.py"), *args], cwd=ROOT).returncode


def checar() -> int:
    print("=" * 70 + "\nDIA D — SIMULAÇÃO (nada é enviado, nada muda)\n" + "=" * 70)
    bloqueios = []
    flag = auditoria_aprovada()
    print(f"\n1. Flag: auditoria_aprovada = {str(flag).lower()} "
          f"({'já virada' if flag else 'vira no dia D, via PR'})")

    print("\n2. Credenciais")
    for ok, msg in checar_credenciais():
        print(f"   [{'ok' if ok else '!!'}] {msg}")
        if not ok and "youtube_client_secret" in msg:
            bloqueios.append(msg)

    cfg = up.carregar_config()
    cota = up.Cota(cfg["cota_limite_dia"])
    print(f"\n3. Cota hoje (dia do Pacífico): {cota.usadas:,}/{cota.limite:,} · teste = "
          f"{cfg['cota_upload'] + cfg['cota_thumbnail']:,} · cada Short = {cfg['cota_upload']:,}")

    print("\n4. Teste do dia D (1 vídeo agendado público)")
    alvo = candidato_teste()
    if alvo:
        print(f"   longo: {alvo['stem']} bloco {alvo['id']:02d} · {alvo['titulo'][:60]}")
        print(f"   comando: uv run py scripts/09_upload.py {alvo['stem']} --bloco={alvo['id']} --max=1")
        if _rodar_09(alvo["stem"], f"--bloco={alvo['id']}", "--max=1", "--dry-run",
                     "--como-aprovada"):
            bloqueios.append("dry-run do teste falhou")
    else:   # todo longo aprovado já foi agendado à mão: o teste é o 1º Short da fila
        print("   nenhum longo aprovado fora do YouTube → o teste é o 1º Short da fila "
              "(publica em horas: dá pra ver o 'público' no mesmo dia)")
        print("   comando: uv run py scripts/09_upload.py todos --shorts --max=1")
        if _rodar_09("todos", "--shorts", "--max=1", "--dry-run", "--como-aprovada"):
            bloqueios.append("dry-run do teste falhou")

    print(f"\n5. Shorts liberados (horários {', '.join(cfg['shorts_horarios'])}, "
          f"nunca antes do longo ir ao ar)")
    print("   comando: uv run py scripts/09_upload.py todos --shorts")
    if _rodar_09("todos", "--shorts", "--dry-run", "--como-aprovada"):
        bloqueios.append("dry-run dos Shorts falhou")

    print("\n" + "=" * 70)
    if bloqueios:
        print("NÃO PRONTO: " + " · ".join(bloqueios))
    else:
        print("PRONTO pro dia D. Runbook: .claude/skills/youtube-compliance/references/dia-d.md")
    evento(None, "dia_d", "aviso" if bloqueios else "ok", agente="publicador",
           mensagem="checar: " + ("; ".join(bloqueios) if bloqueios else "pronto"))
    return 1 if bloqueios else 0


# ── verificar ──────────────────────────────────────────────────────────────

def veredito(v: dict) -> tuple[str, str]:
    """('OK'|'ALERTA'|'FALHA', explicação) a partir do videos.list (part=status)."""
    st = v.get("status", {})
    upload, priv = st.get("uploadStatus"), st.get("privacyStatus")
    if upload in ("rejected", "failed", "deleted"):
        motivo = st.get("rejectionReason") or st.get("failureReason") or "?"
        return "FALHA", f"upload {upload} ({motivo})"
    processando = " · ainda processando" if upload == "uploaded" else ""
    if priv == "public":
        return "OK", "público" + processando
    if priv == "private" and st.get("publishAt"):
        return "OK", f"agendado: publica em {st['publishAt']} (UTC){processando}"
    if priv == "private":
        return "ALERTA", ("privado SEM data. Se o Studio mostrar 'bloqueado/restrito como privado', "
                          "a auditoria NÃO destravou: volte a flag pra false e pare o dia D")
    return "ALERTA", f"privacidade {priv!r} inesperada{processando}"


def verificar(ids: list[str], yt=None) -> int:
    if not ids:
        sys.exit("Uso: uv run py scripts/dia_d.py verificar <youtube_id> [...]")
    if yt is None:
        from _youtube_leitura import youtube
        yt = youtube(interativo=False)
    itens = {v["id"]: v for v in yt.videos().list(part="status,snippet",
                                                  id=",".join(ids)).execute().get("items", [])}
    pior = 0
    for vid in ids:
        v = itens.get(vid)
        nivel, msg = veredito(v) if v else ("FALHA", "não encontrado no canal")
        titulo = v["snippet"]["title"][:60] if v else ""
        print(f"[{nivel}] {vid} · {msg}\n        {titulo}\n"
              f"        Studio: https://studio.youtube.com/video/{vid}/edit")
        pior = max(pior, {"OK": 0, "ALERTA": 1, "FALHA": 2}[nivel])
        evento(None, "dia_d", "ok" if nivel == "OK" else "aviso", agente="publicador",
               mensagem=f"verificar {vid}: {nivel} {msg}")
    return 1 if pior else 0


# ── relacionados ───────────────────────────────────────────────────────────

def relacionados(feitos: set[str] | None = None) -> int:
    feitos = feitos or set()
    pendentes = 0
    for reg in sorted(_paths.OUTPUTS.glob(f"*/{up.SHORTS_JSON}")):
        dados = up.ler_registro(reg.parent, up.SHORTS_JSON)
        mudou = False
        for nn, item in sorted(dados.items()):
            if item.get("relacionado_ok"):
                continue
            if item["youtube_id"] in feitos:
                item["relacionado_ok"], mudou = True, True
                print(f"   ok {item['youtube_id']} marcado")
                continue
            pendentes += 1
            print(f"{item['publish_at'][:16].replace('T', ' ')} · {reg.parent.name} #{nn} · "
                  f"{item['titulo'][:50]}\n"
                  f"   Short:  https://studio.youtube.com/video/{item['youtube_id']}/edit\n"
                  f"   Vídeo relacionado → https://youtu.be/{item['longo_id']}")
        if mudou:
            up.salvar_registro(reg.parent, dados, up.SHORTS_JSON)
    print(f"\n{pendentes} Short(s) sem vídeo relacionado." + (
        " No Studio: Detalhes → Vídeo relacionado → escolha o longo. Depois: "
        "dia_d.py relacionados --feito=ID,ID" if pendentes else ""))
    return 0


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    cmd = pos[0] if pos else "checar"
    if cmd == "checar":
        return checar()
    if cmd == "verificar":
        return verificar(pos[1:])
    if cmd == "relacionados":
        feito = flags.get("feito")
        return relacionados(set(feito.split(",")) if isinstance(feito, str) else None)
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
