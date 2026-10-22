"""Escolha de frame e enquadramento da thumb pelo rosto (OpenCV Haar, local, grátis).

Usado pelo 07_thumb.py:
  - ranquear(): amostra frames do cold open e do corte e dá nota a cada um pelo rosto
    (tamanho, iluminação e nitidez). As variantes a/b/c são os 3 melhores, e o revisor
    (11) pede o próximo da lista quando reprova a thumb.
  - detectar_overlays(): caixas de overlay da fonte (logo/bandeira de canto, quadro de
    transmissão) que sobraram no corte depois do zoom anti-overlay do 04.
  - posicionar(): recorte "cover" do frame (preenche a thumb inteira) com o rosto grande no
    terço direito, fugindo dos overlays; o que não der pra deixar de fora vira máscara escura.
"""
from pathlib import Path

AMOSTRAS_COLD = 10
AMOSTRAS_CORTE = 16
SEPARACAO_S = 2.0          # variantes a/b/c não podem ser frames quase iguais
LARGURA_DETECCAO = 640
MARGEM_ROSTO = 0.3         # caixa do Haar pega só o rosto: +30% pra cabelo/queixo/orelhas
BRILHO_MIN, BRILHO_MAX = 70, 200
NITIDEZ_REF = 120.0        # variância do Laplaciano a partir da qual o rosto está nítido

# layout da thumb (1280x720): imagem cheia, rosto no terço direito, texto à esquerda
LARGURA, ALTURA = 1280, 720
ROSTO_ALVO = 0.40          # altura do rosto (caixa do Haar) como fração da thumb
ALVO_X = 0.78              # centro do rosto nessa fração da largura (terço direito)...
FAIXA_X = (0.66, 0.88)     # ...e nunca fora dessa faixa (quando o frame deixa)
ALVO_Y = 0.38              # centro do rosto nessa altura, acima do texto embaixo
ZOOM_MAX = 1.6             # o frame é 720p: mais que isso fica borrado
ZOOM_EXTRA = (1.0, 1.05, 1.1, 1.15, 1.2)  # aproximar um pouco além do alvo pra deixar overlay de fora
PASSO_PX = 8               # busca do recorte, de 8 em 8 px
PESO_OVERLAY = 3.0         # custo de overlay dentro que vira mancha escura x rosto fora do alvo
PESO_OVERLAY_ESQ = 0.3     # overlay à esquerda do rosto: some no degradê do texto, custa pouco
MULTA_MANCHA = 0.3         # + por overlay que vira mancha, mesmo que só um pedaço (≈ tirar o rosto 30% do alvo)

# overlays da fonte (quadro de transmissão, tela de react): retângulo de bordas retas que
# muda ao longo do vídeo, encostado em cenário parado. Mede-se o desvio padrão de cada pixel
# no tempo, binariza e fecha os buracos (pedaço parado dentro do quadro, ex: barra do player).
AMOSTRAS_OVERLAY = 16
ATIV_MIN = 6.0             # desvio padrão (0-255) a partir do qual o pixel "muda"
FECHA_PX, ABRE_PX = 41, 9  # morfologia: tapa buracos até ~40 px, tira ruído até ~9 px
ATIV_ALTA, ATIV_BAIXA = 0.8, 0.2    # fração que muda de um lado x do outro da borda
FAIXA_PX = 10              # largura da faixa comparada de cada lado da borda
SEG_MIN = 100              # px de borda reta contínua
LOGO_CANAL = (1142, 28, 1252, 138)  # nosso logo queimado pelo 04 (LOGO_W=110, LOGO_MARGIN=28, sup.-dir.)
JUNTA_PX = 8               # segmentos a até 8 px um do outro são da mesma caixa
VAO_MAX = 250              # canto de caixa com trecho de borda sumido (conteúdo parecido dos dois lados)
BORDA_FRAC = 0.25          # caixa a até 25% da borda do frame encosta nela (overlay mora na borda)
AREA_MAX = 0.6             # caixa maior que isso é cenário, não overlay


def expandir(rosto: tuple, largura: int, altura: int, margem: float = MARGEM_ROSTO) -> tuple:
    """Caixa do rosto com margem, presa dentro do frame. (x, y, w, h)."""
    x, y, w, h = rosto
    dx, dy = w * margem, h * margem
    x0, y0 = max(0, x - dx), max(0, y - dy)
    x1, y1 = min(largura, x + w + dx), min(altura, y + h + dy)
    return x0, y0, x1 - x0, y1 - y0


def nota(rosto: tuple | None, largura: int, altura: int, brilho: float, nitidez: float) -> float:
    """0 sem rosto. Com rosto: área relativa x fator de luz x fator de nitidez x borda."""
    if rosto is None:
        return 0.0
    x, y, w, h = rosto
    area = (w * h) / (largura * altura)
    if brilho < BRILHO_MIN:
        luz = max(0.0, brilho / BRILHO_MIN) ** 2
    elif brilho > BRILHO_MAX:
        luz = max(0.0, 1 - (brilho - BRILHO_MAX) / 55)
    else:
        luz = 1.0
    nitido = min(1.0, nitidez / NITIDEZ_REF)
    cortado = x < 2 or y < 2 or x + w > largura - 2 or y + h > altura - 2
    return area * luz * (0.3 + 0.7 * nitido) * (0.4 if cortado else 1.0)


def _intersecao(a, b) -> float:
    """Área em comum de duas caixas (x0, y0, x1, y1)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _mascaras(overlays, escala: float, esq: float, topo: float) -> list[list[int]]:
    """Overlays que caem dentro do recorte, em coordenadas da thumb (x0, y0, x1, y1)."""
    out = []
    for x0, y0, x1, y1 in overlays:
        c = [max(0, round(x0 * escala - esq)), max(0, round(y0 * escala - topo)),
             min(LARGURA, round(x1 * escala - esq)), min(ALTURA, round(y1 * escala - topo))]
        if c[2] > c[0] and c[3] > c[1]:
            out.append(c)
    return out


def posicionar(largura: int, altura: int, rosto: tuple | None, overlays=()) -> dict:
    """Recorte cover do frame pra thumb inteira (LARGURA x ALTURA).
    Devolve {escala, esq, topo, mascaras, rosto_x0}: redimensiona o frame por `escala`, recorta
    a partir de (esq, topo), escurece as `mascaras` (overlay que não deu pra deixar de fora)
    e o degradê do texto vai até `rosto_x0` (onde começa o rosto na thumb).
    Com rosto: ~ROSTO_ALVO da altura (zoom até ZOOM_MAX), centro em ALVO_X dentro da FAIXA_X,
    inteiro no quadro; entre os recortes possíveis, o que deixa menos overlay dentro.
    Sem rosto: recorte centralizado."""
    base = max(LARGURA / largura, ALTURA / altura)
    if rosto is None:
        esq, topo = (largura * base - LARGURA) // 2, (altura * base - ALTURA) // 2
        return {"escala": base, "esq": int(esq), "topo": int(topo),
                "mascaras": _mascaras(overlays, base, esq, topo), "rosto_x0": int(LARGURA * 0.6)}
    x, y, w, h = rosto
    ex, ey, ew, eh = expandir(rosto, largura, altura)
    alvo = base * min(ZOOM_MAX, max(1.0, ROSTO_ALVO * ALTURA / (h * base)))
    melhor = None
    for extra in ZOOM_EXTRA:
        escala = alvo * extra
        if escala > base * ZOOM_MAX + 1e-9:
            break
        nw, nh = largura * escala, altura * escala
        cx, cy = (x + w / 2) * escala, (y + h / 2) * escala
        # vertical: rosto em ALVO_Y, mas inteiro (com margem) no quadro; ou descer o recorte
        # até sair de baixo de um overlay do topo, comendo no máximo metade da margem do cabelo
        topo = min(max(cy - ALTURA * ALVO_Y, (ey + eh) * escala - ALTURA), ey * escala)
        topo = int(min(max(topo, 0), nh - ALTURA))
        topo_max = min(nh - ALTURA, (y - (y - ey) / 2) * escala)
        topos = [topo] + [int(o[3] * escala) + 1 for o in overlays if topo < o[3] * escala + 1 <= topo_max]
        # horizontal: centro do rosto na FAIXA_X e rosto inteiro; se o frame não deixa, o mais perto
        lim0 = max(0, cx - FAIXA_X[1] * LARGURA, (ex + ew) * escala - LARGURA)
        lim1 = min(nw - LARGURA, cx - FAIXA_X[0] * LARGURA, ex * escala)
        if lim0 > lim1:
            lim0 = lim1 = min(max(cx - ALVO_X * LARGURA, 0), nw - LARGURA)
        for esq, topo in [(e, t) for t in topos for e in [*range(int(lim0), int(lim1) + 1, PASSO_PX), int(lim1)]]:
            janela = (esq, topo, esq + LARGURA, topo + ALTURA)
            custo = (abs((cx - esq) / LARGURA - ALVO_X) + abs((cy - topo) / ALTURA - ALVO_Y)
                     + 0.5 * (extra - 1))
            for o in overlays:
                caixa = [v * escala for v in o]
                area = _intersecao(caixa, janela)
                if caixa[2] <= ex * escala:
                    custo += PESO_OVERLAY_ESQ * area / (LARGURA * ALTURA)
                elif area:
                    custo += MULTA_MANCHA + PESO_OVERLAY * area / (LARGURA * ALTURA)
            if melhor is None or custo < melhor[0] - 1e-9:
                melhor = (custo, escala, esq, topo)
    _, escala, esq, topo = melhor
    return {"escala": escala, "esq": int(esq), "topo": int(topo),
            "mascaras": _mascaras(overlays, escala, esq, topo),
            "rosto_x0": max(0, int(ex * escala - esq))}


def alpha_degrade(x: int, solido: int, fim: int, alpha0: int) -> int:
    """Opacidade do degradê do texto na coluna x: alpha0 até `solido`, depois cai em
    smoothstep até 0 em `fim`. O smoothstep começa e termina sem inclinação, então a passagem
    da área escura pra imagem não forma linha (a curva antiga despencava logo no início)."""
    if x < solido:
        return alpha0
    if x >= fim:
        return 0
    t = (x - solido) / (fim - solido)
    return int(round(alpha0 * (1 - t * t * (3 - 2 * t))))


# ── overlays ────────────────────────────────────────────────────────────────

def _fronteiras(ativ):
    """Fronteiras verticais no mapa de atividade (0-1, fração que muda): em (y, p), -1 quando
    a faixa à esquerda da coluna p muda (> ATIV_ALTA) e a da direita fica parada
    (< ATIV_BAIXA), +1 no contrário, 0 sem fronteira. As faixas pulam 2 px da borda e têm
    FAIXA_PX de largura."""
    import numpy as np
    alt, larg = ativ.shape
    c = np.concatenate([np.zeros((alt, 1)), np.cumsum(ativ, axis=1)], axis=1)
    p = np.arange(FAIXA_PX + 2, larg - FAIXA_PX - 1)
    esq = (c[:, p - 2] - c[:, p - 2 - FAIXA_PX]) / FAIXA_PX
    dir_ = (c[:, p + 2 + FAIXA_PX] - c[:, p + 2]) / FAIXA_PX
    f = np.zeros((alt, larg), np.int8)
    f[:, p] = np.where((esq > ATIV_ALTA) & (dir_ < ATIV_BAIXA), -1,
                       np.where((dir_ > ATIV_ALTA) & (esq < ATIV_BAIXA), 1, 0))
    return f


def _trechos(linha) -> list[tuple[int, int]]:
    """Trechos contínuos True com pelo menos SEG_MIN px: [(ini, fim_exclusivo)]."""
    import numpy as np
    d = np.diff(np.concatenate(([0], linha.astype(np.int8), [0])))
    ini, fim = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(int(a), int(b)) for a, b in zip(ini, fim) if b - a >= SEG_MIN]


# Segmento de borda: (x0, y0, x1, y1, lado). Vertical tem 1 px de largura, horizontal 1 de
# altura. lado = -1 quando o lado que muda (o de dentro do overlay) é o de coordenada menor
# (esquerda/cima), +1 quando é o de coordenada maior (direita/baixo).

def _vertical(s) -> bool:
    return s[3] - s[1] > s[2] - s[0]


def _canto(v, h) -> bool:
    """v (vertical) e h (horizontal) são duas bordas da mesma caixa: cada uma sai da linha da
    outra (com vão de até VAO_MAX) para o lado de dentro da outra."""
    vx, hy, j = v[0], h[1], JUNTA_PX
    if v[4] < 0:                                  # dentro à esquerda de v: h vem da esquerda
        h_ok = vx - VAO_MAX <= h[2] <= vx + j
    else:
        h_ok = vx - j <= h[0] <= vx + VAO_MAX
    if h[4] > 0:                                  # dentro abaixo de h: v desce a partir de h
        v_ok = hy - j <= v[1] <= hy + VAO_MAX
    else:
        v_ok = hy - VAO_MAX <= v[3] <= hy + j
    return h_ok and v_ok


def _conectados(a, b) -> bool:
    """Mesma caixa: bordas na mesma linha e do mesmo lado (com vão de até VAO_MAX; adjacentes
    a até JUNTA_PX contam como a mesma linha) ou formando um canto."""
    if _vertical(a) == _vertical(b):
        if a[4] != b[4]:
            return False
        eixo = 0 if _vertical(a) else 1          # coordenada da linha: x da vertical, y da horizontal
        ao_longo = 1 - eixo
        mesma_linha = abs(a[eixo] - b[eixo]) <= JUNTA_PX
        vao = max(a[ao_longo] - b[ao_longo + 2], b[ao_longo] - a[ao_longo + 2], 0)
        return mesma_linha and vao <= VAO_MAX
    v, h = (a, b) if _vertical(a) else (b, a)
    return _canto(v, h)


def _agrupar(itens: list, ligados) -> list[list]:
    """Componentes conexos de `itens` pela relação `ligados(a, b)`."""
    grupos = []
    for s in itens:
        juntos = [g for g in grupos if any(ligados(s, t) for t in g)]
        grupos = [g for g in grupos if g not in juntos] + [[s] + [t for g in juntos for t in g]]
    return grupos


def caixas_de_segmentos(segs: list, largura: int, altura: int) -> list[list[int]]:
    """Agrupa segmentos de borda (x0, y0, x1, y1, lado) em caixas de overlay. Só vale grupo com
    canto (borda vertical + horizontal): linha solta é cenário. Caixa perto da borda do frame
    é esticada até ela (overlay mora na borda) e caixas que se sobrepõem viram uma só."""
    caixas = []
    for g in _agrupar(segs, _conectados):
        if not (any(_vertical(s) for s in g) and not all(_vertical(s) for s in g)):
            continue
        x0, y0 = min(s[0] for s in g), min(s[1] for s in g)
        x1, y1 = max(s[2] for s in g), max(s[3] for s in g)
        x0 = 0 if x0 <= largura * BORDA_FRAC else x0
        x1 = largura if largura - x1 <= largura * BORDA_FRAC else x1
        y0 = 0 if y0 <= altura * BORDA_FRAC else y0
        y1 = altura if altura - y1 <= altura * BORDA_FRAC else y1
        caixas.append((x0, y0, x1, y1))
    fundidas = [(min(c[0] for c in g), min(c[1] for c in g), max(c[2] for c in g), max(c[3] for c in g))
                for g in _agrupar(caixas, lambda a, b: _intersecao(a, b) > 0)]
    return sorted([int(v) for v in c] for c in fundidas
                  if (c[2] - c[0]) * (c[3] - c[1]) <= AREA_MAX * largura * altura)


def rostos_do_falante(rostos) -> list:
    """Só os rostos de quem fala: os perto da posição mediana (a câmera fica nele). Rosto
    num quadro de transmissão (close do debate) aparece às vezes e fica de fora."""
    import numpy as np
    if not rostos:
        return []
    centros = np.array([(x + w / 2, y + h / 2) for x, y, w, h in rostos])
    meio = np.median(centros, axis=0)
    raio = float(np.median([w for _, _, w, _ in rostos]))
    return [r for r, c in zip(rostos, centros) if np.hypot(*(c - meio)) <= raio]


def mapa_atividade(frames):
    """0/1 por pixel: muda ao longo dos frames (desvio padrão > ATIV_MIN), com buracos
    tapados e ruído tirado."""
    import cv2
    import numpy as np
    cinza = np.stack([f.mean(axis=2) if f.ndim == 3 else f for f in frames]).astype(np.float32)
    m = (cinza.std(axis=0) > ATIV_MIN).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((FECHA_PX, FECHA_PX), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((ABRE_PX, ABRE_PX), np.uint8))
    return m.astype(np.float32)


def overlays_dos_frames(frames, rostos=()) -> list[list[int]]:
    """Caixas de overlay (x0, y0, x1, y1) a partir de frames BGR do mesmo vídeo: retângulos
    que mudam encostados em cenário parado. Caixa que pega o rosto de quem fala (dos `rostos`
    (x, y, w, h) detectados no vídeo) é a pessoa, não overlay."""
    frames = [f for f in frames if f is not None]
    if len(frames) < 6:
        return []
    altura, largura = frames[0].shape[:2]
    m = mapa_atividade(frames)
    fv = _fronteiras(m)               # bordas verticais (coluna x)
    fh = _fronteiras(m.T).T           # bordas horizontais (linha y)
    segs = []
    for lado in (-1, 1):
        segs += [(x, a, x + 1, b, lado) for x in range(largura) for a, b in _trechos(fv[:, x] == lado)]
        segs += [(a, y, b, y + 1, lado) for y in range(altura) for a, b in _trechos(fh[y, :] == lado)]
    faces = [(x, y, x + w, y + h) for x, y, w, h in rostos_do_falante(rostos)]
    return [c for c in caixas_de_segmentos(segs, largura, altura)
            if not any(_intersecao(c, f) for f in faces)]


def detectar_overlays(video: Path | None, rostos=()) -> list[list[int]]:
    """Overlays da fonte no corte (amostra AMOSTRAS_OVERLAY frames do vídeo)."""
    if video is None:
        return []
    frames = [ler_frame(video, t) for t in tempos(duracao(video), AMOSTRAS_OVERLAY)]
    return overlays_dos_frames(frames, rostos)


# ── frames ──────────────────────────────────────────────────────────────────

def analisar(imagem_bgr) -> dict:
    """Rosto principal (o maior) de um frame BGR do OpenCV, com brilho e nitidez dele."""
    import cv2
    alt, larg = imagem_bgr.shape[:2]
    esc = min(1.0, LARGURA_DETECCAO / larg)
    cinza = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2GRAY)
    pequeno = cv2.resize(cinza, None, fx=esc, fy=esc) if esc < 1 else cinza
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    achados = detector.detectMultiScale(pequeno, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24))
    if len(achados) == 0:
        return {"rosto": None, "nota": 0.0}
    fx, fy, fw, fh = max(achados, key=lambda r: r[2] * r[3])
    rosto = (int(fx / esc), int(fy / esc), int(fw / esc), int(fh / esc))
    x, y, w, h = rosto
    regiao = cinza[y:y + h, x:x + w]
    brilho = float(regiao.mean())
    nitidez = float(cv2.Laplacian(regiao, cv2.CV_64F).var())
    return {"rosto": rosto, "brilho": round(brilho, 1), "nitidez": round(nitidez, 1),
            "nota": nota(rosto, larg, alt, brilho, nitidez)}


def ler_frame(video: Path, t: float):
    """Frame BGR em t segundos (ou None)."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
    finally:
        cap.release()
    return frame if ok else None


def duracao(video: Path) -> float:
    import cv2
    cap = cv2.VideoCapture(str(video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        return cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    finally:
        cap.release()


def tempos(dur: float, n: int) -> list[float]:
    """n instantes espalhados pelo vídeo, pulando as pontas (fades)."""
    return [round(dur * (i + 1) / (n + 1), 2) for i in range(n)] if dur > 0 else []


def ordenar(candidatos: list[dict]) -> list[dict]:
    """Por nota (melhor primeiro); frames a menos de SEPARACAO_S de um melhor do mesmo
    vídeo vão pro fim da fila (são quase o mesmo quadro)."""
    melhores, repetidos = [], []
    for c in sorted(candidatos, key=lambda c: -c["nota"]):
        perto = any(m["fonte"] == c["fonte"] and abs(m["t"] - c["t"]) < SEPARACAO_S
                    for m in melhores)
        (repetidos if perto else melhores).append(c)
    return melhores + repetidos


def tem_mancha(rosto: tuple | None, overlays, largura: int = LARGURA, altura: int = ALTURA) -> bool:
    """O melhor recorte desse rosto ainda deixa overlay fora do degradê do texto (vira mancha)."""
    if not rosto or not overlays:
        return False
    p = posicionar(largura, altura, rosto, overlays)
    return any(m[2] > p["rosto_x0"] for m in p["mascaras"])


def rebaixar_manchas(candidatos: list[dict], overlays) -> list[dict]:
    """Frame cujo recorte não escapa de um overlay vale metade e a fila é reordenada."""
    for c in candidatos:
        if c.get("rosto") and tem_mancha(c["rosto"], overlays):
            c["nota"] = c["nota"] * 0.5
            c["mancha"] = True
    return ordenar(candidatos)


def ranquear(cold: Path | None, corte: Path | None) -> list[dict]:
    """Candidatos [{fonte, video, t, nota, rosto, ...}] do cold open e do corte, melhor
    primeiro. Frames sem rosto entram no fim (nota 0), na ordem do vídeo."""
    candidatos = []
    for fonte, video, n in (("cold", cold, AMOSTRAS_COLD), ("corte", corte, AMOSTRAS_CORTE)):
        if video is None:
            continue
        for t in tempos(duracao(video), n):
            frame = ler_frame(video, t)
            if frame is None:
                continue
            candidatos.append({"fonte": fonte, "video": video.name, "t": t, **analisar(frame)})
    return ordenar(candidatos)
