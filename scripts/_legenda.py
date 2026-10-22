"""Legenda karaokê (.ass) compartilhada pelo 04c (vídeo longo) e pelo 10 (Shorts).

Palavras vêm do words.json (step 2). O .ass usa \\k: a palavra acende na cor
primária (amarelo 14) quando é falada; o resto da linha fica na secundária (branco).
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
FONTS_DIR = ROOT / "assets" / "fonts"

GAP_QUEBRA_S = 0.7      # pausa maior que isso começa linha nova
FOLGA_FIM_S = 0.3       # linha fica na tela um pouco depois da última palavra

# Cores ASS são &HAABBGGRR (alpha 00 = opaco)
AMARELO_14 = "&H0018C5F5"   # #F5C518
BRANCO = "&H00FFFFFF"
PRETO = "&H000A0A0A"        # #0A0A0A
SOMBRA = "&H80000000"

_FORMATO_ESTILO = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                   "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
                   "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
                   "MarginR, MarginV, Encoding")


def hhmmss_para_segundos(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def palavras_na_janela(todas: list[dict], inicio_s: float, fim_s: float) -> list[dict]:
    """Palavras do words.json em [inicio_s, fim_s), com tempos relativos a inicio_s."""
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


def agrupar_linhas(palavras: list[dict], max_palavras: int, max_chars: int) -> list[list[dict]]:
    """Linhas curtas: quebra no limite de palavras/chars, em pausa ou fim de frase."""
    linhas, atual = [], []
    for w in palavras:
        if atual:
            texto = " ".join(p["word"] for p in atual + [w])
            if (len(atual) >= max_palavras or len(texto) > max_chars
                    or w["start"] - atual[-1]["end"] > GAP_QUEBRA_S
                    or atual[-1]["word"][-1] in ".?!"):
                linhas.append(atual)
                atual = []
        atual.append(w)
    if atual:
        linhas.append(atual)
    return linhas


def ts_ass(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def limpar(texto: str) -> str:
    # chaves e barra invertida são comando no ASS
    return texto.replace("\\", "").replace("{", "").replace("}", "").upper()


def estilo(nome: str, tamanho: int, alinhamento: int, margem_v: int,
           primaria: str = AMARELO_14, secundaria: str = BRANCO,
           borda: int = 1, contorno: int = 5, fundo: str = SOMBRA) -> str:
    """Linha Style do ASS. alinhamento: numpad (2 = embaixo/centro, 8 = topo/centro);
    borda 1 = contorno, 3 = caixa opaca (usa a cor de fundo)."""
    return (f"Style: {nome},Anton,{tamanho},{primaria},{secundaria},{PRETO},{fundo},"
            f"0,0,0,0,100,100,1,0,{borda},{contorno},2,{alinhamento},60,60,{margem_v},1")


def cabecalho_ass(largura: int, altura: int, estilos: list[str]) -> str:
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {largura}\nPlayResY: {altura}\n"
            f"WrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n{_FORMATO_ESTILO}\n"
            + "\n".join(estilos)
            + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
              "MarginV, Effect, Text\n")


def dialogo(ini: float, fim: float, nome_estilo: str, texto: str) -> str:
    return f"Dialogue: 0,{ts_ass(ini)},{ts_ass(fim)},{nome_estilo},,0,0,0,,{texto}"


def eventos_karaoke(linhas: list[list[dict]], nome_estilo: str = "Karaoke") -> list[str]:
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
            partes.append(f"{{\\k{dur_cs}}}{limpar(w['word'])}")
        eventos.append(dialogo(ini, fim, nome_estilo, " ".join(partes)))
    return eventos


def filtro_ass(ass: Path) -> tuple[str, Path]:
    """(filtro, cwd) pro ffmpeg. Roda de dentro da pasta do .ass com caminhos relativos:
    o filtro ass do ffmpeg engasga com 'C:' (o ':' é separador de opção)."""
    fonts = Path(os.path.relpath(FONTS_DIR, ass.parent)).as_posix()
    return f"ass={ass.name}:fontsdir={fonts}", ass.parent
