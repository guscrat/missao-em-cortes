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
import os
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

from _ffmpeg import AENC, VENC
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent
FONTS_DIR = ROOT / "assets" / "fonts"

# Devem casar com os paddings do 04_cortar.py (timestamp global -> relativo ao corte)
PADDING_INICIO_S = 1.0
PADDING_FIM_S = 2.0

MAX_PALAVRAS = 4        # por linha: curto pra ler de relance
MAX_CHARS = 26          # Anton 72px em 1280 de largura cabe folgado
GAP_QUEBRA_S = 0.7      # pausa maior que isso começa linha nova
FOLGA_FIM_S = 0.3       # linha fica na tela um pouco depois da última palavra

# Cores ASS são &HAABBGGRR (alpha 00 = opaco)
AMARELO_14 = "&H0018C5F5"   # #F5C518
BRANCO = "&H00FFFFFF"
PRETO = "&H000A0A0A"        # #0A0A0A
SOMBRA = "&H80000000"

CABECALHO_ASS = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Anton,72,{AMARELO_14},{BRANCO},{PRETO},{SOMBRA},0,0,0,0,100,100,1,0,1,5,2,2,60,60,56,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def hhmmss_para_segundos(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def palavras_do_bloco(todas: list[dict], bloco: dict) -> list[dict]:
    """Palavras do bloco com tempos relativos ao início do corte_NN.mp4."""
    inicio_s = max(0, hhmmss_para_segundos(bloco["timestamp_inicio"]) - PADDING_INICIO_S)
    fim_s = hhmmss_para_segundos(bloco["timestamp_fim"]) + PADDING_FIM_S
    return [{"word": w["word"].strip(),
             "start": max(0.0, w["start"] - inicio_s),
             "end": max(0.0, w["end"] - inicio_s)}
            for w in todas
            if inicio_s <= w["start"] < fim_s and w["word"].strip()]


def remapear_polido(palavras: list[dict], intervalos: list[dict]) -> list[dict]:
    """Aplica o jump cut do 04b nos tempos: some a palavra que caiu num trecho
    removido e puxa as seguintes pra trás pelo tempo já cortado."""
    ivs = sorted((iv["t_inicio"], iv["t_fim"]) for iv in intervalos)

    def novo_t(t: float) -> float:
        return t - sum(min(fim, t) - ini for ini, fim in ivs if ini < t)

    saida = []
    for w in palavras:
        meio = (w["start"] + w["end"]) / 2
        if any(ini <= meio < fim for ini, fim in ivs):
            continue
        saida.append({**w, "start": novo_t(w["start"]), "end": novo_t(w["end"])})
    return saida


def agrupar_linhas(palavras: list[dict]) -> list[list[dict]]:
    """Linhas curtas: quebra no limite de palavras/chars, em pausa ou fim de frase."""
    linhas, atual = [], []
    for w in palavras:
        if atual:
            texto = " ".join(p["word"] for p in atual + [w])
            if (len(atual) >= MAX_PALAVRAS or len(texto) > MAX_CHARS
                    or w["start"] - atual[-1]["end"] > GAP_QUEBRA_S
                    or atual[-1]["word"][-1] in ".?!"):
                linhas.append(atual)
                atual = []
        atual.append(w)
    if atual:
        linhas.append(atual)
    return linhas


def _ts_ass(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _limpar(texto: str) -> str:
    # chaves e barra invertida são comando no ASS
    return texto.replace("\\", "").replace("{", "").replace("}", "").upper()


def gerar_ass(linhas: list[list[dict]]) -> str:
    eventos = []
    for i, linha in enumerate(linhas):
        ini = linha[0]["start"]
        fim = linha[-1]["end"] + FOLGA_FIM_S
        if i + 1 < len(linhas):
            fim = min(fim, linhas[i + 1][0]["start"])   # nunca duas linhas ao mesmo tempo
        fim = max(fim, linha[-1]["end"])
        partes, cursor = [], ini
        for j, w in enumerate(linha):
            # cada \k vai do início da palavra até o início da próxima (a pausa fica com ela)
            prox = linha[j + 1]["start"] if j + 1 < len(linha) else w["end"]
            dur_cs = max(1, round((max(prox, w["end"]) - cursor) * 100))
            cursor += dur_cs / 100
            partes.append(f"{{\\k{dur_cs}}}{_limpar(w['word'])}")
        eventos.append(f"Dialogue: 0,{_ts_ass(ini)},{_ts_ass(fim)},Karaoke,,0,0,0,,"
                       + " ".join(partes))
    return CABECALHO_ASS + "\n".join(eventos) + "\n"


def cmd_queimar(entrada: Path, ass: Path, saida: Path) -> tuple[list, Path]:
    """Comando ffmpeg + cwd. Roda de dentro da pasta do .ass com caminhos relativos:
    o filtro ass do ffmpeg engasga com 'C:' (o ':' é separador de opção)."""
    fonts = Path(os.path.relpath(FONTS_DIR, ass.parent)).as_posix()
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(entrada.resolve()), "-vf", f"ass={ass.name}:fontsdir={fonts}",
           *VENC, *AENC, str(saida.resolve())]
    return cmd, ass.parent


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
