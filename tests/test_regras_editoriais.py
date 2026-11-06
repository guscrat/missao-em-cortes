"""Guarda das regras editoriais que moram em prompt (06/11/2026): se alguém reescrever o
prompt e perder a regra, o teste avisa. Só lê o texto, sem API."""
from pathlib import Path

RAIZ = Path(__file__).parent.parent
SEGMENTACAO = (RAIZ / "prompts" / "segmentacao.md").read_text(encoding="utf-8")
POLIR = (RAIZ / "scripts" / "04b_polir.py").read_text(encoding="utf-8")


def test_03_atualidade_score_baixo_e_nao_vira_bloco():
    assert "**Atualidade**" in SEGMENTACAO
    for termo in ("previsão", "debate de uma eleição já encerrada", "apuração",
                  "pesquisa de intenção de voto superada", "no máximo 3", "DATA DA LIVE"):
        assert termo in SEGMENTACAO, termo


def test_03_leitura_de_pix_nunca_vira_bloco():
    assert "NÃO criar bloco de leitura de Pix, superchat ou doação" in SEGMENTACAO
    assert "o polimento remove a leitura" in SEGMENTACAO


def test_04b_remove_pix_no_meio_do_assunto():
    assert "Leitura de Pix, superchat ou doação no meio do assunto" in POLIR


def test_apelido_de_pessoa_real_proibido_no_03_editor_e_revisor():
    editor = (RAIZ / "scripts" / "_editor.py").read_text(encoding="utf-8")
    revisor = (RAIZ / "scripts" / "11_revisor.py").read_text(encoding="utf-8")
    assert "NUNCA usam apelido de pessoa real" in SEGMENTACAO
    assert "NUNCA usam apelido de pessoa real" in editor
    assert "usam apelido de pessoa real" in revisor


def test_lulinha_e_excecao_na_regra_de_apelido():
    import sys
    sys.path.insert(0, str(RAIZ / "scripts"))
    import _grafias
    assert _grafias.corrigir("LULINHA E OS INQUÉRITOS") == "LULINHA E OS INQUÉRITOS"
    for arq in ("prompts/segmentacao.md", "scripts/_editor.py", "scripts/11_revisor.py"):
        assert 'Exceção: "Lulinha"' in (RAIZ / arq).read_text(encoding="utf-8"), arq


def test_07_so_troca_thumb_publicada_com_flag_e_nunca_arquivada():
    fonte = (RAIZ / "scripts" / "07_thumb.py").read_text(encoding="utf-8")
    assert 'NAO_MEXER = {"agendado", "publicado", "arquivado"}' in fonte
    assert 'if status in NAO_MEXER and not (trocar_publicada and status != "arquivado"):' in fonte
    assert "--trocar-publicada exige --bloco=N" in fonte
