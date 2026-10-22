"""Escolha de frame e enquadramento da thumb pelo rosto (OpenCV Haar, local, grátis).

Usado pelo 07_thumb.py:
  - ranquear(): amostra frames do cold open e do corte e dá nota a cada um pelo rosto
    (tamanho, iluminação e nitidez). As variantes a/b/c são os 3 melhores, e o revisor
    (11) pede o próximo da lista quando reprova a thumb.
  - posicionar(): onde recortar o frame pra o rosto ficar inteiro na área visível, e quanto
    de degradê lateral cabe sem cair em cima dele.
"""
from pathlib import Path

AMOSTRAS_COLD = 10
AMOSTRAS_CORTE = 16
SEPARACAO_S = 2.0          # variantes a/b/c não podem ser frames quase iguais
LARGURA_DETECCAO = 640
MARGEM_ROSTO = 0.3         # caixa do Haar pega só o rosto: +30% pra cabelo/queixo/orelhas
BRILHO_MIN, BRILHO_MAX = 70, 200
NITIDEZ_REF = 120.0        # variância do Laplaciano a partir da qual o rosto está nítido

# layout da thumb (1280x720): frame na faixa FRAME_X..FRAME_X+FRAME_W, metade direita preta
FRAME_W, ALTURA = 760, 720
ALVO_X = 500               # centro do rosto nessa coluna da faixa do frame
ALVO_Y = 0.40              # e nessa altura (fração), acima do texto embaixo
ROSTO_MIN_W = 170          # rosto menor que isso na thumb: aproxima (zoom)
ZOOM_MAX = 1.35            # o frame é 720p: mais que isso fica borrado
FADE_DIR, FADE_ESQ, MARGEM_FADE = 180, 140, 24


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


def posicionar(largura: int, altura: int, rosto: tuple | None) -> dict:
    """Recorte do frame pra faixa FRAME_W x ALTURA da thumb.
    Devolve {escala, esq, topo, fade_esq, fade_dir}: redimensiona o frame por `escala`,
    recorta a partir de (esq, topo) e aplica os degradês laterais com essas larguras.
    Sem rosto: recorte centralizado e degradês cheios (layout antigo)."""
    escala = max(FRAME_W / largura, ALTURA / altura)
    if rosto is None:
        nw, nh = largura * escala, altura * escala
        return {"escala": escala, "esq": int((nw - FRAME_W) // 2), "topo": int((nh - ALTURA) // 2),
                "fade_esq": FADE_ESQ, "fade_dir": FADE_DIR}
    x, y, w, h = expandir(rosto, largura, altura)
    if w * escala < ROSTO_MIN_W:
        escala *= min(ZOOM_MAX, ROSTO_MIN_W / (w * escala))
    nw, nh = largura * escala, altura * escala
    cx, cy = (x + w / 2) * escala, (y + h / 2) * escala
    esq = int(min(max(cx - ALVO_X, 0), nw - FRAME_W))
    topo = int(min(max(cy - ALTURA * ALVO_Y, 0), nh - ALTURA))
    rx0, rx1 = x * escala - esq, (x + w) * escala - esq
    return {"escala": escala, "esq": esq, "topo": topo,
            "fade_esq": int(min(FADE_ESQ, max(0, rx0 - MARGEM_FADE))),
            "fade_dir": int(min(FADE_DIR, max(0, FRAME_W - rx1 - MARGEM_FADE)))}


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
