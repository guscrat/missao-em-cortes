"""evidencias_pdf.py: junta os PNGs numerados 01-05 em PDF A4, em ordem, < 10 MB."""
import os
import re

from PIL import Image

import evidencias_pdf as ev


def _png(pasta, nome, tamanho=(1920, 1080), ruido=False):
    if ruido:   # imagem "pesada" (não comprime) pra testar o limite de tamanho
        img = Image.frombytes("RGB", tamanho, os.urandom(tamanho[0] * tamanho[1] * 3))
    else:
        img = Image.new("RGBA", tamanho, (245, 197, 24, 255))
    img.save(pasta / nome)


def _paginas(pdf: bytes) -> list[tuple[float, float]]:
    """(largura, altura) em pontos de cada página, pelo MediaBox."""
    return [(float(w), float(h)) for w, h in
            re.findall(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", pdf)]


def test_so_numerados_01_a_05_entram_no_pdf(tmp_path, capsys):
    for nome in ("02_consent.png", "01_oauth.png", "05_studio.png", "06_extra.png",
                 "site_home.png", "site_privacidade.png", "notas.txt"):
        (_png(tmp_path, nome) if nome.endswith(".png") else (tmp_path / nome).write_text("x"))
    assert ev.main([str(tmp_path)]) == 0
    pdf = (tmp_path / "evidencias.pdf").read_bytes()
    assert len(_paginas(pdf)) == 3
    out = capsys.readouterr().out
    assert "3 página(s)" in out
    assert "fora  site_home.png" in out and "fora  06_extra.png" in out
    dentro, fora = ev.selecionar(tmp_path)
    assert [p.name for p in dentro] == ["01_oauth.png", "02_consent.png", "05_studio.png"]
    assert {p.name for p in fora} == {"06_extra.png", "site_home.png", "site_privacidade.png"}


def test_faixa_customizada(tmp_path):
    for nome in ("01_a.png", "06_b.png", "07_c.png"):
        _png(tmp_path, nome)
    assert ev.main([str(tmp_path), "--faixa=06-07"]) == 0
    assert len(_paginas((tmp_path / "evidencias.pdf").read_bytes())) == 2


def test_paginas_a4_na_orientacao_da_imagem(tmp_path):
    _png(tmp_path, "01_paisagem.png", (1920, 1080))
    _png(tmp_path, "02_retrato.png", (800, 1600))
    ev.main([str(tmp_path)])
    (w1, h1), (w2, h2) = _paginas((tmp_path / "evidencias.pdf").read_bytes())
    a4 = (595.3, 841.9)   # pontos
    assert abs(w1 - a4[1]) < 2 and abs(h1 - a4[0]) < 2      # paisagem
    assert abs(w2 - a4[0]) < 2 and abs(h2 - a4[1]) < 2      # retrato


def test_reduz_resolucao_pra_caber_no_limite(tmp_path, monkeypatch):
    for i in range(3):
        _png(tmp_path, f"{i + 1:02d}_r.png", (1600, 1000), ruido=True)
    monkeypatch.setattr(ev, "LIMITE_BYTES", 900_000)   # força cair pras tentativas mais leves
    ev.main([str(tmp_path)])
    tamanho = (tmp_path / "evidencias.pdf").stat().st_size
    assert tamanho < 900_000


def test_falha_alto_se_nao_couber(tmp_path, monkeypatch):
    _png(tmp_path, "01_x.png", (1600, 1000), ruido=True)
    monkeypatch.setattr(ev, "LIMITE_BYTES", 1_000)
    try:
        ev.main([str(tmp_path)])
        assert False, "devia ter falhado"
    except SystemExit as e:
        assert "10 MB" in str(e)
    assert not (tmp_path / "evidencias.pdf").exists()


def test_pasta_sem_png(tmp_path, capsys):
    assert ev.main([str(tmp_path)]) == 1
    assert "Nenhum .png" in capsys.readouterr().out


def test_so_pngs_sem_numero_nao_gera_pdf(tmp_path, capsys):
    _png(tmp_path, "site_home.png")
    assert ev.main([str(tmp_path)]) == 1
    assert not (tmp_path / "evidencias.pdf").exists()


def test_saida_customizada(tmp_path):
    _png(tmp_path, "01_a.png")
    destino = tmp_path / "sub_auditoria.pdf"
    ev.main([str(tmp_path), f"--saida={destino}"])
    assert destino.read_bytes().startswith(b"%PDF")


def test_modos_P_LA_L_e_extensao_maiuscula(tmp_path):
    Image.new("P", (300, 200)).save(tmp_path / "01_p.png")
    Image.new("LA", (300, 200), (128, 100)).save(tmp_path / "02_la.png")
    Image.new("L", (300, 200), 128).save(tmp_path / "03_l.PNG")
    assert ev.main([str(tmp_path)]) == 0
    assert len(_paginas((tmp_path / "evidencias.pdf").read_bytes())) == 3


def test_imagem_minuscula_nao_e_ampliada(tmp_path):
    pagina = ev._pagina(Image.new("RGB", (40, 30), "black"), 150)
    assert pagina.getpixel((pagina.width // 2, pagina.height // 2)) == (0, 0, 0)
    assert pagina.getpixel((pagina.width // 2 + 100, pagina.height // 2)) == (255, 255, 255)
