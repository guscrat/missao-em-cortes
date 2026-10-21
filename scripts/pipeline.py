"""Roda o pipeline completo pra um stem: (02) -> 03 -> 04 -> (04b) -> (04c) -> 05 -> 06 -> 07 -> 08.

Uso: uv run py scripts/pipeline.py <stem> [--polir] [--sem-llm] [--legendas] [--desde=N]

  --polir     inclui o polimento (04b, ~$0.20 de API) e monta com --polido
  --sem-llm   com --polir: 04b só remove silêncios programáticos (custo $0,
              sem cortes de fillers/problemas técnicos)
  --legendas  inclui a legenda karaokê burned-in (04c, $0) e monta com --legendado
  --desde=N   retoma a partir do step N (aceita 4b e 4c). Ex: --desde=4 pra re-cortar
              depois de recalibrar o zoom, sem re-segmentar.

Sem --desde, detecta sozinho: pula o step 2 se a transcrição já existe.
Cada step é o script de sempre rodado em sequência (mesma saída no terminal);
para na primeira falha e mostra o --desde pra retomar de onde parou.
Custo de API: step 3 (~$0.20) + step 4b se --polir (~$0.20; $0 com --sem-llm). 4c: $0.

O download (01_baixar.py) fica de fora de propósito — rode antes, uma vez.
"""
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
import time
from pathlib import Path
from _paths import stem_de
from _eventos import evento

ROOT = Path(__file__).parent.parent
SCRIPTS = Path(__file__).parent
OUTPUTS = ROOT / "outputs"

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]

if not args:
    sys.exit("Uso: uv run py scripts/pipeline.py <stem> [--polir] [--desde=N]")

alvo = args[0]                    # stem ou nome completo da pasta (os steps resolvem)
stem = stem_de(Path(alvo))        # stem puro, pra achar inputs/<stem>.mp4
polir = "--polir" in flags
sem_llm = "--sem-llm" in flags
legendas = "--legendas" in flags

desde = None
for f in flags:
    if f.startswith("--desde="):
        v = f.split("=", 1)[1]
        desde = {"4b": 4.5, "4c": 4.7}.get(v) or float(v)

VIDEO = ROOT / "inputs" / f"{stem}.mp4"
tem_transcricao = any(
    (p / "transcricao.txt").exists() for p in OUTPUTS.glob(f"*_{stem}") if p.is_dir()
)

if desde is None:
    desde = 3.0 if tem_transcricao else 2.0
    if tem_transcricao:
        print(f"Transcrição já existe — começando do step 3 (use --desde=2 pra re-transcrever)")

if desde <= 2 and not VIDEO.is_file():
    sys.exit(f"[!] {VIDEO} não existe. Baixe antes: "
             f"uv run py scripts/01_baixar.py <URL> {stem}")

# (numero, script, args) — o 4b/4c/6 mudam conforme --polir/--legendas
steps = [
    (2.0, "02_transcribe.py", [str(VIDEO)]),
    (3.0, "03_segmentar.py", [alvo]),
    (4.0, "04_cortar.py", [alvo]),
    *([(4.5, "04b_polir.py", [alvo] + (["--sem-llm"] if sem_llm else []))] if polir else []),
    *([(4.7, "04c_legendas.py", [alvo] + (["--polido"] if polir else []))] if legendas else []),
    (5.0, "05_cards.py", [alvo]),
    (6.0, "06_montar.py", [alvo] + (["--polido"] if polir else [])
                          + (["--legendado"] if legendas else [])),
    (7.0, "07_thumb.py", [alvo]),
    (8.0, "08_descricao.py", [alvo]),
]

rotulo = {2.0: "2", 3.0: "3", 4.0: "4", 4.5: "4b", 4.7: "4c", 5.0: "5", 6.0: "6", 7.0: "7", 8.0: "8"}
t0 = time.time()

for num, script, sargs in steps:
    if num < desde:
        continue
    print(f"\n{'=' * 60}")
    print(f">> Step {rotulo[num]}: {script} {' '.join(sargs)}")
    print(f"{'=' * 60}")
    t_step = time.time()
    etapa = script.removesuffix(".py")
    evento(stem, etapa, "inicio")
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *sargs])
    if result.returncode != 0:
        evento(stem, etapa, "falha", mensagem=f"exit {result.returncode}",
               duracao_s=time.time() - t_step)
        sys.exit(f"\n[!] Step {rotulo[num]} ({script}) falhou (exit {result.returncode}). "
                 f"Depois de corrigir, retome com:\n"
                 f"    uv run py scripts/pipeline.py {alvo}"
                 f"{' --polir' if polir else ''}{' --sem-llm' if sem_llm else ''}"
                 f"{' --legendas' if legendas else ''}"
                 f" --desde={rotulo[num]}")
    evento(stem, etapa, "ok", duracao_s=time.time() - t_step)
    print(f"   (step {rotulo[num]}: {(time.time() - t_step) / 60:.1f} min)")

# Atualiza o painel com o que os steps geraram (cortes, finalizados, thumbs)
subprocess.run([sys.executable, str(SCRIPTS / "sincronizar_estado.py")],
               stdout=subprocess.DEVNULL)

print(f"\n{'=' * 60}")
print(f"OK Pipeline completo pra '{alvo}' em {(time.time() - t0) / 60:.1f} min")
print(f"   Finalizados em outputs/*_{stem}/finalizados/")
print(f"   Falta você: escolher thumbs (a/b/c) no Canva + revisar descricoes.txt + subir")
