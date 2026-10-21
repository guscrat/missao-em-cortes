"""Step 10 (off-pipeline): Shorts 9:16 a partir dos cold opens.

Uso:
    uv run py scripts/10_shorts.py <stem> [--bloco=N]

Pra cada bloco com cold_open no blocos.json:
  1. Recorta a janela do cold open direto do vídeo ORIGINAL (inputs/<stem>.mp4, 1080p):
     o cold_NN.mp4 é 720p e já zoomado, ficaria borrado esticado pra 1080x1920
  2. Acha o rosto (OpenCV, local, grátis) em frames a cada 0.5s e centraliza a janela
     9:16 nele. A janela fica SEMPRE dentro da área anti-overlay do config/zoom.json,
     então os overlays da live continuam fora (stem sem zoom: usa o quadro inteiro e avisa)
  3. Queima: texto_thumb como manchete no topo, legenda karaokê grande (words.json) e a
     marca MISSÃO EM CORTES embaixo

Saída: outputs/<pasta>/shorts/short_NN_<slug>.mp4 (1080x1920, 30fps, NVENC) + shorts.json
com o recorte e a taxa de frames com rosto de cada um. Taxa baixa (<30%) = provável tela
compartilhada ou plateia: o script avisa, revise antes de subir.
Custo: $0 (sem API).
"""
import json
import re
import statistics
import subprocess
import sys
import unicodedata
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

from _ffmpeg import AENC, VENC
from _legenda import (AMARELO_14, PRETO, agrupar_linhas, cabecalho_ass, dialogo, estilo,
                      eventos_karaoke, filtro_ass, hhmmss_para_segundos, limpar,
                      palavras_na_janela)
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent
INPUTS = ROOT / "inputs"
ZOOM_JSON = ROOT / "config" / "zoom.json"

LARGURA, ALTURA = 1080, 1920
COLD_PADDING_S = 0.5     # igual ao 04_cortar
FADE_S = 0.3
AMOSTRA_S = 0.5          # 1 frame a cada meio segundo pra achar o rosto
TAXA_MIN_ROSTO = 0.3     # abaixo disso: avisa (tela compartilhada/plateia)
MAX_CHARS_TITULO = 16

ESTILOS = [
    estilo("Karaoke", 110, alinhamento=2, margem_v=560, contorno=7),
    # caixa preta opaca atrás da manchete (borda 3 usa a cor de fundo)
    estilo("Titulo", 96, alinhamento=8, margem_v=200, primaria=AMARELO_14,
           borda=3, contorno=18, fundo=PRETO),
    estilo("Marca", 46, alinhamento=2, margem_v=110, contorno=3),
]


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:50]


def ler_zoom(stem: str) -> tuple[int, int, int, int] | None:
    """(w, h, x, y) da área anti-overlay do stem, ou None se não cadastrado."""
    if not ZOOM_JSON.exists():
        return None
    valor = json.loads(ZOOM_JSON.read_text(encoding="utf-8")).get(stem)
    if not valor:
        return None
    w, h, x, y = (int(v) for v in valor.removeprefix("crop=").split(":"))
    return w, h, x, y


def janela_9x16(regiao: tuple[int, int, int, int], cx: float | None) -> tuple[int, int, int, int]:
    """Janela 9:16 com a altura toda da região, centrada em cx e presa dentro dela.
    Sem rosto (cx None): centro da região. Dimensões pares (yuv420p exige)."""
    rw, rh, rx, ry = regiao
    h = rh - rh % 2
    w = min(rw, round(h * 9 / 16))
    w -= w % 2
    centro = rx + rw / 2 if cx is None else cx
    x = int(min(max(centro - w / 2, rx), rx + rw - w))
    if x % 2:   # par sem sair da região
        x = x + 1 if x + 1 + w <= rx + rw else x - 1
    return w, h, x, ry


def agrupar_rostos(deteccoes: list[dict]) -> list[list[dict]]:
    """Junta detecções de frames diferentes que são o mesmo rosto (centro próximo).
    Cada detecção: {"frame", "cx", "cy", "w"}."""
    grupos: list[list[dict]] = []
    for d in deteccoes:
        for g in grupos:
            ref = g[-1]
            lim = max(d["w"], ref["w"]) * 1.5
            if abs(d["cx"] - ref["cx"]) < lim and abs(d["cy"] - ref["cy"]) < lim:
                g.append(d)
                break
        else:
            grupos.append([d])
    return grupos


def escolher_rosto(grupos: list[list[dict]], amostras: int,
                   centro_x: float) -> tuple[float | None, float]:
    """(cx mediano do rosto de quem fala, fração de frames em que ele aparece).
    Quem filma mantém quem fala perto do centro do quadro: entre os rostos presentes em
    pelo menos TAXA_MIN_ROSTO dos frames, ganha o mais perto do centro (o maior rosto
    perdia pra foto no telão, e o "mais mexido" pra quem bebia água na mesa).
    Nenhum frequente: o mais frequente, e a taxa baixa dispara o aviso de revisão."""
    if not grupos or not amostras:
        return None, 0.0
    taxa = lambda g: len({d["frame"] for d in g}) / amostras   # noqa: E731
    mediana = lambda g: statistics.median(d["cx"] for d in g)   # noqa: E731
    frequentes = [g for g in grupos if taxa(g) >= TAXA_MIN_ROSTO]
    g = (min(frequentes, key=lambda g: abs(mediana(g) - centro_x)) if frequentes
         else max(grupos, key=taxa))
    return mediana(g), taxa(g)


def centro_rosto(video: Path, ini: float, fim: float,
                 regiao: tuple[int, int, int, int]) -> tuple[float | None, float]:
    """Detecta rostos (Haar, OpenCV) a cada AMOSTRA_S dentro da região anti-overlay e
    escolhe quem fala. 960px de largura: rápido e ainda pega rosto pequeno no púlpito."""
    import cv2
    rw, rh, rx, ry = regiao
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(video))
    escala = min(1.0, 960 / rw)
    deteccoes, amostras, t = [], 0, ini
    try:
        while t < fim:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            t += AMOSTRA_S
            if not ok:
                continue
            recorte = cv2.resize(frame[ry:ry + rh, rx:rx + rw], None, fx=escala, fy=escala)
            cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
            for fx, fy, fw, fh in detector.detectMultiScale(cinza, scaleFactor=1.1,
                                                            minNeighbors=6, minSize=(20, 20)):
                deteccoes.append({"frame": amostras, "cx": rx + (fx + fw / 2) / escala,
                                  "cy": ry + (fy + fh / 2) / escala, "w": fw / escala})
            amostras += 1
    finally:
        cap.release()
    return escolher_rosto(agrupar_rostos(deteccoes), amostras, rx + rw / 2)


def quebrar_titulo(texto: str) -> str:
    """Manchete em até 3 linhas curtas (\\N é quebra de linha no ASS)."""
    linhas, atual = [], ""
    for p in limpar(texto).split():
        if atual and len(atual) + 1 + len(p) > MAX_CHARS_TITULO:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        linhas.append(atual)
    return "\\N".join(linhas[:3])


def gerar_ass_short(palavras: list[dict], titulo: str, duracao: float) -> str:
    linhas = agrupar_linhas(palavras, max_palavras=3, max_chars=16)
    eventos = [dialogo(0, duracao, "Titulo", quebrar_titulo(titulo)),
               dialogo(0, duracao, "Marca", "MISSÃO EM CORTES"),
               *eventos_karaoke(linhas)]
    return cabecalho_ass(LARGURA, ALTURA, ESTILOS) + "\n".join(eventos) + "\n"


def cmd_short(video: Path, ini: float, dur: float, crop: tuple[int, int, int, int],
              ass: Path, saida: Path) -> tuple[list, Path]:
    w, h, x, y = crop
    vf_ass, cwd = filtro_ass(ass)
    fo = max(0.0, dur - FADE_S)
    vf = (f"crop={w}:{h}:{x}:{y},scale={LARGURA}:{ALTURA}:flags=lanczos,setsar=1,fps=30,"
          f"{vf_ass},fade=t=in:st=0:d={FADE_S},fade=t=out:st={fo:.3f}:d={FADE_S}")
    af = f"afade=t=in:st=0:d={FADE_S},afade=t=out:st={fo:.3f}:d={FADE_S}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{ini:.3f}", "-i", str(video.resolve()), "-t", f"{dur:.3f}",
           "-vf", vf, "-af", af, *VENC, *AENC, str(saida.resolve())]
    return cmd, cwd


def dimensoes(video: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, check=True)
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    if not pos:
        sys.exit("Uso: uv run py scripts/10_shorts.py <stem> [--bloco=N]")
    so_bloco = int(flags["bloco"]) if "bloco" in flags else None

    pasta = achar_pasta(pos[0])
    stem = stem_de(pasta)
    video = INPUTS / f"{stem}.mp4"
    if not video.exists():
        sys.exit(f"[!] {video} não existe — o Short sai do vídeo original (1080p). "
                 f"Baixe de novo: uv run py scripts/01_baixar.py <URL> {stem}")
    words_json = pasta / "words.json"
    if not words_json.exists():
        sys.exit(f"[!] {words_json} não existe — rode o step 2 (02_transcribe.py) antes.")
    todas = json.loads(words_json.read_text(encoding="utf-8"))["words"]
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]

    regiao = ler_zoom(stem)
    if regiao is None:
        vw, vh = dimensoes(video)
        regiao = (vw, vh, 0, 0)
        print(f"[aviso] '{stem}' sem entrada no config/zoom.json — usando o quadro inteiro "
              f"(overlays da live podem aparecer no Short)")

    out_dir = pasta / "shorts"
    out_dir.mkdir(exist_ok=True)
    registro_path = out_dir / "shorts.json"
    registro = (json.loads(registro_path.read_text(encoding="utf-8"))
                if registro_path.exists() else {})
    print(f"Shorts de '{stem}' · custo $0 (sem API)")

    feitos, falhas = 0, 0
    for b in blocos:
        bid, nn = b["id"], f"{b['id']:02d}"
        if so_bloco is not None and bid != so_bloco:
            continue
        co = b.get("cold_open")
        if not co:
            print(f"  [aviso] bloco {bid}: sem cold_open no blocos.json — pulando")
            continue
        ini = max(0.0, hhmmss_para_segundos(co["timestamp_inicio"]) - COLD_PADDING_S)
        fim = hhmmss_para_segundos(co["timestamp_fim"]) + COLD_PADDING_S
        dur = fim - ini

        cx, taxa = centro_rosto(video, ini, fim, regiao)
        crop = janela_9x16(regiao, cx)
        alerta = taxa < TAXA_MIN_ROSTO
        print(f"\n  bloco {bid}: {dur:.0f}s · rosto em {taxa:.0%} dos frames · crop {crop}")
        if alerta:
            print(f"  [aviso] pouco rosto: provável tela compartilhada/plateia — "
                  f"{'centralizado' if cx is None else 'usando o que achou'}, REVISE antes de subir")

        ass = out_dir / f"short_{nn}.ass"
        palavras = palavras_na_janela(todas, ini, fim)
        ass.write_text(gerar_ass_short(palavras, b.get("texto_thumb") or b["tema"], dur),
                       encoding="utf-8")
        saida = out_dir / f"short_{nn}_{slug(b['tema'])}.mp4"
        cmd, cwd = cmd_short(video, ini, dur, crop, ass, saida)
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            falhas += 1
            print(f"  [!] bloco {bid}: ffmpeg falhou:\n{r.stderr[-600:]}")
            continue
        feitos += 1
        registro[nn] = {"arquivo": saida.name, "duracao_s": round(dur, 2),
                        "crop": "{}:{}:{}:{}".format(*crop), "taxa_rosto": round(taxa, 2),
                        "revisar": alerta}
        registro_path.write_text(json.dumps(registro, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        print(f"  OK shorts/{saida.name}")

    print(f"\n{feitos} Short(s) gerado(s), {falhas} falha(s) em {out_dir}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
