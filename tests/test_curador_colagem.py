"""Curador: modo da thumb colagem (config/thumb.json). subprocess falso, nunca roda 07b de verdade."""
import pytest

from test_curador import _item, cu, raiz  # noqa: F401  (raiz = fixture do projeto falso)


def _thumb_cfg(raiz, conteudo):
    (raiz / "config" / "thumb.json").write_text(conteudo, encoding="utf-8")


@pytest.mark.parametrize("conteudo,esperado", [
    (None, "desligado"), ('{"colagem": "teste"}', "teste"), ('{"colagem": "padrao"}', "padrao"),
    ('{"colagem": "xpto"}', "desligado"), ("{quebrado", "desligado"), ("{}", "desligado")])
def test_modo_colagem(raiz, conteudo, esperado):
    if conteudo is not None:
        _thumb_cfg(raiz, conteudo)
    assert cu.modo_colagem() == esperado


def _mock_publicacao(raiz, monkeypatch, aprov=()):
    import _paths
    import _publicacao
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: raiz / "outputs" / stem)
    monkeypatch.setattr(_publicacao, "aprovados", lambda pasta: [{"id": i} for i in aprov])
    monkeypatch.setattr(_publicacao, "gerar", lambda pasta: (None, []))


def test_colagem_teste_roda_depois_dos_shorts(raiz, monkeypatch):
    _thumb_cfg(raiz, '{"colagem": "teste"}')
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append((script, *a)) or True)
    _mock_publicacao(raiz, monkeypatch, aprov=[1])
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert [c[0] for c in chamadas][-2:] == ["10_shorts.py", "07b_colagem.py"]
    assert ("07b_colagem.py", "renan_x") in chamadas
    assert res["colagem"].endswith("colagem")


def test_colagem_padrao_aplica_antes_do_revisor(raiz, monkeypatch):
    _thumb_cfg(raiz, '{"colagem": "padrao"}')
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append((script, *a)) or True)
    _mock_publicacao(raiz, monkeypatch)
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    nomes = [c[0] for c in chamadas]
    assert nomes.index("07b_colagem.py") == nomes.index("11_revisor.py") - 1
    assert ("07b_colagem.py", "renan_x", "--aplicar") in chamadas
    assert "colagem" not in res


def test_colagem_desligada_nao_roda(raiz, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append(script) or True)
    _mock_publicacao(raiz, monkeypatch)
    cu.processar({**_item("a"), "stem": "renan_x"})
    assert "07b_colagem.py" not in chamadas


@pytest.mark.parametrize("modo", ["teste", "padrao"])
def test_falha_da_colagem_vira_aviso(raiz, monkeypatch, modo):
    _thumb_cfg(raiz, '{"colagem": "%s"}' % modo)
    monkeypatch.setattr(cu, "rodar", lambda script, *a: script != "07b_colagem.py")
    _mock_publicacao(raiz, monkeypatch)
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert res["ok"] and any("colagem" in a for a in res["avisos"])


def test_resumo_tem_secao_colagem(raiz):
    rodada = {"quando": "x", "custo": 0.0, "estoque": None, "avisos": [], "fila": [], "recusados": [],
              "escolhidos": [],
              "processados": [{"stem": "s", "titulo": "Live", "canal": "Renan", "ok": True, "aprovados": 0,
                               "colagem": "/p/thumbs/colagem", "avisos": []}]}
    txt = cu.escrever_resumo(rodada)
    assert "## Thumb colagem (teste)" in txt and "/p/thumbs/colagem" in txt
