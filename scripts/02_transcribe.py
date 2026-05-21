"""Transcreve a live e gera um TXT com timestamps."""
from pathlib import Path
from datetime import timedelta
from faster_whisper import WhisperModel

INPUT = Path("inputs/live_teste.mp4")
OUTPUT = Path("outputs/live_teste_transcricao.txt")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# medium = boa qualidade em pt-BR, roda em CPU sem morrer (~3GB RAM)
# Se tem GPU NVIDIA: troca pra "large-v3" + device="cuda" + compute_type="float16"
print("Carregando modelo...")
model = WhisperModel("large-v3", device="cuda", compute_type="float16")

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

print(f"\n✓ Salvo em {OUTPUT}")