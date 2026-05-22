"""Corta os blocos identificados usando ffmpeg."""
import json
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIDEO = ROOT / "inputs" / "live_teste.mp4"
BLOCOS_JSON = ROOT / "outputs" / "live_teste_blocos.json"
OUT_DIR = ROOT / "outputs" / "cortes"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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
    
    # Blur localizado nos overlays (em vez de drawbox preto)
    # Sintaxe: split → crop em cada área → boxblur → overlay de volta
    MASCARAS = (
        "[0:v]split=3[base][a1][a2];"
        "[a1]crop=247:130:1033:20,boxblur=20:1[b1];"      # contador novos membros
        "[a2]crop=200:160:1080:555,boxblur=20:1[b2];"     # qr code
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
        "-map", "0:a",                        # áudio do input original
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-loglevel", "warning",
        str(saida),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ ERRO: {result.stderr}")
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  ✓ Salvo: {saida.name} ({size_mb:.1f} MB)")

print(f"\n✓ {len(data['blocos'])} cortes salvos em {OUT_DIR}")