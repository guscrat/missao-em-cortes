"""Gera thumb (PNG 1280x720) pra cada bloco.

Layout:
  - Frame do speaker (o de melhor rosto) preenchendo a thumb inteira (cover), com o rosto
    grande (~40% da altura) no terco direito
  - Logo 'MISSAO EM CORTES' no topo esquerdo
  - Titulo grande no canto inferior esquerdo (amarelo + branco), sobre um degrade escuro
    que vem da esquerda e para antes do rosto
  - Overlays da fonte (quadro de transmissao, nosso logo do 04) ficam fora do recorte; o
    que nao der pra tirar some no degrade escuro (overlays em thumbs/candidatos_NN.json)

Uso: uv run py scripts/07_thumb.py <stem>
     uv run py scripts/07_thumb.py <stem> --bloco=N            # so o bloco N (a/b/c)
     uv run py scripts/07_thumb.py <stem> --bloco=N --t=MM:SS  # frame manual de um timestamp
     uv run py scripts/07_thumb.py <stem> --bloco=N --t=4:12 --fonte=cold
     uv run py scripts/07_thumb.py <stem> --bloco=N --titulo="TEXTO CURTO"  # texto da thumb na mao
     uv run py scripts/07_thumb.py <stem> --bloco=N --variante=b  # so a variante b (usado pelo editor)
     uv run py scripts/07_thumb.py <stem> --bloco=N --proximo     # proximo frame da fila em thumb_NN_a (usado pelo revisor)

Frames pelo rosto (_thumb_rosto.py, OpenCV, gratis): amostra o cold open e o corte, da nota
pelo rosto (tamanho, luz, nitidez) e as variantes a/b/c sao os 3 melhores. O recorte poe o
rosto inteiro no terco direito e foge dos overlays. A fila de frames fica em
thumbs/candidatos_NN.json: o --proximo pega o seguinte (sai com codigo 2 quando nao sobra
frame com rosto).

Texto da thumb: usa o campo curto texto_thumb do blocos.json (2-5 palavras, gerado
pelo LLM); na falta dele, cai pro tema. NUNCA usa o titulo_sugerido (titulo de
YouTube, frase longa que estourava a thumb). --titulo= sobrescreve pra um bloco.

Modo manual (--t): pra lives com tela compartilhada, onde os frames automaticos
(25/50/75% do cold open) caem na tela em vez do speaker. Voce abre o corte, acha
um segundo com o speaker na camera e passa o timestamp. Puxa do corte completo
por padrao (mais momentos na camera); --fonte=cold puxa do cold open.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import json
import subprocess
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter
from _paths import achar_pasta, stem_de
import _thumb_rosto as tr

ROOT = Path(__file__).parent.parent

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]
input_arg = args[0] if args else "live_teste"

# Override manual (ver docstring): --bloco=N [--t=MM:SS] [--fonte=corte|cold]
def _parse_t(v):
    """Aceita segundos ('252') ou MM:SS / HH:MM:SS ('4:12')."""
    seg = 0.0
    for p in v.split(":"):
        seg = seg * 60 + float(p)
    return seg

bloco_manual = None
t_manual = None
fonte_manual = "corte"
TITULO_OVERRIDE = None
variante = None
proximo = "--proximo" in flags
for f in flags:
    if f.startswith("--bloco="):
        bloco_manual = int(f.split("=", 1)[1])
    elif f.startswith("--t="):
        t_manual = _parse_t(f.split("=", 1)[1])
    elif f.startswith("--fonte="):
        fonte_manual = f.split("=", 1)[1].strip()
    elif f.startswith("--titulo="):
        TITULO_OVERRIDE = f.split("=", 1)[1]
    elif f.startswith("--variante="):
        variante = f.split("=", 1)[1].strip()

if variante is not None and (bloco_manual is None or variante not in ("a", "b", "c")):
    sys.exit("[!] --variante=a|b|c exige --bloco=N (refaz só a thumb escolhida, ex: pelo editor)")
if proximo and bloco_manual is None:
    sys.exit("[!] --proximo exige --bloco=N (troca o frame da thumb escolhida de um bloco)")
if TITULO_OVERRIDE is not None and bloco_manual is None:
    sys.exit("[!] --titulo exige --bloco=N (o texto se aplica a um bloco so)")

PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
BLOCOS_JSON = PASTA / "blocos.json"
CORTES_DIR = PASTA / "cortes"
OUT_DIR = PASTA / "thumbs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FONT_PATHS = [
    ROOT / "assets" / "fonts" / "Anton-Regular.ttf",
    Path("C:/Windows/Fonts/impact.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
]

def get_font(size):
    for fp in FONT_PATHS:
        if fp.exists():
            return ImageFont.truetype(str(fp), size)
    return ImageFont.load_default()

PRETO = (10, 10, 10)
AMARELO = (245, 197, 24)
BRANCO = (255, 255, 255)

LARGURA, ALTURA = tr.LARGURA, tr.ALTURA
ESCURO_MAX = 255    # opacidade (0-255) do degrade do texto onde ele e "solido" (em cima de overlay)
ESCURO_TEXTO = 190  # opacidade na borda esquerda quando nao ha overlay (so contraste do texto)
FADE_PX = 200       # largura da transicao do degrade ate ficar transparente
GAP_SUB = 0.35      # espaco entre a manchete e o subtitulo, em fracao da fonte da manchete
LOGO_04 = ROOT / "assets" / "logoCanal.png"   # se existe, o 04 queimou ele no canto sup.-dir.

def extrair_frame(video, segundo, output_png):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{segundo:.2f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", "-loglevel", "error", str(output_png)],
        check=True
    )

def encontrar_cold_open(bloco_id):
    """Procura o cold_NN_*.mp4 do bloco."""
    matches = list(CORTES_DIR.glob(f"cold_{bloco_id:02d}_*.mp4"))
    if matches:
        return matches[0]
    # fallback: corte completo
    return encontrar_corte(bloco_id)

def encontrar_corte(bloco_id):
    """Corte completo do bloco, ignorando os _polido (timestamps deslocados pelo jump cut)."""
    matches = [m for m in CORTES_DIR.glob(f"corte_{bloco_id:02d}_*.mp4")
               if "_polido" not in m.stem]
    return matches[0] if matches else None

def quebrar_texto(texto, max_chars=14):
    palavras = texto.split()
    linhas, linha = [], []
    for palavra in palavras:
        if len(' '.join(linha + [palavra])) <= max_chars:
            linha.append(palavra)
        else:
            if linha:
                linhas.append(' '.join(linha))
            linha = [palavra]
    if linha:
        linhas.append(' '.join(linha))
    return linhas

def titulo_curto(bloco):
    """Texto da thumb. Prefere o campo curto texto_thumb (2-5 palavras, do LLM);
    cai pro tema (3-6 palavras). NUNCA usa titulo_sugerido — esse e o titulo de
    YouTube (frase longa), que estoura a thumb e tem que ser truncado. --titulo=
    sobrescreve tudo (override manual)."""
    if TITULO_OVERRIDE is not None:
        return TITULO_OVERRIDE.strip().upper()
    t = bloco.get("texto_thumb") or bloco.get("tema", "")
    return t.split("|")[0].strip().upper()

def colar_frame(canvas, frame_path, rosto=None, overlays=()):
    """Cola o frame cobrindo a thumb inteira, rosto no terco direito. Overlay que sobrou no
    recorte: se esta a esquerda do rosto, o degrade do texto fica solido ate depois dele;
    senao, vira uma mancha escura de borda suave."""
    frame = Image.open(frame_path).convert("RGB")
    pos = tr.posicionar(frame.width, frame.height, rosto, overlays)
    new_w, new_h = round(frame.width * pos["escala"]), round(frame.height * pos["escala"])
    frame = frame.resize((new_w, new_h), Image.LANCZOS)
    left, top = pos["esq"], pos["topo"]
    canvas.paste(frame.crop((left, top, left + LARGURA, top + ALTURA)), (0, 0))

    rosto_x0 = pos["rosto_x0"]
    a_esquerda = [m for m in pos["mascaras"] if m[2] <= rosto_x0]
    outras = [m for m in pos["mascaras"] if m[2] > rosto_x0]
    solido = max((m[2] for m in a_esquerda), default=0)
    escuro = Image.new("L", (LARGURA, ALTURA), 0)
    edraw = ImageDraw.Draw(escuro)
    # degrade do texto: solido ate o fim do overlay (se houver), some antes do rosto
    if solido:
        fim, alpha0 = max(solido + 40, min(rosto_x0 - 10, solido + FADE_PX)), ESCURO_MAX
    else:
        fim, alpha0 = max(40, rosto_x0 - 10), ESCURO_TEXTO
    for x in range(min(fim, LARGURA)):
        a = alpha0 if x < solido else int(alpha0 * (1 - (x - solido) / (fim - solido)) ** 1.4)
        edraw.line([(x, 0), (x, ALTURA)], fill=a)
    if outras:
        manchas = Image.new("L", (LARGURA, ALTURA), 0)
        mdraw = ImageDraw.Draw(manchas)
        for x0, y0, x1, y1 in outras:
            mdraw.rectangle([x0 - 12, y0 - 12, x1 + 12, y1 + 12], fill=ESCURO_MAX)
        escuro = ImageChops.lighter(escuro, manchas.filter(ImageFilter.GaussianBlur(14)))
    canvas.paste(Image.new("RGB", (LARGURA, ALTURA), PRETO), (0, 0), escuro)

def desenhar_texto_com_sombra(draw, pos, texto, fonte, cor, sombra=PRETO, offset=4):
    x, y = pos
    draw.text((x + offset, y + offset), texto, font=fonte, fill=sombra)
    draw.text((x, y), texto, font=fonte, fill=cor)

def layout_titulo(titulo):
    """Escolhe fonte/quebra com base no tamanho do titulo (cabe ate 4 linhas)."""
    # Tenta tamanhos do maior pro menor ate o titulo caber em <=4 linhas
    candidatos = [
        (96, 14, 100),  # fonte, max_chars, line_h
        (84, 16, 88),
        (74, 18, 78),
        (64, 21, 68),
    ]
    for fonte_size, max_chars, line_h in candidatos:
        linhas = quebrar_texto(titulo, max_chars=max_chars)
        if len(linhas) <= 4:
            return linhas, fonte_size, line_h
    # Nao coube nem na menor fonte: texto longo demais pra thumb. Em vez de cortar
    # no meio da frase em silencio (gera incoerencia tipo "...ZEMA E E"), avisa alto
    # pra voce encurtar com --titulo= ou ajustar o texto_thumb no blocos.json.
    linhas_todas = quebrar_texto(titulo, max_chars=21)
    if len(linhas_todas) > 4:
        print(f"  AVISO: texto da thumb longo demais ({len(linhas_todas)} linhas, truncado em 4) — "
              f"use --titulo=\"texto curto e impactante\" ou edite texto_thumb no blocos.json")
    return linhas_todas[:4], 64, 68

def aplicar_gradiente_inferior(canvas, altura_fade=420, alpha_max=235):
    """Escurece a parte inferior do canvas pra texto ficar legivel."""
    overlay = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    y_inicio = ALTURA - altura_fade
    for i in range(altura_fade):
        # Curva quadratica: comeca quase invisivel, fica forte embaixo
        t = i / altura_fade
        alpha = int(alpha_max * (t ** 1.8))
        odraw.line([(0, y_inicio + i), (LARGURA, y_inicio + i)], fill=(0, 0, 0, alpha))
    base = canvas.convert("RGBA")
    base.alpha_composite(overlay)
    return base.convert("RGB")

def gerar_thumb(bloco, output_png, frame_png=None, rosto=None, overlays=()):
    canvas = Image.new("RGB", (LARGURA, ALTURA), PRETO)

    if frame_png and frame_png.exists():
        colar_frame(canvas, frame_png, rosto, overlays)

    # Gradiente escuro embaixo pra contraste do texto sem cobrir o rosto
    canvas = aplicar_gradiente_inferior(canvas)

    draw = ImageDraw.Draw(canvas)
    fonte_logo_y = get_font(38)
    fonte_logo_w = get_font(22)

    # Logo "MISSAO / EM CORTES" topo esquerdo
    desenhar_texto_com_sombra(draw, (40, 25), "MISSÃO", fonte_logo_y, AMARELO)
    desenhar_texto_com_sombra(draw, (40, 70), "EM CORTES", fonte_logo_w, BRANCO, offset=2)

    # Titulo principal (amarelo) - layout adaptativo
    titulo = titulo_curto(bloco)
    linhas, fonte_size, line_h = layout_titulo(titulo)
    fonte_titulo = get_font(fonte_size)
    fonte_sub = get_font(int(fonte_size * 0.42))

    sub = bloco["tema"].split(":")[-1].strip().upper() if ":" in bloco["tema"] else ""
    mostrar_sub = bool(sub) and len(sub) <= 40
    gap = int(fonte_size * GAP_SUB)
    sub_h = gap + int(fonte_size * 0.42) + 10 if mostrar_sub else 0

    total_h = len(linhas) * line_h + sub_h
    y0 = ALTURA - total_h - 50

    for i, linha in enumerate(linhas):
        desenhar_texto_com_sombra(draw, (40, y0 + i * line_h), linha, fonte_titulo, AMARELO, offset=5)

    if mostrar_sub:
        desenhar_texto_com_sombra(draw, (40, y0 + len(linhas) * line_h + gap), sub, fonte_sub, BRANCO, offset=3)

    canvas.save(output_png)
    print(f"  OK thumb: {output_png.name}")


def overlays_do_bloco(bid, rostos):
    """Overlays a evitar no bloco: os da fonte (detectados no corte) + nosso logo do 04."""
    achados = tr.detectar_overlays(encontrar_corte(bid) or encontrar_cold_open(bid), rostos)
    if LOGO_04.exists():
        achados.append(list(tr.LOGO_CANAL))
    if achados:
        print(f"  {len(achados)} overlay(s) a evitar: {achados}")
    return achados


with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

# ── Modo manual: uma thumb a partir de um timestamp escolhido ────────────────
if t_manual is not None:
    if bloco_manual is None:
        sys.exit("[!] --t exige --bloco=N (qual bloco gerar)")
    b = next((x for x in data["blocos"] if x["id"] == bloco_manual), None)
    if b is None:
        sys.exit(f"[!] bloco {bloco_manual} nao existe no blocos.json")
    video = encontrar_cold_open(bloco_manual) if fonte_manual == "cold" else encontrar_corte(bloco_manual)
    if not video:
        sys.exit(f"[!] video do bloco {bloco_manual} (fonte={fonte_manual}) nao encontrado em {CORTES_DIR}")
    print(f"[Bloco {bloco_manual}] {b['tema']}")
    print(f"  Frame manual: {video.name} @ {t_manual:.1f}s")
    tmp = OUT_DIR / f"_frame_{bloco_manual:02d}_manual.png"
    extrair_frame(video, t_manual, tmp)
    out = OUT_DIR / f"thumb_{bloco_manual:02d}_manual.png"
    import cv2
    rosto = tr.analisar(cv2.imread(str(tmp)))["rosto"]
    gerar_thumb(b, out, tmp, rosto, overlays_do_bloco(bloco_manual, [rosto] if rosto else []))
    tmp.unlink(missing_ok=True)
    print(f"\nOK thumb manual salva: {out.name}")
    sys.exit(0)

LETRAS = ("a", "b", "c")


def caminho_fila(bid):
    return OUT_DIR / f"candidatos_{bid:02d}.json"


def ler_fila(bid):
    try:
        return json.loads(caminho_fila(bid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def gravar_fila(bid, fila):
    caminho_fila(bid).write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")


def nova_fila(bid):
    """Ranqueia os frames do bloco pelo rosto (cold open + corte) e grava a fila."""
    cands = tr.ranquear(encontrar_cold_open(bid), encontrar_corte(bid))
    com_rosto = sum(1 for c in cands if c["nota"] > 0)
    print(f"  {len(cands)} frame(s) analisado(s), {com_rosto} com rosto")
    overlays = overlays_do_bloco(bid, rostos_da_fila(cands))
    cands = tr.rebaixar_manchas(cands, overlays)
    return {"candidatos": cands, "variantes": {}, "proximo": min(len(LETRAS), len(cands)),
            "overlays": overlays}


def rostos_da_fila(cands):
    return [c["rosto"] for c in cands if c.get("rosto")]


def garantir_overlays(bid, fila):
    """Fila de antes dos overlays (thumb antiga): detecta agora e guarda junto."""
    if "overlays" not in fila:
        fila["overlays"] = overlays_do_bloco(bid, rostos_da_fila(fila["candidatos"]))
    return fila


def thumb_do_candidato(b, letra, cand, overlays):
    tmp = OUT_DIR / f"_frame_{b['id']:02d}_{letra}.png"
    extrair_frame(CORTES_DIR / cand["video"], cand["t"], tmp)
    gerar_thumb(b, OUT_DIR / f"thumb_{b['id']:02d}_{letra}.png", tmp, cand.get("rosto"), overlays)
    tmp.unlink(missing_ok=True)
    print(f"    {letra}: {cand['fonte']} @ {cand['t']:.1f}s · nota {cand['nota']:.4f}"
          + ("" if cand.get("rosto") else " (sem rosto)"))


blocos_iter = [x for x in data["blocos"] if x["id"] == bloco_manual] if bloco_manual is not None else data["blocos"]
if bloco_manual is not None and not blocos_iter:
    sys.exit(f"[!] bloco {bloco_manual} nao existe no blocos.json")

# ── --proximo: troca o frame da thumb escolhida (a) pelo seguinte da fila ────
if proximo:
    b = blocos_iter[0]
    fila = ler_fila(b["id"]) or {**nova_fila(b["id"]), "proximo": 0}
    i = fila["proximo"]
    if i >= len(fila["candidatos"]) or fila["candidatos"][i]["nota"] <= 0:
        print(f"[!] bloco {b['id']}: nao sobrou frame com rosto na fila ({i} usado(s))")
        sys.exit(2)
    print(f"[Bloco {b['id']}] frame {i + 1} da fila")
    garantir_overlays(b["id"], fila)
    thumb_do_candidato(b, "a", fila["candidatos"][i], fila["overlays"])
    fila["variantes"]["a"] = i
    fila["proximo"] = i + 1
    gravar_fila(b["id"], fila)
    sys.exit(0)

print(f"Gerando thumbs ({'variante ' + variante if variante else 'a/b/c'}) em {OUT_DIR}\n")
for b in blocos_iter:
    print(f"[Bloco {b['id']}] {b['tema']}")
    fila = ler_fila(b["id"]) if variante else None   # editor: mesmo frame, texto novo
    if fila is None:
        fila = nova_fila(b["id"])
    if not fila["candidatos"]:
        print(f"  AVISO: cold open/corte nao encontrado, gerando sem frame")
        gerar_thumb(b, OUT_DIR / f"thumb_{b['id']:02d}.png")
        print()
        continue
    garantir_overlays(b["id"], fila)
    for k, letra in enumerate(LETRAS):
        if variante and letra != variante:
            continue
        i = fila["variantes"].get(letra, k)
        if i >= len(fila["candidatos"]):
            continue
        thumb_do_candidato(b, letra, fila["candidatos"][i], fila["overlays"])
        fila["variantes"][letra] = i
    gravar_fila(b["id"], fila)
    print()

print(f"OK Thumbs salvas em {OUT_DIR}")
print("Escolha a melhor variante (a/b/c).")
