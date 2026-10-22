"""Step 13: agente Curador. yt-dlp, Claude e subprocess falsos (nunca rede, nunca API)."""
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec = importlib.util.spec_from_file_location(
    "curador", Path(__file__).parent.parent / "scripts" / "13_curador.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)

HOJE = date.today()
CFG = {"dias": 3, "duracao_min": 20, "duracao_max": 240, "max_por_dia": 1, "por_canal": 8,
       "canais": [{"nome": "Renan Santos", "url": "https://www.youtube.com/@renan",
                   "prefixo": "renan", "zoom": "1696:954:16:0"},
                  {"nome": "Kim", "url": "https://www.youtube.com/@kim", "prefixo": "kim",
                   "zoom": None}]}


def _item(vid, titulo="Live boa", minutos=90, dias_atras=1, canal=0, **extra):
    c = CFG["canais"][canal]
    return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "titulo": titulo,
            "duracao_s": minutos * 60, "data": (HOJE - timedelta(days=dias_atras)).isoformat(),
            "live_status": "was_live", "canal": c["nome"], "prefixo": c["prefixo"],
            "zoom": c["zoom"], **extra}


@pytest.fixture
def raiz(tmp_path, monkeypatch, banco):
    """Projeto falso: config/, inputs/, outputs/, state/ em tmp_path."""
    (tmp_path / "config").mkdir()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "config" / "canais.json").write_text(json.dumps(CFG), encoding="utf-8")
    (tmp_path / "config" / "zoom.json").write_text('{"antigo": "1:1:0:0"}', encoding="utf-8")
    for nome, valor in (("ROOT", tmp_path), ("CONFIG", tmp_path / "config" / "canais.json"),
                        ("ZOOM_JSON", tmp_path / "config" / "zoom.json"),
                        ("INPUTS", tmp_path / "inputs"), ("OUTPUTS", tmp_path / "outputs"),
                        ("ESTADO", tmp_path / "state" / "curadoria.json"),
                        ("RESUMO", tmp_path / "state" / "curador_resumo.md"),
                        ("TRAVA", tmp_path / "state" / "curador.lock")):
        monkeypatch.setattr(cu, nome, valor)
    return tmp_path


# --- filtro grátis ------------------------------------------------------------------------

@pytest.mark.parametrize("item,motivo", [
    (_item("a"), None),
    (_item("a", minutos=10), "curto"),
    (_item("a", minutos=300), "longo demais"),
    (_item("a", dias_atras=5), "antigo"),
    (_item("a", live_status="is_live"), "ao vivo"),
    (_item("a", live_status="is_upcoming"), "ao vivo"),
])
def test_motivo_filtro(item, motivo):
    r = cu.motivo_filtro(item, CFG, HOJE, set())
    assert (r is None) if motivo is None else (motivo in r)


def test_motivo_filtro_ja_processado_e_sem_data():
    assert cu.motivo_filtro(_item("a"), CFG, HOJE, {"a"}) == "já processado"
    assert cu.motivo_filtro({**_item("b"), "data": None}, CFG, HOJE, set()) is None


def test_id_do_url():
    assert cu.id_do_url("https://www.youtube.com/watch?v=ZLA8JDXA28o\n") == "ZLA8JDXA28o"
    assert cu.id_do_url("https://youtu.be/ZLA8JDXA28o") == "ZLA8JDXA28o"
    assert cu.id_do_url("https://www.youtube.com/live/ZLA8JDXA28o?si=x") == "ZLA8JDXA28o"
    assert cu.id_do_url("lixo") is None


def test_ids_ja_processados_le_inputs_e_banco(raiz):
    (raiz / "inputs" / "x.url").write_text("https://www.youtube.com/watch?v=AAAAAAAAAAA\n",
                                          encoding="utf-8")
    cu.upsert_video("y", fonte_url="https://www.youtube.com/watch?v=BBBBBBBBBBB")
    assert cu.ids_ja_processados() == {"AAAAAAAAAAA", "BBBBBBBBBBB"}


# --- stem e zoom --------------------------------------------------------------------------

def test_montar_stem_slug_ascii_e_colisao(raiz):
    assert cu.montar_stem("renan", "É POSSÍVEL QUE LULA VIRE? | ANÁLISES") == \
        "renan_possivel_que_lula_vire_analises"
    (raiz / "inputs" / "kim_live_boa.mp4").touch()
    (raiz / "outputs" / "2026-10-22_kim_live_boa_2").mkdir()
    assert cu.montar_stem("kim", "Live boa") == "kim_live_boa_3"
    assert cu.montar_stem("kim", "?!") == "kim_video"
    assert cu.montar_stem("kim", "Live boa", {"kim_live_boa_3"}) == "kim_live_boa_4"


def test_rodada_mesmo_titulo_nao_colide(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a", "Live de hoje"), _item("b", "Live de hoje!")]}
    rodada["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9)}
    cu.main(["--max=2"])
    assert sorted(rodada["processados"]) == ["renan_live_hoje", "renan_live_hoje_2"]


def test_cadastrar_zoom_copia_do_canal_sem_sobrescrever(raiz):
    assert cu.cadastrar_zoom("novo", "1696:954:16:0") is True
    assert cu.cadastrar_zoom("antigo", "9:9:9:9") is True          # já tinha: mantém
    assert cu.cadastrar_zoom("sem", None) is False
    dados = json.loads((raiz / "config" / "zoom.json").read_text(encoding="utf-8"))
    assert dados == {"antigo": "1:1:0:0", "novo": "1696:954:16:0"}


# --- listagem -----------------------------------------------------------------------------

class _FakeYDL:
    def __init__(self, abas):
        self.abas = abas

    def __call__(self, opcoes):
        return self

    def extract_info(self, url, download=False):
        aba = url.rsplit("/", 1)[1]
        if aba not in self.abas:
            raise RuntimeError("This channel does not have a videos tab")
        return {"entries": self.abas[aba]}


def test_listar_canal_junta_abas_e_ignora_aba_inexistente(monkeypatch):
    ts = datetime(2026, 10, 21, 12).timestamp()
    fake = _FakeYDL({"streams": [{"id": "s1", "title": "Live", "duration": 3600,
                                  "timestamp": ts, "live_status": "was_live"}, None]})
    monkeypatch.setattr(cu, "_ydl", fake)
    itens = cu.listar_canal(CFG["canais"][0], 5)
    assert [i["id"] for i in itens] == ["s1"]
    assert itens[0]["data"] == "2026-10-21" and itens[0]["prefixo"] == "renan"
    assert itens[0]["url"].endswith("v=s1")


def test_detalhar_troca_titulo_e_data(monkeypatch):
    class Det:
        def extract_info(self, url, download=False):
            return {"title": "Título em português", "upload_date": "20261021",
                    "duration": 6000, "live_status": "was_live", "description": "x" * 500}
    monkeypatch.setattr(cu, "_ydl", lambda opcoes: Det())
    d = cu.detalhar(_item("a", titulo="English title"))
    assert d["titulo"] == "Título em português" and d["data"] == "2026-10-21"
    assert len(d["descricao"]) == 300


def test_detalhar_falha_devolve_item(monkeypatch):
    class Quebra:
        def extract_info(self, url, download=False):
            raise RuntimeError("rede")
    monkeypatch.setattr(cu, "_ydl", lambda opcoes: Quebra())
    item = _item("a")
    assert cu.detalhar(item) is item


# --- LLM ----------------------------------------------------------------------------------

def _resp(avaliacoes, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=2000, output_tokens=300),
        content=[SimpleNamespace(type="text", text=json.dumps({"avaliacoes": avaliacoes}))])


class _Cliente:
    def __init__(self, resposta):
        self.resposta, self.chamadas = resposta, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.chamadas.append(kw)
        return self.resposta


def test_avaliar_filtra_ids_desconhecidos_e_calcula_custo():
    cli = _Cliente(_resp([{"id": "a", "vale": True, "prioridade": 8, "motivo": "quente"},
                          {"id": "zzz", "vale": True, "prioridade": 9, "motivo": "inventado"}]))
    av, (tin, tout, custo) = cu.avaliar(cli, [_item("a")])
    assert set(av) == {"a"}
    assert (tin, tout) == (2000, 300) and custo == pytest.approx(2000 / 1e6 * 4 + 300 / 1e6 * 20)
    kw = cli.chamadas[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["effort"] == "low"
    assert kw["extra_body"] == {"fallbacks": "default"}
    assert "id=a" in kw["messages"][0]["content"]


def test_avaliar_recusa_devolve_vazio():
    av, custo = cu.avaliar(_Cliente(_resp([], stop="refusal")), [_item("a")])
    assert av == {} and custo[2] > 0


# --- rodada completa ----------------------------------------------------------------------

@pytest.fixture
def rodada(raiz, monkeypatch):
    """Liga a rodada a fakes: canais, LLM e processamento. Devolve o registro de chamadas."""
    reg = {"listar": {}, "avaliacoes": {}, "processados": [], "llm": 0}
    monkeypatch.setattr(cu, "listar_canal", lambda canal, n: reg["listar"].get(canal["prefixo"], []))
    monkeypatch.setattr(cu, "detalhar", lambda item: item)

    def avaliar(client, itens):
        reg["llm"] += 1
        reg["enviados"] = [i["id"] for i in itens]
        return {i["id"]: reg["avaliacoes"][i["id"]] for i in itens if i["id"] in reg["avaliacoes"]}, \
            (1000, 100, 0.006)
    monkeypatch.setattr(cu, "avaliar", avaliar)

    def processar(item):
        reg["processados"].append(item["stem"])
        return {"stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
                "ok": True, "aprovados": 3, "publicacao": "pub.txt", "avisos": []}
    monkeypatch.setattr(cu, "processar", processar)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: object())
    return reg


def _av(vale, prioridade=5, motivo="m"):
    return {"vale": vale, "prioridade": prioridade, "motivo": motivo}


def test_rodada_escolhe_por_prioridade_fila_e_recusa(raiz, rodada, banco):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")],
                        "kim": [_item("c", "Jingle", canal=1)]}
    rodada["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9), "c": _av(False, 1, "jingle")}
    assert cu.main([]) == 0
    assert rodada["processados"] == ["renan_live_bravo"]               # max_por_dia = 1
    estado = json.loads(cu.ESTADO.read_text(encoding="utf-8"))
    assert {k: v["decisao"] for k, v in estado.items()} == \
        {"a": "fila", "b": "escolhido", "c": "recusado"}
    resumo = cu.RESUMO.read_text(encoding="utf-8")
    assert "Prontos pra publicar" in resumo and "3 corte(s)" in resumo and "jingle" in resumo
    eventos = banco("SELECT etapa, status, custo_usd, mensagem FROM eventos WHERE agente='curador'")
    assert any(e["status"] == "llm" and e["custo_usd"] == pytest.approx(0.006) for e in eventos)
    assert any(e["status"] == "recusado" and "jingle" in e["mensagem"] for e in eventos)
    assert not cu.TRAVA.exists()                                    # trava solta no fim


def test_rodada_seguinte_usa_fila_sem_llm_e_nao_reavalia(raiz, rodada):
    cu.gravar_estado({"a": {"decisao": "fila", "prioridade": 6, "motivo": "m", "titulo": "Live Alfa",
                            "canal": "Renan Santos"},
                      "c": {"decisao": "recusado", "motivo": "jingle"},
                      "b": {"decisao": "escolhido", "stem": "renan_live_bravo"}})
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")],
                        "kim": [_item("c", "Jingle", canal=1)]}
    assert cu.main([]) == 0
    assert rodada["llm"] == 0                                       # nada novo: sem custo
    assert rodada["processados"] == ["renan_live_alfa"]


def test_dry_run_nao_chama_llm_nem_processa(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a")]}
    assert cu.main(["--dry-run"]) == 0
    assert rodada["llm"] == 0 and rodada["processados"] == []
    assert not cu.ESTADO.exists()


def test_sem_pipeline_registra_mas_nao_processa(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a")]}
    rodada["avaliacoes"] = {"a": _av(True, 7)}
    assert cu.main(["--sem-pipeline"]) == 0
    assert rodada["processados"] == []
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]["decisao"] == "escolhido"


def test_max_sobrescreve_config(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    rodada["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9)}
    cu.main(["--max=2"])
    assert rodada["processados"] == ["renan_live_bravo", "renan_live_alfa"]


def test_trava_impede_rodada_dupla(raiz, rodada):
    cu.TRAVA.parent.mkdir(parents=True, exist_ok=True)
    cu.TRAVA.write_text("123", encoding="utf-8")
    assert cu.main([]) == 1
    assert cu.TRAVA.exists()                                        # não solta a trava alheia


def test_trava_velha_e_liberada(raiz, rodada):
    import os
    cu.TRAVA.parent.mkdir(parents=True, exist_ok=True)
    cu.TRAVA.write_text("123", encoding="utf-8")
    velho = (datetime.now() - timedelta(hours=cu.TRAVA_HORAS + 1)).timestamp()
    os.utime(cu.TRAVA, (velho, velho))
    assert cu.main([]) == 0


def test_falha_no_llm_registra_e_sai_com_erro(raiz, rodada, monkeypatch, banco):
    rodada["listar"] = {"renan": [_item("a")]}
    def quebra(client, itens):
        raise RuntimeError("API fora")
    monkeypatch.setattr(cu, "avaliar", quebra)
    assert cu.main([]) == 1
    assert banco("SELECT status FROM eventos WHERE agente='curador' AND status='falha'")


# --- processar ----------------------------------------------------------------------------

def test_processar_roda_etapas_em_ordem_e_avisa_sem_zoom(raiz, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append(script) or True)
    import _paths, _publicacao
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: raiz / "outputs" / stem)
    monkeypatch.setattr(_publicacao, "gerar", lambda pasta: (pasta / "publicacao.txt", [1, 2]))
    res = cu.processar({**_item("c", "Live", canal=1), "stem": "kim_live"})
    assert chamadas == ["01_baixar.py", "pipeline.py", "11_revisor.py"]
    assert res["ok"] and res["aprovados"] == 2
    assert res["avisos"] and "zoom" in res["avisos"][0]


def test_processar_para_na_primeira_falha(raiz, monkeypatch, banco):
    chamadas = []
    monkeypatch.setattr(cu, "rodar",
                        lambda script, *a: chamadas.append(script) or script != "pipeline.py")
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert chamadas == ["01_baixar.py", "pipeline.py"]
    assert not res["ok"] and "pipeline.py" in res["erro"]
    assert banco("SELECT 1 FROM eventos WHERE agente='curador' AND status='falha'")


# --- lacunas: resumo, fila + novos, recusa do modelo ---------------------------------------

def _rodada_vazia(**kw):
    return {"quando": "2026-10-22T09:00:00", "custo": 0.0, "escolhidos": [], "fila": [],
            "recusados": [], "processados": [], **kw}


def test_escrever_resumo_falhas_avisos_e_secoes(raiz):
    reg = {"titulo": "Live Z", "canal": "Kim", "motivo": "tema fraco"}
    texto = cu.escrever_resumo(_rodada_vazia(
        custo=0.0123, fila=[reg], recusados=[reg],
        processados=[
            {"stem": "a", "titulo": "Live A", "canal": "Renan", "ok": True, "aprovados": 2,
             "publicacao": "pub.txt", "avisos": ["a: canal sem zoom"]},
            {"stem": "b", "titulo": "Live B", "canal": "Kim", "ok": False, "aprovados": 0,
             "publicacao": None, "avisos": [], "erro": "pipeline.py falhou"}]))
    assert "US$ 0.012" in texto and "2 vídeo(s)" in texto
    assert "2 corte(s)" in texto and "`pub.txt`" in texto
    assert "## Falhas" in texto and "- b: pipeline.py falhou" in texto
    assert "Na fila" in texto and "Recusados" in texto and "tema fraco" in texto
    assert "## Avisos" in texto and "a: canal sem zoom" in texto
    assert "b: pipeline.py falhou" in texto
    assert cu.RESUMO.read_text(encoding="utf-8") == texto


def test_escrever_resumo_vazio_sem_secoes(raiz):
    texto = cu.escrever_resumo(_rodada_vazia())
    assert "0 vídeo(s)" in texto and "##" not in texto


def test_rodada_fila_e_novo_na_mesma_rodada(raiz, rodada):
    cu.gravar_estado({"a": {"decisao": "fila", "prioridade": 6, "motivo": "m",
                            "titulo": "Live Alfa", "canal": "Renan Santos",
                            "avaliado_em": "2026-10-21T09:00:00"}})
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("n", "Live Novo")]}
    rodada["avaliacoes"] = {"n": _av(True, 9)}
    assert cu.main([]) == 0
    assert rodada["enviados"] == ["n"]                    # só o novo vai pro LLM
    assert rodada["processados"] == ["renan_live_novo"]   # prioridade 9 > 6 da fila
    estado = json.loads(cu.ESTADO.read_text(encoding="utf-8"))
    assert estado["a"]["decisao"] == "fila" and estado["n"]["decisao"] == "escolhido"
    assert estado["a"]["avaliado_em"] == "2026-10-21T09:00:00"   # mantém a data original


def test_recusa_do_modelo_nao_grava_estado_do_id_sem_avaliacao(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    rodada["avaliacoes"] = {"a": _av(True, 8)}            # "b" volta sem avaliação
    assert cu.main([]) == 0
    estado = json.loads(cu.ESTADO.read_text(encoding="utf-8"))
    assert "b" not in estado and estado["a"]["decisao"] == "escolhido"
    assert rodada["processados"] == ["renan_live_alfa"]


def test_modelo_recusa_tudo_nao_grava_nada_e_nao_processa(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a")]}
    assert cu.main([]) == 0                               # avaliacoes vazio
    assert rodada["processados"] == []
    estado = json.loads(cu.ESTADO.read_text(encoding="utf-8")) if cu.ESTADO.exists() else {}
    assert estado == {}


def test_processamento_com_falha_sai_com_codigo_1(raiz, rodada, monkeypatch):
    rodada["listar"] = {"renan": [_item("a")]}
    rodada["avaliacoes"] = {"a": _av(True, 8)}
    monkeypatch.setattr(cu, "processar", lambda item: {
        "stem": item["stem"], "titulo": "t", "canal": "c", "ok": False, "aprovados": 0,
        "publicacao": None, "avisos": [], "erro": "01_baixar.py falhou"})
    assert cu.main([]) == 1
    assert "01_baixar.py falhou" in cu.RESUMO.read_text(encoding="utf-8")
    assert not cu.TRAVA.exists()


# --- robustez (rodada 2 do revisor) -------------------------------------------------------

def test_excecao_num_video_nao_derruba_os_outros(raiz, rodada, monkeypatch, banco):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    rodada["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9)}
    feitos = []

    def processar(item):
        feitos.append(item["stem"])
        if item["stem"] == "renan_live_bravo":
            raise SystemExit("[!] mais de uma pasta pro stem")
        return {"stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
                "ok": True, "aprovados": 1, "publicacao": "p.txt", "avisos": []}
    monkeypatch.setattr(cu, "processar", processar)
    assert cu.main(["--max=2"]) == 1
    assert feitos == ["renan_live_bravo", "renan_live_alfa"]       # seguiu depois do erro
    resumo = cu.RESUMO.read_text(encoding="utf-8")
    assert "SystemExit" in resumo and "Live Alfa" in resumo
    assert banco("SELECT 1 FROM eventos WHERE agente='curador' AND status='falha'")
    assert not cu.TRAVA.exists()


def _falha(item):
    return {"stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
            "ok": False, "aprovados": 0, "publicacao": None, "avisos": [], "erro": "01_baixar.py falhou"}


def test_download_falho_volta_pra_fila_e_desiste_na_terceira(raiz, rodada, monkeypatch):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 6)}
    monkeypatch.setattr(cu, "processar", _falha)
    for tentativa in (1, 2):
        cu.main([])
        e = json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]
        assert e["decisao"] == "fila" and e["tentativas"] == tentativa
    assert rodada["llm"] == 1                                       # a fila não chama o LLM de novo
    cu.main([])
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]["decisao"] == "falhou"
    rodada["processados"].clear()
    cu.main([])                                                     # "falhou" não volta mais
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]["decisao"] == "falhou"


def test_falha_depois_do_download_fica_escolhido(raiz, rodada, monkeypatch):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 6)}

    def baixou_e_falhou(item):
        (raiz / "inputs" / f"{item['stem']}.url").write_text(item["url"], encoding="utf-8")
        return _falha(item)
    monkeypatch.setattr(cu, "processar", baixou_e_falhou)
    cu.main([])
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]["decisao"] == "escolhido"


def test_resumo_cita_processado_sem_aprovado(raiz):
    texto = cu.escrever_resumo({"quando": "x", "custo": 0, "escolhidos": [], "fila": [],
                                "recusados": [], "processados": [
                                    {"stem": "s", "titulo": "Live", "canal": "Kim", "ok": True,
                                     "aprovados": 0, "publicacao": None, "avisos": []}]})
    assert "sem corte aprovado" in texto and "revisao.json de s" in texto
