"""Grafias oficiais + usos no 08, _colagem, _editor, 07b e 11. Tudo mockado."""
import importlib
import importlib.util
import json
import types
from pathlib import Path

import pytest
from PIL import Image

import _colagem as col
import _descricoes
import _editor
import _grafias as g

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, SCRIPTS / arquivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c07 = _carregar("colagem07b_g", "07b_colagem.py")
rv = _carregar("revisor_g", "11_revisor.py")
desc = importlib.import_module("08_descricao")

LISTA = [
    {"nome": "Nikolas Ferreira", "curto": "Nikolas",
     "erradas": ["Nicolas Ferreira", "Nicolas", "Nicholas"], "nao_trocar": ["Nicolas Maduro"]},
    {"nome": "Flávio Bolsonaro", "curto": "Flávio", "erradas": ["Flavio Bolsonaro"]},
    {"nome": "Jair Bolsonaro", "curto": "Bolsonaro", "erradas": []},
    {"nome": "Luiz Inácio Lula da Silva", "curto": "Lula", "erradas": []},
    {"nome": "Fábio Luís Lula da Silva", "curto": "Lulinha", "erradas": []},
    {"nome": "André Janones", "curto": "Janones", "erradas": ["Janone"]},
]


# --- _grafias ---------------------------------------------------------------------------------

def test_carregar_ausente_e_invalido(tmp_path):
    assert g.carregar(tmp_path / "nao.json") == []
    ruim = tmp_path / "x.json"
    ruim.write_text("{nao é json", encoding="utf-8")
    assert g.carregar(ruim) == []
    ruim.write_text('{"outra": 1}', encoding="utf-8")
    assert g.carregar(ruim) == []
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"personagens": [{"nome": "A B"}, {"x": 1}]}), encoding="utf-8")
    assert g.carregar(ok) == [{"nome": "A B"}]


def test_corrigir_nome_completo_e_caixa_alta():
    assert g.corrigir("Nicolas Ferreira fala", LISTA) == "Nikolas Ferreira fala"
    assert g.corrigir("NICOLAS FERREIRA", LISTA) == "NIKOLAS FERREIRA"
    assert g.corrigir("NICOLAS", LISTA) == "NIKOLAS"
    assert g.corrigir("o Nicolas disse", LISTA) == "o Nikolas disse"
    assert g.corrigir("", LISTA) == "" and g.corrigir(None, LISTA) is None


def test_corrigir_palavra_solta_seguida_de_nome_proprio():
    assert g.corrigir("Nicolas Maduro caiu", LISTA) == "Nicolas Maduro caiu"
    assert g.corrigir("Nicolas Sarkozy caiu", LISTA) == "Nicolas Sarkozy caiu"   # misto: inicial maiúscula


def test_corrigir_caixa_alta_troca_o_personagem_e_protege_nao_trocar():
    """Texto da thumb/Short é todo em maiúsculas: troca o Nikolas, nunca o Maduro."""
    assert g.corrigir("NICOLAS SERÁ O REI?", LISTA) == "NIKOLAS SERÁ O REI?"
    assert g.corrigir("NICOLAS MADURO CAIU", LISTA) == "NICOLAS MADURO CAIU"
    assert g.corrigir("nicolas maduro caiu", LISTA) == "nicolas maduro caiu"
    assert g.corrigir("NICOLAS E NICOLAS MADURO", LISTA) == "NIKOLAS E NICOLAS MADURO"
    assert g.corrigir("NICOLAS FERREIRA X NICOLAS MADURO", LISTA) == "NIKOLAS FERREIRA X NICOLAS MADURO"


def test_config_real_protege_maduro_em_caixa_alta():
    assert g.corrigir("NICOLAS MADURO") == "NICOLAS MADURO"
    assert g.corrigir("NICOLAS SERÁ O REI?") == "NIKOLAS SERÁ O REI?"


def test_corrigir_nao_mexe_em_palavra_parecida():
    assert g.corrigir("Janones e Janone", LISTA) == "Janones e Janones"
    assert "Janoness" not in g.corrigir("Janones", LISTA)


def test_para_prompt_e_variantes():
    p = g.para_prompt(LISTA)
    assert ("- Nikolas Ferreira (curto: Nikolas; nunca: Nicolas Ferreira, Nicolas, Nicholas; "
            "outra pessoa, não trocar: Nicolas Maduro)") in p
    assert "- Jair Bolsonaro (curto: Bolsonaro)" in p
    assert g.variantes("nikolas ferreira", LISTA)[:2] == ["Nikolas Ferreira", "Nikolas"]
    assert "Nicolas" in g.variantes("Nikolas Ferreira", LISTA)
    assert g.variantes("Desconhecido", LISTA) == ["Desconhecido"]


def test_citados_forma_longa_primeiro():
    assert g.citados(["Flávio Bolsonaro fala"], lista=LISTA) == ["Flávio Bolsonaro"]
    assert g.citados(["Bolsonaro e Flávio Bolsonaro"], lista=LISTA) == ["Flávio Bolsonaro", "Jair Bolsonaro"]
    assert g.citados(["Fábio Luís Lula da Silva"], lista=LISTA) == ["Fábio Luís Lula da Silva"]
    assert g.citados(["Lula"], lista=LISTA) == ["Luiz Inácio Lula da Silva"]
    assert g.citados(["nicolas ferreira"], lista=LISTA) == ["Nikolas Ferreira"]
    assert g.citados([], lista=LISTA) == []


def test_citados_excluir_apresentador():
    r = g.citados(["Flávio Bolsonaro e Lula"], excluir="Flávio Bolsonaro", lista=LISTA)
    assert r == ["Luiz Inácio Lula da Silva"]


# --- _descricoes.trocar_creditos -----------------------------------------------------------------

def _txt(ids, extra=None):
    extra = extra or {}
    partes = []
    for bid in ids:
        partes += ["=" * 70, f"VÍDEO {bid:02d} — tema", "=" * 70, "", "TÍTULO (1 chars):", "T", "",
                   "-" * 70, "DESCRIÇÃO:", "-" * 70, f"desc {bid}"] + extra.get(bid, []) + [
                   "-" * 70, "TAGS (x):", "-" * 70, "a", ""]
    return "\n".join(partes)


def test_trocar_creditos_so_do_bloco_certo():
    antigo = "Foto de Fulano (CC BY) (fundo removido)"
    txt = _txt([1, 2], {1: [antigo], 2: [antigo]})
    novo = _descricoes.trocar_creditos(txt, 2, ["Foto de Beltrano (CC0) (fundo removido)"])
    d = _descricoes.ler_descricoes(novo)
    assert "Fulano" in d[1]["descricao"]
    assert "Fulano" not in d[2]["descricao"] and "Beltrano" in d[2]["descricao"]
    assert d[2]["descricao"].startswith("desc 2")


def test_trocar_creditos_vazio_so_tira_e_idempotente():
    antigo = "Foto de Fulano (CC BY) (fundo removido)"
    txt = _txt([1], {1: [antigo]})
    limpo = _descricoes.trocar_creditos(txt, 1, [])
    assert "Foto de" not in limpo
    assert _descricoes.ler_descricoes(limpo)[1]["descricao"] == "desc 1"
    nova = ["Foto de X (CC0) (fundo removido)"]
    uma = _descricoes.trocar_creditos(txt, 1, nova)
    assert _descricoes.trocar_creditos(uma, 1, nova) == uma
    assert uma.count("Foto de") == 1
    assert _descricoes.trocar_creditos(txt, 9, nova) == txt


# --- 08_descricao ---------------------------------------------------------------------------------

BLOCO = {"id": 1, "tema": "tema", "titulo_sugerido": "Nicolas Ferreira detona", "resumo": "R.",
         "ganchos": ["g"], "tags": ["x"]}


def test_08_titulo_passa_pela_grafia():
    texto = desc.bloco_para_texto(BLOCO, "https://youtube.com/watch?v=1")
    assert "Nikolas Ferreira detona" in texto and "Nicolas" not in texto


def test_08_repor_creditos(tmp_path, monkeypatch):
    txt = _txt([1])
    reg = {"status": "ok", "creditos": ["Foto de Z (CC0) (fundo removido)"]}
    monkeypatch.setattr(col, "colagem_aplicada", lambda thumbs, bid: reg)
    assert "Foto de Z" in desc.repor_creditos(txt, tmp_path, [{"id": 1}])
    monkeypatch.setattr(col, "colagem_aplicada", lambda thumbs, bid: None)
    assert desc.repor_creditos(txt, tmp_path, [{"id": 1}]) == txt
    monkeypatch.setattr(col, "colagem_aplicada", lambda thumbs, bid: {"status": "ok", "creditos": []})
    assert "Foto de" not in desc.repor_creditos(txt, tmp_path, [{"id": 1}])


# --- _colagem ---------------------------------------------------------------------------------

def _thumbs(tmp_path, registro, igual=True):
    thumbs = tmp_path / "thumbs"
    (thumbs / "colagem").mkdir(parents=True)
    (thumbs / "thumb_01_a.png").write_bytes(b"img")
    (thumbs / "colagem" / "thumb_01_a.png").write_bytes(b"img" if igual else b"outra")
    (thumbs / "colagem" / "colagem.json").write_text(json.dumps(registro), encoding="utf-8")
    return thumbs


def test_colagem_aplicada(tmp_path):
    reg = {"status": "ok", "creditos": ["c"],
           "variantes": {"a": {"arquivo": "thumb_01_a.png", "texto": ["A", "*B*"]}}}
    t = _thumbs(tmp_path, {"1": reg})
    assert col.colagem_aplicada(t, 1) == reg
    assert col.colagem_aplicada(t, 2) is None                       # outro bloco: sem thumb


def test_colagem_aplicada_arquivo_diferente_e_fallback(tmp_path):
    var = {"a": {"arquivo": "thumb_01_a.png", "texto": ["A", "*B*"]}}
    t = _thumbs(tmp_path / "x", {"1": {"status": "ok", "variantes": var}}, igual=False)
    assert col.colagem_aplicada(t, 1) is None
    t2 = _thumbs(tmp_path / "y", {"1": {"status": "fallback", "variantes": var}})
    assert col.colagem_aplicada(t2, 1) is None
    t3 = _thumbs(tmp_path / "z", {"1": {"status": "ok", "variantes": var}})
    (t3 / "colagem" / "colagem.json").write_text("lixo", encoding="utf-8")
    assert col.colagem_aplicada(t3, 1) is None


def test_personagens_do_bloco_casa_grafia_errada(tmp_path, monkeypatch):
    monkeypatch.setattr(col, "PERSONAGENS", tmp_path)
    (tmp_path / "nikolas.webp").write_bytes(b"x")
    (tmp_path / "lula.webp").write_bytes(b"x")
    monkeypatch.setattr(col._grafias, "carregar", lambda *a: LISTA)
    lic = [{"nome": "Nikolas Ferreira", "apelidos": [], "arquivo": "nikolas.webp"},
           {"nome": "Luiz Inácio Lula da Silva", "apelidos": ["lula"], "arquivo": "lula.webp"}]
    r = col.personagens_do_bloco({"tags": ["nicolas ferreira"]}, licencas=lic)
    assert [p["nome"] for p in r] == ["Nikolas Ferreira"]
    # Fábio Luís Lula da Silva não puxa a foto do Lula
    assert col.personagens_do_bloco({"tags": ["Fábio Luís Lula da Silva"]}, licencas=lic) == []
    # apresentador não vira cena dele mesmo
    assert col.personagens_do_bloco({"tags": ["Nicolas"]}, excluir="Nikolas Ferreira", licencas=lic) == []


def test_montar_conteudo_visao_pessoas():
    im = Image.new("RGB", (32, 18))
    com = col.montar_conteudo_visao([im], [im], "tema", ["Nikolas Ferreira", "Lula"])
    assert "PESSOAS CITADAS: Nikolas Ferreira, Lula" in com[0]["text"]
    sem = col.montar_conteudo_visao([im], [im], "tema")
    assert "PESSOAS CITADAS" not in sem[0]["text"]


# --- _editor ----------------------------------------------------------------------------------

def _cli(texto):
    resp = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=texto)],
                                 usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
    return types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: resp)))


def test_editor_corrige_grafia_da_saida(monkeypatch):
    monkeypatch.setattr(_editor._grafias, "carregar", lambda *a: LISTA)
    j = json.dumps({"opcoes": [{"linha1": "nicolas ferreira", "linha2": "*cai*?"}]})
    r, _ = _editor.texto_colagem(_cli(j), "p")
    assert r == [["NIKOLAS FERREIRA", "*CAI*?"]]
    j2 = json.dumps({"titulo": "Nicolas Ferreira: tal", "texto_thumb": "NICOLAS CAI", "mudanca": "m"})
    novo, _ = _editor.reescrever(_cli(j2), "p")
    assert novo["titulo"] == "Nikolas Ferreira: tal" and novo["texto_thumb"] == "NIKOLAS CAI"


def test_editor_pedidos_tem_grafias(monkeypatch):
    monkeypatch.setattr(_editor._grafias, "carregar", lambda *a: LISTA)
    assert "GRAFIAS OFICIAIS" in _editor.montar_pedido("t", "T", "prob", "fala", [])
    p = _editor.montar_pedido_colagem("t", "T", "", "", "fala")
    assert "GRAFIAS OFICIAIS" in p and "Nikolas Ferreira" in p


@pytest.fixture
def runs(monkeypatch):
    cmds, rcs = [], {}

    def fake(cmd, **kw):
        cmds.append(cmd)
        rc = next((v for k, v in rcs.items() if any(k in str(c) for c in cmd)), 0)
        return types.SimpleNamespace(returncode=rc)
    monkeypatch.setattr(_editor.subprocess, "run", fake)
    return cmds, rcs


def _pasta(tmp_path):
    p = tmp_path / "2026-06-25_v"
    p.mkdir()
    return p


def test_refazer_artes_colagem_ok(tmp_path, monkeypatch, runs):
    cmds, _ = runs
    monkeypatch.setattr(_editor, "_colagem_aplicada", lambda t: {"texto": ["a"]})
    p = _pasta(tmp_path)
    assert _editor.refazer_artes(p, 1, p / "thumbs" / "thumb_01_a.png") == []
    assert len(cmds) == 1 and cmds[0][1].endswith("07b_colagem.py")
    assert "--aplicar" in cmds[0] and "--sem-editor" in cmds[0] and "--bloco=1" in cmds[0]
    assert not any("07_thumb" in str(c) for cmd in cmds for c in cmd)


def test_refazer_artes_colagem_falha_volta_pro_template(tmp_path, monkeypatch, runs):
    cmds, rcs = runs
    rcs["07b_colagem"] = 2
    monkeypatch.setattr(_editor, "_colagem_aplicada", lambda t: {"texto": ["a"]})
    p = _pasta(tmp_path)
    av = _editor.refazer_artes(p, 1, p / "thumbs" / "thumb_01_b.png")
    assert len(av) == 1 and "template" in av[0]
    assert cmds[1][1].endswith("07_thumb.py")
    assert not any(str(c).startswith("--variante") for c in cmds[1])


def test_refazer_artes_thumb_normal_usa_variante(tmp_path, monkeypatch, runs):
    cmds, _ = runs
    monkeypatch.setattr(_editor, "_colagem_aplicada", lambda t: None)
    p = _pasta(tmp_path)
    assert _editor.refazer_artes(p, 1, p / "thumbs" / "thumb_01_c.png") == []
    assert cmds[0][1].endswith("07_thumb.py") and "--variante=c" in cmds[0]


# --- 07b ---------------------------------------------------------------------------------------

def test_07b_textos_sem_editor_nao_chama_client(monkeypatch):
    class Boom:
        def __getattr__(self, n):
            raise AssertionError("não devia chamar o client")
    monkeypatch.setattr(c07._grafias, "carregar", lambda *a: LISTA)
    b = {"texto_thumb": "Nicolas Ferreira cai agora", "tema": "t"}
    linhas, usd = c07.textos(Boom(), "s", b, "t", "fala", [], False, sem_editor=True)
    esperado = col.quebrar_em_2("Nikolas Ferreira cai agora")
    assert linhas == [esperado] * 3 and usd == 0.0
    assert "NICOLAS" not in " ".join(linhas[0]).upper()


def _main_07b(tmp_path, monkeypatch, reg, aplicar=True):
    pasta = tmp_path / "2026-10-22_x"
    pasta.mkdir()
    (pasta / "blocos.json").write_text(json.dumps({"blocos": [
        {"id": 1, "tema": "t", "timestamp_inicio": "00:00:00", "timestamp_fim": "00:05:00"}]}),
        encoding="utf-8")
    monkeypatch.setattr(c07, "achar_pasta", lambda s: pasta)
    monkeypatch.setattr(c07, "stem_de", lambda p: "x")
    monkeypatch.setattr(c07, "apresentador", lambda s: "")
    monkeypatch.setattr(c07, "ler_bloco", lambda *a: None)
    monkeypatch.setattr(c07, "evento", lambda *a, **k: None)
    monkeypatch.setattr(c07, "processar_bloco", lambda *a, **k: dict(reg))
    monkeypatch.setattr(c07, "aplicar", lambda *a, **k: None)
    args = ["x", "--bloco=1", "--sem-llm"] + (["--aplicar"] if aplicar else [])
    return c07.main(args)


def test_07b_main_bloco_em_fallback_devolve_2(tmp_path, monkeypatch):
    assert _main_07b(tmp_path, monkeypatch, {"status": "fallback", "motivo": "m", "custo_usd": 0.0}) == 2


def test_07b_main_bloco_ok_devolve_0(tmp_path, monkeypatch):
    assert _main_07b(tmp_path, monkeypatch, {"status": "ok", "custo_usd": 0.0, "variantes": {}, "cenas": ["a"]}) == 0


# --- 11_revisor ----------------------------------------------------------------------------------

def test_11_texto_da_thumb(tmp_path, monkeypatch):
    monkeypatch.setattr(rv._colagem, "colagem_aplicada", lambda t, b: None)
    assert rv.texto_da_thumb(tmp_path, 1, "TXT") == "TXT"
    reg = {"variantes": {"a": {"texto": ["QUEM *MANDA*", "[LULA]?"]},
                         "b": {"texto": ["OUTRO", "TEXTO"]},
                         "c": {"texto": ["QUEM *MANDA*", "[LULA]?"]}}}
    monkeypatch.setattr(rv._colagem, "colagem_aplicada", lambda t, b: reg)
    assert rv.texto_da_thumb(tmp_path, 1, "TXT") == "QUEM MANDA LULA? | OUTRO TEXTO"
    monkeypatch.setattr(rv._colagem, "colagem_aplicada", lambda t, b: {"variantes": {}})
    assert rv.texto_da_thumb(tmp_path, 1, "TXT") == "TXT"


def test_voltar_template_tira_credito(tmp_path, runs):
    cmds, _ = runs
    p = _pasta(tmp_path)
    cred = "Foto de Lula: X / Wikimedia Commons, CC BY 2.0 (fundo removido)"
    (p / "descricoes.txt").write_text(_txt([1, 2], {1: [cred], 2: [cred]}), encoding="utf-8")
    assert _editor.voltar_template(p, 1) is True
    assert cmds[0][1].endswith("07_thumb.py") and "--bloco=1" in cmds[0]
    texto = (p / "descricoes.txt").read_text(encoding="utf-8")
    assert texto.count(cred) == 1          # só o bloco 2 manteve


def test_voltar_template_falha_nao_mexe_na_descricao(tmp_path, runs):
    _, rcs = runs
    rcs["07_thumb"] = 1
    p = _pasta(tmp_path)
    cred = "Foto de Lula: X / Wikimedia Commons, CC BY 2.0 (fundo removido)"
    (p / "descricoes.txt").write_text(_txt([1], {1: [cred]}), encoding="utf-8")
    assert _editor.voltar_template(p, 1) is False
    assert cred in (p / "descricoes.txt").read_text(encoding="utf-8")


def test_citados_ignora_nao_trocar():
    assert g.citados(["Nicolas Maduro discursou"], lista=LISTA) == []
    assert g.citados(["NICOLÁS MADURO e Nicolas Ferreira"], lista=LISTA + [
        {"nome": "X", "erradas": [], "nao_trocar": ["Nicolás Maduro"]}]) == ["Nikolas Ferreira"]
