"""Step 11 (off-pipeline): agente REVISOR de conteúdo — aprova ou põe em quarentena cada bloco.

Uso:
    uv run py scripts/11_revisor.py <stem> --dry-run     # mostra o que vai revisar e o custo estimado
    uv run py scripts/11_revisor.py <stem> [--bloco=N]

Antes de qualquer chamada paga, a checagem de ABERTURA (código, $0): o corte abre com
propaganda/patrocínio da live (config/propaganda.json)? → o início vai pra 1ª frase depois
dela e o bloco é refeito; sem ela fica < 8 min → "quarentena". Depois, a de FRONTEIRA: o corte
começa no começo de frase e termina em fim de frase com pausa depois (últimas palavras do
words.json)? Reprovou → reajusta sozinho: leva a ponta pro fim de frase mais perto (até 30s),
grava no blocos.json e refaz o bloco (pipeline.py --bloco=N, ~US$ 0.03 do 04b). Sem ponto
natural perto ou falhou ao refazer → "quarentena" (ajuste à mão).

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
  5. momentos_fora: itens de "Principais momentos" da descrição que não estão na transcrição
     do trecho → saem sozinhos do descricoes.txt e dos ganchos do blocos.json ($0)
  6. capitulos_errados: capítulos da descrição ("MM:SS Título") cujo título não bate com o
     trecho dele (a transcrição vai com marcas [CAPÍTULO ...]) → saem sozinhos do descricoes.txt
     e do blocos.json ($0); sem o de 00:00 ou com menos de 3, a seção inteira sai

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
  - modo ab (config/thumb.json → modo: "ab", a/b/c = 3 versões da clássica): aprovado →
    confere também a arte de b/c (~US$ 0.01 cada); reprovou → a variante vira
    thumb_NN_<l>_reprovada.png e sai do "Testar e comparar". Colagem ab antiga (b/c =
    colagem): reprovou → b/c voltam pro template
  - seta/círculo em pessoa que não dá pra confirmar (pelo nome escrito na cena ou por ser o
    apresentador) que é a citada no texto → thumb reprovada
Nunca mexe em bloco já "agendado", "publicado" ou "arquivado". --sem-editor desliga as reescritas.
Resultado completo em outputs/<pasta>/revisao.json.

Custo: ~US$ 0.05 por bloco (claude-opus-5-5, ~7 imagens pequenas + transcrição),
~US$ 0.25 por live; cada rodada do editor soma ~US$ 0.06 (reescrita + nova revisão) e cada
troca de frame da thumb ~US$ 0.01 (reavalia só a thumb).
Logado por bloco no banco (agente="revisor" e agente="editor").
"""
import base64
import difflib
import json
import os
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
from pathlib import Path

import _capitulos
import _colagem
import _custo
import _editor
import _fronteira
import _grafias
from _descricoes import (ler_descricoes, momentos as momentos_da_descricao, remover_capitulos,
                         remover_momentos, trocar_capitulos)
from _eventos import atualizar_tarefa, evento, ler_bloco, termos_semana, upsert_bloco
from _legenda import hhmmss_para_segundos, palavras_na_janela
from _paths import achar_pasta, escolher_thumb, stem_de

MODELO = "claude-opus-5-5"
CUSTO_ESTIMADO_BLOCO = 0.05            # só pro --dry-run (+ até ~US$ 0.03 se trocar a thumb)
CUSTO_REFAZER_BLOCO = 0.03             # 04b (LLM) ao refazer um bloco com a fronteira reajustada
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
        "momentos_fora": {"type": "array", "items": {"type": "string"}},
        "capitulos_errados": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo_fiel", "titulo_problema", "thumb_ok", "thumb_problema",
                 "tela_compartilhada", "tela_problema", "corte_sem_sentido", "sentido_problema",
                 "momentos_fora", "capitulos_errados"],
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
tela, vídeo ou foto; o que vale é o rosto do APRESENTADOR inteiro e o texto legível. SETA OU CÍRCULO destacando uma pessoa: só passa se der pra ter CERTEZA, sem reconhecer rosto, de que a pessoa destacada é a citada no texto da thumb ou no título: ela é o apresentador (quem fala, em primeiro plano) ou o nome dela está ESCRITO na cena destacada (legenda, tarja, crachá, @ do post). Reprove se a cena destacada traz o nome de OUTRA pessoa (ex.: seta numa cena com a tarja "KIM KATAGUIRI" numa thumb sobre o Marçal) ou se nada escrito confirma quem é: na dúvida, reprove e diga isso em thumb_problema."""

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
grafia oficial (lista GRAFIAS OFICIAIS no fim destas instruções) também reprova. Se \
vierem várias variantes de texto da thumb separadas por " | " (teste A/B do "Testar e comparar"), TODAS precisam passar: aponte qual \
falhou. Reprove TAMBÉM se o título ou o texto da thumb destacam palavrão ou \
termo que possa soar como ofensa a um grupo (raça, etnia, gênero, orientação sexual, \
religião, origem, deficiência etc.), MESMO que esteja na fala: diga isso em titulo_problema.
2. thumb_ok: """ + CRITERIO_THUMB + """
3. tela_compartilhada: nos frames do corte (imagens seguintes), a MAIOR parte mostra tela \
compartilhada (navegador, matéria, gráfico, documento) em vez de pessoas falando? Isso é \
true. Algum frame de tela no meio é normal: aí é false.
4. corte_sem_sentido: pela transcrição, o trecho NÃO se sustenta sozinho? Ex.: começa ou \
termina no meio de um raciocínio a ponto de não dar pra entender do que se fala, ou pula \
de assunto sem fio condutor. Começo abrupto mas compreensível é false.
5. momentos_fora: cada item dos PRINCIPAIS MOMENTOS DA DESCRIÇÃO tem que estar DENTRO da \
transcrição do trecho (fala citada ou fato dito nele; paráfrase fiel de algo dito no trecho é \
ok). Liste, copiando o item EXATAMENTE como veio, cada um que não está: fala de outro momento \
da live, inventada ou distorcida. Lista vazia [] quando todos estão (ou não há itens).
6. capitulos_errados: se a transcrição traz marcas [CAPÍTULO MM:SS: título], cada título tem \nque descrever o que é dito no trecho dele (da marca até a próxima). Liste, copiando o título \nEXATAMENTE como veio na marca, cada um que fala de outra coisa, promete o que o trecho não \nentrega ou destaca palavrão/termo ofensivo. Rótulo genérico mas correto é ok. Lista vazia [] \nquando todos batem (ou não há marcas)."""


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
                    thumb_b64: str | None, frames: list[str],
                    momentos: list[str] = ()) -> list[dict]:
    img = lambda b64: {"type": "image",   # noqa: E731
                       "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    conteudo = []
    if thumb_b64:
        conteudo += [{"type": "text", "text": "THUMB:"}, img(thumb_b64)]
    conteudo += [{"type": "text", "text": f"FRAMES DO CORTE ({len(frames)}):"}]
    conteudo += [img(f) for f in frames]
    sem_thumb = "" if thumb_b64 else "SEM THUMB ESCOLHIDA: marque thumb_ok=false.\n"
    lista = "\n".join(f"• {m}" for m in momentos) or "(nenhum)"
    conteudo.append({"type": "text", "text": (
        f"TÍTULO DO YOUTUBE: {titulo}\nTEXTO DA THUMB: {texto_thumb}\n{sem_thumb}"
        f"\nPRINCIPAIS MOMENTOS DA DESCRIÇÃO:\n{lista}\n"
        f"\nTRANSCRIÇÃO DO TRECHO:\n{transcricao}")})
    return conteudo


def sistema_revisor() -> list[dict]:
    """Parte fixa do pedido (instruções + grafias, ~2K tokens) com o breakpoint do prompt
    cache no fim: blocos revisados em sequência (< 5 min entre um e outro) leem isso do
    cache. O que muda (thumb, frames, título, transcrição) vem depois, na mensagem."""
    return [{"type": "text", "text": SISTEMA},
            {"type": "text", "text": f"GRAFIAS OFICIAIS:\n{_grafias.para_prompt()}",
             "cache_control": {"type": "ephemeral"}}]


def textos_classica(pasta: Path, bid: int) -> dict[str, str]:
    """{letra: texto} que o 07 desenhou em cada thumb clássica (fila candidatos_NN.json)."""
    try:
        fila = json.loads((pasta / "thumbs" / f"candidatos_{bid:02d}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    textos = fila.get("textos") if isinstance(fila, dict) else None
    return textos if isinstance(textos, dict) else {}


def texto_da_thumb(pasta: Path, bid: int, texto_thumb: str) -> str:
    """O texto que está NAS thumbs que sobem (a/b/c vão todas pro "Testar e comparar"),
    separados por ' | ': o da colagem onde ela foi aplicada, o que o 07 desenhou na clássica
    (modo ab: textos diferentes), texto_thumb na falta."""
    textos, classica = [], textos_classica(pasta, bid)
    for letra in "abc":
        thumb = pasta / "thumbs" / f"thumb_{bid:02d}_{letra}.png"
        if thumb.exists():
            v = _colagem.variante_aplicada(thumb)
            textos.append(_colagem.sem_marcas(" ".join(v["texto"])) if v
                          else classica.get(letra) or texto_thumb)
    return " | ".join(dict.fromkeys(textos)) or texto_thumb


def chamar_claude(client, conteudo: list[dict], sistema: str | None = None, schema: dict = SCHEMA,
                  effort: str = "medium") -> tuple[dict | None, object]:
    """(checagens ou None se recusou, resposta). Fallback de refusal ligado (servidor).
    Sem `sistema`: o do revisor completo, com prompt cache."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        system=sistema_revisor() if sistema is None else sistema,
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
    u = _custo.uso(resp, MODELO)
    return u["tokens_in"], u["tokens_out"], u["custo_usd"]


def escolher_video(pasta: Path, nn: str) -> Path | None:
    """Corte completo (sem _polido): é o que os frames precisam mostrar."""
    cortes = sorted(p for p in (pasta / "cortes").glob(f"corte_{nn}_*.mp4")
                    if "_polido" not in p.stem)
    return cortes[0] if cortes else None


def revisar_bloco(client, anthropic, stem, pasta, b, nn, video, titulo, texto_thumb,
                  transcricao, momentos=()):
    """Uma revisão (uma chamada). (checagens, status, motivo, custo) ou None se falhou."""
    bid = b["id"]
    thumb = escolher_thumb(pasta / "thumbs", nn)
    t0 = time.time()
    _custo.checar_orcamento(stem, "11_revisor")
    evento(stem, "11_revisor", "inicio", agente="revisor", bloco_id=bid)
    try:
        conteudo = montar_conteudo(titulo, texto_thumb, transcricao,
                                   ler_imagem_b64(thumb) if thumb else None, frames_b64(video),
                                   momentos)
        checagens, resp = chamar_claude(client, conteudo)
    except (anthropic.APIError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"  [!] {nn}: revisão falhou ({type(e).__name__}: {str(e)[:200]})")
        evento(stem, "11_revisor", "falha", agente="revisor", bloco_id=bid,
               mensagem=_custo.descrever_erro(e), duracao_s=time.time() - t0)
        return None
    tin, tout, usd = custo(resp)
    evento(stem, "11_revisor", "llm", agente="revisor", bloco_id=bid, tokens_in=tin,
           tokens_out=tout, custo_usd=usd, mensagem=resp.model, duracao_s=time.time() - t0,
           **_custo.cache(resp))
    status, motivo = decidir(checagens)
    print(f"  {nn}: revisor → {status}{' — ' + motivo if motivo else ''} (US$ {usd:.3f})")
    return checagens, status, motivo, usd


def editar(client, anthropic, stem, pasta, b, titulo, texto_thumb, problema, transcricao,
           tentativas) -> tuple[dict | None, float]:
    """Uma reescrita do editor, já gravada (txt, json, thumb, Short). (novo ou None, custo)."""
    bid, nn = b["id"], f"{b['id']:02d}"
    _custo.checar_orcamento(stem, "11_editor")
    evento(stem, "11_editor", "inicio", agente="editor", bloco_id=bid)
    pedido = _editor.montar_pedido(titulo, texto_thumb, problema, transcricao, tentativas,
                                   [t["termo"] for t in termos_semana()])
    try:
        novo, resp = _editor.reescrever(client, pedido)
    except (anthropic.APIError, json.JSONDecodeError) as e:
        print(f"  [!] {nn}: editor falhou ({type(e).__name__}: {str(e)[:200]})")
        evento(stem, "11_editor", "falha", agente="editor", bloco_id=bid,
               mensagem=_custo.descrever_erro(e))
        return None, 0.0
    tin, tout, usd = _editor.custo(resp)
    evento(stem, "11_editor", "llm", agente="editor", bloco_id=bid, tokens_in=tin,
           tokens_out=tout, custo_usd=usd, mensagem=resp.model, **_custo.cache(resp))
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
               duracao_s=time.time() - t0, **_custo.cache(resp))
        if r is None:
            return "quarentena", "thumb: revisor recusou analisar — revisar à mão", problemas, usd_total
        print(f"  {nn}: frame novo da thumb → {'ok' if r['thumb_ok'] else r['thumb_problema']}"
              f" (US$ {usd:.3f})")
        if r["thumb_ok"]:
            return "aprovado", None, problemas, usd_total
        problemas.append(r["thumb_problema"])
    return ("descartado", f"thumb: nenhum frame com rosto serviu ({len(problemas) - 1} troca(s); "
            f"último problema: {problemas[-1]})", problemas, usd_total)


def conferir_colagem_ab(client, anthropic, stem, pasta, bid, titulo) -> float:
    """Modo ab: o revisor avaliou a 'a' (template), mas as colagens b/c também sobem no
    "Testar e comparar". Confere a arte delas (~US$ 0.01 cada); reprovou → b/c voltam pro
    template (o bloco segue aprovado, só sai do teste). Devolve o custo."""
    usd_total = 0.0
    for thumb in _colagem.colagem_ab(pasta / "thumbs", bid):
        texto = _colagem.sem_marcas(" ".join(_colagem.variante_aplicada(thumb)["texto"]))
        t0 = time.time()
        try:
            r, resp = checar_thumb(client, thumb, titulo, texto)
        except (anthropic.APIError, json.JSONDecodeError) as e:
            r, problema = None, f"falhou ao avaliar ({type(e).__name__})"
        else:
            tin, tout, usd = custo(resp)
            usd_total += usd
            evento(stem, "11_revisor", "llm", agente="revisor", bloco_id=bid, tokens_in=tin,
                   tokens_out=tout, custo_usd=usd, mensagem=f"{resp.model} (colagem ab)",
                   duracao_s=time.time() - t0, **_custo.cache(resp))
            problema = "revisor recusou analisar" if r is None else r["thumb_problema"]
        if r is not None and r["thumb_ok"]:
            continue
        ok = _editor.voltar_template(pasta, bid, ("b", "c"))
        destino = "voltaram pro template" if ok else "NÃO voltaram pro template (falhou o 07)"
        msg = f"colagem {thumb.stem[-1]} reprovada ({problema}) → b/c {destino}"
        print(f"  {bid:02d}: {msg}")
        evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=bid, mensagem=msg[:300])
        break
    return usd_total


def conferir_classica_ab(client, anthropic, stem, pasta, bid, titulo) -> float:
    """Modo ab da clássica: o revisor avaliou a 'a', mas b/c (outros frames e textos) também
    sobem no "Testar e comparar". Confere a arte de cada uma (~US$ 0.01); reprovada → vira
    thumb_NN_<l>_reprovada.png e sai do teste (o bloco segue aprovado). Devolve o custo."""
    from _paths import modo_thumb
    if modo_thumb() != "ab":
        return 0.0
    usd_total, textos = 0.0, textos_classica(pasta, bid)
    for letra in "bc":
        thumb = pasta / "thumbs" / f"thumb_{bid:02d}_{letra}.png"
        if not thumb.exists() or _colagem.variante_aplicada(thumb):
            continue
        t0 = time.time()
        try:
            _custo.checar_orcamento(stem, "11_revisor")   # estourado: sem conferir, sai do teste
            r, resp = checar_thumb(client, thumb, titulo, textos.get(letra, ""))
        except _custo.OrcamentoEstourado:
            r, problema = None, "não conferida: orçamento da live estourado"
        except (anthropic.APIError, json.JSONDecodeError) as e:
            r, problema = None, f"falhou ao avaliar ({type(e).__name__})"
        else:
            tin, tout, usd = custo(resp)
            usd_total += usd
            evento(stem, "11_revisor", "llm", agente="revisor", bloco_id=bid, tokens_in=tin,
                   tokens_out=tout, custo_usd=usd, mensagem=f"{resp.model} (thumb ab {letra})",
                   duracao_s=time.time() - t0, **_custo.cache(resp))
            problema = "revisor recusou analisar" if r is None else r["thumb_problema"]
        if r is not None and r["thumb_ok"]:
            continue
        thumb.replace(thumb.with_name(f"{thumb.stem}_reprovada.png"))
        msg = f"thumb {letra} reprovada ({problema}) → fora do Testar e comparar"
        print(f"  {bid:02d}: {msg}")
        evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=bid, mensagem=msg[:300])
    return usd_total


def flags_refazer(pasta: Path, nn: str) -> list[str]:
    """Flags do pipeline.py que refazem o bloco do mesmo jeito que ele foi feito."""
    cortes = pasta / "cortes"
    polido = any(cortes.glob(f"corte_{nn}_*_polido.mp4"))
    legendado = any((cortes / "legendados").glob(f"corte_{nn}_*.mp4"))
    return (["--polir"] if polido else []) + ([] if legendado else ["--sem-legendas"])


def refazer_bloco(pasta: Path, bid: int) -> bool:
    """pipeline.py --bloco=N: re-corta, pole, legenda e monta só esse bloco (04b com LLM:
    ~US$ 0.03, logado pelo próprio 04b)."""
    cmd = [sys.executable, str(SCRIPTS / "pipeline.py"), pasta.name, f"--bloco={bid}",
           *flags_refazer(pasta, f"{bid:02d}")]
    try:
        ok = subprocess.run(cmd, capture_output=True, timeout=1800).returncode == 0
    except subprocess.TimeoutExpired:
        return False
    if ok:
        recalcular_capitulos(pasta, bid)
    return ok


def recalcular_capitulos(pasta: Path, bid: int) -> None:
    """Bloco refeito com outros tempos: o relógio do vídeo mudou, então a seção "Capítulos:" do
    descricoes.txt é refeita a partir do blocos.json ($0). Bloco sem capítulos: não mexe."""
    desc, blocos_path = pasta / "descricoes.txt", pasta / "blocos.json"
    if not (desc.exists() and blocos_path.exists()):
        return
    b = next((x for x in json.loads(blocos_path.read_text(encoding="utf-8"))["blocos"]
              if x["id"] == bid), None)
    if not (b and b.get("capitulos")):
        return
    wj = pasta / "words.json"
    todas = json.loads(wj.read_text(encoding="utf-8")).get("words", []) if wj.exists() else []
    linhas = _capitulos.linhas(b["capitulos"], _capitulos.LinhaDoTempo(pasta, b, todas),
                               _grafias.corrigir)
    desc.write_text(trocar_capitulos(desc.read_text(encoding="utf-8"), bid, linhas),
                    encoding="utf-8")


def transcricao_com_capitulos(pasta: Path, b: dict, todas: list[dict], descricao: str,
                              removidos_s: list[tuple[float, float]]) -> tuple[str, list[str]]:
    """Transcrição do trecho com uma marca [CAPÍTULO MM:SS: título] onde cada capítulo da
    descrição começa (tempo do vídeo final levado de volta pra live). Devolve (texto, títulos);
    sem capítulos na descrição, a transcrição pura e []."""
    ini = hhmmss_para_segundos(b["timestamp_inicio"])
    fim = hhmmss_para_segundos(b["timestamp_fim"])
    caps = _capitulos.no_video(descricao)
    tempo = _capitulos.LinhaDoTempo(pasta, b, todas) if caps else None
    marcas = [(ini if i == 0 else tempo.para_live(t), f"[CAPÍTULO {_capitulos.mmss(t)}: {titulo}]")
              for i, (t, titulo) in enumerate(caps)]
    partes = []
    for w in palavras_na_janela(todas, ini, fim):
        t = ini + w["start"]
        if any(a <= t < z for a, z in removidos_s):
            continue
        while marcas and marcas[0][0] <= t + 0.01:
            partes.append("\n" + marcas.pop(0)[1] + "\n")
        partes.append(w["word"])
    partes += ["\n" + m for _, m in marcas]
    return " ".join(partes), [titulo for _, titulo in caps]


def limpar_capitulos(pasta: Path, bid: int, errados: list[str], titulos: list[str]) -> list[str]:
    """Capítulo cujo título não bate com o trecho sai do descricoes.txt e do blocos.json (o 08
    não traz de volta). Sem o de 00:00 ou com menos de 3, sai a seção inteira. $0."""
    norm = _fronteira._norm
    removidos = []
    for e in errados:
        par = max(titulos, key=lambda t: difflib.SequenceMatcher(None, norm(t), norm(e)).ratio(),
                  default=None)
        if par and par not in removidos and \
                difflib.SequenceMatcher(None, norm(par), norm(e)).ratio() >= _MOMENTO_PARECIDO:
            removidos.append(par)
    if not removidos:
        return []
    desc = pasta / "descricoes.txt"
    if desc.exists():
        desc.write_text(remover_capitulos(desc.read_text(encoding="utf-8"), bid, removidos,
                                          _capitulos.MIN_CAPITULOS), encoding="utf-8")
    blocos_path = pasta / "blocos.json"
    data = json.loads(blocos_path.read_text(encoding="utf-8"))
    alvo = {norm(r) for r in removidos}
    for x in data["blocos"]:
        if x["id"] == bid and x.get("capitulos"):
            ficam = [c for c in x["capitulos"] if norm(_grafias.corrigir(c["titulo"])) not in alvo
                     and norm(c["titulo"]) not in alvo]
            # sem o 1º (00:00), o 08 rotularia a abertura com o título errado: tira todos
            x["capitulos"] = ficam if ficam and ficam[0] is x["capitulos"][0] else []
    blocos_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return removidos


def gravar_tempos(stem: str, pasta: Path, b: dict, novo_ini: float, novo_fim: float) -> None:
    """Grava os tempos novos do bloco no blocos.json (e no dict `b`) e a duração no banco."""
    blocos_path = pasta / "blocos.json"
    data = json.loads(blocos_path.read_text(encoding="utf-8"))
    for x in data["blocos"]:
        if x["id"] == b["id"]:
            x["timestamp_inicio"] = b["timestamp_inicio"] = _fronteira.segundos_para_ts(novo_ini)
            x["timestamp_fim"] = b["timestamp_fim"] = _fronteira.segundos_para_ts(novo_fim)
            x["duracao_minutos"] = b["duracao_minutos"] = round((novo_fim - novo_ini) / 60, 1)
            x["faixa_duracao"] = b["faixa_duracao"] = _fronteira.faixa(x["duracao_minutos"])
    blocos_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    upsert_bloco(stem, b["id"], duracao_min=b["duracao_minutos"])


def conferir_abertura(stem: str, pasta: Path, b: dict, todas: list[dict],
                      reajustar: bool = True) -> tuple[dict | None, str | None]:
    """Regra editorial: nenhum corte abre com propaganda/patrocínio da live original
    (config/propaganda.json). Código, $0. Abre com propaganda → o início vai pra 1ª frase
    depois dela, grava no blocos.json e refaz o bloco sozinho. Sem ela o corte fica com menos
    de 8 min → quarentena. (registro pro revisao.json ou None, motivo de quarentena ou None)."""
    bid, nn = b["id"], f"{b['id']:02d}"
    ini, fim = hhmmss_para_segundos(b["timestamp_inicio"]), hhmmss_para_segundos(b["timestamp_fim"])
    pp = _fronteira.pular_propaganda(todas, ini, *_fronteira.termos_propaganda())
    if pp is None:
        return None, None
    novo_ini, pulado = pp
    registro = {"pulado_s": round(novo_ini - ini, 2), "trecho": pulado[-200:]}
    print(f"  {nn}: abre com propaganda da live (\"{pulado[:60]}…{pulado[-60:]}\") → começa "
          f"{novo_ini - ini:.0f}s depois")
    if not reajustar:
        return registro, "corte abre com propaganda da live"
    if (fim - novo_ini) / 60 < _fronteira.LONGO_MIN:
        return registro, (f"corte abre com propaganda da live e sem ela fica com "
                          f"{(fim - novo_ini) / 60:.1f} min (mínimo {_fronteira.LONGO_MIN:.0f}) — "
                          f"revisar à mão")
    gravar_tempos(stem, pasta, b, novo_ini, fim)
    evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=bid,
           mensagem=f"abertura sem propaganda: +{novo_ini - ini:.0f}s")
    if not refazer_bloco(pasta, bid):
        return registro, "início movido pra depois da propaganda, mas falhou ao refazer o bloco"
    return registro, None


_MOMENTO_PARECIDO = 0.85    # o revisor às vezes devolve o item com outra pontuação/acento


def limpar_momentos(pasta: Path, bid: int, fora: list[str], momentos: list[str]) -> list[str]:
    """Regra editorial: toda fala de "Principais momentos" está dentro do trecho. Tira do
    descricoes.txt (edição manual vale: mexe só nessas linhas) e dos ganchos do blocos.json os
    itens que o revisor achou fora. Devolve os itens removidos ($0, sem refazer vídeo)."""
    norm = _fronteira._norm   # sem acento, pontuação e espaço
    removidos = []
    for f in fora:
        par = max(momentos, key=lambda m: difflib.SequenceMatcher(None, norm(m), norm(f)).ratio(),
                  default=None)
        if par and par not in removidos and \
                difflib.SequenceMatcher(None, norm(par), norm(f)).ratio() >= _MOMENTO_PARECIDO:
            removidos.append(par)
    if not removidos:
        return []
    desc = pasta / "descricoes.txt"
    if desc.exists():
        desc.write_text(remover_momentos(desc.read_text(encoding="utf-8"), bid, removidos),
                        encoding="utf-8")
    blocos_path = pasta / "blocos.json"
    data = json.loads(blocos_path.read_text(encoding="utf-8"))
    alvo = {norm(r) for r in removidos}
    for x in data["blocos"]:
        if x["id"] == bid:
            x["ganchos"] = [g for g in x.get("ganchos", [])
                            if norm(_grafias.corrigir(g)) not in alvo and norm(g) not in alvo]
    blocos_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return removidos


def conferir_fronteira(stem: str, pasta: Path, b: dict, todas: list[dict],
                       reajustar: bool = True) -> tuple[dict, str | None]:
    """Regra editorial: corte começa e termina em ponto natural (fim de frase + pausa).
    Checagem por código (words.json), $0, antes da chamada paga. Reprovou → leva a ponta
    pro fim de frase mais perto, grava no blocos.json e refaz o bloco sozinho.
    (registro pro revisao.json, motivo de quarentena ou None)."""
    bid, nn = b["id"], f"{b['id']:02d}"
    ini, fim = hhmmss_para_segundos(b["timestamp_inicio"]), hhmmss_para_segundos(b["timestamp_fim"])
    chk = _fronteira.checar(todas, ini, fim)
    registro = {"inicio_ok": chk["inicio_ok"], "fim_ok": chk["fim_ok"],
                "ultimas": chk["ultimas"], "pausa_depois_s": chk["pausa_depois_s"]}
    if chk["inicio_ok"] and chk["fim_ok"]:
        return registro, None
    pontas = " e ".join(p for p, ok in (("começa", chk["inicio_ok"]), ("termina", chk["fim_ok"]))
                        if not ok)
    print(f"  {nn}: fronteira reprovada — {pontas} no meio de frase "
          f"(início: \"{chk['primeiras']}…\" · fim: \"…{chk['ultimas']}\", "
          f"pausa depois {chk['pausa_depois_s']}s)")
    if not reajustar:
        return registro, f"corte {pontas} no meio de frase"
    dur = fim - ini
    e = _fronteira.encaixar(
        todas, ini, fim, _fronteira.JANELA_BLOCO_S,
        _fronteira.LONGO_MIN * 60 if dur >= _fronteira.LONGO_MIN * 60 else None,
        _fronteira.LONGO_MAX * 60 if dur <= _fronteira.LONGO_MAX * 60 else None)
    if (not chk["inicio_ok"] and not e["inicio_ok"]) or (not chk["fim_ok"] and not e["fim_ok"]):
        return registro, (f"corte {pontas} no meio de frase e não há ponto natural a até "
                          f"{_fronteira.JANELA_BLOCO_S:.0f}s — ajuste os tempos à mão no blocos.json")
    novo_ini = e["inicio"] if not chk["inicio_ok"] else ini
    novo_fim = e["fim"] if not chk["fim_ok"] else fim
    if abs(novo_ini - ini) < 0.01 and abs(novo_fim - fim) < 0.01:
        # o ponto natural é o próprio tempo e a checagem reprova: refazer daria o mesmo vídeo
        return registro, (f"corte {pontas} no meio de frase, mas o ponto natural mais perto é "
                          f"o tempo atual — revisar à mão")
    gravar_tempos(stem, pasta, b, novo_ini, novo_fim)
    registro["reajuste_s"] = [round(novo_ini - ini, 2), round(novo_fim - fim, 2)]
    print(f"  {nn}: reajustado ({registro['reajuste_s'][0]:+.1f}s no início, "
          f"{registro['reajuste_s'][1]:+.1f}s no fim) → refazendo o bloco (pipeline --bloco, "
          f"~US$ {CUSTO_REFAZER_BLOCO:.2f} do 04b se polido)")
    evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=bid,
           mensagem=f"fronteira reajustada {registro['reajuste_s']}")
    if not refazer_bloco(pasta, bid):
        return registro, "fronteira reajustada, mas falhou ao refazer o bloco (pipeline --bloco)"
    chk = _fronteira.checar(todas, novo_ini, novo_fim)
    registro.update(inicio_ok=chk["inicio_ok"], fim_ok=chk["fim_ok"], ultimas=chk["ultimas"],
                    pausa_depois_s=chk["pausa_depois_s"])
    if not (chk["inicio_ok"] and chk["fim_ok"]):
        return registro, "fronteira continua no meio de frase depois do reajuste — revisar à mão"
    return registro, None


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
             f"/bloco se o editor reescrever)" if com_editor else "")
          + f" · +~US$ {CUSTO_REFAZER_BLOCO:.2f}/bloco com fronteira reajustada (04b refeito)")
    if dry or not fila:
        for b, nn, _ in fila:   # abertura e fronteira são de graça: mostra no dry-run
            conferir_abertura(stem, pasta, b, todas, reajustar=False)
            conferir_fronteira(stem, pasta, b, todas, reajustar=False)
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
        abertura, motivo_fr = conferir_abertura(stem, pasta, b, todas)
        fronteira = None
        if not motivo_fr:
            fronteira, motivo_fr = conferir_fronteira(stem, pasta, b, todas)
        if motivo_fr:
            upsert_bloco(stem, bid, status="quarentena", forcar_status=True, motivo=motivo_fr)
            revisao[nn] = {"status": "quarentena", "motivo": motivo_fr, "fronteira": fronteira,
                           "abertura": abertura, "modelo": None, "custo_usd": 0.0}
            revisao_path.write_text(json.dumps(revisao, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            evento(stem, "11_revisor", "ok", agente="revisor", bloco_id=bid,
                   mensagem=f"quarentena: {motivo_fr}"[:300])
            print(f"  {nn}: QUARENTENA — {motivo_fr}")
            continue
        video = escolher_video(pasta, nn) or video   # refeito pelo reajuste: mesmo nome
        titulo = descricoes.get(bid, {}).get("titulo") or b.get("titulo_sugerido", "")
        texto_base = b.get("texto_thumb") or b.get("tema", "")    # o do template (07)
        texto_thumb = texto_da_thumb(pasta, bid, texto_base)
        ini = hhmmss_para_segundos(b["timestamp_inicio"])
        fim = hhmmss_para_segundos(b["timestamp_fim"])
        removidos_s = [(hhmmss_para_segundos(r["inicio"]), hhmmss_para_segundos(r["fim"]))
                       for r in b.get("remover") or []]   # cortado pelo 04b: não está no vídeo
        transcricao = " ".join(w["word"] for w in palavras_na_janela(todas, ini, fim)
                               if not any(a <= ini + w["start"] < z for a, z in removidos_s))
        momentos = momentos_da_descricao(descricoes.get(bid, {}).get("descricao", ""))
        transcricao_rev, capitulos = transcricao_com_capitulos(
            pasta, b, todas,   # relido: o reajuste da fronteira pode ter refeito os capítulos
            (ler_descricoes(desc_txt.read_text(encoding="utf-8")) if desc_txt.exists() else {})
            .get(bid, {}).get("descricao", ""), removidos_s)
        tentativas, custo_bloco = [], 0.0
        while True:
            r = revisar_bloco(client, anthropic, stem, pasta, b, nn, video, titulo, texto_thumb,
                              transcricao_rev, momentos)
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
        escolhida_colagem = _colagem.variante_aplicada(escolher_thumb(pasta / "thumbs", nn))
        if status == "quarentena" and checagens and checagens["titulo_fiel"] \
                and not checagens["thumb_ok"] and escolhida_colagem:
            # colagem reprovada na arte: as 3 variantes voltam pro template (o --proximo só
            # trocaria a 'a') e o bloco é revisado de novo, com o texto do template
            print(f"  {nn}: colagem reprovada ({checagens['thumb_problema']}) → template atual")
            if _editor.voltar_template(pasta, bid):
                texto_thumb = texto_base
                r2 = revisar_bloco(client, anthropic, stem, pasta, b, nn, video, titulo,
                                   texto_thumb, transcricao_rev, momentos)
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
        if status == "aprovado":
            usd_ab = (conferir_colagem_ab(client, anthropic, stem, pasta, bid, titulo)
                      + conferir_classica_ab(client, anthropic, stem, pasta, bid, titulo))
            total += usd_ab
            custo_bloco += usd_ab
            texto_thumb = texto_da_thumb(pasta, bid, texto_base)

        # falas de "Principais momentos" fora do trecho: saem da descrição sozinhas ($0)
        removidos = limpar_momentos(pasta, bid, (checagens or {}).get("momentos_fora") or [],
                                    momentos)
        if removidos:
            print(f"  {nn}: {len(removidos)} momento(s) da descrição fora do trecho — removido(s): "
                  + " | ".join(removidos))
            evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=bid,
                   mensagem=f"momentos fora do trecho removidos: {' | '.join(removidos)}"[:300])
            if status == "aprovado" and len(removidos) >= 2 and len(removidos) * 2 > len(momentos):
                # a maior parte da descrição fala de outro trecho: sinal de tempos do bloco
                # trocados (o LLM do 03 deu tempos de um trecho e frases de outro)
                status = "quarentena"
                motivo = (f"{len(removidos)} de {len(momentos)} momentos da descrição eram de fora "
                          f"do trecho (removidos) — confira se os tempos do bloco estão certos")
        # capítulo com título que não bate com o trecho: sai da descrição sozinho ($0)
        caps_fora = limpar_capitulos(pasta, bid, (checagens or {}).get("capitulos_errados") or [],
                                     capitulos)
        if caps_fora:
            print(f"  {nn}: {len(caps_fora)} capítulo(s) não batem com o trecho — removido(s): "
                  + " | ".join(caps_fora))
            evento(stem, "11_revisor", "aviso", agente="revisor", bloco_id=bid,
                   mensagem=f"capítulos removidos: {' | '.join(caps_fora)}"[:300])
        upsert_bloco(stem, bid, status=status, forcar_status=True, motivo=motivo)
        thumb = escolher_thumb(pasta / "thumbs", nn)
        revisao[nn] = {"status": status, "motivo": motivo, "checagens": checagens,
                       "fronteira": fronteira, "abertura": abertura,
                       "momentos_removidos": removidos, "capitulos_removidos": caps_fora,
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
