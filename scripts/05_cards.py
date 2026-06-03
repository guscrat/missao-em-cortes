"""Gera card de contexto (PNG + MP4 5s) pra cada bloco."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import json
import subprocess
from PIL import Image, ImageDraw, ImageFont
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent

input_arg = sys.argv[1] if len(sys.argv) > 1 else "live_teste"
PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
BLOCOS_JSON = PASTA / "blocos.json"
OUT_DIR = PASTA / "cards"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Tenta Anton primeiro; fallback pra Impact (Windows)
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

# Identidade visual
PRETO = (10, 10, 10)
AMARELO = (245, 197, 24)
BRANCO = (255, 255, 255)

# Mesma resolução dos cortes (importante pro concat depois)
LARGURA, ALTURA = 1280, 720

def quebrar_texto(texto, max_chars=18):
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

def gerar_card(bloco, output_png):
    img = Image.new('RGB', (LARGURA, ALTURA), PRETO)
    draw = ImageDraw.Draw(img)
    
    fonte_tema = get_font(100)
    fonte_marca = get_font(28)
    fonte_badge = get_font(32)
    
    # Badge "MISSÃO 14" canto superior esquerdo
    draw.rectangle([50, 50, 280, 105], fill=AMARELO)
    draw.text((70, 58), "MISSÃO 14", font=fonte_badge, fill=PRETO)
    
    # Marca d'água "MISSÃO EM CORTES" canto inferior direito
    marca = "MISSÃO EM CORTES"
    bbox = draw.textbbox((0, 0), marca, font=fonte_marca)
    draw.text(
        (LARGURA - (bbox[2] - bbox[0]) - 50, ALTURA - 60),
        marca, font=fonte_marca, fill=AMARELO
    )
    
    # Tema principal (CAPS, centralizado)
    linhas = quebrar_texto(bloco["tema"].upper(), max_chars=18)
    line_h = 120
    total_h = len(linhas) * line_h
    y0 = (ALTURA - total_h) // 2 - 50
    
    for i, linha in enumerate(linhas):
        bbox = draw.textbbox((0, 0), linha, font=fonte_tema)
        x = (LARGURA - (bbox[2] - bbox[0])) // 2
        cor = AMARELO if i == 0 else BRANCO
        draw.text((x, y0 + i * line_h), linha, font=fonte_tema, fill=cor)

    img.save(output_png)
    print(f"  OK PNG: {output_png.name}")

def png_para_mp4(png_path, mp4_path, duracao=3):
    """Converte PNG estático em MP4 no formato canônico do pipeline (pro concat -c copy)."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(png_path),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duracao),
        "-vf", "setsar=1,fps=30",
        "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23",
        "-b:v", "0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-shortest", "-loglevel", "warning",
        str(mp4_path)
    ]
    subprocess.run(cmd, check=True)
    print(f"  OK MP4: {mp4_path.name}")

# Main
with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

print(f"Gerando {len(data['blocos'])} cards...\n")
for b in data["blocos"]:
    nome_base = f"card_{b['id']:02d}"
    print(f"[Bloco {b['id']}] {b['tema']}")
    gerar_card(b, OUT_DIR / f"{nome_base}.png")
    png_para_mp4(OUT_DIR / f"{nome_base}.png", OUT_DIR / f"{nome_base}.mp4")
    print()

print(f"OK Cards salvos em {OUT_DIR}")
