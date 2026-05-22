"""Concatena intro + card + corte + outro pra cada bloco."""
import json
import re
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(__file__).parent.parent

input_arg = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "outputs" / "live_teste_blocos.json")
BLOCOS_JSON = Path(input_arg)
stem = BLOCOS_JSON.stem.replace("_blocos", "")  # ex: "renan_entrevista"
INTRO = ROOT / "assets" / "intro.mp4"
OUTRO = ROOT / "assets" / "outro.mp4"
INTRO_NORM = ROOT / "assets" / "intro_norm.mp4"
OUTRO_NORM = ROOT / "assets" / "outro_norm.mp4"
CARDS_DIR = ROOT / "outputs" / "cards"
CORTES_DIR = ROOT / "outputs" / "cortes" / stem
OUT_DIR = ROOT / "outputs" / "finalizados"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def slug(texto):
    s = re.sub(r"[^\w\s-]", "", texto.lower())
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:50]

def tem_stream_audio(video_path: Path) -> bool:
    """Verifica se o vídeo tem stream de áudio via ffprobe."""
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
        # Já tem áudio - só copia
        cmd = ["ffmpeg", "-y", "-i", str(entrada), "-c", "copy",
               "-loglevel", "error", str(saida)]
        tem_audio = True
    else:
        # Sem áudio - gera silencioso e gruda
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
    card = CARDS_DIR / f"card_{b['id']:02d}.mp4"
    cortes = list(CORTES_DIR.glob(f"corte_{b['id']:02d}_*.mp4"))
    if not cortes:
        print(f"[!] Bloco {b['id']}: corte não encontrado, pulando")
        continue
    corte = cortes[0]
    
    saida = OUT_DIR / f"video_{b['id']:02d}_{slug(b['tema'])}.mp4"
    
    print(f"\n[Bloco {b['id']}] {b['tema']}")
    print(f"  Concatenando intro + card + corte + outro...")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(INTRO_NORM),
        "-i", str(card),
        "-i", str(corte),
        "-i", str(OUTRO_NORM),
        "-filter_complex", (
            "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v0];"
            "[1:v]scale=1280:720,setsar=1,fps=30[v1];"
            "[2:v]scale=1280:720,setsar=1,fps=30[v2];"
            "[3:v]scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v3];"
            "[0:a]aresample=44100,aformat=channel_layouts=stereo[a0];"
            "[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];"
            "[2:a]aresample=44100,aformat=channel_layouts=stereo[a2];"
            "[3:a]aresample=44100,aformat=channel_layouts=stereo[a3];"
            "[v0][a0][v1][a1][v2][a2][v3][a3]concat=n=4:v=1:a=1[outv][outa]"
        ),
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-loglevel", "warning",
        str(saida)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO ERRO:\n{result.stderr[-800:]}")
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        duration_s = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(saida)],
            capture_output=True, text=True
        ).stdout.strip()
        print(f"  OK {saida.name}")
        print(f"    {size_mb:.1f} MB · {float(duration_s)/60:.1f} min")

print(f"\nOK Vídeos finais salvos em {OUT_DIR}")
