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

import json
from datetime import timedelta
from faster_whisper import WhisperModel
from _paths import criar_pasta

input_arg = sys.argv[1] if len(sys.argv) > 1 else "inputs/live_teste.mp4"
INPUT = Path(input_arg)
if not INPUT.is_file():
    sys.exit(f"[!] Vídeo não encontrado: {INPUT}")
stem = INPUT.stem  # ex: "renan_entrevista"
PASTA = criar_pasta(stem)               # outputs/<AAAA-MM-DD>_<stem>/ (reusa se já existe)
OUTPUT = PASTA / "transcricao.txt"
WORDS_OUT = PASTA / "words.json"        # word-level pro 04b_polir (evita re-transcrever)

# medium = boa qualidade em pt-BR, roda em CPU sem morrer (~3GB RAM)
# Se tem GPU NVIDIA: troca pra "large-v3" + device="cuda" + compute_type="float16"
print("Carregando modelo...")
try:
    model = WhisperModel("medium", device="cuda", compute_type="int8_float16")
except Exception as e:
    print(f"[!] CUDA indisponível ({e}) — caindo pra CPU (4-5x mais lento)")
    model = WhisperModel("medium", device="cpu", compute_type="int8")

print(f"Transcrevendo {INPUT.name}... (vai demorar)")
segments, info = model.transcribe(
    str(INPUT),
    language="pt",
    vad_filter=True,        # pula silêncios (acelera bem)
    beam_size=2,            # 2 é bem mais rápido que 5, com perda mínima em pt-BR claro
    word_timestamps=True,   # gera <stem>_words.json pro 04b reaproveitar (não re-transcreve)
    condition_on_previous_text=False,  # evita propagar erros em live longa
)

print(f"Duração: {info.duration/60:.1f} min · idioma: {info.language}")

def hhmmss(s):
    return str(timedelta(seconds=int(s))).rjust(8, "0")

palavras = []
with OUTPUT.open("w", encoding="utf-8") as f:
    for seg in segments:
        line = f"[{hhmmss(seg.start)}] Speaker: {seg.text.strip()}"
        f.write(line + "\n")
        print(line)  # streaming pra você ver acontecendo
        if seg.words:
            for w in seg.words:
                palavras.append({"word": w.word.strip(), "start": w.start, "end": w.end})

WORDS_OUT.write_text(
    json.dumps({"duration": info.duration, "words": palavras}, ensure_ascii=False),
    encoding="utf-8",
)

print(f"\nSalvo em {OUTPUT}")
print(f"Word-level salvo em {WORDS_OUT} ({len(palavras)} palavras)")