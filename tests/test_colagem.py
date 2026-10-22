"""Thumb colagem: _colagem, 07b, personagens, _editor (colagem), _descricoes.adicionar_credito.
Tudo sintetico e mockado: sem rembg, sem rede, sem API, sem ffmpeg."""
import importlib.util
import json
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import _colagem as col
import _descricoes
import _editor

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, SCRIPTS / arquivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c07 = _carregar("colagem07b", "07b_colagem.py")
import personagens as pers  # noqa: E402


# --- texto -----------------------------------------------------------------------------------

def test_pedacos_e_sem_marcas():
    assert col.pedacos("QUEM *MANDA* [LULA]?") == [
        ("QUEM ", col.BRANCO), ("MANDA", col.AMARELO), (" ", col.BRANCO),
        ("LULA", col.VERMELHO), ("?", col.BRANCO)]
    assert col.sem_marcas("QUEM *MANDA* [LULA]?") == "QUEM MANDA LULA?"


def test_quebrar_em_2():
    assert col.quebrar_em_2("um dois tres quatro") == ["UM DOIS", "*TRES QUATRO*"]
    assert col.quebrar_em_2("fim") == ["*FIM*"]


def test_tamanho_texto_cabe_e_encolhe():
    assert col.tamanho_texto(["OI"]) == col.TEXTO_MAX
    t = col.tamanho_texto(["UMA LINHA ABSURDAMENTE LONGA " * 4])
    assert col.TEXTO_MIN <= t < col.TEXTO_MAX


def test_normalizar():
    assert col.normalizar("  Flávio  Bolsonaro! ") == "flavio  bolsonaro"


# --- personagens_do_bloco ------------------------------------------------------------------------

@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(col, "PERSONAGENS", tmp_path)
    for a in ("lula.webp", "flavio.webp"):
        (tmp_path / a).write_bytes(b"x")
    return [{"nome": "Luiz Inácio Lula da Silva", "apelidos": ["lula"], "arquivo": "lula.webp"},
            {"nome": "Flávio Bolsonaro", "apelidos": ["flavio"], "arquivo": "flavio.webp"},
            {"nome": "Sumido", "apelidos": [], "arquivo": "nao_existe.webp"}]


def test_personagens_por_apelido_na_ordem_das_tags(banco):
    b = {"tags": ["Flávio", "Lula"], "tema": "", "titulo_sugerido": "Sumido fala"}
    assert [p["nome"] for p in col.personagens_do_bloco(b, licencas=banco)] == [
        "Flávio Bolsonaro", "Luiz Inácio Lula da Silva"]   # Sumido: arquivo inexistente


def test_personagens_exclui_apresentador_e_palavra_inteira(banco):
    b = {"tags": ["lula", "flavio"]}
    r = col.personagens_do_bloco(b, excluir="Flávio Bolsonaro", licencas=banco)
    assert [p["nome"] for p in r] == ["Luiz Inácio Lula da Silva"]
    assert col.personagens_do_bloco({"tema": "lulap"}, licencas=banco) == []


# --- imagem ---------------------------------------------------------------------------------------

def test_mascara_da_pessoa_fica_com_componente_do_rosto():
    alpha = np.zeros((40, 60), np.uint8)
    alpha[2:12, 2:12] = 255          # pequeno, tem o rosto
    alpha[20:38, 20:58] = 255        # maior
    m = col.mascara_da_pessoa(alpha, (3, 3, 5, 5))
    assert m[5, 5] == 255 and m[30, 30] == 0
    m2 = col.mascara_da_pessoa(alpha, None)      # sem rosto: o maior
    assert m2[30, 30] == 255 and m2[5, 5] == 0
    assert col.mascara_da_pessoa(np.zeros((5, 5), np.uint8), None).sum() == 0


def test_caixas_de_cena_filtra_logo_e_pequenas():
    grande = [0, 0, 400, 300]
    r = col.caixas_de_cena([grande, list(col.tr.LOGO_CANAL), [0, 0, 10, 10]], 1280, 720)
    assert r == [grande]


def test_diferenca_e_repetida():
    a = Image.new("RGB", (64, 36), (10, 10, 10))
    b = Image.new("RGB", (64, 36), (240, 240, 240))
    assert col.diferenca(a, a) == 0 and col.repetida(a, a)
    assert col.diferenca(a, b) > 200 and not col.repetida(a, b)


def test_expressoes_sem_mancha_primeiro_e_limite():
    cands = [{"nota": 9, "rosto": [1, 1, 1, 1], "mancha": True, "t": 1},
             {"nota": 5, "rosto": [1, 1, 1, 1], "t": 2},
             {"nota": 0, "rosto": [1, 1, 1, 1], "t": 3},
             {"nota": 7, "rosto": None, "t": 4},
             {"nota": 6, "rosto": [1, 1, 1, 1], "t": 5}]
    assert [c["t"] for c in col.expressoes({"candidatos": cands})] == [5, 2, 1]
    muitas = [{"nota": i + 1, "rosto": [1] * 4, "t": i} for i in range(20)]
    assert len(col.expressoes({"candidatos": muitas})) == col.N_EXPRESSOES


# --- escolha --------------------------------------------------------------------------------------

def test_validar_escolha():
    r = col.validar_escolha({"expressoes": [5, 1, 1, -1, 0], "cena_assunto": 9,
                             "assunto_descricao": "x", "cena_contexto": 1}, 3, 2)
    assert r["expressoes"] == [1, 0] and r["cena_assunto"] == -1 and r["assunto_descricao"] == ""
    assert r["cena_contexto"] == 1
    igual = col.validar_escolha({"cena_assunto": 1, "cena_contexto": 1}, 3, 2)
    assert igual["cena_contexto"] == -1 and igual["expressoes"] == [0, 1, 2]


def test_escolha_sem_llm():
    assert col.escolha_sem_llm(5, 0)["cena_assunto"] == -1
    e = col.escolha_sem_llm(2, 2)
    assert e["expressoes"] == [0, 1] and (e["cena_assunto"], e["cena_contexto"]) == (0, 1)


def _resp_visao(texto=None, stop="end_turn"):
    cont = [types.SimpleNamespace(type="text", text=texto)] if texto is not None else []
    return types.SimpleNamespace(stop_reason=stop, content=cont, model="m",
                                 usage=types.SimpleNamespace(input_tokens=1000, output_tokens=100))


class _Cli:
    def __init__(self, resp):
        self.messages = types.SimpleNamespace(create=lambda **kw: resp)


def test_escolher_ok_refusal_e_sem_texto():
    img = Image.new("RGB", (50, 50))
    ok = _Cli(_resp_visao(json.dumps({"expressoes": [0], "cena_assunto": 0, "cena_contexto": 1})))
    esc, resp = col.escolher(ok, [img], [img, img], "tema")
    assert esc["cena_assunto"] == 0 and esc["cena_contexto"] == 1
    assert col.escolher(_Cli(_resp_visao(stop="refusal")), [img], [img], "t")[0] is None
    with pytest.raises(json.JSONDecodeError):
        col.escolher(_Cli(_resp_visao(None)), [img], [img], "t")
    tin, tout, usd = col.custo(resp)
    assert (tin, tout) == (1000, 100) and usd == pytest.approx(0.0001 + 0.00005)


# --- variante_aplicada ----------------------------------------------------------------------------

def test_variante_aplicada(tmp_path):
    thumbs = tmp_path / "thumbs"
    (thumbs / "colagem").mkdir(parents=True)
    (thumbs / "thumb_01_a.png").write_bytes(b"img")
    (thumbs / "colagem" / "thumb_01_a.png").write_bytes(b"img")
    assert col.variante_aplicada(None) is None
    assert col.variante_aplicada(thumbs / "thumb_01_a.png") is None      # sem colagem.json
    reg = {"1": {"variantes": {"a": {"arquivo": "thumb_01_a.png", "texto": ["X", "*Y*"]}}}}
    (thumbs / "colagem" / "colagem.json").write_text(json.dumps(reg), encoding="utf-8")
    assert col.variante_aplicada(thumbs / "thumb_01_a.png")["texto"] == ["X", "*Y*"]
    (thumbs / "thumb_01_a.png").write_bytes(b"trocada")                  # revisor trocou o frame
    assert col.variante_aplicada(thumbs / "thumb_01_a.png") is None


# --- compor ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("marcador", ["circulo", "seta"])
def test_compor_tamanho(marcador):
    cena1 = Image.new("RGB", (640, 360), (200, 50, 50))
    cena2 = Image.new("RGBA", (300, 400), (50, 50, 200, 255))
    recorte = Image.new("RGBA", (300, 500), (0, 255, 0, 255))
    img = col.compor(cena1, (250, 100, 60, 60), cena2, (100, 50, 60, 60), recorte, (120, 60, 60, 60),
                     ["QUEM *MANDA*", "[LULA]?"], marcador)
    assert img.size == (col.LARGURA, col.ALTURA)
    tela = col.compor(cena1, None, Image.new("RGB", (400, 300), (9, 9, 9)), None,
                      recorte, None, ["A", "*B*"])
    assert tela.size == (1280, 720)


# --- 07b ------------------------------------------------------------------------------------------

def test_apresentador(tmp_path, monkeypatch):
    cfg = tmp_path / "canais.json"
    cfg.write_text(json.dumps({"canais": [{"nome": "Renan Santos", "prefixo": "renan"}]}), encoding="utf-8")
    monkeypatch.setattr(c07, "CANAIS", cfg)
    assert c07.apresentador("renan_live") == "Renan Santos"
    assert c07.apresentador("outro_x") == ""
    monkeypatch.setattr(c07, "CANAIS", tmp_path / "nao.json")
    assert c07.apresentador("renan_live") == ""


def test_montar_cenas_live_primeiro_e_banco_completa(banco, monkeypatch):
    Image.new("RGBA", (20, 20)).save(col.PERSONAGENS / "lula.webp", "WEBP")
    monkeypatch.setattr(c07.col, "rosto_de", lambda img: (1, 1, 5, 5))
    cenas = [{"imagem": Image.new("RGB", (30, 30)), "origem": "tela a"}]
    esc = {"cena_assunto": 0, "assunto_descricao": "post", "cena_contexto": -1, "contexto_descricao": ""}
    pers_ = [{"nome": "Lula", "arquivo": "lula.webp", "rosto": [1, 2, 3, 4], "credito": "Foto: X (CC BY)"}]
    r = c07.montar_cenas(esc, cenas, pers_)
    assert [c["origem"] for c in r] == ["tela a", "banco: Lula"]
    assert r[1]["rosto"] == (1, 2, 3, 4) and r[1]["credito"] == "Foto: X (CC BY)"
    sem = {**esc, "cena_assunto": -1}
    assert len(c07.montar_cenas(sem, cenas, [])) == 0


def test_destacada():
    a = {"rosto": (1, 1, 1, 1), "descricao": "A"}
    b = {"rosto": None, "descricao": "B"}
    assert c07.destacada([a, b]) == ("A", "B")
    assert c07.destacada([{**a, "rosto": None}, {**b, "rosto": (1, 1, 1, 1)}]) == ("B", "A")
    assert c07.destacada([{**a, "rosto": None}, b]) == ("", "B")


def test_aplicar_copia_variantes_e_poe_credito(tmp_path):
    pasta = tmp_path / "2026-10-22_x"
    saida = pasta / "thumbs" / "colagem"
    saida.mkdir(parents=True)
    for l in "abc":
        (saida / f"thumb_01_{l}.png").write_bytes(l.encode())
    (pasta / "descricoes.txt").write_text(_txt([1]), encoding="utf-8")
    reg = {"variantes": {l: {"arquivo": f"thumb_01_{l}.png"} for l in "abc"},
           "creditos": ["Foto: Fulano (CC BY 2.0)"]}
    c07.aplicar(pasta, saida, 1, reg)
    c07.aplicar(pasta, saida, 1, reg)                      # idempotente
    assert (pasta / "thumbs" / "thumb_01_b.png").read_bytes() == b"b"
    assert (pasta / "descricoes.txt").read_text(encoding="utf-8").count("Foto: Fulano") == 1


def test_processar_bloco_sem_corte_vira_fallback(tmp_path):
    (tmp_path / "cortes").mkdir()
    reg = c07.processar_bloco(None, tmp_path, "x", {"id": 1}, "t", "", tmp_path, True, "")
    assert reg["status"] == "fallback" and "sem corte" in reg["motivo"]


def test_processar_bloco_sem_expressao_e_sem_2_cenas(tmp_path, monkeypatch):
    (tmp_path / "cortes").mkdir()
    (tmp_path / "cortes" / "corte_01_a.mp4").write_bytes(b"")
    (tmp_path / "cortes" / "corte_01_a_polido.mp4").write_bytes(b"")
    assert c07.corte_do_bloco(tmp_path, 1).name == "corte_01_a.mp4"
    monkeypatch.setattr(c07, "ler_fila", lambda *a: {"candidatos": [], "overlays": []})
    r = c07.processar_bloco(None, tmp_path, "x", {"id": 1}, "t", "", tmp_path, True, "")
    assert "sem frame" in r["motivo"]
    fila = {"candidatos": [{"nota": 5, "rosto": [1, 1, 5, 5], "video": "corte_01_a.mp4", "t": 1.0}],
            "overlays": []}
    monkeypatch.setattr(c07, "ler_fila", lambda *a: fila)
    monkeypatch.setattr(c07, "frame_pil", lambda p, c: Image.new("RGB", (64, 36)))
    monkeypatch.setattr(c07.col, "cenas_do_video", lambda *a, **k: [])
    r = c07.processar_bloco(None, tmp_path, "x", {"id": 1}, "t", "", tmp_path, True, "")
    assert r["status"] == "fallback" and "só 0 cena" in r["motivo"]


def test_processar_bloco_ok_com_mocks(tmp_path, monkeypatch):
    (tmp_path / "cortes").mkdir()
    (tmp_path / "cortes" / "corte_01_a.mp4").write_bytes(b"")
    fila = {"candidatos": [{"nota": 5, "rosto": [10, 10, 20, 20], "video": "corte_01_a.mp4", "t": 1.0}],
            "overlays": []}
    monkeypatch.setattr(c07, "ler_fila", lambda *a: fila)
    monkeypatch.setattr(c07, "frame_pil", lambda p, c: Image.new("RGB", (200, 120)))
    cenas = [{"imagem": Image.new("RGB", (100, 60)), "origem": f"c{i}"} for i in range(2)]
    monkeypatch.setattr(c07.col, "cenas_do_video", lambda *a, **k: cenas)
    monkeypatch.setattr(c07.col, "rosto_de", lambda img: None)
    monkeypatch.setattr(c07.col, "recortar",
                        lambda f, r: (Image.new("RGBA", (100, 200), (0, 255, 0, 255)), (30, 20, 30, 30)))
    saida = tmp_path / "saida"
    saida.mkdir()
    r = c07.processar_bloco(None, tmp_path, "x", {"id": 1, "texto_thumb": "quem manda agora"},
                            "t", "", saida, True, "")
    assert r["status"] == "ok" and set(r["variantes"]) == {"a", "b", "c"} and r["custo_usd"] == 0
    assert (saida / "thumb_01_c.png").exists()


# --- personagens ----------------------------------------------------------------------------------

@pytest.mark.parametrize("lic,sa,esperado", [
    ("CC0", False, True), ("Public domain", False, True), ("CC BY 4.0", False, True),
    ("CC BY 2.0", False, True), ("Attribution", False, True), ("PD-Brazil-Government", False, True),
    ("CC BY-SA 4.0", False, False), ("CC BY-SA 4.0", True, True),
    ("CC BY-NC 2.0", True, False), ("CC BY-ND 2.0", True, False),
    ("", False, False), (None, False, False), ("Fair use", False, False),
])
def test_licenca_ok(lic, sa, esperado):
    assert pers.licenca_ok(lic, sa) is esperado


def test_contar_nomes_e_candidatos(tmp_path):
    for i, tags in enumerate([["Lula", "Flávio Bolsonaro", "economia"], ["lula", "Nicolas Ferreira"]]):
        p = tmp_path / f"2026-01-0{i + 1}_x"
        p.mkdir()
        (p / "blocos.json").write_text(json.dumps({"blocos": [{"tags": tags}]}), encoding="utf-8")
    (tmp_path / "ruim").mkdir()
    (tmp_path / "ruim" / "blocos.json").write_text("{quebrado", encoding="utf-8")
    cont = pers.contar_nomes(tmp_path)
    assert cont["luiz inacio lula da silva"] == 2 and cont["nikolas ferreira"] == 1
    nomes = pers.candidatos(cont)
    assert "economia" not in nomes and "flavio bolsonaro" in nomes
    assert "renan santos" in nomes       # FIXOS entram mesmo sem tag


def test_apelidos_de():
    r = pers.apelidos_de("Lula", "Luiz Inácio Lula da Silva", "Luiz Inácio Lula da Silva")
    assert r == ["lula"]


def test_registrar_mescla_por_slug(tmp_path, monkeypatch):
    monkeypatch.setattr(col, "LICENCAS", tmp_path / "licencas.json")
    pers.registrar({"slug": "lula", "nome": "Lula", "apelidos": ["lula"], "arquivo": "lula.webp"})
    pers.registrar({"slug": "lula", "nome": "Lula", "apelidos": ["ex presidente"], "arquivo": "lula.webp"})
    pers.registrar({"slug": "ana", "nome": "Ana", "apelidos": [], "arquivo": "ana.webp"})
    ps = col.ler_licencas()
    assert [p["slug"] for p in ps] == ["ana", "lula"]
    assert next(p for p in ps if p["slug"] == "lula")["apelidos"] == ["ex presidente", "lula"]


# --- _editor (colagem) ----------------------------------------------------------------------------

def test_opcao_valida():
    assert _editor.opcao_valida(["QUEM MANDA", "*AGORA*?"])
    assert _editor.opcao_valida(["QUEM *MANDA*", "[LULA]?"])
    assert not _editor.opcao_valida(["UMA SO"])                      # 1 linha
    assert not _editor.opcao_valida(["SEM", "AMARELO"])              # 0 amarelas
    assert not _editor.opcao_valida(["*A* *B* *C*", "X"])            # 3 amarelas
    assert not _editor.opcao_valida(["[A] *B*", "[C]"])              # 2 nomes
    assert not _editor.opcao_valida(["X" * 40, "*Y*"])               # estoura a linha
    assert not _editor.opcao_valida(["*A", "B"])                     # asterisco impar
    assert not _editor.opcao_valida(["", "*B*"])


def _resp_ed(opcoes=None, stop="end_turn"):
    cont = [types.SimpleNamespace(type="text", text=json.dumps({"opcoes": opcoes}))] if opcoes is not None else []
    return types.SimpleNamespace(stop_reason=stop, content=cont)


def _cli_ed(resp):
    return types.SimpleNamespace(beta=types.SimpleNamespace(
        messages=types.SimpleNamespace(create=lambda **kw: resp)))


def test_texto_colagem_filtra_invalidas_e_limita():
    ops = [{"linha1": "quem manda", "linha2": "*agora*?"},
           {"linha1": "sem amarelo", "linha2": "nenhum"},
           {"linha1": "x" * 50, "linha2": "*y*"}]
    r, _ = _editor.texto_colagem(_cli_ed(_resp_ed(ops)), "pedido")
    assert r == [["QUEM MANDA", "*AGORA*?"]]


def test_texto_colagem_refusal_e_sem_texto():
    assert _editor.texto_colagem(_cli_ed(_resp_ed(stop="refusal")), "p")[0] is None
    # resposta paga sem texto vira [] (com a resposta, pra logar o custo), não exceção
    r, resp = _editor.texto_colagem(_cli_ed(_resp_ed(None)), "p")
    assert r == [] and resp is not None


def test_montar_pedido_colagem():
    p = _editor.montar_pedido_colagem("Titulo", "TXT", "", "ctx", "fala aqui")
    assert "TÍTULO DO YOUTUBE: Titulo" in p and "sem descrição (não use nome)" in p
    assert "OUTRA CENA: ctx" in p and p.endswith("fala aqui")


# --- _descricoes.adicionar_credito ----------------------------------------------------------------

def _txt(ids):
    partes = []
    for bid in ids:
        partes += ["=" * 70, f"VÍDEO {bid:02d} — tema", "=" * 70, "", "TÍTULO (1 chars):", "T", "",
                   "-" * 70, "DESCRIÇÃO:", "-" * 70, f"desc {bid}", "-" * 70, "TAGS (x):", "-" * 70, "a", ""]
    return "\n".join(partes)


def test_adicionar_credito_bloco_certo_e_idempotente():
    novo = _descricoes.adicionar_credito(_txt([1, 2]), 2, "Foto: X (CC BY)")
    d = _descricoes.ler_descricoes(novo)
    assert "Foto: X (CC BY)" in d[2]["descricao"] and "Foto" not in d[1]["descricao"]
    assert d[2]["descricao"].startswith("desc 2")
    assert _descricoes.adicionar_credito(novo, 2, "Foto: X (CC BY)") == novo


def test_adicionar_credito_bloco_inexistente():
    txt = _txt([1])
    assert _descricoes.adicionar_credito(txt, 9, "Foto") == txt
