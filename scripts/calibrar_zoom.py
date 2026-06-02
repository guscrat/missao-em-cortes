"""Calibração VISUAL do zoom anti-overlay (ferramenta de dev, off-pipeline).

Renderiza, pra cada nível de zoom, um preview lado-a-lado:
  ESQUERDA  = frame original com a região que será MANTIDA marcada em verde
              (o resto, que vai ser cortado, escurecido)
  DIREITA   = resultado final (o que o espectador vê), já em 1280x720

Objetivo: você bate o olho, escolhe o zoom/pan que tira as logos mantendo o
máximo de conteúdo, e a gente fixa esses parâmetros como padrão no 04_cortar.

Uso:
  uv run py scripts/calibrar_zoom.py [video] [--ts=600] [--zoom=1.15,1.22,1.30]
                                     [--fx=0.0] [--fy=0.4]

  fx = pan horizontal do recorte: 0.0 = colado na ESQUERDA (descarta a direita),
       0.5 = centro, 1.0 = colado na direita
  fy = pan vertical: 0.0 = colado no TOPO, 1.0 = colado na base

Saídas em outputs/_calibracao/zoom_preview_a/b/c.png
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "outputs" / "_calibracao"
OUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080          # resolução da fonte
ALVO_W, ALVO_H = 1280, 720  # resolução final do pipeline

# Regiões aproximadas dos overlays (fração de W,H) só pra marcar no preview.
# Ajuste se as coordenadas estiverem off — é só visual, não afeta o corte.
OVERLAYS = {
    "contador (topo-dir)": (0.77, 0.00, 1.00, 0.23),
    "QR (base-dir)":       (0.83, 0.78, 1.00, 1.00),
    "logo MBL (topo-esq)": (0.00, 0.00, 0.32, 0.40),
}


def parse_args():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a.split("=", 1)[0][2:]: a.split("=", 1)[1]
             for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    video = Path(args[0]) if args else (ROOT / "inputs" / "renan_live2.mp4")
    ts = float(flags.get("ts", 600))
    zooms = [float(z) for z in flags.get("zoom", "1.15,1.22,1.30").split(",")]
    fx = float(flags.get("fx", 0.0))
    fy = float(flags.get("fy", 0.4))
    salvar = flags.get("salvar")  # stem pra gravar o crop em config/zoom.json
    return video, ts, zooms, fx, fy, salvar


def get_font(size):
    for fp in [ROOT / "assets" / "fonts" / "Anton-Regular.ttf",
               Path("C:/Windows/Fonts/arialbd.ttf")]:
        if fp.exists():
            return ImageFont.truetype(str(fp), size)
    return ImageFont.load_default()


def crop_rect(zoom, fx, fy):
    """Retângulo de recorte (16:9) pro zoom/pan dados. Retorna (cw,ch,cx,cy)."""
    cw = int(W / zoom); cw -= cw % 2
    ch = int(H / zoom); ch -= ch % 2
    cx = round((W - cw) * fx)
    cy = round((H - ch) * fy)
    return cw, ch, cx, cy


def extrair_frame(video, ts):
    orig = OUT_DIR / "_frame_orig.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(ts), "-i", str(video),
         "-frames:v", "1", "-q:v", "2", "-loglevel", "error", str(orig)],
        check=True,
    )
    return Image.open(orig).convert("RGB")


def render_preview(orig, zoom, fx, fy, saida):
    cw, ch, cx, cy = crop_rect(zoom, fx, fy)
    painel_w = 640  # cada metade do preview

    # --- ANTES: original escurecido fora do recorte + retângulo verde ---
    antes = orig.copy()
    escuro = Image.new("RGB", antes.size, (0, 0, 0))
    mask = Image.new("L", antes.size, 160)  # escurece tudo
    dentro = Image.new("L", (cw, ch), 0)     # menos a área mantida
    mask.paste(dentro, (cx, cy))
    antes = Image.composite(escuro, antes, mask)
    d = ImageDraw.Draw(antes)
    # marca os overlays-alvo em vermelho tracejado (referência)
    for nome, (x0, y0, x1, y1) in OVERLAYS.items():
        d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=(255, 60, 60), width=4)
    d.rectangle([cx, cy, cx + cw, cy + ch], outline=(40, 230, 90), width=8)
    antes = antes.resize((painel_w, int(painel_w * H / W)))

    # --- DEPOIS: recorte escalado pro tamanho final ---
    depois = orig.crop((cx, cy, cx + cw, cy + ch)).resize((ALVO_W, ALVO_H))
    depois = depois.resize((painel_w, int(painel_w * ALVO_H / ALVO_W)))

    # --- compõe lado a lado com legenda ---
    barra = 70
    ph = max(antes.height, depois.height)
    canvas = Image.new("RGB", (painel_w * 2, ph + barra), (15, 15, 15))
    canvas.paste(antes, (0, barra))
    canvas.paste(depois, (painel_w, barra))
    d = ImageDraw.Draw(canvas)
    fonte = get_font(26)
    fonte_p = get_font(20)
    keep_pct = (cw * ch) / (W * H) * 100
    d.text((12, 10), f"ANTES  (verde = mantido)", font=fonte_p, fill=(40, 230, 90))
    d.text((painel_w + 12, 10), f"DEPOIS  (1280x720)", font=fonte_p, fill=(245, 197, 24))
    d.text((12, 38), f"zoom={zoom:g}  fx={fx:g}  fy={fy:g}  "
                     f"crop={cw}x{ch}+{cx}+{cy}  (mantém {keep_pct:.0f}% do quadro)",
           font=fonte_p, fill=(230, 230, 230))
    canvas.save(saida)
    return cw, ch, cx, cy, keep_pct


def salvar_crop(stem, cw, ch, cx, cy):
    cfg_path = ROOT / "config" / "zoom.json"
    cfg = {}
    if cfg_path.exists():
        with cfg_path.open(encoding="utf-8") as f:
            cfg = json.load(f)
    cfg[stem] = f"{cw}:{ch}:{cx}:{cy}"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSalvo em config/zoom.json: \"{stem}\": \"{cw}:{ch}:{cx}:{cy}\"")


def main():
    video, ts, zooms, fx, fy, salvar = parse_args()
    if not video.exists():
        print(f"[!] Vídeo não encontrado: {video}")
        sys.exit(1)
    print(f"Fonte: {video.name} @ {ts:.0f}s   pan fx={fx:g} fy={fy:g}\n")
    orig = extrair_frame(video, ts)

    letras = "abcdefghij"
    for i, zoom in enumerate(zooms):
        saida = OUT_DIR / f"zoom_preview_{letras[i]}.png"
        cw, ch, cx, cy, keep = render_preview(orig, zoom, fx, fy, saida)
        print(f"[{letras[i]}] zoom={zoom:g}  crop={cw}:{ch}:{cx}:{cy}  "
              f"mantém {keep:.0f}%  ->  {saida.name}")
        print(f"     filtro ffmpeg: crop={cw}:{ch}:{cx}:{cy},scale={ALVO_W}:{ALVO_H}")

    if salvar:
        if len(zooms) == 1:
            cw, ch, cx, cy = crop_rect(zooms[0], fx, fy)
            salvar_crop(salvar, cw, ch, cx, cy)
        else:
            print(f"\n[!] --salvar precisa de um único --zoom (você passou {len(zooms)}). "
                  f"Rode de novo com o zoom escolhido pra gravar.")

    print(f"\nAbra os previews em {OUT_DIR} e me diga qual zoom/pan agrada "
          f"(ou peça pra ajustar fx/fy/zoom).")


if __name__ == "__main__":
    main()
