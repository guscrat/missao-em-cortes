"""Step 11 (off-pipeline): agente REVISOR de conteúdo — aprova ou põe em quarentena cada bloco.

Uso:
    uv run py scripts/11_revisor.py <stem> --dry-run     # mostra o que vai revisar e o custo estimado
    uv run py scripts/11_revisor.py <stem> [--bloco=N]

Pra cada bloco montado, UMA chamada ao Claude (com visão) recebe:
  - o título que vai pro YouTube (descricoes.txt; edição manual vale) e o texto da thumb
  - a transcrição do trecho (words.json)
  - a thumb escolhida (manual > a > b > c) e 6 frames espalhados pelo corte
e responde 4 checagens em JSON estruturado:
  1. título fiel à fala (gancho pode ser ousado, mas não pode distorcer o que foi dito) e
     sem destacar palavrão ou termo que soe como ofensa a um grupo, mesmo que dito
  2. thumb ok (a thumb FINAL: rosto inteiro, visível e iluminado, sem sombra/degradê em
     cima, texto legível e coerente, não é tela compartilhada)
  3. tela compartilhada (a maior parte do corte mostra tela em vez de gente falando)
  4. corte sem sentido (o trecho não se sustenta sozinho)

Quem decide é o código, não o modelo (regra de produto da quarentena):
  - problema de CONTEÚDO (3 ou 4) → "descartado" com o motivo; não sobe, não chama ninguém
  - título reprovado → o EDITOR (_editor.py) reescreve título + texto da thumb, refaz a
    thumb/Short e o revisor reavalia; no máx. 2 reescritas. Reprovou nas 2 → "quarentena"
    e vira decisão do Gu (faixa amarela na tarefa do MISSAO_TAREFA, se houver)
  - só a thumb reprovada → troca o frame sozinho: 07_thumb.py --proximo (próximo frame com
    rosto da fila, por nota de tamanho/luz/nitidez) e reavalia só a thumb, até
    MAX_TROCAS_THUMB vezes. Nenhum serviu → "descartado". Thumb manual reprovada →
    "quarentena" (foi escolhida à mão: refazer com 07_thumb.py --t=)
  - tudo ok → "aprovado"
Nunca mexe em bloco já "agendado", "publicado" ou "arquivado". --sem-editor desliga as reescritas.
Resultado completo em outputs/<pasta>/revisao.json.

Custo: ~US$ 0.05 por bloco (claude-opus-5-5, ~7 imagens pequenas + transcrição),
~US$ 0.25 por live; cada rodada do editor soma ~US$ 0.06 (reescrita + nova revisão) e cada
troca de frame da thumb ~US$ 0.01 (reavalia só a thumb).
Logado por bloco no banco (agente="revisor" e agente="editor").
"""
import base64
import json
import os
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import _colagem
import _editor
import _grafias
from _descricoes import ler_descricoes
from _eventos import atualizar_tarefa, evento, ler_bloco, upsert_bloco
from _legenda import hhmmss_para_segundos, palavras_na_janela
from _paths import achar_pasta, escolher_thumb, stem_de

MODELO = "claude-opus-5-5"
PRECO_IN, PRECO_OUT = 4.0, 20.0        # US$ por 1M tokens (opus 5.5)
CUSTO_ESTIMADO_BLOCO = 0.05            # só pro --dry-run (+ até ~US$ 0.03 se trocar a thumb)
N_FRAMES = 6
LARGURA_IMG = 512                      # imagem pequena = menos token; dá pra ler a tela
NAO_MEXER = {"agendado", "publicado", "arquivado"}  # decisão já tomada: revisor não mexe
MAX_TROCAS_THUMB = 3                   # frames novos tentados antes de descartar o bloco
SCRIPTS = Path(__file__).parent

SCHEMA = {
    "type": "object",
    "properties": {
        "titulo_fiel": {"type": "boolean"},
        "titulo_problema": {"type": "string"},
        "thumb_ok": {"type": "boolean"},
        "thumb_problema": {"type": "string"},
        "tela_compartilhada": {"type": "boolean"},
        "tela_problema": {"type": "string"},
        "corte_sem_sentido": {"type": "boolean"},
        "sentido_problema": {"type": "string"},
    },
    "required": ["titulo_fiel", "titulo_problema", "thumb_ok", "thumb_problema",
                 "tela_compartilhada", "tela_problema", "corte_sem_sentido", "sentido_problema"],
    "additionalProperties": False,
}

SCHEMA_THUMB = {
    "type": "object",
    "properties": {"thumb_ok": {"type": "boolean"}, "thumb_problema": {"type": "string"}},
    "required": ["thumb_ok", "thumb_problema"],
    "additionalProperties": False,
}

CRITERIO_THUMB = """a thumb (primeira imagem) é a arte FINAL que vai pro YouTube. Ela mostra \
o rosto de quem fala INTEIRO (sem cortar testa, queixo ou metade do rosto), visível e bem \
iluminado, sem sombra, degradê ou escurecimento em cima dele? O texto está legível, sem corte \
no meio de palavra, e coerente com o título? Reprove se o fundo é tela compartilhada ou \
documento, se não há rosto, se o rosto está escuro, cortado ou coberto, ou se o texto está \
truncado ou sem sentido. EXCEÇÃO, thumb colagem (apresentador recortado com contorno branco na \
frente + 2 cenas do assunto ao fundo, círculo ou seta vermelha): as cenas ao fundo podem ser \
tela, vídeo ou foto; o que vale é o rosto do APRESENTADOR inteiro e o texto legível."""

SISTEMA = """Você é o revisor de conteúdo do canal "Missão em Cortes", que publica cortes de \
lives e entrevistas do Partido Missão. Linha editorial: simpática ao partido, com independência \
crítica. Títulos podem ser ousados e com gancho, desde que NÃO distorçam o que foi dito.

Avalie o bloco e responda só o JSON pedido. Nos campos *_problema, escreva em português, \
uma frase curta e concreta (vazio "" quando não há problema).

1. titulo_fiel: o título e o texto da thumb são sustentados pela transcrição? Reprove se \
atribuem ao speaker algo que ele não disse, invertem o sentido, exageram um fato a ponto de \
ficar falso, ou prometem um assunto que o trecho não entrega. Gancho forte, paráfrase e \
simplificação são OK. Números, datas, fatos e nomes têm que bater EXATAMENTE com a \
transcrição (ex.: "3 INQUÉRITOS" quando a fala diz 2 reprova). Nome de pessoa fora da \
grafia oficial (lista no pedido) também reprova. Se vierem várias variantes de texto da \
thumb separadas por " | " (teste A/B da thumb colagem), TODAS precisam passar: aponte qual \
falhou. Reprove TAMBÉM se o título ou o texto da thumb destacam palavrão ou \
termo que possa soar como ofensa a um grupo (raça, etnia, gênero, orientação sexual, \
religião, origem, deficiência etc.), MESMO que esteja na fala: diga isso em titulo_problema.
2. thumb_ok: """ + CRITERIO_THUMB + """
3. tela_compartilhada: nos frames do corte (imagens seguintes), a MAIOR parte mostra tela \
compartilhada (navegador, matéria, gráfico, documento) em vez de pessoas falando? Isso é \
true. Algum frame de tela no meio é normal: aí é false.
4. corte_sem_sentido: pela transcrição, o trecho NÃO se sustenta sozinho? Ex.: começa ou \
termina no meio de um raciocínio a ponto de não dar pra entender do que se fala, ou pula \
de assunto sem fio condutor. Começo abrupto mas compreensível é false."""


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
        f"\nGRAFIAS OFICIAIS:\n{_grafias.para_prompt()}\n"
        f"\nTRANSCRIÇÃO DO TRECHO:\n{transcricao}")})
    return conteudo


def texto_da_thumb(pasta: Path, bid: int, texto_thumb: str) -> str:
    """O texto que está NA thumb que sobe: com a colagem aplicada (modo padrão), os textos das
    variantes a/b/c (vão todas pro "Testar e comparar"), separados por ' | '."""
    reg = _colagem.colagem_aplicada(pasta / "thumbs", bid)
    if not reg:
        return texto_thumb
    textos = [_colagem.sem_marcas(" ".join(v["texto"])) for v in reg.get("variantes", {}).values()]
    return " | ".join(dict.fromkeys(textos)) or texto_thumb


def chamar_claude(client, conteudo: list[dict], sistema: str = SISTEMA, schema: dict = SCHEMA,
                  effort: str = "medium") -> tuple[dict | None, object]:
    """(checagens ou None se recusou, resposta). Fallback de refusal ligado (servidor)."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        system=sistema,
        messages=[{"role": "user", "content": conteudo}],
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": schema}},
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
    """(status, motivo). O veredito é do código: conteúdo ruim = descartado; título ou
    thumb reprovados = quarentena (o título ainda passa pelo editor no main)."""
    if checagens is None:
        return "quarentena", "revisor automático recusou analisar — revisar à mão"
    conteudo = []
    if checagens["tela_compartilhada"]:
        conteudo.append(f"tela compartilhada: {checagens['tela_problema'] or 'maior parte do corte'}")
    if checagens.get("corte_sem_sentido"):
        conteudo.append(f"corte sem sentido: {checagens.get('sentido_problema') or 'não se sustenta sozinho'}")
    if conteudo:
        return "descartado", "; ".join(conteudo)
    problemas = []
    if not checagens["titulo_fiel"]:
        problemas.append(f"título: {checagens['titulo_problema'] or 'não fiel à fala'}")
    if not checagens["thumb_ok"]:
        problemas.append(f"thumb: {checagens['thumb_problema'] or 'reprovada'}")
    return ("quarentena", "; ".join(problemas)) if problemas else ("aprovado", None)


def precisa_editor(status: str, checagens: dict | None) -> bool:
    return status == "quarentena" and checagens is not None and not checagens["titulo_fiel"]


def custo(resp) -> tuple[int, int, float]:
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    return tin, tout, tin / 1e6 * PRECO_IN + tout / 1e6 * PRECO_OUT


def escolher_video(pasta: Path, nn: str) -> Path | None:
    """Corte completo (sem _polido): é o que os frames precisam mostrar."""
    cortes = sorted(p for p in (pasta / "cortes").glob(f"corte_{nn}_*.mp4")
                    if "_polido" not in p.stem)
    return cortes[0] if cortes else None


def revisar_bloco(client, anthropic, stem, pasta, b, nn, video, titulo, texto_thumb,
                  transcricao):
    """Uma revisão (uma chamada). (checagens, status, motivo, custo) ou None se falhou."""
    bid = b["id"]
    thumb = escolher_thumb(pasta / "thumbs", nn)
    t0 = time.time()
    evento(stem, "11_revisor", "inicio", agente="revisor", bloco_id=bid)
    try:
        conteudo = montar_conteudo(titulo, texto_thumb, transcricao,
                                   ler_imagem_b64(thumb) if thumb else None, frames_b64(video))
        checagens, resp = chamar_claude(client, conteudo)
    except (anthropic.APIError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"  [!] {nn}: revisão falhou ({type(e).__name__}: {str(e)[:200]})")
        evento(stem, "11_revisor", "falha", agente="revisor", bloco_id=bid,
               mensagem=type(e).__name__, duracao_s=time.time() - t0)
        return None
    tin, tout, usd = custo(resp)
    evento(stem, "11_revisor", "llm", agente="revisor", bloco_id=bid, tokens_in=tin,
           tokens_out=tout, custo_usd=usd, mensagem=resp.model, duracao_s=time.time() - t0)
    status, motivo = decidir(checagens)
    print(f"  {nn}: revisor → {status}{' — ' + motivo if motivo else ''} (US$ {usd:.3f})")
    return checagens, status, motivo, usd


def editar(client, anthropic, stem, pasta, b, titulo, texto_thumb, problema, transcricao,
           tentativas) -> tuple[dict | None, float]:
    """Uma reescrita do editor, já gravada (txt, json, thumb, Short). (novo ou None, custo)."""
    bid, nn = b["id"], f"{b['id']:02d}"
    evento(stem, "11_editor", "inicio", agente="editor", bloco_id=bid)
    pedido = _editor.montar_pedido(titulo, texto_thumb, problema, transcricao, tentativas)
    try:
        novo, resp = _editor.reescrever(client, pedido)
    except (anthropic.APIError, json.JSONDecodeError) as e:
        print(f"  [!] {nn}: editor falhou ({type(e).__name__}: {str(e)[:200]})")
        evento(stem, "11_editor", "falha", agente="editor", bloco_id=bid, mensagem=type(e).__name__)
        return None, 0.0
    tin, tout, usd = _editor.custo(resp)
    evento(stem, "11_editor", "llm", agente="editor", bloco_id=bid, tokens_in=tin,
           tokens_out=tout, custo_usd=usd, mensagem=resp.model)
    if novo is None:
        evento(stem, "11_editor", "falha", agente="editor", bloco_id=bid, mensagem="recusou")
        return None, usd
    _editor.gravar_texto(pasta, bid, novo["titulo"], novo["texto_thumb"])
    for aviso in _editor.refazer_artes(pasta, bid, escolher_thumb(pasta / "thumbs", nn)):
        print(f"  [aviso] {nn}: {aviso}")
    evento(stem, "11_editor", "ok", agente="editor", bloco_id=bid,
           mensagem=f"{novo['titulo']} | {novo['mudanca']}"[:300])
    print(f"  {nn}: editor reescreveu (US$ {usd:.3f}) → '{novo['titulo']}' · "
          f"thumb '{novo['texto_thumb']}'")
    return novo, usd


SISTEMA_THUMB = f"""Você é o revisor de thumbs do canal "Missão em Cortes". Avalie só a thumb \
e responda o JSON pedido (thumb_problema: uma frase curta em português, "" se ok).
thumb_ok: {CRITERIO_THUMB}"""


def checar_thumb(client, thumb: Path, titulo: str, texto_thumb: str) -> tuple[dict | None, object]:
    """Reavalia só a thumb (1 imagem, sem frames nem transcrição): ~US$ 0.01."""
    conteudo = [{"type": "text", "text": "THUMB:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": ler_imagem_b64(thumb)}},
                {"type": "text", "text": f"TÍTULO DO YOUTUBE: {titulo}\nTEXTO DA THUMB: {texto_thumb}"}]
    return chamar_claude(client, conteudo, SISTEMA_THUMB, SCHEMA_THUMB, effort="low")


def proximo_frame(pasta: Path, bid: int) -> bool | None:
    """07_thumb --proximo: troca o frame da thumb_NN_a pelo seguinte da fila.
    True = trocou; False = acabou a fila (o 07 sai com 2); None = o 07 quebrou."""
    try:
        r = subprocess.run([sys.executable, str(SCRIPTS / "07_thumb.py"), pasta.name,
                            f"--bloco={bid}", "--proximo"], capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        print(f"  [!] {bid:02d}: 07_thumb --proximo passou de 5 min")
        return None
    if r.returncode not in (0, 2):
        erro = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
        print(f"  [!] {bid:02d}: 07_thumb --proximo falhou: {' '.join(erro)[:200]}")
        return None
    return r.returncode == 0


def trocar_thumb(client, anthropic, stem, pasta, bid, nn, titulo, texto_thumb,
                 problema) -> tuple[str, str | None, list[str], float]:
    """Thumb reprovada (e o resto ok): tenta os próximos frames com rosto até
    MAX_TROCAS_THUMB. (status, motivo, problemas de cada troca, custo)."""
    thumb = escolher_thumb(pasta / "thumbs", nn)
    if thumb and thumb.stem.endswith("_manual"):
        return ("quarentena", f"thumb manual reprovada: {problema} — refaça com "
                f"07_thumb.py --bloco={bid} --t=MM:SS", [], 0.0)
    problemas, usd_total = [problema], 0.0
    for _ in range(MAX_TROCAS_THUMB):
        trocou = proximo_frame(pasta, bid)
        if trocou is None:
            return ("quarentena", "thumb: falhou ao gerar frame novo (07_thumb) — revisar à mão",
                    problemas, usd_total)
        if not trocou:
            break
        t0 = time.time()
        try:
            r, resp = checar_thumb(client, escolher_thumb(pasta / "thumbs", nn), titulo, texto_thumb)
        except (anthropic.APIError, json.JSONDecodeError) as e:
            evento(stem, "11_revisor", "falha", agente="revisor", bloco_id=bid,
                   mensagem=f"thumb: {type(e).__name__}")
            return ("quarentena", f"thumb: falhou ao reavaliar o frame novo ({type(e).__name__})"
                    " — revisar à mão", problemas, usd_total)
        tin, tout, usd = custo(resp)
        usd_total += usd
        evento(stem, "11_revisor", "llm", agente="revisor", bloco_id=bid, tokens_in=tin,
               tokens_out=tout, custo_usd=usd, mensagem=f"{resp.model} (thumb)",
               duracao_s=time.time() - t0)
        if r is None:
            return "quarentena", "thumb: revisor recusou analisar — revisar à mão", problemas, usd_total
        print(f"  {nn}: frame novo da thumb → {'ok' if r['thumb_ok'] else r['thumb_problema']}"
              f" (US$ {usd:.3f})")
        if r["thumb_ok"]:
            return "aprovado", None, problemas, usd_total
        problemas.append(r["thumb_problema"])
    return ("descartado", f"thumb: nenhum frame com rosto serviu ({len(problemas) - 1} troca(s); "
            f"último problema: {problemas[-1]})", problemas, usd_total)


def chamar_gu(stem: str, nn: str, motivo: str) -> None:
    """Título reprovou em todas as reescritas: decisão do Gu (chat + faixa amarela)."""
    print(f"\n  >>> DECISÃO DO GU ({stem} bloco {nn}): {motivo}\n")
    evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=int(nn),
           mensagem=f"decisão do Gu: {motivo}"[:300])
    tarefa = os.environ.get("MISSAO_TAREFA", "")
    if tarefa.isdigit():
        atualizar_tarefa(int(tarefa), decisao_pendente=f"{stem} bloco {nn}: título reprovou "
                         f"{_editor.MAX_RODADAS}x após reescrita. Aprovar um título à mão?")


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    if not pos:
        sys.exit("Uso: uv run py scripts/11_revisor.py <stem> [--bloco=N] [--dry-run]")
    dry = bool(flags.get("dry-run"))
    com_editor = not flags.get("sem-editor")
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
          f"custo estimado ~US$ {CUSTO_ESTIMADO_BLOCO * len(fila):.2f}"
          + (f" (até +US$ {(CUSTO_ESTIMADO_BLOCO + _editor.CUSTO_ESTIMADO) * _editor.MAX_RODADAS:.2f}"
             f"/bloco se o editor reescrever)" if com_editor else ""))
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
        texto_base = b.get("texto_thumb") or b.get("tema", "")    # o do template (07)
        texto_thumb = texto_da_thumb(pasta, bid, texto_base)
        ini = hhmmss_para_segundos(b["timestamp_inicio"])
        fim = hhmmss_para_segundos(b["timestamp_fim"])
        transcricao = " ".join(w["word"] for w in palavras_na_janela(todas, ini, fim))
        tentativas, custo_bloco = [], 0.0
        while True:
            r = revisar_bloco(client, anthropic, stem, pasta, b, nn, video, titulo, texto_thumb,
                              transcricao)
            if r is None:
                falhas += 1
                break
            checagens, status, motivo, usd = r
            total += usd
            custo_bloco += usd
            if not (com_editor and precisa_editor(status, checagens)):
                break
            if len(tentativas) == _editor.MAX_RODADAS:
                motivo = (f"título reprovou nas {_editor.MAX_RODADAS} reescritas do editor — "
                          f"decisão do Gu ({motivo})")
                chamar_gu(stem, nn, motivo)
                break
            novo, usd_ed = editar(client, anthropic, stem, pasta, b, titulo, texto_thumb,
                                  checagens["titulo_problema"], transcricao, tentativas)
            total += usd_ed
            custo_bloco += usd_ed
            if novo is None:
                motivo += " (editor não conseguiu reescrever — revisar à mão)"
                break
            tentativas.append({"titulo": titulo, "texto_thumb": texto_thumb,
                               "problema": checagens["titulo_problema"]})
            # colagem refeita com o texto novo (ou voltou pro template): confere o que ficou
            titulo, texto_base = novo["titulo"], novo["texto_thumb"]
            texto_thumb = texto_da_thumb(pasta, bid, texto_base)
        if r is None:
            continue
        if status == "quarentena" and checagens and checagens["titulo_fiel"] \
                and not checagens["thumb_ok"] and _colagem.colagem_aplicada(pasta / "thumbs", bid):
            # colagem reprovada na arte: as 3 variantes voltam pro template (o --proximo só
            # trocaria a 'a') e o bloco é revisado de novo, com o texto do template
            print(f"  {nn}: colagem reprovada ({checagens['thumb_problema']}) → template atual")
            if _editor.voltar_template(pasta, bid):
                texto_thumb = texto_base
                r2 = revisar_bloco(client, anthropic, stem, pasta, b, nn, video, titulo,
                                   texto_thumb, transcricao)
                if r2 is not None:
                    checagens, status, motivo, usd = r2
                    total += usd
                    custo_bloco += usd
            else:
                motivo += " (falhou ao voltar pro template — revisar à mão)"
        trocas_thumb = []
        if status == "quarentena" and checagens and checagens["titulo_fiel"] \
                and not checagens["thumb_ok"]:
            status, motivo, trocas_thumb, usd_t = trocar_thumb(
                client, anthropic, stem, pasta, bid, nn, titulo, texto_thumb,
                checagens["thumb_problema"])
            total += usd_t
            custo_bloco += usd_t
            if status == "aprovado":
                checagens = {**checagens, "thumb_ok": True, "thumb_problema": ""}

        upsert_bloco(stem, bid, status=status, forcar_status=True, motivo=motivo)
        thumb = escolher_thumb(pasta / "thumbs", nn)
        revisao[nn] = {"status": status, "motivo": motivo, "checagens": checagens,
                       "titulo": titulo, "texto_thumb": texto_thumb,
                       "thumb": thumb.name if thumb else None,
                       "reescritas": tentativas, "trocas_thumb": trocas_thumb[1:],
                       "modelo": MODELO,
                       "custo_usd": round(custo_bloco, 4)}
        revisao_path.write_text(json.dumps(revisao, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        evento(stem, "11_revisor", "ok", agente="revisor", bloco_id=bid,
               mensagem=f"{status}{': ' + motivo if motivo else ''}"[:300])
        icone = {"aprovado": "OK", "descartado": "DESCARTADO"}.get(status, "QUARENTENA")
        extra = f" após {len(tentativas)} reescrita(s)" if tentativas else ""
        print(f"  {nn}: {icone}{extra}{' — ' + motivo if motivo else ''}")

    print(f"\nRevisados {len(fila) - falhas}/{len(fila)} · custo US$ {total:.3f} · "
          f"detalhes em {revisao_path.name}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
