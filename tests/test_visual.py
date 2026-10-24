"""Identidade visual do painel (painel/visual.py): cartões, barras rotuladas e tema."""
from unittest.mock import patch

import pandas as pd

import visual


def test_cartao_escapa_texto_e_aplica_tom():
    h = visual.cartao("Fila <b>", 3, "até qua & cia", tom="alerta", ajuda="diz 'oi'")
    assert "<div class='ct alerta'>" in h
    assert "Fila &lt;b&gt;" in h and "até qua &amp; cia" in h
    assert "title='diz &#x27;oi&#x27;'" in h
    assert "<div class='ct-v'>3</div>" in h and "medidor" not in h


def test_cartao_medidor_fica_entre_0_e_100():
    assert "width:100.0%" in visual.cartao("Custo", "$12", medidor=1.8)
    assert "width:0.0%" in visual.cartao("Custo", "$0", medidor=-0.2)
    assert "width:18.0%" in visual.cartao("Custo", "$1.80", medidor=0.18)


def test_grade_grande_e_pequena():
    with patch.object(visual.st, "markdown") as md:
        visual.grade(["<a>"], grande=True)
        visual.grade(["<b>"])
    assert md.call_args_list[0].args[0] == "<div class='grade g'><a></div>"
    assert md.call_args_list[1].args[0] == "<div class='grade p'><b></div>"


def test_barras_escreve_o_valor_em_cada_barra():
    serie = pd.Series({"editor": 1.012, "revisor": 0.68})
    with patch.object(visual.st, "altair_chart") as graf:
        visual.barras(serie)
    spec = graf.call_args.args[0].to_dict()
    camadas = [c["mark"]["type"] for c in spec["layer"]]
    assert camadas == ["bar", "text"]
    dados = next(iter(spec["datasets"].values()))
    assert [d["rotulo"] for d in dados] == ["US$ 1.01", "US$ 0.68"]
    assert spec["layer"][0]["encoding"]["x"]["axis"] is None   # o valor fica na barra, não no eixo


def test_barras_vazia_nao_desenha():
    with patch.object(visual.st, "altair_chart") as graf:
        visual.barras(pd.Series(dtype=float))
    graf.assert_not_called()


def test_tema_ativo_padrao_escuro_e_tokens_dos_dois_temas():
    with patch.object(visual.st, "context") as ctx:
        ctx.theme.type = None
        assert visual.tema_ativo() == "dark"
        ctx.theme.type = "light"
        assert visual.tema_ativo() == "light"
    assert visual.TOKENS["dark"].keys() == visual.TOKENS["light"].keys()
    assert visual.TOKENS["light"]["bg"] != "#FFFFFF" and visual.TOKENS["dark"]["bg"] != "#000000"


def test_seletor_so_injeta_script_quando_troca_de_tema():
    with patch.object(visual.st, "context") as ctx, \
         patch.object(visual.st, "segmented_control") as seg, patch.object(visual.st, "html") as js:
        ctx.theme.type = "dark"
        seg.return_value = "Escuro"
        visual.seletor_tema()
        js.assert_not_called()
        seg.return_value = "Claro"
        visual.seletor_tema()
    script = js.call_args.args[0]
    assert "stActiveTheme-" in script and "'Light'" in script and "reload" in script
    assert js.call_args.kwargs == {"unsafe_allow_javascript": True}
