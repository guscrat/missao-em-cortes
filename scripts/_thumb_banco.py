"""Banco de rostos dos apresentadores: reserva da thumb (02/11/2026).

Regra de produto: a thumb nunca derruba um corte. Quando nenhum frame do corte nem da live
inteira passa no revisor (11), a thumb usa um frame já APROVADO do mesmo apresentador, de
outra live. Cada bloco aprovado pelo revisor guarda aqui o frame da thumb escolhida (a).

Onde fica: state/rostos/<pessoa>/<pasta>_<NN>.png + .json (rosto, nota, origem). Fica fora
do git (state/ é gitignored; repo é público e o frame é da live de terceiros).
Até MAX_POR_PESSOA por pessoa, os de maior nota (rosto grande, iluminado, nítido).

Uso:
    uv run py scripts/_thumb_banco.py popular     # guarda os frames das lives já aprovadas
    uv run py scripts/_thumb_banco.py lista

Custo: $0 (ffmpeg local).
"""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent.parent
BANCO = ROOT / "state" / "rostos"
MAX_POR_PESSOA = 12


def slug(nome: str) -> str:
    t = unicodedata.normalize("NFKD", nome.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def apresentador(bloco: dict) -> str | None:
    """Quem fala no bloco (o 1º de speakers_principais): é o rosto que a thumb mostra."""
    falantes = bloco.get("speakers_principais") or []
    if not falantes:
        return None
    nome = falantes[0].strip()
    m = re.fullmatch(r"speaker\s*\((.+)\)", nome, flags=re.IGNORECASE)   # "Speaker (Arthur do Val)"
    return m.group(1).strip() if m else nome


def extrair_frame(video: Path, t: float, saida: Path, crop: str | None = None) -> None:
    """Frame em t segundos (PNG). crop: o zoom do 04 (frame da live crua) → 1280x720."""
    vf = ["-vf", f"crop={crop},scale=1280:720"] if crop else []
    subprocess.run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), *vf,
                    "-frames:v", "1", "-q:v", "2", "-loglevel", "error", str(saida)], check=True)


def video_do_candidato(pasta: Path, cand: dict) -> Path:
    """Candidato do corte guarda só o nome (em cortes/); o da live e o do banco, o caminho."""
    v = Path(cand["video"])
    return v if v.is_absolute() else pasta / "cortes" / v


def _metas(pessoa: str) -> list[tuple[Path, dict]]:
    pasta = BANCO / slug(pessoa)
    saida = []
    for meta in sorted(pasta.glob("*.json")) if pasta.exists() else []:
        png = meta.with_suffix(".png")
        try:
            dados = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if png.exists():
            saida.append((png, dados))
    return saida


def podar(pessoa: str) -> None:
    """Fica só com os MAX_POR_PESSOA de maior nota."""
    for png, _ in sorted(_metas(pessoa), key=lambda x: -x[1].get("nota", 0))[MAX_POR_PESSOA:]:
        png.unlink(missing_ok=True)
        png.with_suffix(".json").unlink(missing_ok=True)


def guardar(pasta: Path, bloco: dict) -> Path | None:
    """Guarda o frame da thumb a de um bloco aprovado. None se não dá (sem fila, sem rosto,
    o frame já veio do banco ou ffmpeg falhou). Nunca levanta: é reserva, não derruba nada."""
    pessoa, bid = apresentador(bloco), bloco["id"]
    try:
        fila = json.loads((pasta / "thumbs" / f"candidatos_{bid:02d}.json").read_text(encoding="utf-8"))
        cand = fila["candidatos"][fila["variantes"]["a"]]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    if not pessoa or not cand.get("rosto") or cand.get("fonte") == "banco":
        return None
    destino = BANCO / slug(pessoa) / f"{pasta.name}_{bid:02d}.png"
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        extrair_frame(video_do_candidato(pasta, cand), cand["t"], destino, cand.get("crop"))
    except (subprocess.CalledProcessError, OSError):
        return None
    destino.with_suffix(".json").write_text(json.dumps(
        {"pessoa": pessoa, "rosto": cand["rosto"], "nota": cand.get("nota", 0),
         "origem": f"{pasta.name} bloco {bid:02d} @ {cand['t']:.1f}s ({cand.get('fonte')})"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    podar(pessoa)
    return destino if destino.exists() else None


def candidatos(pessoa: str | None, excluir: str = "") -> list[dict]:
    """Frames do banco dessa pessoa no formato da fila do 07 (melhor primeiro). `excluir`:
    prefixo do nome (a pasta da live atual: o frame dela já foi tentado)."""
    if not pessoa:
        return []
    saida = [{"fonte": "banco", "video": str(png), "t": 0.0, "nota": d.get("nota", 0),
              "rosto": d.get("rosto"), "origem": d.get("origem", "")}
             for png, d in _metas(pessoa)
             if d.get("rosto") and not (excluir and png.stem.startswith(excluir))]
    return sorted(saida, key=lambda c: -c["nota"])


def popular() -> int:
    """Backfill: frame da thumb a de cada bloco aprovado nas lives já processadas."""
    n = 0
    for rev in sorted((ROOT / "outputs").glob("*/revisao.json")):
        pasta = rev.parent
        try:
            revisao = json.loads(rev.read_text(encoding="utf-8"))
            blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
        except (OSError, ValueError, KeyError):
            continue
        for b in blocos:
            if (revisao.get(f"{b['id']:02d}") or {}).get("status") == "aprovado" and guardar(pasta, b):
                n += 1
    return n


def main(argv: list[str]) -> int:
    if argv[:1] == ["popular"]:
        print(f"{popular()} frame(s) guardado(s) em {BANCO}")
    elif argv[:1] == ["lista"]:
        for pasta in sorted(BANCO.glob("*")) if BANCO.exists() else []:
            print(f"{pasta.name}: {len(list(pasta.glob('*.png')))} frame(s)")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
