"""Corta os blocos identificados usando ffmpeg.

Uso: uv run py scripts/04_cortar.py <stem> [--bloco=N]

A janela de cada corte vem do _fronteira.janela(): o padding de sempre (1s antes, 2s
depois; 0,5s no cold open), mas sem pegar pedaço da frase vizinha (words.json).
"""
import json
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
from pathlib import Path
import _fronteira as fr
from _ffmpeg import VENC, AENC, SCALE_PAD
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent

args = [a for a in sys.argv[1:] if not a.startswith("--")]
only_bloco = next((int(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--bloco=")), None)
input_arg = args[0] if args else "live_teste"
PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
BLOCOS_JSON = PASTA / "blocos.json"
WORDS_JSON = PASTA / "words.json"
VIDEO = ROOT / "inputs" / f"{stem}.mp4"
OUT_DIR = PASTA / "cortes"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PALAVRAS = (json.loads(WORDS_JSON.read_text(encoding="utf-8")).get("words", [])
            if WORDS_JSON.exists() else [])

FADE_COLD_D       = 0.4   # duração do fade in/out no cold open (s)
FADE_CORTE_OUT_D  = 0.5   # duração do fade out no corte completo (s)

# Anti-overlay: zoom (crop+scale) que tira os overlays das lives sem blur. O recorte
# é POR FONTE (estúdios diferentes têm overlays em posições diferentes), lido de
# config/zoom.json por stem. Calibre fontes novas com scripts/calibrar_zoom.py.
# Stem sem entrada no config roda SEM zoom (só scale+pad) e loga um aviso.
# O zoom aplica-se ao corte E ao cold open.
ZOOM_CONFIG = ROOT / "config" / "zoom.json"
ZOOM_CROP = None
if ZOOM_CONFIG.exists():
    with ZOOM_CONFIG.open(encoding="utf-8") as f:
        ZOOM_CROP = json.load(f).get(stem)
USE_ZOOM = ZOOM_CROP is not None
if USE_ZOOM:
    print(f"Zoom anti-overlay: crop={ZOOM_CROP} (fonte '{stem}')")
else:
    print(f"[!] '{stem}' sem zoom calibrado em {ZOOM_CONFIG.name} — cortando SEM zoom "
          f"(overlays podem aparecer). Calibre com scripts/calibrar_zoom.py")

# Logo do canal (marca queimada). Aplicada ao corte E ao cold open, por cima do
# zoom/scale (sobre o quadro final 1280x720), canto superior-direito. Se o arquivo
# não existir, roda sem logo. Posição oposta à marca d'água do YouTube.
LOGO = ROOT / "assets" / "logoCanal.png"
USE_LOGO = LOGO.exists()
LOGO_W = 110          # largura do selo em px (logo é quadrada 150x150)
LOGO_MARGIN = 28      # margem das bordas em px
LOGO_POS = f"W-w-{LOGO_MARGIN}:{LOGO_MARGIN}"   # superior-direito
if USE_LOGO:
    print(f"Logo do canal: {LOGO.name} ({LOGO_W}px, superior-direito)")
else:
    print(f"[!] {LOGO.name} não encontrada — cortando SEM logo do canal")


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

    # Zoom anti-overlay (crop+scale) ou scale+pad padrão. Os dois terminam no
    # formato canônico 1280x720, então o resto do pipeline não muda.
    if USE_ZOOM:
        geo = f"crop={ZOOM_CROP},scale=1280:720,setsar=1,fps=30"
    else:
        geo = SCALE_PAD

    cmd = ["ffmpeg", "-y", "-ss", f"{inicio_s:.3f}", "-i", str(VIDEO)]

    if USE_LOGO:
        # Logo entra como 2º input e é sobreposta via filter_complex (overlay
        # repete o frame único pela duração toda). Áudio também passa pelo
        # filtergraph pra poder usar -map junto com a saída de vídeo rotulada.
        cmd += ["-i", str(LOGO), "-t", f"{duracao:.3f}",
                "-filter_complex",
                f"[0:v]{geo},{fade_chain}[base];"
                f"[1:v]scale={LOGO_W}:-1[lg];"
                f"[base][lg]overlay={LOGO_POS}[v];"
                f"[0:a]{af}[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-t", f"{duracao:.3f}", "-vf", f"{geo},{fade_chain}", "-af", af]

    cmd += [*VENC, *AENC, "-movflags", "+faststart", "-loglevel", "warning", str(saida)]
    return cmd


falhas = []  # acumula erros de ffmpeg pra falhar alto no final (exit 1)


def run_ffmpeg(cmd: list, saida: Path, label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO {label}: {result.stderr}")
        falhas.append(label)
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  OK {label}: {saida.name} ({size_mb:.1f} MB)")


with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

for b in data["blocos"]:
    if only_bloco is not None and b["id"] != only_bloco:
        continue
    s = slug(b["tema"])

    # ── Corte completo ──────────────────────────────────────────────────────
    inicio_s, fim_s = fr.janela(PALAVRAS, hhmmss_para_segundos(b["timestamp_inicio"]),
                                hhmmss_para_segundos(b["timestamp_fim"]))
    duracao  = fim_s - inicio_s

    nome_corte  = f"corte_{b['id']:02d}_{s}.mp4"
    saida_corte = OUT_DIR / nome_corte

    print(f"\n[Bloco {b['id']}] {b['tema']}")
    print(f"  {b['timestamp_inicio']} → {b['timestamp_fim']} ({b['duracao_minutos']:.1f}min)")
    print(f"  Corte completo → {nome_corte}")

    cmd = build_cmd(inicio_s, duracao, saida_corte,
                    fade_in_d=None, fade_out_d=FADE_CORTE_OUT_D)
    run_ffmpeg(cmd, saida_corte, f"corte completo (bloco {b['id']})")

    # ── Cold open ───────────────────────────────────────────────────────────
    if not b.get("cold_open"):
        print(f"  AVISO: campo cold_open ausente — pulando cold open do bloco {b['id']}")
        continue

    co = b["cold_open"]
    cold_inicio_s, cold_fim_s = fr.janela(PALAVRAS, hhmmss_para_segundos(co["timestamp_inicio"]),
                                          hhmmss_para_segundos(co["timestamp_fim"]),
                                          fr.COLD_PADDING_S, fr.COLD_PADDING_S)
    cold_duracao  = cold_fim_s - cold_inicio_s

    nome_cold  = f"cold_{b['id']:02d}_{s}.mp4"
    saida_cold = OUT_DIR / nome_cold

    print(f"  Cold open: {co['timestamp_inicio']} → {co['timestamp_fim']} ({cold_duracao:.1f}s) → {nome_cold}")

    cmd_cold = build_cmd(cold_inicio_s, cold_duracao, saida_cold,
                         fade_in_d=FADE_COLD_D, fade_out_d=FADE_COLD_D)
    run_ffmpeg(cmd_cold, saida_cold, f"cold open (bloco {b['id']})")

if falhas:
    print(f"\n[!] {len(falhas)} falha(s) de ffmpeg:")
    for f in falhas:
        print(f"   - {f}")
    sys.exit(1)

print(f"\nOK {len(data['blocos'])} blocos processados em {OUT_DIR}")
