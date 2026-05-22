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
stem = BLOCOS_JSON.stem.replace("_blocos", "")  # ex: "renan_entrevista"
VIDEO = ROOT / "inputs" / f"{stem}.mp4"
OUT_DIR = ROOT / "outputs" / "cortes" / stem
OUT_DIR.mkdir(parents=True, exist_ok=True)

APLICAR_BLUR = "--blur" in sys.argv

PADDING_INICIO_S = 1.0   # folga antes do início (evita cortar respiração)
PADDING_FIM_S = 2.0      # folga no fim (deixa frase completar)

def slug(texto: str) -> str:
    """Converte tema em nome de arquivo amigável."""
    s = texto.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:50]

def hhmmss_para_segundos(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

for b in data["blocos"]:
    inicio_s = max(0, hhmmss_para_segundos(b["timestamp_inicio"]) - PADDING_INICIO_S)
    fim_s = hhmmss_para_segundos(b["timestamp_fim"]) + PADDING_FIM_S
    duracao = fim_s - inicio_s
    
    nome = f"corte_{b['id']:02d}_{slug(b['tema'])}.mp4"
    saida = OUT_DIR / nome
    
    print(f"\n[Bloco {b['id']}] {b['tema']}")
    print(f"  {b['timestamp_inicio']} → {b['timestamp_fim']} ({b['duracao_minutos']:.1f}min)")
    print(f"  Reencodando para {nome}...")

    if APLICAR_BLUR:
        # Blur localizado nos overlays — coordenadas pra 1280x720 Arthur do Val
        MASCARAS = (
            "[0:v]split=3[base][a1][a2];"
            "[a1]crop=247:130:1033:20,boxblur=20:1[b1];"
            "[a2]crop=200:160:1080:555,boxblur=20:1[b2];"
            "[base][b1]overlay=1033:20[tmp];"
            "[tmp][b2]overlay=1080:555[outv]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{inicio_s:.3f}",
            "-i", str(VIDEO),
            "-t", f"{duracao:.3f}",
            "-filter_complex", MASCARAS,
            "-map", "[outv]",
            "-map", "0:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-loglevel", "warning",
            str(saida),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{inicio_s:.3f}",
            "-i", str(VIDEO),
            "-t", f"{duracao:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-loglevel", "warning",
            str(saida),
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO ERRO: {result.stderr}")
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  OK Salvo: {saida.name} ({size_mb:.1f} MB)")

print(f"\nOK {len(data['blocos'])} cortes salvos em {OUT_DIR}")