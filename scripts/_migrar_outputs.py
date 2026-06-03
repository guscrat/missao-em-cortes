"""Migração one-off: estrutura antiga do outputs/ -> pasta por vídeo.

Antes:  outputs/<stem>_blocos.json + outputs/cortes/<stem>/ + ...
Depois: outputs/<AAAA-MM-DD>_<stem>/{blocos.json, cortes/, ...}

Data = mtime do blocos.json (fallback: transcricao.txt). Dry-run por padrão;
passe --executar pra mover de verdade. Não toca em _old/_calibracao/_debug.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUTS = ROOT / "outputs"
EXECUTAR = "--executar" in sys.argv[1:]

SUFIXOS = {
    "_transcricao.txt": "transcricao.txt",
    "_words.json": "words.json",
    "_blocos.json": "blocos.json",
    "_polimento.json": "polimento.json",
    "_descricoes.txt": "descricoes.txt",
}
TIPOS = ["cortes", "cards", "thumbs", "finalizados"]


def data_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


stems = sorted(p.name[: -len("_transcricao.txt")]
               for p in OUTPUTS.glob("*_transcricao.txt"))
if not stems:
    print("Nada solto pra migrar (nenhum *_transcricao.txt na raiz do outputs/).")
    sys.exit(0)

print(f"{'EXECUTANDO' if EXECUTAR else 'DRY-RUN (use --executar pra mover)'} "
      f"· {len(stems)} vídeo(s)\n")

total_moves = 0
for stem in stems:
    blocos = OUTPUTS / f"{stem}_blocos.json"
    base = blocos if blocos.exists() else OUTPUTS / f"{stem}_transcricao.txt"
    dest = OUTPUTS / f"{data_iso(base)}_{stem}"

    moves = []
    for suf, novo in SUFIXOS.items():
        src = OUTPUTS / f"{stem}{suf}"
        if src.exists():
            moves.append((src, dest / novo))
    for t in TIPOS:
        src = OUTPUTS / t / stem
        if src.is_dir():
            moves.append((src, dest / t))

    print(f"{dest.name}/  ({len(moves)} itens)")
    for src, dst in moves:
        rel_src = src.relative_to(OUTPUTS)
        print(f"    {rel_src}  ->  {dst.relative_to(OUTPUTS)}")
        if EXECUTAR:
            dest.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"      [pulado: destino já existe]")
                continue
            shutil.move(str(src), str(dst))
    total_moves += len(moves)
    print()

print(f"{'Movidos' if EXECUTAR else 'Seriam movidos'}: {total_moves} itens em {len(stems)} pastas.")
if not EXECUTAR:
    print("Reveja acima e rode com --executar pra aplicar.")
