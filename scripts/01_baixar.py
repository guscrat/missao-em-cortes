"""Baixa a live do YouTube e guarda a URL da fonte.

Uso: uv run py scripts/01_baixar.py <URL> <stem>

Salva:
  inputs/<stem>.mp4  — vídeo (1080p60 mp4 + m4a, com fallback se o formato não existir)
  inputs/<stem>.url  — URL da fonte (o 08_descricao.py lê pra preencher o
                       "Conteúdo original" sem placeholder manual)
"""
import re
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(__file__).parent.parent
INPUTS = ROOT / "inputs"

# 299+140 = 1080p60 mp4 + m4a 129k (recomendado); fallbacks pra vídeos sem esse formato
FORMATO = "299+140/bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best"

if len(sys.argv) < 3:
    sys.exit("Uso: uv run py scripts/01_baixar.py <URL> <stem>\n"
             "Ex:  uv run py scripts/01_baixar.py https://youtube.com/watch?v=XXXX renan_live3")

url, stem = sys.argv[1], sys.argv[2]

if not re.fullmatch(r"[\w-]+", stem):
    sys.exit(f"[!] Stem inválido: '{stem}'. Use só letras, números e _ (ex: renan_live3).")

destino = INPUTS / f"{stem}.mp4"
if destino.exists():
    sys.exit(f"[!] {destino} já existe. Apague ou escolha outro stem.")

INPUTS.mkdir(exist_ok=True)
print(f"Baixando {url} -> {destino.name}")
result = subprocess.run([
    sys.executable, "-m", "yt_dlp",
    "-f", FORMATO,
    "--merge-output-format", "mp4",
    "--js-runtimes", "node",   # sem runtime JS o YouTube devolve 403 nos formatos bons
    "-o", str(destino),
    url,
])
if result.returncode != 0:
    sys.exit(f"[!] yt-dlp falhou (exit {result.returncode})")

url_file = INPUTS / f"{stem}.url"
url_file.write_text(url + "\n", encoding="utf-8")

size_mb = destino.stat().st_size / (1024 * 1024)
print(f"\nOK {destino.name} ({size_mb:.0f} MB)")
print(f"OK URL salva em {url_file.name} (o 08_descricao.py preenche sozinho)")
print(f"\nPróximo passo: uv run py scripts/02_transcribe.py inputs/{stem}.mp4")
