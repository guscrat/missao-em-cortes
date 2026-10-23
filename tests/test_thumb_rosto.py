"""Enquadramento e nota da thumb pelo rosto (_thumb_rosto). Só funções puras, sem vídeo."""
import _thumb_rosto as tr


def _na_thumb(p, caixa):
    """Caixa (x, y, w, h) do frame em coordenadas da thumb (x0, y0, x1, y1)."""
    x, y, w, h = caixa
    e = p["escala"]
    return x * e - p["esq"], y * e - p["topo"], (x + w) * e - p["esq"], (y + h) * e - p["topo"]


def test_sem_rosto_cobre_a_thumb_centralizado():
    p = tr.posicionar(1280, 720, None)
    assert (p["escala"], p["esq"], p["topo"], p["mascaras"]) == (1.0, 0, 0, [])
    p = tr.posicionar(1920, 1080, None)                       # 1080p: reduz pra cobrir 1280x720
    assert p["escala"] == 1280 / 1920 and p["esq"] == 0


def test_rosto_grande_no_terco_direito_e_inteiro():
    rosto = (600, 250, 180, 180)                              # no meio do frame
    p = tr.posicionar(1280, 720, rosto)
    x0, y0, x1, y1 = _na_thumb(p, rosto)
    assert (y1 - y0) / 720 == pytest.approx(tr.ROSTO_ALVO, abs=0.06)       # ~40% da altura
    assert tr.FAIXA_X[0] * 1280 <= (x0 + x1) / 2 <= tr.FAIXA_X[1] * 1280   # terço direito
    ex0, ey0, ex1, ey1 = _na_thumb(p, tr.expandir(rosto, 1280, 720))
    assert 0 <= ex0 and ex1 <= 1280 and 0 <= ey0 and ey1 <= 720            # com cabelo/queixo
    assert p["rosto_x0"] == int(ex0)


def test_rosto_pequeno_aproxima_com_limite():
    p = tr.posicionar(1280, 720, (900, 300, 40, 40))
    assert p["escala"] == pytest.approx(tr.ZOOM_MAX)          # sem zoom borrado
    p = tr.posicionar(1280, 720, (700, 150, 400, 400))
    assert p["escala"] <= max(tr.ZOOM_EXTRA)                  # já é grande: no máximo o ajuste fino


def test_recorte_nunca_sai_do_frame():
    for rosto in [(0, 0, 100, 100), (1180, 620, 100, 100), (600, 300, 120, 120), (40, 300, 200, 200)]:
        p = tr.posicionar(1280, 720, rosto)
        assert 0 <= p["esq"] <= 1280 * p["escala"] - 1280
        assert 0 <= p["topo"] <= 720 * p["escala"] - 720


def test_recorte_foge_do_logo_quando_da():
    rosto, logo = (852, 202, 216, 216), list(tr.LOGO_CANAL)
    p = tr.posicionar(1280, 720, rosto, [logo])
    assert p["mascaras"] == []                                # logo ficou fora do recorte
    x0, _, x1, _ = _na_thumb(p, rosto)
    assert tr.FAIXA_X[0] * 1280 <= (x0 + x1) / 2 <= tr.FAIXA_X[1] * 1280


def test_overlay_a_esquerda_vira_mascara_no_degrade():
    rosto, pip = (852, 202, 216, 216), [0, 0, 624, 720]       # quadro de transmissão à esquerda
    p = tr.posicionar(1280, 720, rosto, [pip])
    assert len(p["mascaras"]) == 1
    assert p["mascaras"][0][2] <= p["rosto_x0"]               # não encosta no rosto
    assert not tr.tem_mancha(rosto, [pip])


def test_tem_mancha_e_rebaixar():
    logo = list(tr.LOGO_CANAL)
    preso = (1060, 20, 200, 200)                              # rosto colado no logo: não dá pra fugir
    assert tr.tem_mancha(preso, [logo])
    assert not tr.tem_mancha(None, [logo]) and not tr.tem_mancha(preso, [])
    c = [{"fonte": "cold", "t": 1.0, "nota": 0.05, "rosto": preso},
         {"fonte": "cold", "t": 9.0, "nota": 0.04, "rosto": (600, 250, 180, 180)}]
    r = tr.rebaixar_manchas(c, [logo])
    assert [x["t"] for x in r] == [9.0, 1.0] and r[1]["mancha"] and r[1]["nota"] == 0.025


def test_alpha_degrade_solido_depois_suave_ate_zero():
    a = [tr.alpha_degrade(x, 600, 880, 255) for x in range(0, 900)]
    assert a[0] == a[599] == 255 and a[880] == a[899] == 0
    assert all(p >= q for p, q in zip(a, a[1:]))              # nunca volta a escurecer
    assert max(p - q for p, q in zip(a, a[1:])) <= 3          # sem degrau (era a "linha reta")
    assert a[600] == 255 and a[610] >= 250                    # sai do sólido sem despencar


def test_alpha_degrade_sem_overlay_comeca_na_borda():
    assert tr.alpha_degrade(0, 0, 700, 190) == 190
    assert tr.alpha_degrade(350, 0, 700, 190) == 95
    assert tr.alpha_degrade(700, 0, 700, 190) == 0


def test_alpha_degrade_bordas_exatas():
    assert tr.alpha_degrade(599, 600, 880, 255) == 255
    assert tr.alpha_degrade(600, 600, 880, 255) == 255      # t=0 -> alpha0
    assert tr.alpha_degrade(879, 600, 880, 255) <= 1        # quase zero antes do fim
    assert tr.alpha_degrade(880, 600, 880, 255) == 0        # x == fim -> 0


def test_alpha_degrade_faixa_minima():
    # fim - solido = 1: sem divisao por zero, so um passo
    assert tr.alpha_degrade(10, 10, 11, 200) == 200
    assert tr.alpha_degrade(11, 10, 11, 200) == 0
    assert tr.alpha_degrade(5, 10, 11, 200) == 200


def test_alpha_degrade_meio_e_alpha_zero():
    assert tr.alpha_degrade(740, 600, 880, 200) == 100      # smoothstep(0.5) = 0.5
    assert tr.alpha_degrade(700, 600, 880, 0) == 0


def test_alpha_degrade_alem_do_fim_e_antes_do_inicio():
    assert tr.alpha_degrade(5000, 0, 100, 255) == 0
    assert tr.alpha_degrade(-5, 0, 100, 255) == 255


# ── overlays: segmentos de borda → caixas ──────────────────────────────────

def test_caixas_canto_vira_caixa_e_encosta_na_borda():
    # quadro de transmissão à esquerda: borda direita (dentro à esquerda) + topo (dentro abaixo)
    segs = [(619, 300, 620, 560, -1), (330, 140, 619, 141, 1), (90, 136, 215, 137, 1)]
    assert tr.caixas_de_segmentos(segs, 1280, 720) == [[0, 0, 620, 720]]


def test_caixas_linha_solta_e_lado_errado_nao_valem():
    assert tr.caixas_de_segmentos([(619, 300, 620, 560, -1)], 1280, 720) == []    # sem canto
    # prateleira à direita da borda do quadro, com "dentro" pra baixo: não fecha caixa
    segs = [(620, 303, 621, 409, -1), (620, 411, 741, 412, 1)]
    assert tr.caixas_de_segmentos(segs, 1280, 720) == []


def test_caixa_gigante_e_cenario():
    segs = [(1200, 50, 1201, 700, -1), (0, 40, 1200, 41, 1)]
    assert tr.caixas_de_segmentos(segs, 1280, 720) == []


def test_rostos_do_falante_ignora_rosto_no_quadro():
    falante = [(850, 200, 210, 210), (860, 210, 200, 200), (840, 190, 220, 220)]
    assert tr.rostos_do_falante(falante + [(200, 300, 90, 90)]) == falante
    assert tr.rostos_do_falante([]) == []


def _frames_com_quadro(n=12, rosto_mexe=True):
    """Cenário parado + quadro de transmissão (0..620 x 140..620) com conteúdo que troca."""
    rng = np.random.RandomState(1)
    frames = []
    for i in range(n):
        f = np.full((720, 1280, 3), 90, np.uint8)
        f[140:620, 0:620] = rng.randint(0, 255, 3)            # "corte de câmera" no quadro
        if rosto_mexe:
            f[200 + i * 3:420 + i * 3, 850:1070] = 60 + 12 * i  # falante se mexendo
        frames.append(f)
    return frames


def test_overlays_dos_frames_acha_quadro_e_ignora_falante():
    caixas = tr.overlays_dos_frames(_frames_com_quadro(), rostos=[(860, 210, 200, 200)])
    assert caixas == [[0, 0, 622, 720]] or (len(caixas) == 1 and caixas[0][2] in range(615, 630))


def test_overlays_dos_frames_poucos_frames_ou_tudo_parado():
    assert tr.overlays_dos_frames(_frames_com_quadro(n=3)) == []
    parado = [np.full((720, 1280, 3), 90, np.uint8)] * 8
    assert tr.overlays_dos_frames(parado) == []


def test_nota_prefere_rosto_grande_iluminado_e_nitido():
    base = tr.nota((500, 200, 150, 150), 1280, 720, brilho=130, nitidez=300)
    assert tr.nota(None, 1280, 720, 130, 300) == 0
    assert tr.nota((500, 200, 80, 80), 1280, 720, 130, 300) < base       # menor
    assert tr.nota((500, 200, 150, 150), 1280, 720, 30, 300) < base      # escuro
    assert tr.nota((500, 200, 150, 150), 1280, 720, 130, 20) < base      # borrado
    assert tr.nota((0, 200, 150, 150), 1280, 720, 130, 300) < base       # cortado na borda


def test_ordenar_joga_frames_quase_iguais_pro_fim():
    c = [{"fonte": "cold", "t": 5.0, "nota": 0.05}, {"fonte": "cold", "t": 5.5, "nota": 0.049},
         {"fonte": "corte", "t": 5.2, "nota": 0.04}, {"fonte": "cold", "t": 12.0, "nota": 0.03}]
    assert [(x["fonte"], x["t"]) for x in tr.ordenar(c)] == \
        [("cold", 5.0), ("corte", 5.2), ("cold", 12.0), ("cold", 5.5)]


def test_tempos_pulam_as_pontas():
    assert tr.tempos(10, 4) == [2.0, 4.0, 6.0, 8.0]
    assert tr.tempos(0, 4) == []


# ── analisar() e ranquear() com mocks ──────────────────────────────────────
import types
from pathlib import Path

import numpy as np
import pytest


class _FakeDetector:
    achados: list = []

    def __init__(self, *a, **k):
        pass

    def detectMultiScale(self, img, **kw):
        _FakeDetector.visto = img.shape
        return np.array(_FakeDetector.achados, dtype=int).reshape(-1, 4)


@pytest.fixture
def fake_cv2(monkeypatch):
    import cv2
    monkeypatch.setattr(cv2, "CascadeClassifier", _FakeDetector)
    return cv2


def test_analisar_sem_rosto(fake_cv2):
    _FakeDetector.achados = []
    img = np.full((720, 1280, 3), 100, np.uint8)
    assert tr.analisar(img) == {"rosto": None, "nota": 0.0}


def test_analisar_escolhe_maior_rosto_e_reescala(fake_cv2):
    img = np.random.RandomState(0).randint(90, 150, (720, 1280, 3)).astype(np.uint8)
    _FakeDetector.achados = [(10, 10, 20, 20), (100, 50, 60, 60)]   # coords na imagem 640 de largura
    r = tr.analisar(img)
    assert _FakeDetector.visto == (360, 640)          # reduziu pra LARGURA_DETECCAO
    assert r["rosto"] == (200, 100, 120, 120)         # voltou pra escala original
    assert r["nota"] > 0 and 90 <= r["brilho"] <= 150 and r["nitidez"] > 0


def test_analisar_imagem_pequena_nao_reescala(fake_cv2):
    _FakeDetector.achados = [(20, 20, 50, 50)]
    img = np.full((200, 400, 3), 128, np.uint8)
    r = tr.analisar(img)
    assert _FakeDetector.visto == (200, 400) and r["rosto"] == (20, 20, 50, 50)


def test_ranquear_junta_cold_e_corte_ordenado(monkeypatch):
    monkeypatch.setattr(tr, "duracao", lambda v: 100.0)
    monkeypatch.setattr(tr, "ler_frame", lambda v, t: (v.name, t))
    notas = {"cold.mp4": 0.01, "corte.mp4": 0.05}
    monkeypatch.setattr(tr, "analisar", lambda f: {"rosto": (1, 1, 1, 1), "nota": notas[f[0]] + f[1] / 1e6})
    r = tr.ranquear(Path("cold.mp4"), Path("corte.mp4"))
    assert len(r) == tr.AMOSTRAS_COLD + tr.AMOSTRAS_CORTE
    assert r[0]["fonte"] == "corte" and r[0]["video"] == "corte.mp4"
    assert {c["fonte"] for c in r} == {"cold", "corte"}


def test_ranquear_pula_none_e_frames_ilegiveis(monkeypatch):
    monkeypatch.setattr(tr, "duracao", lambda v: 50.0)
    monkeypatch.setattr(tr, "ler_frame", lambda v, t: None)
    assert tr.ranquear(Path("c.mp4"), None) == []
    monkeypatch.setattr(tr, "ler_frame", lambda v, t: "f")
    monkeypatch.setattr(tr, "analisar", lambda f: {"rosto": None, "nota": 0.0})
    r = tr.ranquear(None, Path("c.mp4"))
    assert len(r) == tr.AMOSTRAS_CORTE and all(c["fonte"] == "corte" for c in r)


# ── _canto / _conectados / detectar_overlays ────────────────────────────────

@pytest.mark.parametrize("lado_v,lado_h,v,h,esperado", [
    # dentro à esquerda de v (-1), h abaixo (+1): h termina em x=100, v desce de y=50
    (-1, 1, (100, 50, 101, 200), (0, 50, 100, 51), True),
    (-1, 1, (100, 50, 101, 200), (200, 50, 300, 51), False),   # h do lado errado de v
    (1, 1, (100, 50, 101, 200), (100, 50, 220, 51), True),
    (1, 1, (100, 50, 101, 200), (0, 50, 60, 51), False),
    (-1, -1, (100, 0, 101, 50), (0, 50, 100, 51), True),       # h com dentro acima: v termina em y=50
    (1, -1, (100, 0, 101, 50), (100, 50, 200, 51), True),
    (1, -1, (100, 300, 101, 400), (100, 50, 200, 51), False),  # v longe de h
])
def test_canto_orientacoes(lado_v, lado_h, v, h, esperado):
    assert tr._canto(v + (lado_v,), h + (lado_h,)) is esperado


def test_conectados_colinear_respeita_vao_max():
    a = (100, 0, 101, 100, 1)
    perto = (100, 100 + tr.VAO_MAX, 101, 100 + tr.VAO_MAX + 50, 1)
    longe = (100, 100 + tr.VAO_MAX + 1, 101, 100 + tr.VAO_MAX + 50, 1)
    assert tr._conectados(a, perto)
    assert not tr._conectados(a, longe)


def test_conectados_lados_diferentes_ou_linhas_diferentes_nao_ligam():
    a = (100, 0, 101, 100, 1)
    assert not tr._conectados(a, (100, 110, 101, 200, -1))
    assert not tr._conectados(a, (100 + tr.JUNTA_PX + 1, 110, 101 + tr.JUNTA_PX + 1, 200, 1))


def test_detectar_overlays_sem_video_e_vazio():
    assert tr.detectar_overlays(None) == []


def test_detectar_overlays_usa_frames_amostrados(monkeypatch):
    chamadas = []
    monkeypatch.setattr(tr, "duracao", lambda v: 100.0)
    monkeypatch.setattr(tr, "ler_frame", lambda v, t: chamadas.append(t) or None)
    assert tr.detectar_overlays(Path("x.mp4")) == []   # todos None -> <6 frames
    assert len(chamadas) == tr.AMOSTRAS_OVERLAY
