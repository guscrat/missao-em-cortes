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
