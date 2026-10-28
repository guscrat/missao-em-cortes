"""Capítulos do YouTube na descrição dos longos ("00:00 Título" por mudança de assunto).

Quem usa:
  - 03_segmentar: o LLM devolve `capitulos` no bloco (título curto + frase literal de abertura,
    na mesma chamada, sem custo extra relevante); ancorar() acha o tempo real pelo words.json
  - 08_descricao: linhas() converte o tempo da live pro tempo do VÍDEO FINAL e aplica as regras
    do YouTube (1º em 00:00, ≥ 3 capítulos, cada um com ≥ 10 s)
  - 11_revisor: no_video() lê os capítulos do descricoes.txt (edição manual vale) e para_live()
    leva cada um de volta pra transcrição, pro revisor conferir se o título bate com o trecho

Vídeo final = [cold open] → [intro] → [card] → [corte, com os jump cuts do 04b se for o polido]
→ [outro]. O capítulo 00:00 cobre cold open + intro + card + o começo do corte. A duração de
cold open, intro, card e outro é MEDIDA nos arquivos que o 06 usou (ffprobe); as constantes
abaixo só valem quando a medição falha (arquivo faltando, ffprobe fora do PATH).
Custo: $0 (sem API).
"""
import functools
import json
import re
import subprocess
from pathlib import Path

import _fronteira as fr
from _legenda import hhmmss_para_segundos
from _paths import escolher_arquivo

ROOT = Path(__file__).parent.parent
# reserva, se o ffprobe falhar
INTRO_S = 3.0          # = INTRO_SEGUNDOS do 06_montar
CARD_S = 3.0           # = duração do card do 05_cards
OUTRO_S = 5.0
MIN_CAPITULOS, MAX_CAPITULOS = 3, 8
MIN_CAPITULO_S = 10.0  # regra do YouTube
MIN_CORTE_MIN = 8.0    # só corte de 8 min ou mais ganha capítulos
JANELA_S = fr.JANELA_TRECHO_S   # encaixe do início do capítulo no começo de frase
TITULO_MAX = 50        # chars: capítulo é rótulo curto

CABECALHO = "Capítulos:"
_LINHA = re.compile(r"^((?:\d{1,2}:)?\d{1,2}:\d{2}) (.+)$")


def ancorar(palavras: list[dict], capitulos: list[dict], ini: float, fim: float) -> tuple[list[dict], list[str]]:
    """Capítulos do LLM com o tempo real (frase_de_abertura no words.json, encaixada no começo
    de frase), dentro de [ini, fim), em ordem, o 1º no início do bloco. Devolve (capítulos,
    avisos). Sem words.json, fica o tempo do LLM."""
    avisos, saida = [], []
    for c in capitulos or []:
        titulo = " ".join(str(c.get("titulo") or "").split())
        try:
            t = hhmmss_para_segundos(c["timestamp_inicio"])
        except (KeyError, ValueError, AttributeError):
            avisos.append(f"capítulo '{titulo}' com tempo ilegível — fora")
            continue
        if not titulo:
            continue
        if palavras:
            t = fr.ancorar(palavras, c.get("frase_de_abertura") or "", t, "inicio") or t
            t = fr.ajustar_inicio(palavras, t, JANELA_S) or t
        if not ini - JANELA_S <= t < fim:   # o encaixe pode puxar o 1º pra antes da abertura
            avisos.append(f"capítulo '{titulo}' fora do bloco — fora")
            continue
        saida.append({**c, "titulo": titulo[:TITULO_MAX].rstrip(),
                      "timestamp_inicio": fr.segundos_para_ts(max(t, ini))})
    saida.sort(key=lambda c: hhmmss_para_segundos(c["timestamp_inicio"]))
    if saida:
        saida[0]["timestamp_inicio"] = fr.segundos_para_ts(ini)   # 1º = abertura do corte
    if len(saida) > MAX_CAPITULOS:
        avisos.append(f"{len(saida)} capítulos — ficam os {MAX_CAPITULOS} primeiros")
        saida = saida[:MAX_CAPITULOS]
    return saida, avisos


@functools.lru_cache(maxsize=None)
def _ffprobe(caminho: str, mtime: float) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", caminho],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        d = float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return d if d > 0 else None


def duracao_s(video: Path | None) -> float | None:
    """Duração real do arquivo (ffprobe), ou None se não existe ou não deu pra medir. Cache por
    arquivo+mtime: a intro e o outro são os mesmos em todos os blocos."""
    if not video or not video.is_file():
        return None
    return _ffprobe(str(video), video.stat().st_mtime)


def _primeiro(pasta: Path, padrao: str) -> Path | None:
    achados = sorted(pasta.glob(padrao)) if pasta.is_dir() else []
    return achados[0] if achados else None


class LinhaDoTempo:
    """Tempo da live ↔ tempo do vídeo final de um bloco, montado como o 06 monta."""

    def __init__(self, pasta: Path, bloco: dict, palavras: list[dict]):
        nn = f"{bloco['id']:02d}"
        self.ini, self.fim = fr.janela(palavras, hhmmss_para_segundos(bloco["timestamp_inicio"]),
                                       hhmmss_para_segundos(bloco["timestamp_fim"]))
        # o vídeo que sobe (09): o polido leva os jump cuts do polimento.json
        video = escolher_arquivo(pasta / "finalizados", f"video_{nn}_*.mp4")
        self.reserva = []   # partes que não deu pra medir (valem as constantes/janela)

        # cold open: o mesmo que o 06 usou (legendado se o vídeo é _legendado e ele existe)
        cold_arq = None
        if video and video.stem.endswith("_legendado"):
            cold_arq = _primeiro(pasta / "cortes" / "legendados", f"cold_{nn}_*.mp4")
        cold_arq = cold_arq or _primeiro(pasta / "cortes", f"cold_{nn}_*.mp4")
        cold = 0.0
        if cold_arq:
            cold = duracao_s(cold_arq)
            co = bloco.get("cold_open")
            if cold is None and co:
                self.reserva.append("cold open")
                a, z = fr.janela(palavras, hhmmss_para_segundos(co["timestamp_inicio"]),
                                 hhmmss_para_segundos(co["timestamp_fim"]),
                                 fr.COLD_PADDING_S, fr.COLD_PADDING_S)
                cold = z - a
            cold = cold or 0.0
        intro = (duracao_s(ROOT / "assets" / "intro_trim.mp4")
                 or duracao_s(ROOT / "assets" / "intro_norm.mp4"))
        card = duracao_s(pasta / "cards" / f"card_{nn}.mp4")
        outro = duracao_s(ROOT / "assets" / "outro_norm.mp4")
        for nome, medido in (("intro", intro), ("card", card), ("outro", outro)):
            if medido is None:
                self.reserva.append(nome)
        self.offset = cold + (intro or INTRO_S) + (card or CARD_S)
        self.ivs = []
        if video and "_polido" in video.stem and (pasta / "polimento.json").exists():
            pol = json.loads((pasta / "polimento.json").read_text(encoding="utf-8"))
            self.ivs = sorted((iv["t_inicio"], iv["t_fim"]) for pb in pol.get("blocos", [])
                              if pb.get("id") == bloco["id"]
                              for iv in pb.get("intervalos_remover", []))
        self.corte_s = (self.fim - self.ini) - sum(z - a for a, z in self.ivs)
        self.total_s = self.offset + self.corte_s + (outro or OUTRO_S)

    def para_video(self, t_live: float) -> float:
        t = min(max(t_live - self.ini, 0.0), self.fim - self.ini)
        return self.offset + t - sum(min(z, t) - a for a, z in self.ivs if a < t)

    def para_live(self, t_video: float) -> float:
        t = max(t_video - self.offset, 0.0)
        for a, z in self.ivs:      # desfaz os jump cuts em ordem
            if a <= t:
                t += z - a
        return self.ini + min(t, self.fim - self.ini)


def mmss(t: float) -> str:
    t = int(t)
    h, m, s = t // 3600, t // 60 % 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def linhas(capitulos: list[dict], tempo: LinhaDoTempo, corrigir=lambda s: s) -> list[str]:
    """"MM:SS Título" no tempo do vídeo final, com as regras do YouTube: 1º em 00:00, cada um com
    ≥ 10 s (o que ficaria curto sai), ≥ 3 no total. Corte < 8 min ou < 3 capítulos: []."""
    if tempo.corte_s < MIN_CORTE_MIN * 60 or len(capitulos or []) < MIN_CAPITULOS:
        return []
    pontos = []
    for i, c in enumerate(capitulos[:MAX_CAPITULOS]):
        t = 0.0 if i == 0 else tempo.para_video(hhmmss_para_segundos(c["timestamp_inicio"]))
        if pontos and t - pontos[-1][0] < MIN_CAPITULO_S:
            continue
        pontos.append((t, corrigir(c["titulo"])))
    while len(pontos) > 1 and tempo.total_s - pontos[-1][0] < MIN_CAPITULO_S:
        pontos.pop()
    if len(pontos) < MIN_CAPITULOS:
        return []
    return [f"{mmss(t)} {titulo}" for t, titulo in pontos]


def no_video(descricao: str) -> list[tuple[float, str]]:
    """[(segundo no vídeo, título)] da seção "Capítulos:" de uma descrição."""
    saida, dentro = [], False
    for linha in descricao.replace("\r\n", "\n").split("\n"):
        if linha.strip() == CABECALHO:
            dentro = True
            continue
        m = _LINHA.match(linha.strip()) if dentro else None
        if not m:
            if dentro and saida:
                break
            continue
        ts = m.group(1) if m.group(1).count(":") == 2 else f"0:{m.group(1)}"
        saida.append((hhmmss_para_segundos(ts), m.group(2).strip()))
    return saida
