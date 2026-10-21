"""Step 11 (off-pipeline): agente REVISOR de conteúdo — aprova ou põe em quarentena cada bloco.

Uso:
    uv run py scripts/11_revisor.py <stem> --dry-run     # mostra o que vai revisar e o custo estimado
    uv run py scripts/11_revisor.py <stem> [--bloco=N]

Pra cada bloco montado, UMA chamada ao Claude (com visão) recebe:
  - o título que vai pro YouTube (descricoes.txt; edição manual vale) e o texto da thumb
  - a transcrição do trecho (words.json)
  - a thumb escolhida (manual > a > b > c) e 6 frames espalhados pelo corte
e responde 3 checagens em JSON estruturado:
  1. título fiel à fala (gancho pode ser ousado, mas não pode distorcer o que foi dito)
  2. thumb ok (rosto do speaker visível, texto legível e coerente, não é tela compartilhada)
  3. tela compartilhada (a maior parte do corte mostra tela em vez de gente falando)

Quem decide é o código, não o modelo: tudo ok → status "aprovado"; qualquer problema →
"quarentena" com o motivo (aparece no painel). Nunca mexe em bloco já "agendado" ou
"publicado". Resultado completo em outputs/<pasta>/revisao.json.

Custo: ~US$ 0.05 por bloco (claude-opus-5-5, ~7 imagens pequenas + transcrição),
~US$ 0.25 por live. Logado por bloco no banco (agente="revisor").
"""
import base64
import json
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

from _descricoes import ler_descricoes
from _eventos import evento, ler_bloco, upsert_bloco
from _legenda import hhmmss_para_segundos, palavras_na_janela
from _paths import achar_pasta, escolher_thumb, stem_de

MODELO = "claude-opus-5-5"
PRECO_IN, PRECO_OUT = 4.0, 20.0        # US$ por 1M tokens (opus 5.5)
CUSTO_ESTIMADO_BLOCO = 0.05            # só pro --dry-run
N_FRAMES = 6
LARGURA_IMG = 512                      # imagem pequena = menos token; dá pra ler a tela
NAO_MEXER = {"agendado", "publicado"}  # decisão já tomada adiante: revisor não rebaixa

SCHEMA = {
    "type": "object",
    "properties": {
        "titulo_fiel": {"type": "boolean"},
        "titulo_problema": {"type": "string"},
        "thumb_ok": {"type": "boolean"},
        "thumb_problema": {"type": "string"},
        "tela_compartilhada": {"type": "boolean"},
        "tela_problema": {"type": "string"},
    },
    "required": ["titulo_fiel", "titulo_problema", "thumb_ok", "thumb_problema",
                 "tela_compartilhada", "tela_problema"],
    "additionalProperties": False,
}

SISTEMA = """Você é o revisor de conteúdo do canal "Missão em Cortes", que publica cortes de \
lives e entrevistas do Partido Missão. Linha editorial: simpática ao partido, com independência \
crítica. Títulos podem ser ousados e com gancho, desde que NÃO distorçam o que foi dito.

Avalie o bloco e responda só o JSON pedido. Nos campos *_problema, escreva em português, \
uma frase curta e concreta (vazio "" quando não há problema).

1. titulo_fiel: o título e o texto da thumb são sustentados pela transcrição? Reprove se \
atribuem ao speaker algo que ele não disse, invertem o sentido, exageram um fato a ponto de \
ficar falso, ou prometem um assunto que o trecho não entrega. Gancho forte, paráfrase e \
simplificação são OK.
2. thumb_ok: a thumb (primeira imagem) mostra uma pessoa com o rosto visível, tem texto \
legível, sem corte no meio de palavra, e coerente com o título? Reprove se o fundo é tela \
compartilhada/documento, se não há rosto, ou se o texto está truncado ou sem sentido.
3. tela_compartilhada: nos frames do corte (imagens seguintes), a MAIOR parte mostra tela \
compartilhada (navegador, matéria, gráfico, documento) em vez de pessoas falando? Isso é \
true. Algum frame de tela no meio é normal: aí é false."""


def ler_imagem_b64(path: Path, largura: int = LARGURA_IMG) -> str:
    """Imagem (thumb) reduzida pra largura em JPEG base64."""
    from io import BytesIO
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if img.width > largura:
        img = img.resize((largura, round(img.height * largura / img.width)))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def duracao(video: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def frames_b64(video: Path, n: int = N_FRAMES) -> list[str]:
    """n frames espalhados pelo vídeo (pulando as pontas), JPEG base64."""
    dur = duracao(video)
    saida = []
    for i in range(n):
        t = dur * (i + 1) / (n + 1)
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={LARGURA_IMG}:-2",
                            "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, check=True)
        saida.append(base64.standard_b64encode(r.stdout).decode())
    return saida


def montar_conteudo(titulo: str, texto_thumb: str, transcricao: str,
                    thumb_b64: str | None, frames: list[str]) -> list[dict]:
    img = lambda b64: {"type": "image",   # noqa: E731
                       "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    conteudo = []
    if thumb_b64:
        conteudo += [{"type": "text", "text": "THUMB:"}, img(thumb_b64)]
    conteudo += [{"type": "text", "text": f"FRAMES DO CORTE ({len(frames)}):"}]
    conteudo += [img(f) for f in frames]
    sem_thumb = "" if thumb_b64 else "SEM THUMB ESCOLHIDA: marque thumb_ok=false.\n"
    conteudo.append({"type": "text", "text": (
        f"TÍTULO DO YOUTUBE: {titulo}\nTEXTO DA THUMB: {texto_thumb}\n{sem_thumb}"
        f"\nTRANSCRIÇÃO DO TRECHO:\n{transcricao}")})
    return conteudo


def chamar_claude(client, conteudo: list[dict]) -> tuple[dict | None, object]:
    """(checagens ou None se recusou, resposta). Fallback de refusal ligado (servidor)."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        system=SISTEMA,
        messages=[{"role": "user", "content": conteudo}],
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        return None, resp
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if texto is None:   # sem bloco de texto (ex: max_tokens no meio do raciocínio)
        raise json.JSONDecodeError(f"resposta sem texto (stop_reason={resp.stop_reason})", "", 0)
    return json.loads(texto), resp


def decidir(checagens: dict | None) -> tuple[str, str | None]:
    """(status, motivo). O veredito é do código: qualquer checagem reprovada = quarentena."""
    if checagens is None:
        return "quarentena", "revisor automático recusou analisar — revisar à mão"
    problemas = []
    if not checagens["titulo_fiel"]:
        problemas.append(f"título: {checagens['titulo_problema'] or 'não fiel à fala'}")
    if not checagens["thumb_ok"]:
        problemas.append(f"thumb: {checagens['thumb_problema'] or 'reprovada'}")
    if checagens["tela_compartilhada"]:
        problemas.append(f"tela compartilhada: {checagens['tela_problema'] or 'maior parte do corte'}")
    return ("quarentena", "; ".join(problemas)) if problemas else ("aprovado", None)


def custo(resp) -> tuple[int, int, float]:
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    return tin, tout, tin / 1e6 * PRECO_IN + tout / 1e6 * PRECO_OUT


def escolher_video(pasta: Path, nn: str) -> Path | None:
    """Corte completo (sem _polido): é o que os frames precisam mostrar."""
    cortes = sorted(p for p in (pasta / "cortes").glob(f"corte_{nn}_*.mp4")
                    if "_polido" not in p.stem)
    return cortes[0] if cortes else None


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    if not pos:
        sys.exit("Uso: uv run py scripts/11_revisor.py <stem> [--bloco=N] [--dry-run]")
    dry = bool(flags.get("dry-run"))
    so_bloco = int(flags["bloco"]) if "bloco" in flags else None

    pasta = achar_pasta(pos[0])
    stem = stem_de(pasta)
    words_json = pasta / "words.json"
    if not words_json.exists():
        sys.exit(f"[!] {words_json} não existe — rode o step 2 (02_transcribe.py) antes.")
    todas = json.loads(words_json.read_text(encoding="utf-8"))["words"]
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
    desc_txt = pasta / "descricoes.txt"
    descricoes = ler_descricoes(desc_txt.read_text(encoding="utf-8")) if desc_txt.exists() else {}

    fila = []
    for b in blocos:
        bid, nn = b["id"], f"{b['id']:02d}"
        if so_bloco is not None and bid != so_bloco:
            continue
        status = (ler_bloco(stem, bid) or {}).get("status")
        if status in NAO_MEXER:
            print(f"  {nn}: já {status} — revisor não mexe")
            continue
        video = escolher_video(pasta, nn)
        if not video:
            print(f"  [aviso] {nn}: sem corte — rode o step 4 antes")
            continue
        fila.append((b, nn, video))

    print(f"\nRevisão de '{stem}': {len(fila)} bloco(s) · {MODELO} · "
          f"custo estimado ~US$ {CUSTO_ESTIMADO_BLOCO * len(fila):.2f}")
    if dry or not fila:
        print("(dry-run: nada foi enviado)" if dry else "Nada a revisar.")
        return 0

    import anthropic
    from dotenv import load_dotenv
    load_dotenv()
    client = anthropic.Anthropic()
    revisao_path = pasta / "revisao.json"
    revisao = json.loads(revisao_path.read_text(encoding="utf-8")) if revisao_path.exists() else {}
    total, falhas = 0.0, 0

    for b, nn, video in fila:
        bid = b["id"]
        titulo = descricoes.get(bid, {}).get("titulo") or b.get("titulo_sugerido", "")
        texto_thumb = b.get("texto_thumb") or b.get("tema", "")
        ini = hhmmss_para_segundos(b["timestamp_inicio"])
        fim = hhmmss_para_segundos(b["timestamp_fim"])
        transcricao = " ".join(w["word"] for w in palavras_na_janela(todas, ini, fim))
        thumb = escolher_thumb(pasta / "thumbs", nn)
        t0 = time.time()
        evento(stem, "11_revisor", "inicio", agente="revisor", bloco_id=bid)
        try:
            conteudo = montar_conteudo(titulo, texto_thumb, transcricao,
                                       ler_imagem_b64(thumb) if thumb else None, frames_b64(video))
            checagens, resp = chamar_claude(client, conteudo)
        except (anthropic.APIError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            falhas += 1
            print(f"  [!] {nn}: revisão falhou ({type(e).__name__}: {str(e)[:200]})")
            evento(stem, "11_revisor", "falha", agente="revisor", bloco_id=bid,
                   mensagem=type(e).__name__, duracao_s=time.time() - t0)
            continue

        tin, tout, usd = custo(resp)
        total += usd
        evento(stem, "11_revisor", "llm", agente="revisor", bloco_id=bid, tokens_in=tin,
               tokens_out=tout, custo_usd=usd, mensagem=resp.model)
        status, motivo = decidir(checagens)
        upsert_bloco(stem, bid, status=status, forcar_status=True, motivo=motivo)
        revisao[nn] = {"status": status, "motivo": motivo, "checagens": checagens,
                       "titulo": titulo, "thumb": thumb.name if thumb else None,
                       "modelo": resp.model, "custo_usd": round(usd, 4)}
        revisao_path.write_text(json.dumps(revisao, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        evento(stem, "11_revisor", "ok", agente="revisor", bloco_id=bid,
               mensagem=f"{status}{': ' + motivo if motivo else ''}"[:300],
               duracao_s=time.time() - t0)
        icone = "OK" if status == "aprovado" else "QUARENTENA"
        print(f"  {nn}: {icone}{' — ' + motivo if motivo else ''} (US$ {usd:.3f})")

    print(f"\nRevisados {len(fila) - falhas}/{len(fila)} · custo US$ {total:.3f} · "
          f"detalhes em {revisao_path.name}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
