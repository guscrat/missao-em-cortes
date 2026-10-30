"""Concatena [cold open +] intro + card + corte + outro pra cada bloco."""
import json
import re
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from _ffmpeg import VENC, AENC, SCALE_PAD
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]
USE_POLIDO = "--polido" in flags
USE_LEGENDADO = "--legendado" in flags   # cortes de cortes/legendados/ (step 4c)
ONLY_BLOCO = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--bloco=")), None)

input_arg = args[0] if args else "live_teste"
PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
BLOCOS_JSON = PASTA / "blocos.json"
INTRO = ROOT / "assets" / "intro.mp4"
OUTRO = ROOT / "assets" / "outro.mp4"
INTRO_NORM = ROOT / "assets" / "intro_norm.mp4"
OUTRO_NORM = ROOT / "assets" / "outro_norm.mp4"
INTRO_TRIM = ROOT / "assets" / "intro_trim.mp4"

# Encurta a intro pra prender mais cedo (asset do Canva tem 5s). 0 = não cortar.
INTRO_SEGUNDOS = 3.0

CARDS_DIR  = PASTA / "cards"
CORTES_DIR = PASTA / "cortes"
OUT_DIR    = PASTA / "finalizados"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def slug(texto):
    s = re.sub(r"[^\w\s-]", "", texto.lower())
    s = re.sub(r"[\s_-]+", "_", s)
    return s.strip("_")[:50]


def duracao_s(video_path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True
    ).stdout.strip()
    return float(out)


def atualizado(saida: Path, entrada: Path) -> bool:
    """True se a saída existe e é mais nova que a entrada (não precisa regerar)."""
    return saida.exists() and saida.stat().st_mtime >= entrada.stat().st_mtime


def descrever_formato(video_path: Path) -> str:
    """Resumo compacto dos streams (pra apontar qual segmento quebrou o -c copy)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels",
         "-of", "json", str(video_path)],
        capture_output=True, text=True
    ).stdout
    try:
        streams = json.loads(out)["streams"]
    except (json.JSONDecodeError, KeyError):
        return "(ffprobe falhou)"
    partes = []
    for s in streams:
        if s.get("codec_type") == "video":
            partes.append(f"{s.get('codec_name')} {s.get('width')}x{s.get('height')} "
                          f"{s.get('r_frame_rate')}fps {s.get('pix_fmt')}")
        elif s.get("codec_type") == "audio":
            partes.append(f"{s.get('codec_name')} {s.get('sample_rate')}Hz {s.get('channels')}ch")
    return " | ".join(partes) or "(sem streams)"


def tem_stream_audio(video_path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def normalizar_asset(entrada: Path, saida: Path):
    """Re-encoda o asset do Canva (intro/outro) pro formato canônico do pipeline.
    Isso é o que permite o concat -c copy depois (todos os segmentos iguais).
    Cria áudio silencioso se o asset não tiver."""
    if tem_stream_audio(entrada):
        cmd = ["ffmpeg", "-y", "-i", str(entrada),
               "-vf", SCALE_PAD, *VENC, *AENC,
               "-movflags", "+faststart", "-loglevel", "error", str(saida)]
        tem_audio = True
    else:
        cmd = ["ffmpeg", "-y",
               "-i", str(entrada),
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-vf", SCALE_PAD, *VENC, *AENC,
               "-shortest",
               "-movflags", "+faststart", "-loglevel", "error", str(saida)]
        tem_audio = False
    subprocess.run(cmd, check=True)
    return tem_audio


def trim_video(entrada: Path, saida: Path, segundos: float):
    """Corta os primeiros `segundos`. Entrada já é canônica → mantém canônico."""
    cmd = ["ffmpeg", "-y", "-i", str(entrada), "-t", str(segundos),
           *VENC, *AENC,
           "-movflags", "+faststart", "-loglevel", "error", str(saida)]
    subprocess.run(cmd, check=True)


def montar_copy(paths: list[Path], saida: Path, lista_tmp: Path):
    """Concatena via demuxer com -c copy (sem re-encodar). Exige segmentos no
    mesmo formato. Retorna o CompletedProcess pra quem chama decidir o fallback."""
    # Paths absolutos: o concat demuxer resolve relativos à pasta da lista, não ao CWD
    lista_tmp.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista_tmp),
           "-c", "copy", "-movflags", "+faststart", "-loglevel", "error", str(saida)]
    return subprocess.run(cmd, capture_output=True, text=True)


def build_concat_cmd(segments: list[tuple[Path, bool]], saida: Path) -> list:
    """
    Monta o comando ffmpeg de concatenação dinamicamente.
    segments: lista de (path, needs_pad) onde needs_pad=True usa letterbox
              (intro/outro do Canva) e False usa scale simples (cold, card, corte).
    """
    inputs = []
    for path, _ in segments:
        inputs += ["-i", str(path)]

    vfilters, afilters = [], []
    for i, (_, needs_pad) in enumerate(segments):
        if needs_pad:
            vf = (f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                  f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")
        else:
            vf = f"[{i}:v]scale=1280:720,setsar=1,fps=30[v{i}]"
        vfilters.append(vf)
        afilters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")

    n = len(segments)
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_complex = ";".join(vfilters + afilters + [f"{concat_in}concat=n={n}:v=1:a=1[outv][outa]"])

    return [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        *VENC, *AENC,
        "-movflags", "+faststart",
        "-loglevel", "warning",
        str(saida),
    ]


# === Normaliza intro e outro (só se o asset do Canva mudou) ===
print("Preparando assets do Canva...")
for entrada, saida, nome in [(INTRO, INTRO_NORM, "Intro"), (OUTRO, OUTRO_NORM, "Outro")]:
    if atualizado(saida, entrada):
        print(f"  {nome}: {saida.name} reaproveitado (asset não mudou)")
    else:
        tem_audio = normalizar_asset(entrada, saida)
        print(f"  {nome}: normalizado · áudio {'presente' if tem_audio else 'gerado silencioso'}")

# Encurta a intro (asset do Canva ~5s) pra prender o espectador mais cedo.
# Regera se o norm mudou OU se INTRO_SEGUNDOS foi alterado (checa pela duração).
if INTRO_SEGUNDOS and INTRO_SEGUNDOS > 0:
    if atualizado(INTRO_TRIM, INTRO_NORM) and abs(duracao_s(INTRO_TRIM) - INTRO_SEGUNDOS) < 0.2:
        print(f"  Intro: trim de {INTRO_SEGUNDOS:g}s reaproveitado")
    else:
        trim_video(INTRO_NORM, INTRO_TRIM, INTRO_SEGUNDOS)
        print(f"  Intro: cortada pra {INTRO_SEGUNDOS:g}s")
    INTRO_FINAL = INTRO_TRIM
else:
    INTRO_FINAL = INTRO_NORM

# === Concat por bloco ===
with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

falhas = []   # blocos sem vídeo final: o 06 sai com erro (antes dizia "OK" com a pasta vazia)
for b in data["blocos"]:
    if ONLY_BLOCO is not None and b["id"] != ONLY_BLOCO:
        continue
    if b.get("remover") and not USE_POLIDO:
        print(f"\n[!] Bloco {b['id']}: tem trecho em 'remover' (ex.: propaganda da live), que só "
              f"sai no polido — sem --polido ele vai pro vídeo final")
    card   = CARDS_DIR / f"card_{b['id']:02d}.mp4"
    fonte_cortes = CORTES_DIR / "legendados" if USE_LEGENDADO else CORTES_DIR
    if USE_POLIDO:
        cortes = sorted(fonte_cortes.glob(f"corte_{b['id']:02d}_*_polido.mp4"))
        if not cortes:
            print(f"\n[!] Bloco {b['id']}: corte polido{' legendado' if USE_LEGENDADO else ''} "
                  f"não encontrado, pulando (rode 04b_polir.py"
                  f"{' e 04c_legendas.py --polido' if USE_LEGENDADO else ''} antes ou tire o --polido)")
            falhas.append(b["id"])
            continue
    else:
        cortes = [p for p in fonte_cortes.glob(f"corte_{b['id']:02d}_*.mp4")
                  if "_polido" not in p.stem]
        if not cortes:
            print(f"\n[!] Bloco {b['id']}: corte{' legendado' if USE_LEGENDADO else ''} "
                  f"não encontrado, pulando{' (rode 04c_legendas.py antes)' if USE_LEGENDADO else ''}")
            falhas.append(b["id"])
            continue
    corte = cortes[0]

    sufixo = ("_polido" if USE_POLIDO else "") + ("_legendado" if USE_LEGENDADO else "")
    saida = OUT_DIR / f"video_{b['id']:02d}_{slug(b['tema'])}{sufixo}.mp4"

    # Cold open opcional
    colds = sorted(CORTES_DIR.glob(f"cold_{b['id']:02d}_*.mp4"))
    if USE_LEGENDADO:
        # cold legendado (04c, estilo gancho); live antiga sem ele usa o cru
        colds_leg = sorted((CORTES_DIR / "legendados").glob(f"cold_{b['id']:02d}_*.mp4"))
        if colds_leg:
            colds = colds_leg
        elif colds:
            print(f"  AVISO: bloco {b['id']}: cold open sem legenda (rode 04c_legendas.py) — usando o cru")
    cold  = colds[0] if colds else None

    print(f"\n[Bloco {b['id']}] {b['tema']}")

    if cold:
        print(f"  Ordem: cold open → intro → card → corte → outro")
        # needs_pad: cold=False, intro=True, card=False, corte=False, outro=True
        segments = [
            (cold,        False),
            (INTRO_FINAL, True),
            (card,        False),
            (corte,       False),
            (OUTRO_NORM,  True),
        ]
    else:
        print(f"  AVISO: cold open não encontrado — montando sem ele")
        print(f"  Ordem: intro → card → corte → outro")
        segments = [
            (INTRO_FINAL, True),
            (card,        False),
            (corte,       False),
            (OUTRO_NORM,  True),
        ]

    # Tenta concat -c copy (instantâneo). Se falhar (formato divergente), cai pro
    # re-encode via filter_complex, que é robusto mas lento.
    lista_tmp = OUT_DIR / f".concat_{b['id']:02d}.txt"
    result = montar_copy([p for p, _ in segments], saida, lista_tmp)
    modo = "copy"
    if result.returncode != 0:
        print(f"  concat -c copy falhou — formato dos segmentos (procure o destoante):")
        for p, _ in segments:
            print(f"    {p.name}: {descrever_formato(p)}")
        print(f"  re-encodando (fallback)...")
        result = subprocess.run(build_concat_cmd(segments, saida),
                                capture_output=True, text=True)
        modo = "re-encode"
    lista_tmp.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  ERRO:\n{result.stderr[-800:]}")
        falhas.append(b["id"])
    else:
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  OK {saida.name} ({modo})")
        print(f"    {size_mb:.1f} MB · {duracao_s(saida)/60:.1f} min")

if falhas:
    sys.exit(f"\n[!] Bloco(s) {', '.join(map(str, falhas))} sem vídeo final (veja os [!] acima).")
print(f"\nOK Vídeos finais salvos em {OUT_DIR}")
