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
    
    cmd = [
        "ffmpeg", "-y",                       # -y sobrescreve sem perguntar
        "-ss", f"{inicio_s:.3f}",             # início (antes de -i = seek rápido)
        "-i", str(VIDEO),
        "-t", f"{duracao:.3f}",               # duração
        "-c:v", "libx264",                    # re-encode vídeo (garante corte limpo)
        "-preset", "fast",                     # velocidade x qualidade
        "-crf", "20",                          # qualidade (18-23, menor = melhor)
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",            # otimiza pra streaming web
        "-loglevel", "warning",                # menos verbose
        str(saida),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ ERRO: {result.stderr}")
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  ✓ Salvo: {saida.name} ({size_mb:.1f} MB)")

print(f"\n✓ {len(data['blocos'])} cortes salvos em {OUT_DIR}")