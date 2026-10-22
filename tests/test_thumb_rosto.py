"""Enquadramento e nota da thumb pelo rosto (_thumb_rosto). Só funções puras, sem vídeo."""
import _thumb_rosto as tr


def test_sem_rosto_mantem_layout_antigo():
    p = tr.posicionar(1280, 720, None)
    assert p == {"escala": 1.0, "esq": 260, "topo": 0,
                 "fade_esq": tr.FADE_ESQ, "fade_dir": tr.FADE_DIR}


def test_rosto_na_direita_entra_inteiro_e_sem_degrade_em_cima():
    rosto = (1000, 200, 160, 160)       # perto da borda direita do frame
    p = tr.posicionar(1280, 720, rosto)
    x, y, w, h = tr.expandir(rosto, 1280, 720)
    x0, x1 = x * p["escala"] - p["esq"], (x + w) * p["escala"] - p["esq"]
    assert 0 <= x0 and x1 <= tr.FRAME_W                       # rosto inteiro na faixa
    assert x1 <= tr.FRAME_W - p["fade_dir"]                   # degradê não cai no rosto
    assert x0 >= p["fade_esq"]


def test_rosto_pequeno_aproxima_com_limite():
    p = tr.posicionar(1280, 720, (600, 300, 40, 40))
    assert p["escala"] == tr.ZOOM_MAX                         # sem zoom borrado
    p = tr.posicionar(1280, 720, (600, 200, 140, 140))
    assert p["escala"] == 1.0                                 # já é grande


def test_recorte_nunca_sai_do_frame():
    for rosto in [(0, 0, 100, 100), (1180, 620, 100, 100), (600, 300, 120, 120)]:
        p = tr.posicionar(1280, 720, rosto)
        assert 0 <= p["esq"] <= 1280 * p["escala"] - tr.FRAME_W
        assert 0 <= p["topo"] <= 720 * p["escala"] - tr.ALTURA


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
