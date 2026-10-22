"""_descricoes.trocar_titulo: troca só o bloco pedido."""
from _descricoes import ler_descricoes, trocar_titulo


def _txt(titulos):
    partes = []
    for bid, t in titulos.items():
        partes += ["=" * 70, f"VÍDEO {bid:02d} — tema", "=" * 70, "", f"TÍTULO ({len(t)} chars):",
                   t, "", "-" * 70, "DESCRIÇÃO:", "-" * 70, f"desc {bid}", "-" * 70,
                   "TAGS (x):", "-" * 70, "a, b", ""]
    return "\r\n".join(partes)


def test_troca_so_o_bloco_e_atualiza_contagem():
    novo = trocar_titulo(_txt({1: "Um", 2: "Dois", 3: "Três"}), 2, "Título novo")
    d = ler_descricoes(novo)
    assert [d[i]["titulo"] for i in (1, 2, 3)] == ["Um", "Título novo", "Três"]
    assert "TÍTULO (11 chars):\nTítulo novo" in novo and d[3]["descricao"] == "desc 3"


def test_bloco_inexistente_nao_muda_nada():
    txt = _txt({1: "Um"}).replace("\r\n", "\n")
    assert trocar_titulo(txt, 9, "x") == txt
