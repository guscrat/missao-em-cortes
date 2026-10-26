"""Pontos de corte naturais: fim de frase + pausa, pelos tempos das palavras (words.json).

Regra editorial (coerência acima da duração): corte começa e termina em ponto natural,
nunca no meio da fala. Quem usa:
  - 03_segmentar: encaixa os tempos aproximados do LLM no fim de frase mais próximo
  - 04/04b/04c/10: janela() é a janela REAL do vídeo (padding sem vazar a frase vizinha)
  - 11_revisor: checar() reprova corte que começa/termina no meio de frase; reajusta com encaixar()

Fim natural = a palavra termina com . ! ? (reticências não) E tem pausa depois (PAUSA_FIM_S), ou
não tem pontuação nenhuma e a pausa é longa (PAUSA_LONGA_S): o whisper às vezes não pontua.
Vírgula/reticências + pausa não é fim: a frase continua.
Início natural = a palavra anterior é um fim de frase (pontuação ou pausa longa).
Custo: $0 (sem API).
"""
import bisect
import difflib
import re
import unicodedata

FIM_FRASE = (".", "!", "?")
PAUSA_FIM_S = 0.5        # silêncio mínimo depois da última palavra do corte
PAUSA_LONGA_S = 1.2      # pausa que vale como fim de raciocínio mesmo sem pontuação
FOLGA_S = 0.08           # respiro entre a palavra vizinha e a borda da janela

# Folga das janelas (o padding de sempre do 04), agora limitada pela palavra vizinha
PADDING_INICIO_S = 1.0
PADDING_FIM_S = 2.0
COLD_PADDING_S = 0.5

# Até onde procurar um ponto natural a partir do tempo pedido
JANELA_BLOCO_S = 30.0    # longo: o LLM só vê o segundo cheio do segmento
JANELA_TRECHO_S = 10.0   # cold open e Short

# Faixas de duração dos longos (minutos): o Analista compara retenção por faixa
LONGO_MIN, LONGO_MAX = 8.0, 30.0
SHORT_MAX_S = 175.0      # limite do YouTube é 3 min; folga pro padding e fade
FAIXAS = (("curto", 8.0, 12.0), ("medio", 12.0, 20.0), ("longo", 20.0, 30.0))


def faixa(minutos: float | None) -> str | None:
    """'curto' (8-12), 'medio' (12-20), 'longo' (20-30), 'fora' (fora de 8-30) ou None."""
    if minutos is None:
        return None
    for nome, ini, fim in FAIXAS:
        if ini <= minutos < fim or (nome == "longo" and minutos == fim):
            return nome
    return "fora"


def termina_frase(palavra: str) -> bool:
    """Termina com . ! ? — reticências não: no whisper são hesitação ("eu quero dizer é...")."""
    p = palavra.strip().rstrip("\"'”»)")
    return p.endswith(FIM_FRASE) and not p.endswith(("..", "…"))


def pausa_depois(palavras: list[dict], i: int) -> float:
    return palavras[i + 1]["start"] - palavras[i]["end"] if i + 1 < len(palavras) else float("inf")


def sem_pontuacao(palavra: str) -> bool:
    """O whisper não pontuou (a pausa longa decide). Vírgula, reticências, dois-pontos: a
    frase continua, mesmo com pausa."""
    p = palavra.strip().rstrip("\"'”»)")
    return bool(p) and (p[-1].isalnum())


def eh_fim(palavras: list[dict], i: int) -> bool:
    p, w = pausa_depois(palavras, i), palavras[i]["word"]
    return p >= PAUSA_FIM_S and (termina_frase(w) or (sem_pontuacao(w) and p >= PAUSA_LONGA_S))


def eh_inicio(palavras: list[dict], i: int) -> bool:
    if i == 0:
        return True
    w = palavras[i - 1]["word"]
    return termina_frase(w) or (sem_pontuacao(w) and pausa_depois(palavras, i - 1) >= PAUSA_LONGA_S)


def janela(palavras: list[dict], ini: float, fim: float,
           pad_ini: float = PADDING_INICIO_S, pad_fim: float = PADDING_FIM_S) -> tuple[float, float]:
    """(início, fim) do vídeo: o trecho + padding, sem pegar pedaço da palavra vizinha.
    Palavra que já começou antes de `fim` entra inteira; a seguinte fica de fora."""
    a, b = max(0.0, ini - pad_ini), fim + pad_fim
    if not palavras:
        return a, b
    palavras = sorted(palavras, key=lambda w: w["start"])
    starts = [w["start"] for w in palavras]
    i = bisect.bisect_left(starts, ini - 0.01)       # primeira palavra do trecho
    if i > 0 and palavras[i - 1]["end"] <= ini + 0.01:
        a = max(a, palavras[i - 1]["end"] + FOLGA_S)
    j = bisect.bisect_left(starts, fim - 0.01)       # primeira que começa depois do fim
    if 0 < j < len(palavras) and palavras[j - 1]["end"] > fim:
        j_fim = palavras[j - 1]["end"]               # o fim caiu no meio da palavra: inclui
        b = max(min(b, palavras[j]["start"] - FOLGA_S), j_fim + 0.1)
    elif j < len(palavras):
        b = min(b, max(palavras[j]["start"] - FOLGA_S, fim))
    return a, b


def checar(palavras: list[dict], ini: float, fim: float, pad_ini: float = PADDING_INICIO_S,
           pad_fim: float = PADDING_FIM_S) -> dict:
    """Confere o que se ouve no vídeo: a 1ª palavra abre frase? a última fecha frase e tem
    pausa depois? Sem palavras (sem words.json): ok (não dá pra checar)."""
    a, b = janela(palavras, ini, fim, pad_ini, pad_fim)
    dentro = [k for k, w in enumerate(palavras) if a <= w["start"] < b]
    if not dentro:
        return {"inicio_ok": True, "fim_ok": True, "primeiras": "", "ultimas": "",
                "pausa_depois_s": None}
    i, j = dentro[0], dentro[-1]
    pausa = pausa_depois(palavras, j)
    return {"inicio_ok": eh_inicio(palavras, i), "fim_ok": eh_fim(palavras, j),
            "primeiras": " ".join(w["word"] for w in palavras[i:i + 8]),
            "ultimas": " ".join(w["word"] for w in palavras[max(i, j - 7):j + 1]),
            "pausa_depois_s": None if pausa == float("inf") else round(pausa, 2)}


def ajustar_inicio(palavras: list[dict], t: float, janela_s: float) -> float | None:
    """Início natural mais perto de t (até janela_s), no começo exato da palavra."""
    cands = [w["start"] for k, w in enumerate(palavras)
             if abs(w["start"] - t) <= janela_s and eh_inicio(palavras, k)]
    return min(cands, key=lambda s: abs(s - t)) if cands else None


def ajustar_fim(palavras: list[dict], t: float, janela_s: float,
                minimo: float | None = None, maximo: float | None = None) -> float | None:
    """Fim natural mais perto de t (até janela_s), no fim exato da palavra, dentro de
    [minimo, maximo]. Empate pende pra DEPOIS: fechar o raciocínio vale mais que o relógio."""
    cands = [w["end"] for k, w in enumerate(palavras)
             if abs(w["end"] - t) <= janela_s and eh_fim(palavras, k)
             and (minimo is None or w["end"] >= minimo) and (maximo is None or w["end"] <= maximo)]
    return min(cands, key=lambda e: (e - t) if e >= t else 2 * (t - e)) if cands else None


def encaixar(palavras: list[dict], ini: float, fim: float, janela_s: float,
             dur_min: float | None = None, dur_max: float | None = None) -> dict:
    """Leva ini/fim pro ponto natural mais perto, respeitando a duração [dur_min, dur_max] (s).
    Não achou ponto natural numa ponta: mantém o tempo pedido e marca *_ok=False."""
    novo_ini = ajustar_inicio(palavras, ini, janela_s)
    base = ini if novo_ini is None else novo_ini
    novo_fim = ajustar_fim(palavras, fim, janela_s,
                           None if dur_min is None else base + dur_min,
                           None if dur_max is None else base + dur_max)
    return {"inicio": base, "fim": fim if novo_fim is None else novo_fim,
            "inicio_ok": novo_ini is not None, "fim_ok": novo_fim is not None}


ANCORA_JANELA_S = 12 * 60   # em janelas de 60 min o LLM erra poucos minutos (numa chamada
                            # só pra live de 3h20, chegou a errar 10-20 min)
ANCORA_TOKENS = 8           # palavras da frase usadas na busca (começo ou fim dela)
ANCORA_MIN = 0.7            # semelhança mínima (difflib) pra aceitar o achado


def _norm(palavra: str) -> str:
    t = unicodedata.normalize("NFKD", palavra.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t)


def ancorar(palavras: list[dict], frase: str, t: float, ponta: str,
            janela_s: float = ANCORA_JANELA_S) -> float | None:
    """Tempo real de uma frase que o LLM citou literalmente, procurada no words.json a até
    janela_s do tempo t que ele deu. ponta='inicio': começo da 1ª palavra (usa as primeiras
    ANCORA_TOKENS palavras da frase); 'fim': fim da última (usa as últimas). Entre achados
    de semelhança parecida (mesma casa decimal), ganha o mais perto de t: frase repetida
    ("Não comprem.") não puxa pra longe. Frase curta demais ou nada parecido: None."""
    toks = [x for x in (_norm(p) for p in frase.split()) if x]
    if len(toks) < 3 or not palavras:
        return None
    toks = toks[:ANCORA_TOKENS] if ponta == "inicio" else toks[-ANCORA_TOKENS:]
    n, alvo = len(toks), set(toks)
    perto = [k for k, w in enumerate(palavras) if abs(w["start"] - t) <= janela_s]
    if len(perto) < n:
        return None
    lo = perto[0]
    norm = [_norm(palavras[k]["word"]) for k in perto]
    melhor = None
    for i in range(len(norm) - n + 1):
        trecho = norm[i:i + n]
        if len(alvo.intersection(trecho)) < ANCORA_MIN * n:   # filtro barato antes do difflib
            continue
        r = difflib.SequenceMatcher(None, toks, trecho, autojunk=False).ratio()
        if r < ANCORA_MIN:
            continue
        tt = palavras[lo + i]["start"] if ponta == "inicio" else palavras[lo + i + n - 1]["end"]
        chave = (round(r, 1), -abs(tt - t))
        if melhor is None or chave > melhor[0]:
            melhor = (chave, tt)
    return None if melhor is None else melhor[1]


def segundos_para_ts(t: float) -> str:
    """HH:MM:SS.ss (todo leitor de timestamp do pipeline aceita segundo fracionado)."""
    h, resto = divmod(max(0.0, t), 3600)
    m, s = divmod(resto, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
