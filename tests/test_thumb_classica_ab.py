"""Modo ab da thumb clássica (config/thumb.json -> modo: "ab"; colagem pausada).
Tudo mockado: sem API, sem ffmpeg, sem state/ real. O 07_thumb roda no import, então
texto_da_variante/gerar_textos_ab não são testados aqui (exigiria refatorar o script)."""
import importlib
import importlib.util
import json
import types
from pathlib import Path

import pytest

import _editor
import _paths
from test_curador import cu, raiz  # noqa: F401
from test_editor import _Client, _resp

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, SCRIPTS / arquivo)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rv = _carregar("revisor_classica_ab", "11_revisor.py")
c07 = _carregar("colagem07b_pausada", "07b_colagem.py")
ab = importlib.import_module("16_thumb_ab")


def _thumb_json(conteudo):
    _paths.THUMB_JSON.parent.mkdir(parents=True, exist_ok=True)
    _paths.THUMB_JSON.write_text(conteudo if isinstance(conteudo, str) else json.dumps(conteudo),
                                 encoding="utf-8")


def _pasta(tmp_path, letras="abc", textos=None, bid=1):
    pasta = tmp_path / "2026-10-26_live"
    th = pasta / "thumbs"
    th.mkdir(parents=True)
    for l in letras:
        (th / f"thumb_{bid:02d}_{l}.png").write_bytes(b"x" + l.encode())
    if textos is not None:
        (th / f"candidatos_{bid:02d}.json").write_text(json.dumps({"textos": textos}), encoding="utf-8")
    return pasta


# --- _paths.modo_thumb ---------------------------------------------------------------------------

def test_modo_thumb_ausente_e_quebrado_e_classica():
    assert _paths.modo_thumb() == "classica"
    _thumb_json("{quebrado")
    assert _paths.modo_thumb() == "classica"
    _thumb_json("[1, 2]")                       # JSON válido, mas não é objeto
    assert _paths.modo_thumb() == "classica"


def test_modo_thumb_ab_e_outro():
    _thumb_json({"modo": "ab"})
    assert _paths.modo_thumb() == "ab"
    _thumb_json({"modo": "colagem"})
    assert _paths.modo_thumb() == "classica"
    _thumb_json({"colagem": "pausada"})
    assert _paths.modo_thumb() == "classica"


# --- _editor.textos_thumb_ab ---------------------------------------------------------------------

def _ab(opcoes, atual="ATUAL"):
    return _editor.textos_thumb_ab(_Client(_resp(json.dumps({"opcoes": opcoes}))), "p", atual)


def test_textos_thumb_ab_filtra_longo_igual_e_duplicado():
    longo = "X" * (_editor.MAX_TEXTO_THUMB + 1)
    textos, _ = _ab(["  atual ", longo, "novo um", "NOVO UM", "outro", "terceiro"])
    assert textos == ["NOVO UM", "OUTRO"]          # igual ao atual (case/espaço), longo e duplicado saem; máx 2


def test_textos_thumb_ab_no_limite_de_28_passa():
    ok = "A" * _editor.MAX_TEXTO_THUMB
    assert _ab([ok])[0] == [ok]


def test_textos_thumb_ab_recusa_devolve_none():
    textos, resp = _editor.textos_thumb_ab(_Client(_resp(None, stop="refusal")), "p", "A")
    assert textos is None and resp.stop_reason == "refusal"


@pytest.mark.parametrize("texto", ["não é json", '{"outra": 1}', None])
def test_textos_thumb_ab_json_ruim_devolve_lista_vazia(texto):
    textos, resp = _editor.textos_thumb_ab(_Client(_resp(texto)), "p", "A")
    assert textos == [] and resp is not None


def test_montar_pedido_thumb_ab_tem_titulo_texto_e_ganchos():
    ped = _editor.montar_pedido_thumb_ab("Tít", "TXT", {"resumo": "res", "ganchos": ["g1", "g2"]})
    assert "Tít" in ped and "TXT" in ped and "res" in ped and "- g1" in ped and "- g2" in ped


# --- _editor.refazer_classica_ab -----------------------------------------------------------------

@pytest.fixture
def runs(monkeypatch):
    cmds, rcs = [], {}

    def fake(cmd, **kw):
        cmds.append(cmd)
        return types.SimpleNamespace(returncode=next((v for k, v in rcs.items() if k in str(cmd)), 0))
    monkeypatch.setattr(_editor.subprocess, "run", fake)
    return cmds, rcs


def test_refazer_classica_ab_modo_classica_nao_roda(tmp_path, runs):
    cmds, _ = runs
    assert _editor.refazer_classica_ab(_pasta(tmp_path), 1, "a") == [] and cmds == []


def test_refazer_classica_ab_roda_so_nas_outras_letras_existentes(tmp_path, runs):
    cmds, _ = runs
    _thumb_json({"modo": "ab"})
    assert _editor.refazer_classica_ab(_pasta(tmp_path, letras="ac"), 1, "a") == []
    assert len(cmds) == 1                                   # b não existe, a é a feita
    assert cmds[0][1].endswith("07_thumb.py") and "--bloco=1" in cmds[0] and cmds[0][-1] == "--variante=c"


def test_refazer_classica_ab_todas(tmp_path, runs):
    cmds, _ = runs
    _thumb_json({"modo": "ab"})
    _editor.refazer_classica_ab(_pasta(tmp_path), 1, "b")
    assert [c[-1] for c in cmds] == ["--variante=a", "--variante=c"]


def test_refazer_classica_ab_falha_vira_aviso_e_para(tmp_path, runs):
    cmds, rcs = runs
    _thumb_json({"modo": "ab"})
    rcs["--variante=a"] = 1
    av = _editor.refazer_classica_ab(_pasta(tmp_path), 1, "b")
    assert len(av) == 1 and "thumb a" in av[0] and len(cmds) == 1


# --- 11_revisor ----------------------------------------------------------------------------------

def test_criterio_thumb_tem_regra_da_seta():
    assert "SETA OU CÍRCULO" in rv.CRITERIO_THUMB and "CERTEZA" in rv.CRITERIO_THUMB
    assert "na dúvida, reprove" in rv.CRITERIO_THUMB


def test_texto_da_thumb_usa_textos_da_fila(tmp_path):
    pasta = _pasta(tmp_path, textos={"a": "UM", "b": "DOIS", "c": "TRÊS"})
    assert rv.texto_da_thumb(pasta, 1, "BASE") == "UM | DOIS | TRÊS"


def test_texto_da_thumb_fila_parcial_ou_ausente_cai_no_texto_thumb(tmp_path):
    assert rv.texto_da_thumb(_pasta(tmp_path, textos={"b": "DOIS"}), 1, "BASE") == "BASE | DOIS"
    outra = tmp_path / "o"
    outra.mkdir()
    assert rv.texto_da_thumb(_pasta(outra), 1, "BASE") == "BASE"


def test_textos_classica_fila_ruim(tmp_path):
    pasta = _pasta(tmp_path)
    (pasta / "thumbs" / "candidatos_01.json").write_text("{x", encoding="utf-8")
    assert rv.textos_classica(pasta, 1) == {}
    (pasta / "thumbs" / "candidatos_01.json").write_text('{"textos": [1]}', encoding="utf-8")
    assert rv.textos_classica(pasta, 1) == {}


@pytest.fixture
def conferir(tmp_path, monkeypatch):
    pasta = _pasta(tmp_path, textos={"b": "DOIS", "c": "TRÊS"})
    checadas, eventos, resultado = [], [], {}
    resp = types.SimpleNamespace(model="m")

    def checar(client, thumb, titulo, texto):
        checadas.append((thumb.name, texto))
        return resultado.get(thumb.name, {"thumb_ok": True, "thumb_problema": ""}), resp
    monkeypatch.setattr(rv, "checar_thumb", checar)
    monkeypatch.setattr(rv, "custo", lambda r: (10, 5, 0.01))
    monkeypatch.setattr(rv._custo, "cache", lambda r: {})
    monkeypatch.setattr(rv, "evento", lambda *a, **k: eventos.append((a, k)))
    _thumb_json({"modo": "ab"})
    return pasta, types.SimpleNamespace(APIError=RuntimeError), checadas, eventos, resultado


def test_conferir_classica_ab_ok_mantem(conferir):
    pasta, anth, checadas, eventos, _ = conferir
    usd = rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T")
    assert checadas == [("thumb_01_b.png", "DOIS"), ("thumb_01_c.png", "TRÊS")]
    assert usd == pytest.approx(0.02)
    assert (pasta / "thumbs" / "thumb_01_b.png").exists() and (pasta / "thumbs" / "thumb_01_c.png").exists()
    assert not list((pasta / "thumbs").glob("*_reprovada.png"))


def test_conferir_classica_ab_reprovada_renomeia_so_ela(conferir):
    pasta, anth, _, eventos, resultado = conferir
    resultado["thumb_01_b.png"] = {"thumb_ok": False, "thumb_problema": "texto cortado"}
    rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T")
    th = pasta / "thumbs"
    assert not (th / "thumb_01_b.png").exists() and (th / "thumb_01_b_reprovada.png").exists()
    assert (th / "thumb_01_c.png").exists() and (th / "thumb_01_a.png").exists()
    assert any(a[2] == "aviso" for a, _ in eventos)


def test_conferir_classica_ab_erro_de_api_renomeia(conferir, monkeypatch):
    pasta, anth, *_ = conferir

    def falha(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(rv, "checar_thumb", falha)
    assert rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T") == 0.0
    assert (pasta / "thumbs" / "thumb_01_b_reprovada.png").exists()
    assert (pasta / "thumbs" / "thumb_01_c_reprovada.png").exists()


def test_conferir_classica_ab_recusa_renomeia(conferir, monkeypatch):
    pasta, anth, *_ = conferir
    monkeypatch.setattr(rv, "checar_thumb", lambda *a: (None, types.SimpleNamespace(model="m")))
    rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T")
    assert (pasta / "thumbs" / "thumb_01_b_reprovada.png").exists()


def test_conferir_classica_ab_modo_classica_nao_chama(conferir):
    pasta, anth, checadas, *_ = conferir
    _thumb_json({"modo": "classica"})
    assert rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T") == 0.0
    assert checadas == [] and not list((pasta / "thumbs").glob("*_reprovada.png"))


def test_conferir_classica_ab_orcamento_estourado_reprova_sem_api(conferir, monkeypatch):
    pasta, anth, checadas, eventos, _ = conferir
    etapas = []

    def estoura(stem, etapa):
        etapas.append((stem, etapa))
        raise rv._custo.OrcamentoEstourado("estourou")
    monkeypatch.setattr(rv._custo, "checar_orcamento", estoura)
    assert rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T") == 0.0
    assert checadas == []                                   # nenhuma chamada paga
    assert etapas == [("live", "11_revisor")] * 2           # checou antes de cada b/c
    th = pasta / "thumbs"
    assert (th / "thumb_01_b_reprovada.png").exists() and (th / "thumb_01_c_reprovada.png").exists()
    assert any("orçamento" in k.get("mensagem", "") for _, k in eventos)


def test_conferir_classica_ab_pula_colagem_aplicada(conferir, monkeypatch):
    pasta, anth, checadas, *_ = conferir
    monkeypatch.setattr(rv._colagem, "variante_aplicada",
                        lambda t: {"texto": ["X"]} if t.name.endswith("_b.png") else None)
    rv.conferir_classica_ab(None, anth, "live", pasta, 1, "T")
    assert [c[0] for c in checadas] == ["thumb_01_c.png"]


# --- 16_thumb_ab ---------------------------------------------------------------------------------

@pytest.fixture
def ab_env(tmp_path, monkeypatch, banco):
    monkeypatch.setattr(ab, "SAIDA", tmp_path / "state" / "thumb_ab.json")
    return tmp_path


def test_registrar_guarda_textos_da_fila(ab_env):
    pasta = _pasta(ab_env, textos={"a": "UM", "b": "DOIS", "c": "TRÊS"})
    t = ab.registrar(str(pasta), 1, "b")
    assert t["textos"] == {"a": "UM", "b": "DOIS", "c": "TRÊS"} and t["misto"] is False
    assert json.loads(ab.SAIDA.read_text(encoding="utf-8"))["testes"]["live#01"]["textos"]["b"] == "DOIS"


def test_registrar_sem_fila_textos_vazio_e_so_letras_existentes(ab_env):
    assert ab.registrar(str(_pasta(ab_env)), 1, "a")["textos"] == {}
    outra = ab_env / "o"
    outra.mkdir()
    pasta = _pasta(outra, letras="ab", textos={"a": "UM", "b": "DOIS", "c": "TRÊS"})
    assert set(ab.registrar(str(pasta), 1, "a")["textos"]) == {"a", "b"}


def test_textos_fila_ruim(tmp_path):
    pasta = _pasta(tmp_path)
    (pasta / "thumbs" / "candidatos_01.json").write_text("[", encoding="utf-8")
    assert ab.textos(pasta, 1) == {}


def test_placar_classica_conta_so_nao_mistos():
    dados = {"testes": {
        "x#01": {"vencedora": "a", "misto": False}, "x#02": {"vencedora": "b", "misto": False},
        "x#03": {"vencedora": "b", "misto": False}, "x#04": {"vencedora": "empate", "misto": False},
        "x#05": {"vencedora": "c", "misto": True}}}
    assert ab.placar_classica(dados) == {"a": 1, "b": 2, "c": 0, "empate": 1, "testes": 4}


def test_linha_classica_formato():
    linha = ab.linha_classica({"a": 1, "b": 2, "c": 0, "empate": 1, "testes": 4})
    assert "4 teste(s)" in linha and "a (texto do 03) 1" in linha and "b 2" in linha and "empate 1" in linha


# --- Curador -------------------------------------------------------------------------------------

def test_placar_thumb_ab_modo_ab_da_classica(raiz, monkeypatch):
    monkeypatch.setattr(ab, "SAIDA", raiz / "state" / "thumb_ab.json")
    _thumb_json({"modo": "ab", "colagem": "pausada"})
    linha = cu.placar_thumb_ab()
    assert "clássica" in linha and "0 teste(s)" in linha


def test_placar_thumb_ab_classica_pura_e_none(raiz, monkeypatch):
    monkeypatch.setattr(ab, "SAIDA", raiz / "state" / "thumb_ab.json")
    _thumb_json({"modo": "classica", "colagem": "pausada"})
    assert cu.placar_thumb_ab() is None


# --- 07b pausada ---------------------------------------------------------------------------------

def test_07b_pausada_devolve_3_sem_fazer_nada(tmp_path, monkeypatch, capsys):
    _thumb_json({"colagem": "pausada"})
    monkeypatch.setattr(c07, "achar_pasta", lambda s: pytest.fail("não devia procurar a pasta"))
    assert c07.main(["live"]) == 3
    assert "pausada" in capsys.readouterr().out


def test_07b_pausada_forcar_segue(tmp_path, monkeypatch):
    _thumb_json({"colagem": "pausada"})
    chamou = []

    def achar(stem):
        chamou.append(stem)
        raise RuntimeError("parou aqui")
    monkeypatch.setattr(c07, "achar_pasta", achar)
    with pytest.raises(RuntimeError, match="parou aqui"):
        c07.main(["live", "--forcar"])
    assert chamou == ["live"]


def test_07b_pausada_helper():
    assert c07.pausada() is False
    _thumb_json({"colagem": "ab"})
    assert c07.pausada() is False
    _thumb_json({"colagem": "pausada"})
    assert c07.pausada() is True
