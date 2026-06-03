"""Concatena [cold open +] intro + card + corte + outro pra cada bloco."""
import json
import re
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]
USE_POLIDO = "--polido" in flags

input_arg = args[0] if args else "live_teste"
PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
BLOCOS_JSON = PASTA / "blocos.json"
INTRO = ROOT / "assets" / "intro.mp4"
OUTRO = ROOT / "assets" / "outro.mp4"
INTRO_NORM = ROOT / "assets" / "intro_norm.mp4"
OUTRO_NORM = ROOT / "assets" / "outro_norm.mp4"
INTRO_TRIM = ROOT / "assets" / "intro_trim.mp4"

# Encurta a intro pra prender mais cedo (asset do Canva tem 5s). 0 = não cortar.
INTRO_SEGUNDOS = 3.0

# Formato canônico do pipeline (igual ao 04/05). Com tudo nesse formato, a montagem
# concatena com -c copy (instantâneo) em vez de re-encodar o vídeo inteiro.
VENC = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23",
        "-b:v", "0", "-pix_fmt", "yuv420p"]
AENC = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
SCALE_PAD = ("scale=1280:720:force_original_aspect_ratio=decrease,"
             "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")
CARDS_DIR  = PASTA / "cards"
CORTES_DIR = PASTA / "cortes"
OUT_DIR    = PASTA / "finalizados"
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
    """Re-encoda o asset do Canva (intro/outro) pro formato canônico do pipeline.
    Isso é o que permite o concat -c copy depois (todos os segmentos iguais).
    Cria áudio silencioso se o asset não tiver."""
    if tem_stream_audio(entrada):
        cmd = ["ffmpeg", "-y", "-i", str(entrada),
               "-vf", SCALE_PAD, *VENC, *AENC,
               "-movflags", "+faststart", "-loglevel", "error", str(saida)]
        tem_audio = True
    else:
        cmd = ["ffmpeg", "-y",
               "-i", str(entrada),
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-vf", SCALE_PAD, *VENC, *AENC,
               "-shortest",
               "-movflags", "+faststart", "-loglevel", "error", str(saida)]
        tem_audio = False
    subprocess.run(cmd, check=True)
    return tem_audio


def trim_video(entrada: Path, saida: Path, segundos: float):
    """Corta os primeiros `segundos`. Entrada já é canônica → mantém canônico."""
    cmd = ["ffmpeg", "-y", "-i", str(entrada), "-t", str(segundos),
           *VENC, *AENC,
           "-movflags", "+faststart", "-loglevel", "error", str(saida)]
    subprocess.run(cmd, check=True)


def montar_copy(paths: list[Path], saida: Path, lista_tmp: Path):
    """Concatena via demuxer com -c copy (sem re-encodar). Exige segmentos no
    mesmo formato. Retorna o CompletedProcess pra quem chama decidir o fallback."""
    # Paths absolutos: o concat demuxer resolve relativos à pasta da lista, não ao CWD
    lista_tmp.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista_tmp),
           "-c", "copy", "-movflags", "+faststart", "-loglevel", "error", str(saida)]
    return subprocess.run(cmd, capture_output=True, text=True)


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
        *VENC, *AENC,
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

# Encurta a intro (asset do Canva ~5s) pra prender o espectador mais cedo
if INTRO_SEGUNDOS and INTRO_SEGUNDOS > 0:
    trim_video(INTRO_NORM, INTRO_TRIM, INTRO_SEGUNDOS)
    INTRO_FINAL = INTRO_TRIM
    print(f"  Intro: cortada pra {INTRO_SEGUNDOS:g}s")
else:
    INTRO_FINAL = INTRO_NORM

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
            (cold,        False),
            (INTRO_FINAL, True),
            (card,        False),
            (corte,       False),
            (OUTRO_NORM,  True),
        ]
    else:
        print(f"  AVISO: cold open não encontrado — montando sem ele")
        print(f"  Ordem: intro → card → corte → outro")
        segments = [
            (INTRO_FINAL, True),
            (card,        False),
            (corte,       False),
            (OUTRO_NORM,  True),
        ]

    # Tenta concat -c copy (instantâneo). Se falhar (formato divergente), cai pro
    # re-encode via filter_complex, que é robusto mas lento.
    lista_tmp = OUT_DIR / f".concat_{b['id']:02d}.txt"
    result = montar_copy([p for p, _ in segments], saida, lista_tmp)
    modo = "copy"
    if result.returncode != 0:
        print(f"  concat -c copy falhou — re-encodando (fallback)...")
        result = subprocess.run(build_concat_cmd(segments, saida),
                                capture_output=True, text=True)
        modo = "re-encode"
    lista_tmp.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  ERRO:\n{result.stderr[-800:]}")
    else:
        size_mb    = saida.stat().st_size / (1024 * 1024)
        duration_s = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(saida)],
            capture_output=True, text=True
        ).stdout.strip()
        print(f"  OK {saida.name} ({modo})")
        print(f"    {size_mb:.1f} MB · {float(duration_s)/60:.1f} min")

print(f"\nOK Vídeos finais salvos em {OUT_DIR}")
