"""Concatena [cold open +] intro + card + corte + outro pra cada bloco."""
import json
import re
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(__file__).parent.parent

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]
USE_POLIDO = "--polido" in flags

input_arg = args[0] if args else str(ROOT / "outputs" / "live_teste_blocos.json")
BLOCOS_JSON = Path(input_arg)
stem = BLOCOS_JSON.stem.replace("_blocos", "")
INTRO = ROOT / "assets" / "intro.mp4"
OUTRO = ROOT / "assets" / "outro.mp4"
INTRO_NORM = ROOT / "assets" / "intro_norm.mp4"
OUTRO_NORM = ROOT / "assets" / "outro_norm.mp4"
CARDS_DIR  = ROOT / "outputs" / "cards" / stem
CORTES_DIR = ROOT / "outputs" / "cortes" / stem
OUT_DIR    = ROOT / "outputs" / "finalizados" / stem
OUT_DIR.mkdir(parents=True, exist_ok=True)


def slug(texto):
    s = re.sub(r"[^\w\s-]", "", texto.lower())
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:50]


def tem_stream_audio(video_path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def normalizar_asset(entrada: Path, saida: Path):
    """Garante que o asset tem stream de áudio (cria silencioso se faltar)."""
    if tem_stream_audio(entrada):
        cmd = ["ffmpeg", "-y", "-i", str(entrada), "-c", "copy",
               "-loglevel", "error", str(saida)]
        tem_audio = True
    else:
        cmd = ["ffmpeg", "-y",
               "-i", str(entrada),
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-c:v", "copy",
               "-c:a", "aac", "-b:a", "128k",
               "-shortest",
               "-loglevel", "error", str(saida)]
        tem_audio = False
    subprocess.run(cmd, check=True)
    return tem_audio


def build_concat_cmd(segments: list[tuple[Path, bool]], saida: Path) -> list:
    """
    Monta o comando ffmpeg de concatenação dinamicamente.
    segments: lista de (path, needs_pad) onde needs_pad=True usa letterbox
              (intro/outro do Canva) e False usa scale simples (cold, card, corte).
    """
    inputs = []
    for path, _ in segments:
        inputs += ["-i", str(path)]

    vfilters, afilters = [], []
    for i, (_, needs_pad) in enumerate(segments):
        if needs_pad:
            vf = (f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                  f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")
        else:
            vf = f"[{i}:v]scale=1280:720,setsar=1,fps=30[v{i}]"
        vfilters.append(vf)
        afilters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")

    n = len(segments)
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_complex = ";".join(vfilters + afilters + [f"{concat_in}concat=n={n}:v=1:a=1[outv][outa]"])

    return [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-loglevel", "warning",
        str(saida),
    ]


# === Normaliza intro e outro (uma vez só) ===
print("Normalizando assets do Canva...")
intro_tem_audio = normalizar_asset(INTRO, INTRO_NORM)
outro_tem_audio = normalizar_asset(OUTRO, OUTRO_NORM)
print(f"  Intro: áudio {'presente' if intro_tem_audio else 'gerado silencioso'}")
print(f"  Outro: áudio {'presente' if outro_tem_audio else 'gerado silencioso'}")

# === Concat por bloco ===
with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

for b in data["blocos"]:
    card   = CARDS_DIR / f"card_{b['id']:02d}.mp4"
    if USE_POLIDO:
        cortes = sorted(CORTES_DIR.glob(f"corte_{b['id']:02d}_*_polido.mp4"))
        if not cortes:
            print(f"\n[!] Bloco {b['id']}: corte polido não encontrado, pulando "
                  f"(rode 04b_polir.py antes ou tire o --polido)")
            continue
    else:
        cortes = [p for p in CORTES_DIR.glob(f"corte_{b['id']:02d}_*.mp4")
                  if "_polido" not in p.stem]
        if not cortes:
            print(f"\n[!] Bloco {b['id']}: corte não encontrado, pulando")
            continue
    corte = cortes[0]

    sufixo = "_polido" if USE_POLIDO else ""
    saida = OUT_DIR / f"video_{b['id']:02d}_{slug(b['tema'])}{sufixo}.mp4"

    # Cold open opcional
    colds = list(CORTES_DIR.glob(f"cold_{b['id']:02d}_*.mp4"))
    cold  = colds[0] if colds else None

    print(f"\n[Bloco {b['id']}] {b['tema']}")

    if cold:
        print(f"  Ordem: cold open → intro → card → corte → outro")
        # needs_pad: cold=False, intro=True, card=False, corte=False, outro=True
        segments = [
            (cold,       False),
            (INTRO_NORM, True),
            (card,       False),
            (corte,      False),
            (OUTRO_NORM, True),
        ]
    else:
        print(f"  AVISO: cold open não encontrado — montando sem ele")
        print(f"  Ordem: intro → card → corte → outro")
        segments = [
            (INTRO_NORM, True),
            (card,       False),
            (corte,      False),
            (OUTRO_NORM, True),
        ]

    cmd    = build_concat_cmd(segments, saida)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERRO:\n{result.stderr[-800:]}")
    else:
        size_mb    = saida.stat().st_size / (1024 * 1024)
        duration_s = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(saida)],
            capture_output=True, text=True
        ).stdout.strip()
        print(f"  OK {saida.name}")
        print(f"    {size_mb:.1f} MB · {float(duration_s)/60:.1f} min")

print(f"\nOK Vídeos finais salvos em {OUT_DIR}")
