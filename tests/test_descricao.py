"""08_descricao.py: "Conteúdo original" é a FONTE; nosso canal só no "Inscreva-se"."""
import importlib
import json

import _paths
from _canal import CANAL_URL

desc = importlib.import_module("08_descricao")
up = importlib.import_module("09_upload")

FONTE = "https://www.youtube.com/watch?v=Lab_UcxeEDs"
BLOCO = {"id": 1, "tema": "tema", "titulo_sugerido": "Título", "resumo": "Resumo.",
         "ganchos": ["gancho"], "tags": ["Renan Santos"]}


def _linha(texto, trecho):
    return next(l for l in texto.splitlines() if trecho in l)


def test_conteudo_original_e_a_fonte_e_canal_so_no_inscreva_se():
    texto = desc.bloco_para_texto(BLOCO, FONTE)
    assert _linha(texto, "Conteúdo original:").endswith(FONTE)
    assert CANAL_URL in _linha(texto, "Inscreva-se")
    # o link do canal aparece uma vez só, e não na linha de crédito
    assert texto.count(CANAL_URL) == 1
    assert CANAL_URL not in _linha(texto, "Conteúdo original:")


def test_sem_fonte_cai_no_placeholder():
    texto = desc.bloco_para_texto(BLOCO, "")
    assert _linha(texto, "Conteúdo original:").endswith(desc.PLACEHOLDER_URL)


def test_url_do_nosso_canal_nao_vale_como_fonte(tmp_path, capsys):
    (tmp_path / "x.url").write_text(CANAL_URL + "\n", encoding="utf-8")
    (tmp_path / "y.url").write_text("https://youtube.com/@missaoemcortes-14\n", encoding="utf-8")
    (tmp_path / "z.url").write_text(FONTE + "\n", encoding="utf-8")
    assert desc.ler_url_fonte("x", tmp_path) == ""
    assert desc.ler_url_fonte("y", tmp_path) == ""
    assert desc.ler_url_fonte("z", tmp_path) == FONTE
    assert desc.ler_url_fonte("nao_existe", tmp_path) == ""
    assert "NOSSO canal" in capsys.readouterr().out


def test_main_ponta_a_ponta_usa_inputs_url(tmp_path, monkeypatch):
    pasta = tmp_path / "outputs" / "2026-10-21_renan"
    pasta.mkdir(parents=True)
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "renan.url").write_text(FONTE, encoding="utf-8")
    (pasta / "blocos.json").write_text(json.dumps({"blocos": [BLOCO]}), encoding="utf-8")
    monkeypatch.setattr(_paths, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(desc, "ROOT", tmp_path)
    assert desc.main(["renan"]) == 0
    texto = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    assert _linha(texto, "Conteúdo original:").endswith(FONTE)
    # e o 09 lê de volta sem reclamar do crédito
    meta = up.ler_descricoes(texto)[1]
    assert up.problema_credito(meta["descricao"]) is None


def test_upload_recusa_credito_apontando_pro_nosso_canal():
    ok = desc.bloco_para_texto(BLOCO, FONTE)
    errado = ok.replace(f"Conteúdo original: {FONTE}", f"Conteúdo original: {CANAL_URL}")
    sem = desc.bloco_para_texto(BLOCO, "")
    corpo = lambda t: up.ler_descricoes(t)[1]["descricao"]  # noqa: E731
    assert up.problema_credito(corpo(ok)) is None
    assert "nosso canal" in up.problema_credito(corpo(errado))
    assert "faltando" in up.problema_credito(corpo(sem))
    assert "faltando" in up.problema_credito("descrição sem linha de crédito")
