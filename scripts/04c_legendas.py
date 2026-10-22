"""Step 4c (opcional): legenda burned-in estilo karaokê nos cortes completos.

Uso:
    uv run py scripts/04c_legendas.py <stem> [--polido] [--bloco=N]

Pra cada corte_NN_*.mp4:
  1. Fatia os word-timestamps do words.json (step 2) pelo intervalo do bloco — sem
     re-transcrever, sem API (custo $0)
  2. Com --polido: usa o corte_NN_*_polido.mp4 e remapeia os tempos tirando os
     intervalos que o 04b removeu (polimento.json), pra legenda não dessincronizar
  3. Agrupa as palavras em linhas curtas (até 4 palavras) e gera um .ass com \\k:
     a palavra falada acende em amarelo 14, o resto da linha fica branco
  4. Queima com ffmpeg (filtro ass/libass, fonte Anton) no formato canônico

Saída: cortes/legendados/<mesmo nome do corte>.mp4 (+ legenda_NN.ass, editável à mão
se precisar corrigir uma palavra — rode de novo com --so-queimar pra não regerar o .ass).
Subpasta de propósito: os globs corte_NN_*.mp4 dos outros steps não enxergam os legendados.
Pra montar com eles: 06_montar.py <stem> --legendado [--polido].

Cold opens NÃO são legendados (são curtos e o foco é o vídeo longo).
"""
import json
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

from _ffmpeg import AENC, VENC
from _legenda import (agrupar_linhas as _agrupar, cabecalho_ass, estilo, eventos_karaoke,
                      filtro_ass, hhmmss_para_segundos, palavras_na_janela, remapear_polido)
from _paths import achar_pasta, stem_de

# Devem casar com os paddings do 04_cortar.py (timestamp global -> relativo ao corte)
PADDING_INICIO_S = 1.0
PADDING_FIM_S = 2.0

MAX_PALAVRAS = 4        # por linha: curto pra ler de relance
MAX_CHARS = 26          # Anton 72px em 1280 de largura cabe folgado
ESTILO = estilo("Karaoke", 72, alinhamento=2, margem_v=56)


def palavras_do_bloco(todas: list[dict], bloco: dict) -> list[dict]:
    """Palavras do bloco com tempos relativos ao início do corte_NN.mp4."""
    inicio_s = max(0, hhmmss_para_segundos(bloco["timestamp_inicio"]) - PADDING_INICIO_S)
    fim_s = hhmmss_para_segundos(bloco["timestamp_fim"]) + PADDING_FIM_S
    return palavras_na_janela(todas, inicio_s, fim_s)


def agrupar_linhas(palavras: list[dict]) -> list[list[dict]]:
    return _agrupar(palavras, MAX_PALAVRAS, MAX_CHARS)


def gerar_ass(linhas: list[list[dict]]) -> str:
    return cabecalho_ass(1280, 720, [ESTILO]) + "\n".join(eventos_karaoke(linhas)) + "\n"


def cmd_queimar(entrada: Path, ass: Path, saida: Path) -> tuple[list, Path]:
    """Comando ffmpeg + cwd (o filtro ass roda de dentro da pasta do .ass)."""
    vf, cwd = filtro_ass(ass)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(entrada.resolve()), "-vf", vf,
           *VENC, *AENC, str(saida.resolve())]
    return cmd, cwd


def encontrar_corte(cortes_dir: Path, bloco_id: int, polido: bool) -> Path | None:
    nn = f"{bloco_id:02d}"
    if polido:
        achados = sorted(cortes_dir.glob(f"corte_{nn}_*_polido.mp4"))
    else:
        achados = sorted(p for p in cortes_dir.glob(f"corte_{nn}_*.mp4")
                         if "_polido" not in p.stem)
    return achados[0] if achados else None


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True)
                 for a in argv if a.startswith("--"))
    if not pos:
        sys.exit("Uso: uv run py scripts/04c_legendas.py <stem> [--polido] [--bloco=N] [--so-queimar]")
    polido = bool(flags.get("polido"))
    so_bloco = int(flags["bloco"]) if "bloco" in flags else None
    so_queimar = bool(flags.get("so-queimar"))

    pasta = achar_pasta(pos[0])
    words_json = pasta / "words.json"
    if not words_json.exists():
        sys.exit(f"[!] {words_json} não existe — rode o step 2 (02_transcribe.py) antes.")
    todas = json.loads(words_json.read_text(encoding="utf-8"))["words"]
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
    polimento = {}
    if polido:
        pj = pasta / "polimento.json"
        if not pj.exists():
            sys.exit(f"[!] --polido sem {pj.name} — rode o 04b_polir.py antes ou tire o --polido.")
        polimento = {b["id"]: b["intervalos_remover"]
                     for b in json.loads(pj.read_text(encoding="utf-8"))["blocos"]}

    cortes_dir = pasta / "cortes"
    out_dir = cortes_dir / "legendados"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Legendando '{stem_de(pasta)}'{' (polidos)' if polido else ''} · custo $0 (sem API)")

    feitos, falhas = 0, 0
    for b in blocos:
        bid = b["id"]
        if so_bloco is not None and bid != so_bloco:
            continue
        corte = encontrar_corte(cortes_dir, bid, polido)
        if not corte:
            print(f"  [!] bloco {bid}: corte{' polido' if polido else ''} não encontrado — pulando")
            continue
        ass = out_dir / f"legenda_{bid:02d}{'_polido' if polido else ''}.ass"
        if not (so_queimar and ass.exists()):
            palavras = palavras_do_bloco(todas, b)
            if polido:
                palavras = remapear_polido(palavras, polimento.get(bid, []))
            linhas = agrupar_linhas(palavras)
            ass.write_text(gerar_ass(linhas), encoding="utf-8")
            print(f"  bloco {bid}: {len(palavras)} palavras em {len(linhas)} linhas → {ass.name}")
        saida = out_dir / corte.name
        cmd, cwd = cmd_queimar(corte, ass, saida)
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            falhas += 1
            print(f"  [!] bloco {bid}: ffmpeg falhou:\n{r.stderr[-600:]}")
            continue
        feitos += 1
        print(f"  OK {saida.relative_to(pasta).as_posix()}")

    print(f"\n{feitos} corte(s) legendado(s), {falhas} falha(s). "
          f"Monte com: 06_montar.py {pos[0]} --legendado{' --polido' if polido else ''}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
