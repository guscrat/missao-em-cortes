"""Modo ab da thumb (a = template, b/c = colagem): 07b --ab, _colagem.colagem_ab, _editor,
11_revisor, Curador, _publicacao e 16_thumb_ab. Tudo mockado (sem API, sem ffmpeg, sem state/ real)."""
import importlib
import importlib.util
import json
import types
from datetime import datetime
from pathlib import Path

import pytest

import _colagem as col
import _editor
import _publicacao as pub
from test_curador import _item, cu, raiz  # noqa: F401

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, SCRIPTS / arquivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c07 = _carregar("colagem07b_ab", "07b_colagem.py")
rv = _carregar("revisor_ab", "11_revisor.py")
ab = importlib.import_module("16_thumb_ab")


def _pasta_ab(tmp_path, bid=1, colagem="bc"):
    """Pasta com thumbs/thumb_NN_<l>.png; as de `colagem` são cópia idêntica de thumbs/colagem/."""
    pasta = tmp_path / "2026-10-22_live"
    th = pasta / "thumbs"
    (th / "colagem").mkdir(parents=True)
    variantes = {}
    for l in "abc":
        nome = f"thumb_{bid:02d}_{l}.png"
        if l in colagem:
            (th / "colagem" / nome).write_bytes(b"col" + l.encode())
            (th / nome).write_bytes(b"col" + l.encode())
            variantes[l] = {"arquivo": nome, "texto": [f"TXT *{l.upper()}*"]}
        else:
            (th / nome).write_bytes(b"tpl" + l.encode())
    (th / "colagem" / "colagem.json").write_text(
        json.dumps({str(bid): {"status": "ok", "variantes": variantes}}), encoding="utf-8")
    return pasta


# --- 07b --ab ----------------------------------------------------------------------------------

def test_aplicar_ab_so_copia_b_c_e_poe_credito(tmp_path):
    pasta = tmp_path / "2026-10-22_x"
    saida = pasta / "thumbs" / "colagem"
    saida.mkdir(parents=True)
    for l in "abc":
        (saida / f"thumb_01_{l}.png").write_bytes(b"col" + l.encode())
        (pasta / "thumbs" / f"thumb_01_{l}.png").write_bytes(b"tpl")
    (pasta / "descricoes.txt").write_text(
        "=" * 70 + "\nVÍDEO 01 — x\n" + "=" * 70 + "\n\nTÍTULO (1 chars):\nT\n\n" + "-" * 70
        + "\nDESCRIÇÃO:\n" + "-" * 70 + "\nd\n" + "-" * 70 + "\nTAGS (x):\n" + "-" * 70 + "\na\n",
        encoding="utf-8")
    reg = {"variantes": {l: {"arquivo": f"thumb_01_{l}.png"} for l in "abc"},
           "creditos": ["Foto: Fulano (CC BY 2.0)"]}
    c07.aplicar(pasta, saida, 1, reg, c07.LETRAS_AB)
    th = pasta / "thumbs"
    assert (th / "thumb_01_a.png").read_bytes() == b"tpl"            # a fica no template
    assert (th / "thumb_01_b.png").read_bytes() == b"colb"
    assert (th / "thumb_01_c.png").read_bytes() == b"colc"
    assert (pasta / "descricoes.txt").read_text(encoding="utf-8").count("Foto: Fulano") == 1


def test_07b_aplicar_e_ab_conflitam(tmp_path, monkeypatch):
    pasta = tmp_path / "2026-10-22_x"
    pasta.mkdir()
    monkeypatch.setattr(c07, "achar_pasta", lambda s: pasta)
    with pytest.raises(SystemExit) as e:
        c07.main(["x", "--aplicar", "--ab"])
    assert "não combinam" in str(e.value)


def test_07b_ab_com_saida_conflita(tmp_path, monkeypatch):
    pasta = tmp_path / "2026-10-22_x"
    pasta.mkdir()
    monkeypatch.setattr(c07, "achar_pasta", lambda s: pasta)
    with pytest.raises(SystemExit):
        c07.main(["x", "--ab", f"--saida={tmp_path / 'previa'}"])


# --- _colagem.colagem_ab -------------------------------------------------------------------------

def test_colagem_ab_b_c_colagem_com_a_template(tmp_path):
    pasta = _pasta_ab(tmp_path, colagem="bc")
    assert [p.name for p in col.colagem_ab(pasta / "thumbs", 1)] == ["thumb_01_b.png", "thumb_01_c.png"]


def test_colagem_ab_vazio_no_padrao_e_sem_colagem(tmp_path):
    assert col.colagem_ab(_pasta_ab(tmp_path, colagem="abc") / "thumbs", 1) == []     # padrão: a é colagem
    sem = tmp_path / "o"
    sem.mkdir()
    assert col.colagem_ab(_pasta_ab(sem, colagem="") / "thumbs", 1) == []             # tudo template


def test_colagem_ab_so_uma_colagem(tmp_path):
    pasta = _pasta_ab(tmp_path, colagem="c")
    assert [p.name for p in col.colagem_ab(pasta / "thumbs", 1)] == ["thumb_01_c.png"]


# --- _editor -------------------------------------------------------------------------------------

@pytest.fixture
def runs(monkeypatch):
    cmds, rcs = [], {}

    def fake(cmd, **kw):
        cmds.append(cmd)
        rc = next((v for k, v in rcs.items() if any(k in str(c) for c in cmd)), 0)
        return types.SimpleNamespace(returncode=rc)
    monkeypatch.setattr(_editor.subprocess, "run", fake)
    return cmds, rcs


def test_voltar_template_com_letras_roda_07_por_variante(tmp_path, runs):
    cmds, _ = runs
    assert _editor.voltar_template(tmp_path, 3, ("b", "c")) is True
    assert len(cmds) == 2
    assert all(c[1].endswith("07_thumb.py") and "--bloco=3" in c for c in cmds)
    assert [c[-1] for c in cmds] == ["--variante=b", "--variante=c"]


def test_voltar_template_sem_letras_roda_uma_vez_sem_variante(tmp_path, runs):
    cmds, _ = runs
    assert _editor.voltar_template(tmp_path, 3) is True
    assert len(cmds) == 1 and not any(str(c).startswith("--variante") for c in cmds[0])


def test_voltar_template_letras_falha_para_e_nao_mexe_na_descricao(tmp_path, runs):
    cmds, rcs = runs
    rcs["--variante=b"] = 1
    desc = tmp_path / "descricoes.txt"
    desc.write_text("x", encoding="utf-8")
    assert _editor.voltar_template(tmp_path, 3, ("b", "c")) is False
    assert len(cmds) == 1 and desc.read_text(encoding="utf-8") == "x"


def test_refazer_colagem_ab_sem_colagem_nao_roda(tmp_path, runs):
    cmds, _ = runs
    pasta = _pasta_ab(tmp_path, colagem="")
    assert _editor.refazer_colagem_ab(pasta, 1) == [] and cmds == []


def test_refazer_colagem_ab_ok_e_falha(tmp_path, runs):
    cmds, rcs = runs
    pasta = _pasta_ab(tmp_path, colagem="bc")
    assert _editor.refazer_colagem_ab(pasta, 1) == []
    assert cmds[0][1].endswith("07b_colagem.py")
    assert "--ab" in cmds[0] and "--sem-editor" in cmds[0] and "--bloco=1" in cmds[0]
    cmds.clear()
    rcs["07b_colagem"] = 1                                 # 07b falha: b/c voltam pro template
    av = _editor.refazer_colagem_ab(pasta, 1)
    assert len(av) == 1 and "voltou pro template" in av[0]
    assert [c[-1] for c in cmds[1:]] == ["--variante=b", "--variante=c"]


def test_refazer_artes_template_chama_colagem_ab(tmp_path, runs):
    cmds, _ = runs
    pasta = _pasta_ab(tmp_path, colagem="bc")
    assert _editor.refazer_artes(pasta, 1, pasta / "thumbs" / "thumb_01_a.png") == []
    scripts = [Path(c[1]).name for c in cmds]
    assert scripts == ["07_thumb.py", "07b_colagem.py"] and "--ab" in cmds[1]


# --- 11_revisor ----------------------------------------------------------------------------------

def test_texto_da_thumb_misto_ab(tmp_path):
    pasta = _pasta_ab(tmp_path, colagem="bc")
    assert rv.texto_da_thumb(pasta, 1, "TEMPLATE") == "TEMPLATE | TXT B | TXT C"


def test_texto_da_thumb_so_template_e_sem_arquivos(tmp_path):
    assert rv.texto_da_thumb(_pasta_ab(tmp_path, colagem=""), 1, "T") == "T"
    assert rv.texto_da_thumb(tmp_path / "vazia", 1, "T") == "T"


@pytest.fixture
def conferir(tmp_path, monkeypatch):
    """conferir_colagem_ab com tudo mockado: (pasta, anthropic falso, checadas, voltas, eventos, resultado)."""
    pasta = _pasta_ab(tmp_path, colagem="bc")
    checadas, voltas, eventos, resultado = [], [], [], {}
    resp = types.SimpleNamespace(model="m")

    def checar(client, thumb, titulo, texto):
        checadas.append(thumb.name)
        return resultado.get(thumb.name, {"thumb_ok": True, "thumb_problema": ""}), resp
    monkeypatch.setattr(rv, "checar_thumb", checar)
    monkeypatch.setattr(rv, "custo", lambda r: (10, 5, 0.01))
    monkeypatch.setattr(rv._custo, "cache", lambda r: {})
    monkeypatch.setattr(rv, "evento", lambda *a, **k: eventos.append((a, k)))
    monkeypatch.setattr(rv._editor, "voltar_template",
                        lambda p, b, letras=(): voltas.append((b, letras)) or True)
    return pasta, types.SimpleNamespace(APIError=RuntimeError), checadas, voltas, eventos, resultado


def test_conferir_colagem_ab_ok_nao_volta(conferir):
    pasta, anth, checadas, voltas, eventos, _ = conferir
    usd = rv.conferir_colagem_ab(None, anth, "live", pasta, 1, "Título")
    assert checadas == ["thumb_01_b.png", "thumb_01_c.png"] and voltas == []
    assert usd == pytest.approx(0.02)
    assert all(a[2] == "llm" for a, _ in eventos)


def test_conferir_colagem_ab_reprovada_volta_b_c_e_para(conferir):
    pasta, anth, checadas, voltas, eventos, resultado = conferir
    resultado["thumb_01_b.png"] = {"thumb_ok": False, "thumb_problema": "texto cortado"}
    usd = rv.conferir_colagem_ab(None, anth, "live", pasta, 1, "Título")
    assert voltas == [(1, ("b", "c"))]
    assert checadas == ["thumb_01_b.png"]                  # parou na 1ª reprovada
    assert usd == pytest.approx(0.01)
    assert any(a[2] == "aviso" for a, _ in eventos)


def test_conferir_colagem_ab_recusa_conta_como_reprovada(conferir, monkeypatch):
    pasta, anth, checadas, voltas, eventos, _ = conferir
    monkeypatch.setattr(rv, "checar_thumb", lambda *a: (None, types.SimpleNamespace(model="m")))
    rv.conferir_colagem_ab(None, anth, "live", pasta, 1, "T")
    assert voltas == [(1, ("b", "c"))]


def test_conferir_colagem_ab_erro_de_api_volta(conferir, monkeypatch):
    pasta, anth, checadas, voltas, eventos, _ = conferir

    def falha(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(rv, "checar_thumb", falha)
    assert rv.conferir_colagem_ab(None, anth, "live", pasta, 1, "T") == 0.0
    assert voltas == [(1, ("b", "c"))]


def test_conferir_colagem_ab_sem_colagem_nao_checa(tmp_path, conferir):
    _, anth, checadas, voltas, _, _ = conferir
    outra = tmp_path / "outra"
    outra.mkdir()
    pasta = _pasta_ab(outra, colagem="")
    assert rv.conferir_colagem_ab(None, anth, "live", pasta, 1, "T") == 0.0
    assert checadas == [] and voltas == []


# --- Curador -------------------------------------------------------------------------------------

def test_modo_colagem_aceita_ab(raiz):
    (raiz / "config" / "thumb.json").write_text('{"colagem": "ab"}', encoding="utf-8")
    assert cu.modo_colagem() == "ab"


def test_curador_ab_roda_07b_ab_antes_do_revisor(raiz, monkeypatch):
    import _paths
    (raiz / "config" / "thumb.json").write_text('{"colagem": "ab"}', encoding="utf-8")
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append((script, *a)) or True)
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: raiz / "outputs" / stem)
    monkeypatch.setattr(pub, "aprovados", lambda pasta: [])
    monkeypatch.setattr(pub, "gerar", lambda pasta: (None, []))
    cu.processar({**_item("a"), "stem": "renan_x"})
    nomes = [c[0] for c in chamadas]
    assert nomes.index("07b_colagem.py") == nomes.index("11_revisor.py") - 1
    assert ("07b_colagem.py", "renan_x", "--ab") in chamadas
    assert ("07b_colagem.py", "renan_x", "--aplicar") not in chamadas


def test_resumo_tem_secao_thumb_ab(raiz):
    rodada = {"quando": "x", "custo": 0.0, "estoque": None, "avisos": [], "fila": [], "recusados": [],
              "escolhidos": [], "processados": [], "thumb_ab": "template 1 x colagem 2 (empate 0)"}
    txt = cu.escrever_resumo(rodada)
    assert "## Thumb A/B" in txt and "template 1 x colagem 2" in txt and "16_thumb_ab.py registrar" in txt
    assert "## Thumb A/B" not in cu.escrever_resumo({**rodada, "thumb_ab": None})


def test_placar_thumb_ab_so_no_modo_ab(raiz, monkeypatch):
    monkeypatch.setattr(ab, "SAIDA", raiz / "state" / "thumb_ab.json")
    assert cu.placar_thumb_ab() is None                    # sem thumb.json: desligado
    (raiz / "config" / "thumb.json").write_text('{"colagem": "ab"}', encoding="utf-8")
    linha = cu.placar_thumb_ab()
    assert "template 0 x colagem 0" in linha and "0 teste(s)" in linha and "pouco dado" in linha


# --- _publicacao ---------------------------------------------------------------------------------

def test_thumbs_do_teste_estilos(tmp_path):
    pasta = _pasta_ab(tmp_path, colagem="bc")
    lista = pub.thumbs_do_teste(pasta, 1, pasta / "thumbs" / "thumb_01_a.png")
    assert [(t.name, e) for t, e in lista] == [("thumb_01_a.png", "template"),
                                               ("thumb_01_b.png", "colagem"),
                                               ("thumb_01_c.png", "colagem")]


def test_thumbs_do_teste_manual_sobe_sozinha(tmp_path):
    pasta = _pasta_ab(tmp_path, colagem="bc")
    manual = pasta / "thumbs" / "thumb_01_manual.png"
    manual.write_bytes(b"m")
    assert pub.thumbs_do_teste(pasta, 1, manual) == [(manual, "manual")]


def test_thumbs_do_teste_sem_abc_cai_na_escolhida(tmp_path):
    (tmp_path / "thumbs").mkdir()
    esc = tmp_path / "thumbs" / "thumb_01_x.png"
    assert pub.thumbs_do_teste(tmp_path, 1, esc) == [(esc, "template")]
    assert pub.thumbs_do_teste(tmp_path, 1, None) == []


def test_linhas_thumbs_formatos(tmp_path):
    assert pub.linhas_thumbs([]) == ["THUMB:   (sem thumb)"]
    um = [(tmp_path / "thumb_01_manual.png", "manual")]
    assert pub.linhas_thumbs(um) == ["THUMB:   thumbs/thumb_01_manual.png (manual)"]
    tres = [(tmp_path / f"thumb_01_{l}.png", e) for l, e in zip("abc", ("template", "colagem", "colagem"))]
    linhas = pub.linhas_thumbs(tres)
    assert linhas[0].startswith("THUMBS") and "  b: thumbs/thumb_01_b.png (colagem)" in linhas
    assert len(linhas) == 4


def _pub_pasta(tmp_path, monkeypatch, manual=False):
    import _cobertura
    monkeypatch.setattr(_cobertura, "CANAL_JSON", tmp_path / "canal.json")
    pasta = _pasta_ab(tmp_path, colagem="bc")
    (pasta / "finalizados").mkdir()
    (pasta / "finalizados" / "video_01_a.mp4").touch()
    (pasta / "blocos.json").write_text(json.dumps({"blocos": [
        {"id": 1, "score_potencial": 8, "duracao_minutos": 6, "titulo_sugerido": "sug"}]}), encoding="utf-8")
    nome = "thumb_01_manual.png" if manual else "thumb_01_a.png"
    if manual:
        (pasta / "thumbs" / nome).write_bytes(b"m")
    (pasta / "revisao.json").write_text(
        json.dumps({"01": {"status": "aprovado", "thumb": nome}}), encoding="utf-8")
    return pasta


def test_gerar_lista_as_3_thumbs_com_estilo(tmp_path, monkeypatch, banco):
    pasta = _pub_pasta(tmp_path, monkeypatch)
    caminho, lista = pub.gerar(pasta, datetime(2026, 10, 22, 9))
    texto = caminho.read_text(encoding="utf-8")
    assert "THUMBS (Testar e comparar):" in texto
    assert "a: thumbs/thumb_01_a.png (template)" in texto
    assert "b: thumbs/thumb_01_b.png (colagem)" in texto and "c: thumbs/thumb_01_c.png (colagem)" in texto
    assert len(lista[0]["thumbs"]) == 3


def test_gerar_manual_sobe_sozinha(tmp_path, monkeypatch, banco):
    pasta = _pub_pasta(tmp_path, monkeypatch, manual=True)
    caminho, _ = pub.gerar(pasta, datetime(2026, 10, 22, 9))
    corpo = caminho.read_text(encoding="utf-8").split("ARQUIVO:", 1)[1]
    assert "THUMB:   thumbs/thumb_01_manual.png (manual)" in corpo
    assert "THUMBS (Testar e comparar):" not in corpo


# --- 16_thumb_ab ---------------------------------------------------------------------------------

@pytest.fixture
def ab_env(tmp_path, monkeypatch, banco):
    monkeypatch.setattr(ab, "SAIDA", tmp_path / "state" / "thumb_ab.json")
    return tmp_path


def _reg(tmp_path, bid=1, colagem="bc", v="b", **kw):
    pasta = _pasta_ab(tmp_path, bid=bid, colagem=colagem)
    return ab.registrar(str(pasta), bid, v, **kw), pasta


def test_registrar_estilos_e_vencedor_colagem(ab_env):
    t, _ = _reg(ab_env, v="B", watch={"a": 30.0, "b": 40.0, "c": 30.0}, nota="n")
    assert t["vencedora"] == "b" and t["estilo_vencedor"] == "colagem" and t["misto"] is True
    assert t["estilos"] == {"a": "template", "b": "colagem", "c": "colagem"}
    assert t["watch_time_pct"]["b"] == 40.0 and t["nota"] == "n"
    assert json.loads(ab.SAIDA.read_text(encoding="utf-8"))["testes"]["live#01"]["vencedora"] == "b"


def test_registrar_vencedor_template(ab_env):
    t, _ = _reg(ab_env, v="a")
    assert t["estilo_vencedor"] == "template"


def test_registrar_nao_misto(ab_env):
    t, _ = _reg(ab_env, colagem="", v="a")
    assert t["misto"] is False


def test_registrar_empate(ab_env):
    t, _ = _reg(ab_env, v="empate")
    assert t["estilo_vencedor"] == "empate" and t["misto"] is True


def test_registrar_letra_invalida_e_inexistente(ab_env):
    pasta = _pasta_ab(ab_env)
    with pytest.raises(ValueError, match="use a, b, c ou empate"):
        ab.registrar(str(pasta), 1, "d")
    (pasta / "thumbs" / "thumb_01_c.png").unlink()
    with pytest.raises(ValueError, match="não tem thumb 'c'"):
        ab.registrar(str(pasta), 1, "c")
    assert not ab.SAIDA.exists()


def test_registrar_bloco_sem_thumbs(ab_env):
    pasta = _pasta_ab(ab_env)
    with pytest.raises(ValueError, match="sem thumbs"):
        ab.registrar(str(pasta), 7, "a")


def test_registrar_substitui_mesmo_video(ab_env):
    _, pasta = _reg(ab_env, v="a")
    ab.registrar(str(pasta), 1, "c")
    testes = json.loads(ab.SAIDA.read_text(encoding="utf-8"))["testes"]
    assert len(testes) == 1 and testes["live#01"]["vencedora"] == "c"


def _teste(vencedor, misto=True):
    return {"misto": misto, "estilo_vencedor": vencedor}


def test_placar_so_mistos_contam():
    dados = {"testes": {"1": _teste("colagem"), "2": _teste("template"), "3": _teste("empate"),
                        "4": _teste("template", misto=False)}}
    assert ab.placar(dados) == {"template": 1, "colagem": 1, "empate": 1, "testes": 3, "fora": 1}


def test_placar_vazio(ab_env):
    assert ab.placar() == {"template": 0, "colagem": 0, "empate": 0, "testes": 0, "fora": 0}


def test_sugestao_limiar_5():
    p = {"template": 0, "colagem": 4, "empate": 3, "testes": 7, "fora": 0}
    assert "pouco dado" in ab.sugestao(p) and "4/5" in ab.sugestao(p)
    assert "pouco dado" not in ab.sugestao({**p, "colagem": 5})


def test_sugestao_dois_tercos():
    s = ab.sugestao({"template": 2, "colagem": 4, "empate": 0})
    assert "colagem venceu 4 de 6" in s and "colagem: padrao" in s
    s = ab.sugestao({"template": 4, "colagem": 1, "empate": 0})
    assert "template venceu 4 de 5" in s and "colagem: desligado" in s
    assert "sem estilo dominante" in ab.sugestao({"template": 3, "colagem": 3, "empate": 0})
    assert "sem estilo dominante" in ab.sugestao({"template": 2, "colagem": 3, "empate": 0})


def test_main_registrar_e_placar(ab_env, capsys):
    pasta = _pasta_ab(ab_env)
    assert ab.main(["registrar", str(pasta), "1", "b", "--b=41,2", "--nota=x"]) == 0
    assert "venceu b (colagem)" in capsys.readouterr().out
    assert ab.main(["registrar", str(pasta), "1", "z"]) == 1
    assert ab.main(["placar"]) == 0
    assert "colagem 1" in capsys.readouterr().out
    assert ab.main([]) == 1
