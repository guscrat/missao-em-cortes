"""evidencias_pdf.py: junta PNGs em PDF A4, ordem alfabética, < 10 MB."""
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


def test_ordem_alfabetica_e_uma_pagina_por_png(tmp_path, capsys):
    for nome in ("02_consent.png", "01_oauth.png", "10_upload.png", "notas.txt"):
        (_png(tmp_path, nome) if nome.endswith(".png") else (tmp_path / nome).write_text("x"))
    assert ev.main([str(tmp_path)]) == 0
    pdf = (tmp_path / "evidencias.pdf").read_bytes()
    assert len(_paginas(pdf)) == 3
    assert "3 página(s)" in capsys.readouterr().out


def test_paginas_a4_na_orientacao_da_imagem(tmp_path):
    _png(tmp_path, "a_paisagem.png", (1920, 1080))
    _png(tmp_path, "b_retrato.png", (800, 1600))
    ev.main([str(tmp_path)])
    (w1, h1), (w2, h2) = _paginas((tmp_path / "evidencias.pdf").read_bytes())
    a4 = (595.3, 841.9)   # pontos
    assert abs(w1 - a4[1]) < 2 and abs(h1 - a4[0]) < 2      # paisagem
    assert abs(w2 - a4[0]) < 2 and abs(h2 - a4[1]) < 2      # retrato


def test_reduz_resolucao_pra_caber_no_limite(tmp_path, monkeypatch):
    for i in range(3):
        _png(tmp_path, f"{i:02d}.png", (1600, 1000), ruido=True)
    monkeypatch.setattr(ev, "LIMITE_BYTES", 900_000)   # força cair pras tentativas mais leves
    ev.main([str(tmp_path)])
    tamanho = (tmp_path / "evidencias.pdf").stat().st_size
    assert tamanho < 900_000


def test_falha_alto_se_nao_couber(tmp_path, monkeypatch):
    _png(tmp_path, "x.png", (1600, 1000), ruido=True)
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


def test_saida_customizada(tmp_path):
    _png(tmp_path, "a.png")
    destino = tmp_path / "sub_auditoria.pdf"
    ev.main([str(tmp_path), f"--saida={destino}"])
    assert destino.read_bytes().startswith(b"%PDF")
