"""Corta os blocos identificados usando ffmpeg."""
import json
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

input_arg = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "outputs" / "live_teste_blocos.json")
BLOCOS_JSON = Path(input_arg)
stem = BLOCOS_JSON.stem.replace("_blocos", "")
VIDEO = ROOT / "inputs" / f"{stem}.mp4"
OUT_DIR = ROOT / "outputs" / "cortes" / stem
OUT_DIR.mkdir(parents=True, exist_ok=True)

PADDING_INICIO_S  = 1.0   # folga antes do início do corte completo
PADDING_FIM_S     = 2.0   # folga no fim do corte completo
COLD_PADDING_S    = 0.5   # margem menor nas duas pontas do cold open

FADE_COLD_D       = 0.4   # duração do fade in/out no cold open (s)
FADE_CORTE_OUT_D  = 0.5   # duração do fade out no corte completo (s)

# Formato canônico do pipeline (1280x720, 30fps, yuv420p, aac 44100 stereo).
# Tudo sai nesse formato pra que o 06_montar concatene sem re-encodar (-c copy).
VENC = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23",
        "-b:v", "0", "-pix_fmt", "yuv420p"]
AENC = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
SCALE_PAD = ("scale=1280:720:force_original_aspect_ratio=decrease,"
             "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")

# Blur de overlays: ativar para lives MBL (contador de membros + QR code)
USE_BLUR = False
BLUR_MASKS = [
    ("247:130:1033:20",  "1033:20"),   # contador de novos membros (topo direito)
    ("200:160:1080:555", "1080:555"),  # QR code / valete.plus (canto inferior direito)
]


def slug(texto: str) -> str:
    s = texto.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:50]


def hhmmss_para_segundos(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def build_cmd(inicio_s: float, duracao: float, saida: Path,
              fade_in_d: float | None, fade_out_d: float) -> list:
    fo_start = max(0.0, duracao - fade_out_d)

    if fade_in_d is not None:
        fade_chain = f"fade=t=in:st=0:d={fade_in_d},fade=t=out:st={fo_start:.3f}:d={fade_out_d}"
        af = f"afade=t=in:st=0:d={fade_in_d},afade=t=out:st={fo_start:.3f}:d={fade_out_d}"
    else:
        fade_chain = f"fade=t=out:st={fo_start:.3f}:d={fade_out_d}"
        af = f"afade=t=out:st={fo_start:.3f}:d={fade_out_d}"

    if USE_BLUR:
        # Blur nas coordenadas da fonte original (1080p), DEPOIS escala pro canônico.
        n = len(BLUR_MASKS)
        splits = f"[0:v]split={n + 1}[base]" + "".join(f"[a{i}]" for i in range(n)) + ";"
        crops  = "".join(
            f"[a{i}]crop={crop},boxblur=20:1[b{i}];"
            for i, (crop, _) in enumerate(BLUR_MASKS)
        )
        overlays = ""
        src = "base"
        for i, (_, pos) in enumerate(BLUR_MASKS):
            dst = f"tmp{i}" if i < n - 1 else "v_blur"
            overlays += f"[{src}][b{i}]overlay={pos}[{dst}];"
            src = dst
        fc = splits + crops + overlays + f"[v_blur]{SCALE_PAD},{fade_chain}[outv]"
        return [
            "ffmpeg", "-y",
            "-ss", f"{inicio_s:.3f}",
            "-i", str(VIDEO),
            "-t", f"{duracao:.3f}",
            "-filter_complex", fc,
            "-map", "[outv]",
            "-map", "0:a",
            "-af", af,
            *VENC, *AENC,
            "-movflags", "+faststart",
            "-loglevel", "warning",
            str(saida),
        ]

    return [
        "ffmpeg", "-y",
        "-ss", f"{inicio_s:.3f}",
        "-i", str(VIDEO),
        "-t", f"{duracao:.3f}",
        "-vf", f"{SCALE_PAD},{fade_chain}",
        "-af", af,
        *VENC, *AENC,
        "-movflags", "+faststart",
        "-loglevel", "warning",
        str(saida),
    ]


def run_ffmpeg(cmd: list, saida: Path, label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO {label}: {result.stderr}")
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  OK {label}: {saida.name} ({size_mb:.1f} MB)")


with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

for b in data["blocos"]:
    s = slug(b["tema"])

    # ── Corte completo ──────────────────────────────────────────────────────
    inicio_s = max(0, hhmmss_para_segundos(b["timestamp_inicio"]) - PADDING_INICIO_S)
    fim_s    = hhmmss_para_segundos(b["timestamp_fim"]) + PADDING_FIM_S
    duracao  = fim_s - inicio_s

    nome_corte  = f"corte_{b['id']:02d}_{s}.mp4"
    saida_corte = OUT_DIR / nome_corte

    print(f"\n[Bloco {b['id']}] {b['tema']}")
    print(f"  {b['timestamp_inicio']} → {b['timestamp_fim']} ({b['duracao_minutos']:.1f}min)")
    print(f"  Corte completo → {nome_corte}")

    cmd = build_cmd(inicio_s, duracao, saida_corte,
                    fade_in_d=None, fade_out_d=FADE_CORTE_OUT_D)
    run_ffmpeg(cmd, saida_corte, "corte completo")

    # ── Cold open ───────────────────────────────────────────────────────────
    if not b.get("cold_open"):
        print(f"  AVISO: campo cold_open ausente — pulando cold open do bloco {b['id']}")
        continue

    co = b["cold_open"]
    cold_inicio_s = max(0, hhmmss_para_segundos(co["timestamp_inicio"]) - COLD_PADDING_S)
    cold_fim_s    = hhmmss_para_segundos(co["timestamp_fim"]) + COLD_PADDING_S
    cold_duracao  = cold_fim_s - cold_inicio_s

    nome_cold  = f"cold_{b['id']:02d}_{s}.mp4"
    saida_cold = OUT_DIR / nome_cold

    print(f"  Cold open: {co['timestamp_inicio']} → {co['timestamp_fim']} ({cold_duracao:.1f}s) → {nome_cold}")

    cmd_cold = build_cmd(cold_inicio_s, cold_duracao, saida_cold,
                         fade_in_d=FADE_COLD_D, fade_out_d=FADE_COLD_D)
    run_ffmpeg(cmd_cold, saida_cold, "cold open")

print(f"\nOK {len(data['blocos'])} blocos processados em {OUT_DIR}")
