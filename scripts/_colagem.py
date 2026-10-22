"""Thumb "colagem" (estilo canal de react): núcleo usado pelo 07b_colagem.py e pelo personagens.py.

Layout (1280x720):
  - fundo com 2 cenas lado a lado: o assunto comentado (esq.) e o contexto (dir.)
  - círculo ou seta vermelha no rosto-chave da cena (OpenCV Haar)
  - recorte do apresentador sem fundo (rembg, local) à direita, com contorno branco
  - texto grande em 2 linhas com contorno preto grosso: *palavra* em amarelo, [Nome] em vermelho

Fontes das cenas: primeiro a tela compartilhada da própria live (caixa de react que o
_thumb_rosto.detectar_overlays acha, ou frame inteiro sem o apresentador); na falta, o banco de
personagens com licença aberta (assets/personagens/, ver personagens.py).

A escolha da expressão (~6 frames com rosto bom) e das 2 cenas é uma chamada de visão barata
(claude-haiku-5-5, ~US$ 0.0005 por bloco); o texto é do editor (_editor.texto_colagem).
Tudo o mais é local e grátis.
"""
import base64
import json
import re
import unicodedata
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import _grafias
import _thumb_rosto as tr

ROOT = Path(__file__).parent.parent
PERSONAGENS = ROOT / "assets" / "personagens"
LICENCAS = PERSONAGENS / "licencas.json"
FONTE = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"

LARGURA, ALTURA = tr.LARGURA, tr.ALTURA
PRETO = (10, 10, 10)
AMARELO = (245, 197, 24)
BRANCO = (255, 255, 255)
VERMELHO = (229, 28, 35)

# layout
DIVISA_X = 450             # cena 1 em [0, DIVISA_X), cena 2 de DIVISA_X até a borda (atrás do apresentador)
FOCO_CENA2 = 0.28          # rosto/centro da cena 2 nessa fração da largura dela (fora de trás do apresentador)
ROSTO_CENA = 0.30          # altura do rosto-chave como fração da altura da cena
ZOOM_CENA_MAX = 2.2
CARTAO_MARGEM, CARTAO_TOPO = 34, 40   # cartão da cena 2: posição dentro do painel 2...
CARTAO_W, CARTAO_H_MAX = 420, 380     # ...e tamanho máximo (fica entre a divisa e o apresentador)
ROSTO_APRES = 0.42         # altura do rosto (caixa do Haar) na thumb: a cabeça fica com ~45-50%
ZOOM_APRES_MAX = 3.0       # ampliação máxima do frame (720p) do apresentador
APRES_X, APRES_Y = 0.81, 0.39   # centro do rosto do apresentador
CONTORNO_APRES = 7         # px do contorno branco do recorte
TEXTO_X, TEXTO_MAX_W = 36, 860
TEXTO_MAX, TEXTO_MIN = 150, 70
MARGEM_BAIXO = 26

# candidatos
N_EXPRESSOES = 6
N_CENAS = 8
AMOSTRAS_CENA = 8
AREA_CENA_MIN = 0.08       # caixa de react menor que 8% do frame é logo/bandeira, não cena
DIF_REPETIDA = 10.0        # diferença média (0-255) abaixo da qual duas cenas são a mesma imagem
DIF_ESTUDIO = 30.0         # frame sem rosto mais parecido que isso com o estúdio é o apresentador virado
LARGURA_LLM = 384

MODELO_VISAO = "claude-haiku-5-5"
PRECO_IN, PRECO_OUT = 0.10, 0.50   # US$ por 1M tokens (haiku 5.5)

_SESSAO_REMBG = None


# ── texto ───────────────────────────────────────────────────────────────────

_MARCA = re.compile(r"(\*[^*]+\*|\[[^\]]+\])")


def pedacos(linha: str) -> list[tuple[str, tuple]]:
    """'QUEM MANDA *AGORA*?' → [('QUEM MANDA ', branco), ('AGORA', amarelo), ('?', branco)].
    *x* = amarelo, [x] = vermelho (o nome)."""
    saida = []
    for p in _MARCA.split(linha):
        if not p:
            continue
        if p.startswith("*") and p.endswith("*"):
            saida.append((p[1:-1], AMARELO))
        elif p.startswith("[") and p.endswith("]"):
            saida.append((p[1:-1], VERMELHO))
        else:
            saida.append((p, BRANCO))
    return saida


def sem_marcas(linha: str) -> str:
    return "".join(t for t, _ in pedacos(linha))


def fonte(tamanho: int):
    return ImageFont.truetype(str(FONTE), tamanho) if FONTE.exists() else ImageFont.load_default()


def tamanho_texto(linhas: list[str], largura_max: int = TEXTO_MAX_W) -> int:
    """Maior fonte (TEXTO_MIN..TEXTO_MAX) em que todas as linhas cabem na largura."""
    for t in range(TEXTO_MAX, TEXTO_MIN - 1, -4):
        f = fonte(t)
        if all(f.getlength(sem_marcas(l)) + 2 * contorno_texto(t) <= largura_max for l in linhas):
            return t
    return TEXTO_MIN


def contorno_texto(tamanho: int) -> int:
    return max(5, tamanho // 11)


def desenhar_linhas(canvas: Image.Image, linhas: list[str]) -> None:
    """2 linhas grandes embaixo à esquerda, contorno preto grosso e sombra."""
    t = tamanho_texto(linhas)
    f, borda = fonte(t), contorno_texto(t)
    altura_linha = int(t * 1.05)
    y = ALTURA - MARGEM_BAIXO - altura_linha * len(linhas) - borda
    sombra = Image.new("L", canvas.size, 0)
    sdraw = ImageDraw.Draw(sombra)
    draw = ImageDraw.Draw(canvas)
    for i, linha in enumerate(linhas):
        x, yl = TEXTO_X, y + i * altura_linha
        for texto, _ in pedacos(linha):
            sdraw.text((x + 8, yl + 8), texto, font=f, fill=200, stroke_width=borda, stroke_fill=200)
            x += f.getlength(texto)
    canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), sombra.filter(ImageFilter.GaussianBlur(6)))
    for i, linha in enumerate(linhas):
        x, yl = TEXTO_X, y + i * altura_linha
        for texto, cor in pedacos(linha):
            draw.text((x, yl), texto, font=f, fill=cor, stroke_width=borda, stroke_fill=PRETO)
            x += f.getlength(texto)


def quebrar_em_2(texto: str) -> list[str]:
    """Texto curto (texto_thumb) em 2 linhas equilibradas, 1ª palavra-chave em amarelo.
    Usado quando o editor não roda (--sem-llm) ou falha."""
    palavras = texto.upper().split()
    if len(palavras) < 2:
        return [f"*{texto.upper()}*"]
    corte = min(range(1, len(palavras)),
                key=lambda k: abs(len(" ".join(palavras[:k])) - len(" ".join(palavras[k:]))))
    l1, l2 = " ".join(palavras[:corte]), " ".join(palavras[corte:])
    return [l1, f"*{l2}*"]


def variante_aplicada(thumb: Path | None) -> dict | None:
    """Registro (texto, marcador...) da variante de colagem se `thumb` é cópia idêntica dela
    (modo padrão, --aplicar). Thumb trocada depois (revisor/editor/manual) deixa de casar."""
    if thumb is None:
        return None
    copia = thumb.parent / "colagem" / thumb.name
    try:
        if copia.read_bytes() != thumb.read_bytes():
            return None
        registro = json.loads((thumb.parent / "colagem" / "colagem.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((v for r in registro.values() for v in r.get("variantes", {}).values()
                 if v.get("arquivo") == thumb.name), None)


def colagem_aplicada(thumbs: Path, bid: int) -> dict | None:
    """Registro do bloco no colagem.json (variantes, créditos...) se alguma thumb_NN_a/b/c do
    bloco é a colagem aplicada; None se não é (ou se a colagem do bloco não saiu)."""
    nn = f"{bid:02d}"
    if not any(variante_aplicada(thumbs / f"thumb_{nn}_{l}.png") for l in "abc"):
        return None
    try:
        reg = json.loads((thumbs / "colagem" / "colagem.json").read_text(encoding="utf-8")).get(str(bid))
    except (OSError, ValueError, AttributeError):
        return None
    return reg if isinstance(reg, dict) and reg.get("status") == "ok" else None


# ── personagens ─────────────────────────────────────────────────────────────

def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    return re.sub(r"[^a-z0-9 ]+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def ler_licencas() -> list[dict]:
    try:
        return json.loads(LICENCAS.read_text(encoding="utf-8"))["personagens"]
    except (OSError, ValueError, KeyError):
        return []


def campos_de_nomes(bloco: dict) -> list[str]:
    """Onde o bloco cita pessoas: tags, tema, título sugerido e texto da thumb."""
    return [*bloco.get("tags", []), bloco.get("tema", ""), bloco.get("titulo_sugerido", ""),
            bloco.get("texto_thumb", "")]


def personagens_do_bloco(bloco: dict, excluir: str = "", licencas: list[dict] | None = None) -> list[dict]:
    """Personagens do banco citados no bloco (tags, tema, título, texto da thumb), na ordem em
    que aparecem nas tags. `excluir` = nome do apresentador da live (não vira cena dele mesmo)."""
    licencas = ler_licencas() if licencas is None else licencas
    campos = campos_de_nomes(bloco)
    textos = [f" {normalizar(c)} " for c in campos if c]
    fora = f" {normalizar(excluir)} "
    # quem está na lista de grafias casa por ela (também a grafia errada das tags, e sem
    # confundir 'Lula' com 'Fábio Luís Lula da Silva')
    grafias = _grafias.carregar()
    conhecidos = {g["nome"] for g in grafias}
    citados = set(_grafias.citados(campos, excluir, grafias))
    achados = []
    for p in licencas:
        nomes = [normalizar(n) for n in [p["nome"], *p.get("apelidos", [])]]
        if p["nome"] in conhecidos:
            if p["nome"] not in citados:
                continue
            nomes += [normalizar(n) for n in _grafias.variantes(p["nome"], grafias)]
        elif any(f" {n} " in fora for n in nomes):
            continue
        pos = [i for i, t in enumerate(textos) for n in nomes if f" {n} " in t]
        if pos and (PERSONAGENS / p["arquivo"]).exists():
            achados.append((min(pos), p))
    return [p for _, p in sorted(achados, key=lambda x: x[0])]


# ── recorte sem fundo (rembg) ───────────────────────────────────────────────

def _sessao():
    global _SESSAO_REMBG
    if _SESSAO_REMBG is None:
        from rembg import new_session
        _SESSAO_REMBG = new_session("u2net_human_seg")
    return _SESSAO_REMBG


def mascara_da_pessoa(alpha, rosto: tuple | None):
    """Só o pedaço da máscara que contém o rosto (o rembg também pega quem aparece na tela
    de react ou na mesa). alpha: array uint8 0-255. Sem rosto: o maior pedaço."""
    import cv2
    import numpy as np
    binaria = (alpha > 127).astype(np.uint8)
    n, rotulos, stats, _ = cv2.connectedComponentsWithStats(binaria, 8)
    if n <= 1:
        return np.zeros_like(alpha)
    if rosto:
        x, y, w, h = rosto
        regiao = rotulos[y:y + h, x:x + w]
        contagem = np.bincount(regiao.ravel(), minlength=n)
        contagem[0] = 0
        escolhido = int(contagem.argmax()) if contagem.max() > 0 else 0
    else:
        escolhido = 0
    if not escolhido:
        escolhido = 1 + int(stats[1:, cv2.CC_STAT_AREA].argmax())
    return np.where(rotulos == escolhido, alpha, 0).astype(np.uint8)


def recortar(imagem: Image.Image, rosto: tuple | None) -> tuple[Image.Image, tuple | None] | None:
    """(RGBA recortado no contorno da pessoa, rosto em coordenadas do recorte) ou None se o
    rembg não achou ninguém."""
    import numpy as np
    from rembg import remove
    rgba = remove(imagem.convert("RGB"), session=_sessao())
    alpha = mascara_da_pessoa(np.array(rgba.split()[-1]), rosto)
    ys, xs = np.nonzero(alpha > 127)
    if len(xs) < 500:
        return None
    rgba.putalpha(Image.fromarray(alpha))
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    rosto_rel = (rosto[0] - x0, rosto[1] - y0, rosto[2], rosto[3]) if rosto else None
    return rgba.crop((x0, y0, x1, y1)), rosto_rel


def rosto_de(imagem: Image.Image) -> tuple | None:
    """Maior rosto (x, y, w, h) da imagem PIL, ou None."""
    import cv2
    import numpy as np
    return tr.analisar(cv2.cvtColor(np.array(imagem.convert("RGB")), cv2.COLOR_RGB2BGR))["rosto"]


# ── candidatos (frames do vídeo) ────────────────────────────────────────────

def _pil(frame_bgr) -> Image.Image:
    import cv2
    return Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))


def diferenca(a: Image.Image, b: Image.Image) -> float:
    """Diferença média (0-255) entre as duas imagens reduzidas a 32x18 em cinza."""
    import numpy as np
    pa = np.asarray(a.convert("L").resize((32, 18)), dtype=np.float32)
    pb = np.asarray(b.convert("L").resize((32, 18)), dtype=np.float32)
    return float(np.abs(pa - pb).mean())


def repetida(a: Image.Image, b: Image.Image) -> bool:
    return diferenca(a, b) < DIF_REPETIDA


def caixas_de_cena(overlays, largura: int, altura: int) -> list[list[int]]:
    """Caixas de react/tela (overlays da fila do 07) grandes o bastante pra ser cena. Nosso logo
    e bandeiras de canto ficam de fora."""
    return [list(o) for o in overlays
            if list(o) != list(tr.LOGO_CANAL)
            and (o[2] - o[0]) * (o[3] - o[1]) >= AREA_CENA_MIN * largura * altura]


def cenas_do_video(video: Path, fila: dict, estudio: list[Image.Image] = ()) -> list[dict]:
    """Cenas da tela compartilhada: a caixa de react em vários instantes + frames inteiros sem
    rosto detectado (nota 0 na fila do 07) que NÃO são o estúdio (`estudio` = frames do
    apresentador: frame sem rosto parecido com eles é ele virado de lado, não tela).
    Sem repetição, no máximo N_CENAS. [{imagem: PIL, origem: str}]"""
    cenas = []

    def juntar(img, origem):
        if len(cenas) < N_CENAS and not any(repetida(img, c["imagem"]) for c in cenas):
            cenas.append({"imagem": img, "origem": origem})

    dur = tr.duracao(video)
    frames = [(t, tr.ler_frame(video, t)) for t in tr.tempos(dur, AMOSTRAS_CENA)]
    frames = [(t, f) for t, f in frames if f is not None]
    if frames:
        alt, larg = frames[0][1].shape[:2]
        for caixa in caixas_de_cena(fila.get("overlays", []), larg, alt):
            for t, f in frames:
                x0, y0, x1, y1 = caixa
                juntar(_pil(f[y0:y1, x0:x1]), f"tela {video.name} @ {t:.0f}s")
    for c in fila.get("candidatos", []):
        if c["nota"] <= 0 and c.get("fonte") == "corte":
            f = tr.ler_frame(video.parent / c["video"], c["t"])
            if f is None:
                continue
            img = _pil(f)
            if not any(diferenca(img, e) < DIF_ESTUDIO for e in estudio):
                juntar(img, f"frame {c['video']} @ {c['t']:.0f}s")
    return cenas


def expressoes(fila: dict) -> list[dict]:
    """Até N_EXPRESSOES frames com rosto bom (sem mancha de overlay primeiro)."""
    com_rosto = [c for c in fila.get("candidatos", []) if c["nota"] > 0 and c.get("rosto")]
    com_rosto.sort(key=lambda c: (bool(c.get("mancha")), -c["nota"]))
    return com_rosto[:N_EXPRESSOES]


def rosto_ampliado(img: Image.Image, rosto: tuple) -> Image.Image:
    """Recorte de cabeça e ombros (pra julgar a expressão)."""
    x, y, w, h = rosto
    return img.crop((max(0, x - w), max(0, y - int(h * 0.8)),
                     min(img.width, x + 2 * w), min(img.height, y + int(h * 2.2))))


# ── escolha por visão (Haiku) ───────────────────────────────────────────────

SCHEMA_VISAO = {
    "type": "object",
    "properties": {
        "expressoes": {"type": "array", "items": {"type": "integer"}},
        "cena_assunto": {"type": "integer"},
        "assunto_descricao": {"type": "string"},
        "cena_contexto": {"type": "integer"},
        "contexto_descricao": {"type": "string"},
        "motivo": {"type": "string"},
    },
    "required": ["expressoes", "cena_assunto", "assunto_descricao", "cena_contexto",
                 "contexto_descricao", "motivo"],
    "additionalProperties": False,
}

SISTEMA_VISAO = """Você escolhe imagens para a thumbnail de um corte de live política \
(canal "Missão em Cortes"). Responda só o JSON pedido.

- expressoes: índices das imagens ROSTO, da mais expressiva para a menos (no máximo 3). \
PRIORIDADE MÁXIMA a emoção FORTE, legível em miniatura: surpresa/espanto (boca aberta, \
sobrancelha erguida), indignação, riso aberto, gesto de apontar. Rosto neutro, sério ou \
"falando normal" vai por último, mesmo que esteja mais nítido. Evite olhos fechados, boca \
torta no meio de uma sílaba, rosto de lado ou borrado.
- cena_assunto: índice da imagem CENA que melhor mostra a pessoa ou o assunto comentado \
(ex.: o político no vídeo, o post, a manchete). Se o pedido lista PESSOAS CITADAS, prefira \
a CENA em que o nome de uma delas aparece ESCRITO (legenda, púlpito, @ do post). -1 se \
nenhuma serve.
- cena_contexto: índice de OUTRA imagem CENA que dá o contexto (outro participante, notícia, \
gráfico, post, plateia do evento). -1 se nenhuma serve. Nunca o mesmo índice da cena_assunto.
- As imagens ROSTO são o apresentador da live. Uma CENA que mostra essa mesma pessoa ou o \
mesmo estúdio NUNCA serve (use -1). Também não serve: imagem quase preta, borrada, só \
logo/bandeira, tela de carregamento ou palco vazio. Prefira cena com rosto grande ou texto legível.
- assunto_descricao / contexto_descricao: o que a cena mostra, em poucas palavras. Só diga \
QUEM é a pessoa se o nome estiver ESCRITO na imagem (legenda, púlpito, @ do post); nunca \
reconheça alguém pelo rosto. Ex.: "homem de terno no púlpito escrito FLÁVIO BOLSONARO", \
"post do X com gráfico de pesquisa". "" quando a cena é -1.
- motivo: uma frase curta em português."""


def b64_jpeg(img: Image.Image, largura: int = LARGURA_LLM) -> str:
    img = img.convert("RGB")
    if img.width > largura:
        img = img.resize((largura, max(1, round(img.height * largura / img.width))))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=82)
    return base64.standard_b64encode(buf.getvalue()).decode()


def montar_conteudo_visao(rostos: list[Image.Image], cenas: list[Image.Image], tema: str,
                          pessoas: list[str] = ()) -> list[dict]:
    img = lambda im: {"type": "image",   # noqa: E731
                      "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_jpeg(im)}}
    texto = f"ASSUNTO DO CORTE: {tema}"
    if pessoas:
        texto += f"\nPESSOAS CITADAS: {', '.join(pessoas)}"
    conteudo = [{"type": "text", "text": texto}]
    for i, r in enumerate(rostos):
        conteudo += [{"type": "text", "text": f"ROSTO {i}:"}, img(r)]
    for i, c in enumerate(cenas):
        conteudo += [{"type": "text", "text": f"CENA {i}:"}, img(c)]
    if not cenas:
        conteudo.append({"type": "text", "text": "SEM IMAGENS CENA: use -1 nas duas."})
    return conteudo


def validar_escolha(r: dict, n_rostos: int, n_cenas: int) -> dict:
    """Índices fora da faixa viram -1/somem; assunto == contexto vira contexto -1."""
    exp = [i for i in r.get("expressoes", []) if 0 <= i < n_rostos]
    exp = list(dict.fromkeys(exp))[:3] or list(range(min(3, n_rostos)))
    a = r.get("cena_assunto", -1)
    a = a if 0 <= a < n_cenas else -1
    c = r.get("cena_contexto", -1)
    c = c if 0 <= c < n_cenas and c != a else -1
    return {"expressoes": exp, "cena_assunto": a,
            "assunto_descricao": r.get("assunto_descricao", "") if a >= 0 else "",
            "cena_contexto": c, "contexto_descricao": r.get("contexto_descricao", "") if c >= 0 else "",
            "motivo": r.get("motivo", "")}


def escolha_sem_llm(n_rostos: int, n_cenas: int) -> dict:
    """Ordem da fila do 07 (nota do rosto) e as 2 primeiras cenas."""
    return {"expressoes": list(range(min(3, n_rostos))), "cena_assunto": 0 if n_cenas else -1,
            "assunto_descricao": "", "cena_contexto": 1 if n_cenas > 1 else -1,
            "contexto_descricao": "", "motivo": "sem LLM: ordem da nota"}


def escolher(client, rostos: list[Image.Image], cenas: list[Image.Image], tema: str,
             pessoas: list[str] = ()):
    """(escolha validada ou None se recusou, resposta). Haiku, effort low."""
    resp = client.messages.create(
        model=MODELO_VISAO,
        max_tokens=4000,
        system=SISTEMA_VISAO,
        messages=[{"role": "user", "content": montar_conteudo_visao(rostos, cenas, tema, pessoas)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA_VISAO}},
    )
    if resp.stop_reason == "refusal":
        return None, resp
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if texto is None:
        raise json.JSONDecodeError(f"resposta sem texto (stop_reason={resp.stop_reason})", "", 0)
    return validar_escolha(json.loads(texto), len(rostos), len(cenas)), resp


def custo(resp) -> tuple[int, int, float]:
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    return tin, tout, tin / 1e6 * PRECO_IN + tout / 1e6 * PRECO_OUT


# ── layout ──────────────────────────────────────────────────────────────────

def enquadrar_cena(img: Image.Image, largura: int, altura: int, rosto: tuple | None,
                   foco_x: float = 0.5, fundo: tuple = PRETO) -> tuple[Image.Image, tuple | None]:
    """Cena cobrindo largura x altura. Com rosto: aproxima até ~ROSTO_CENA da altura e põe o
    rosto em (foco_x, 0.38). RGBA (personagem do banco) vai sobre `fundo`, ancorado embaixo.
    Devolve (imagem RGB, rosto em coordenadas do painel)."""
    if img.mode == "RGBA":
        base = Image.new("RGB", (largura, altura), fundo)
        esc = min(altura * 0.95 / img.height, largura * 1.1 / img.width)
        if rosto:
            esc = max(esc, altura * ROSTO_CENA / rosto[3])
        esc = min(esc, altura * 1.4 / img.height)
        p = img.resize((max(1, round(img.width * esc)), max(1, round(img.height * esc))), Image.LANCZOS)
        cx = (rosto[0] + rosto[2] / 2) * esc if rosto else p.width / 2
        x = int(min(max(largura * foco_x - cx, largura - p.width), 0)) if p.width > largura \
            else int(min(max(largura * foco_x - cx, 0), largura - p.width))
        y = altura - p.height
        if rosto and y + rosto[1] * esc < altura * 0.08:     # cabeça cortada em cima: desce
            y = int(altura * 0.08 - rosto[1] * esc)
        base.paste(p, (x, y), p)
        r = (int(x + rosto[0] * esc), int(y + rosto[1] * esc), int(rosto[2] * esc), int(rosto[3] * esc)) if rosto else None
        return base, r
    img = img.convert("RGB")
    cobre = max(largura / img.width, altura / img.height)
    esc = cobre
    if rosto:
        esc = min(cobre * ZOOM_CENA_MAX, max(cobre, altura * ROSTO_CENA / rosto[3]))
    nw, nh = round(img.width * esc), round(img.height * esc)
    cx = (rosto[0] + rosto[2] / 2) * esc if rosto else nw / 2
    cy = (rosto[1] + rosto[3] / 2) * esc if rosto else nh / 2
    esq = int(min(max(cx - largura * foco_x, 0), nw - largura))
    topo = int(min(max(cy - altura * 0.38, 0), nh - altura))
    painel = img.resize((nw, nh), Image.LANCZOS).crop((esq, topo, esq + largura, topo + altura))
    r = (int(rosto[0] * esc - esq), int(rosto[1] * esc - topo), int(rosto[2] * esc), int(rosto[3] * esc)) if rosto else None
    return painel, r


def colar_cartao(canvas: Image.Image, img: Image.Image, rosto: tuple | None) -> tuple | None:
    """Cena de contexto como cartão: fundo = ela mesma desfocada e escura cobrindo o painel 2;
    por cima, a imagem INTEIRA (post, manchete, tela) com borda branca, na faixa visível entre
    a divisa e o apresentador. Devolve o rosto em coordenadas da thumb."""
    img = img.convert("RGB")
    largura = LARGURA - DIVISA_X
    cobre = max(largura / img.width, ALTURA / img.height)
    fundo = img.resize((round(img.width * cobre), round(img.height * cobre)), Image.LANCZOS)
    esq, topo = (fundo.width - largura) // 2, (fundo.height - ALTURA) // 2
    fundo = fundo.crop((esq, topo, esq + largura, topo + ALTURA)).filter(ImageFilter.GaussianBlur(18))
    canvas.paste(Image.blend(fundo, Image.new("RGB", fundo.size, (0, 0, 0)), 0.45), (DIVISA_X, 0))
    x0, y0 = DIVISA_X + CARTAO_MARGEM, CARTAO_TOPO
    esc = min(CARTAO_W / img.width, CARTAO_H_MAX / img.height)
    w, h = round(img.width * esc), round(img.height * esc)
    sombra = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(sombra).rectangle([x0 + 10, y0 + 10, x0 + w + 16, y0 + h + 16], fill=150)
    canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), sombra.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(canvas).rectangle([x0 - 6, y0 - 6, x0 + w + 5, y0 + h + 5], fill=BRANCO)
    canvas.paste(img.resize((w, h), Image.LANCZOS), (x0, y0))
    if not rosto:
        return None
    return (int(x0 + rosto[0] * esc), int(y0 + rosto[1] * esc), int(rosto[2] * esc), int(rosto[3] * esc))


def desenhar_circulo(canvas: Image.Image, rosto: tuple) -> None:
    x, y, w, h = rosto
    m = 0.45
    caixa = [x - w * m, y - h * (m + 0.1), x + w * (1 + m), y + h * (1 + m)]
    draw = ImageDraw.Draw(canvas)
    draw.ellipse(caixa, outline=PRETO, width=18)
    draw.ellipse([caixa[0] + 4, caixa[1] + 4, caixa[2] - 4, caixa[3] - 4], outline=VERMELHO, width=10)


def desenhar_seta(canvas: Image.Image, rosto: tuple, limite_x: int) -> None:
    """Seta grossa vindo de cima, do lado com mais espaço (direita se couber antes do
    apresentador), até a lateral do rosto. De cima porque o texto ocupa a parte de baixo."""
    import math
    x, y, w, h = rosto
    lado = 1 if x + w + 240 < limite_x else -1
    alvo = (x + w * (0.95 if lado > 0 else 0.05), y + h * 0.45)
    origem = (alvo[0] + lado * 210, max(30, alvo[1] - 170))
    ang = math.atan2(alvo[1] - origem[1], alvo[0] - origem[0])
    ponta, larg_ponta, corpo = 70, 44, 20
    base = (alvo[0] - ponta * math.cos(ang), alvo[1] - ponta * math.sin(ang))
    nx, ny = -math.sin(ang), math.cos(ang)
    poligono = [
        (origem[0] + nx * corpo, origem[1] + ny * corpo), (base[0] + nx * corpo, base[1] + ny * corpo),
        (base[0] + nx * larg_ponta, base[1] + ny * larg_ponta), alvo,
        (base[0] - nx * larg_ponta, base[1] - ny * larg_ponta), (base[0] - nx * corpo, base[1] - ny * corpo),
        (origem[0] - nx * corpo, origem[1] - ny * corpo),
    ]
    draw = ImageDraw.Draw(canvas)
    draw.polygon(poligono, fill=VERMELHO, outline=PRETO, width=6)


def colar_apresentador(canvas: Image.Image, recorte: Image.Image, rosto: tuple | None) -> None:
    """Recorte com contorno branco e sombra, rosto em (APRES_X, APRES_Y) com ~ROSTO_APRES da
    altura; se o corpo terminava na borda de baixo do frame, continua até a borda da thumb."""
    if rosto:
        esc = min(ZOOM_APRES_MAX, ALTURA * ROSTO_APRES / rosto[3])
        cx, cy = (rosto[0] + rosto[2] / 2) * esc, (rosto[1] + rosto[3] / 2) * esc
    else:
        esc = ALTURA * 0.95 / recorte.height
        cx, cy = recorte.width * esc / 2, recorte.height * esc * 0.3
    p = recorte.resize((max(1, round(recorte.width * esc)), max(1, round(recorte.height * esc))), Image.LANCZOS)
    x = int(LARGURA * APRES_X - cx)
    y = int(ALTURA * APRES_Y - cy)
    if y + p.height < ALTURA:                 # tronco termina antes do fim: encosta embaixo
        y = ALTURA - p.height
    alpha = p.split()[-1]
    borda = alpha.filter(ImageFilter.MaxFilter(2 * CONTORNO_APRES + 1))
    sombra = borda.filter(ImageFilter.GaussianBlur(14))
    camada = Image.new("L", canvas.size, 0)
    camada.paste(sombra, (x + 10, y + 10))
    canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), ImageChops.multiply(camada, Image.new("L", canvas.size, 170)))
    canvas.paste(Image.new("RGB", p.size, BRANCO), (x, y), borda)
    canvas.paste(p, (x, y), p)


def gradiente_baixo(canvas: Image.Image, altura_fade: int = 330, alpha_max: int = 210) -> None:
    mask = Image.new("L", (1, altura_fade))
    for i in range(altura_fade):
        mask.putpixel((0, i), int(alpha_max * (i / altura_fade) ** 1.6))
    mask = mask.resize((LARGURA, altura_fade))
    canvas.paste(Image.new("RGB", (LARGURA, altura_fade), (0, 0, 0)), (0, ALTURA - altura_fade), mask)


def marca(canvas: Image.Image) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.text((22, 14), "MISSÃO", font=fonte(34), fill=AMARELO, stroke_width=3, stroke_fill=PRETO)
    draw.text((22, 54), "EM CORTES", font=fonte(20), fill=BRANCO, stroke_width=2, stroke_fill=PRETO)


def compor(cena1: Image.Image, rosto1: tuple | None, cena2: Image.Image, rosto2: tuple | None,
           recorte: Image.Image, rosto_recorte: tuple | None, linhas: list[str],
           marcador: str = "circulo") -> Image.Image:
    """Monta a thumb. cena1 = assunto (esq.), cena2 = contexto (dir., atrás do apresentador).
    marcador: 'circulo' ou 'seta' no rosto-chave (o da cena 1; senão o da cena 2)."""
    canvas = Image.new("RGB", (LARGURA, ALTURA), PRETO)
    p1, r1 = enquadrar_cena(cena1, DIVISA_X, ALTURA, rosto1, 0.5)
    canvas.paste(p1, (0, 0))
    if cena2.mode == "RGBA":                  # personagem do banco: recorte inteiro, visível
        p2, r2 = enquadrar_cena(cena2, LARGURA - DIVISA_X, ALTURA, rosto2, FOCO_CENA2, fundo=(28, 28, 32))
        canvas.paste(p2, (DIVISA_X, 0))
    else:                                     # tela da live: cartão inteiro sobre ela desfocada
        r2 = colar_cartao(canvas, cena2, rosto2)
        r2 = (r2[0] - DIVISA_X, r2[1], r2[2], r2[3]) if r2 else None
    # escurece a cena 2 atrás do apresentador pra ele saltar
    sombra = Image.new("L", (LARGURA - DIVISA_X, 1))
    for i in range(sombra.width):
        sombra.putpixel((i, 0), int(150 * max(0.0, (i / sombra.width - 0.6) / 0.4)))
    canvas.paste(Image.new("RGB", (LARGURA - DIVISA_X, ALTURA), (0, 0, 0)), (DIVISA_X, 0),
                 sombra.resize((LARGURA - DIVISA_X, ALTURA)))
    ImageDraw.Draw(canvas).rectangle([DIVISA_X - 4, 0, DIVISA_X + 4, ALTURA], fill=PRETO)
    gradiente_baixo(canvas)
    alvo = r1 if r1 else ((r2[0] + DIVISA_X, r2[1], r2[2], r2[3]) if r2 else None)
    if alvo:
        if marcador == "seta":
            desenhar_seta(canvas, alvo, int(LARGURA * APRES_X) - 160)
        else:
            desenhar_circulo(canvas, alvo)
    colar_apresentador(canvas, recorte, rosto_recorte)
    desenhar_linhas(canvas, linhas)
    marca(canvas)
    return canvas
