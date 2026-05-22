"""Transcreve a live e gera um TXT com timestamps."""
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# Fix Windows: adiciona DLLs do CUDA ao path
if os.name == "nt":
    venv_nvidia = Path(__file__).parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia"
    for sub in ["cublas", "cudnn"]:
        bin_path = venv_nvidia / sub / "bin"
        if bin_path.exists():
            os.add_dll_directory(str(bin_path))
        else:
            print(f"[!] Path nao encontrado: {bin_path}")

from datetime import timedelta
from faster_whisper import WhisperModel

input_arg = sys.argv[1] if len(sys.argv) > 1 else "inputs/live_teste.mp4"
INPUT = Path(input_arg)
stem = INPUT.stem  # ex: "renan_entrevista"
OUTPUT = Path(f"outputs/{stem}_transcricao.txt")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# medium = boa qualidade em pt-BR, roda em CPU sem morrer (~3GB RAM)
# Se tem GPU NVIDIA: troca pra "large-v3" + device="cuda" + compute_type="float16"
print("Carregando modelo...")
model = WhisperModel("medium", device="cuda", compute_type="int8_float16")

print(f"Transcrevendo {INPUT.name}... (vai demorar)")
segments, info = model.transcribe(
    str(INPUT),
    language="pt",
    vad_filter=True,        # pula silêncios (acelera bem)
    beam_size=5,            # qualidade > velocidade
    condition_on_previous_text=False,  # evita propagar erros em live longa
)

print(f"Duração: {info.duration/60:.1f} min · idioma: {info.language}")

def hhmmss(s):
    return str(timedelta(seconds=int(s))).rjust(8, "0")

with OUTPUT.open("w", encoding="utf-8") as f:
    for seg in segments:
        line = f"[{hhmmss(seg.start)}] Speaker: {seg.text.strip()}"
        f.write(line + "\n")
        print(line)  # streaming pra você ver acontecendo

print(f"\nSalvo em {OUTPUT}")