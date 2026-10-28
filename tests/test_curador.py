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
                        ("TRAVA", tmp_path / "state" / "curador.lock"),
                        ("PROGRESSO", tmp_path / "state" / "curador_progresso.json")):
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
    reg = {"listar": {}, "avaliacoes": {}, "processados": [], "llm": 0,
           "estoque": {"longos": 0, "shorts": 0, "dias": 0.0}, "canal": [], "aviso_canal": None}
    monkeypatch.setattr(cu, "calcular_estoque",
                        lambda cfg, hoje=None: reg["canal"].append("estoque") or dict(reg["estoque"]))
    monkeypatch.setattr(cu, "sincronizar_canal",
                        lambda dry=False: reg["canal"].append(("sync", dry)) or reg["aviso_canal"])
    reg["placar"] = []
    reg["aviso_placar"] = None
    monkeypatch.setattr(cu, "atualizar_placar",
                        lambda: reg["placar"].append(1) or reg["aviso_placar"])
    monkeypatch.setattr(cu, "listar_canal", lambda canal, n: reg["listar"].get(canal["prefixo"], []))
    monkeypatch.setattr(cu, "detalhar", lambda item: item)

    def avaliar(client, itens, evento=None, em_alta=None):
        reg["evento"] = evento
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
    monkeypatch.setattr(cu, "esperar_livre", lambda: reg.get("ocupado", []))
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
    assert rodada["processados"] == ["renan_live_bravo"]               # 1 por rodada
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
                            "canal": "Renan Santos", "url": "https://www.youtube.com/watch?v=a",
                            "data": HOJE.isoformat()},
                      "c": {"decisao": "recusado", "motivo": "jingle"},
                      "b": {"decisao": "escolhido", "stem": "renan_live_bravo"}})
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")],
                        "kim": [_item("c", "Jingle", canal=1)]}
    assert cu.main([]) == 0
    assert rodada["llm"] == 0                                       # nada novo: sem custo
    assert rodada["processados"] == ["renan_live_alfa"]


def test_rodada_passa_em_alta_pro_avaliar_e_pro_resumo(raiz, rodada, monkeypatch):
    altas = [{"youtube_id": "o", "tema": "Tema X", "titulo": "T", "views_semana": 100, "fator": 4.0}]
    monkeypatch.setattr(cu, "em_alta_atual", lambda: altas)
    visto = {}
    original = cu.avaliar

    def espia(client, itens, evento=None, em_alta=None):
        visto["em_alta"] = em_alta
        return original(client, itens, evento, em_alta)
    monkeypatch.setattr(cu, "avaliar", espia)
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 6)}
    assert cu.main([]) == 0
    assert visto["em_alta"] == altas
    assert "Tema X" in cu.RESUMO.read_text(encoding="utf-8")


def test_rodada_normal_atualiza_placar(raiz, rodada):
    assert cu.main([]) == 0
    assert rodada["placar"] == [1]


def test_falha_do_placar_vira_aviso_e_nao_derruba_a_rodada(raiz, rodada):
    rodada["aviso_placar"] = "placar do canal não atualizado (boom)"
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 6)}
    assert cu.main([]) == 0
    assert rodada["processados"] == ["renan_live_alfa"]
    assert "placar do canal não atualizado (boom)" in cu.RESUMO.read_text(encoding="utf-8")


def test_atualizar_placar_real_captura_excecao(monkeypatch, banco):
    import importlib
    import types
    falso = types.ModuleType("15_placar")

    def quebra(interativo=True):
        assert interativo is False
        raise RuntimeError("sem token")
    falso.atualizar = quebra
    monkeypatch.setitem(importlib.sys.modules, "15_placar", falso)
    aviso = cu.atualizar_placar()
    assert "sem token" in aviso
    ev = banco("SELECT status, agente FROM eventos WHERE etapa='15_placar'")
    assert ev == [{"status": "falha", "agente": "analista"}]


def test_atualizar_placar_real_ok_devolve_none(monkeypatch):
    import importlib
    import types
    chamadas = []
    falso = types.ModuleType("15_placar")
    falso.atualizar = lambda interativo=True: chamadas.append(interativo)
    monkeypatch.setitem(importlib.sys.modules, "15_placar", falso)
    assert cu.atualizar_placar() is None and chamadas == [False]


def test_dry_run_nao_chama_llm_nem_processa(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a")]}
    assert cu.main(["--dry-run"]) == 0
    assert rodada["placar"] == []
    assert rodada["llm"] == 0 and rodada["processados"] == []
    assert not cu.ESTADO.exists()


def test_sem_pipeline_registra_mas_nao_processa(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a")]}
    rodada["avaliacoes"] = {"a": _av(True, 7)}
    assert cu.main(["--sem-pipeline"]) == 0
    assert rodada["processados"] == []
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]["decisao"] == "fila"


def test_estoque_cheio_avalia_mas_nao_processa(raiz, rodada):
    rodada["estoque"] = {"longos": 4, "shorts": 4, "dias": 2.0, "dias_agendados": 0,
                         "coberto_ate": date(2026, 10, 24)}
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 9)}
    assert cu.main([]) == 0
    assert rodada["llm"] == 1 and rodada["processados"] == []
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["a"]["decisao"] == "fila"
    assert "Estoque no início: canal coberto até" in cu.RESUMO.read_text(encoding="utf-8")


def test_estoque_baixo_processa_so_um(raiz, rodada):
    rodada["estoque"] = {"longos": 1, "shorts": 2, "dias": 1.0}
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    rodada["avaliacoes"] = {"a": _av(True, 9), "b": _av(True, 9)}
    cu.main([])
    assert len(rodada["processados"]) == 1


def test_forcar_processa_com_estoque_cheio(raiz, rodada):
    rodada["estoque"] = {"longos": 9, "shorts": 9, "dias": 4.5}
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 5)}
    cu.main(["--forcar"])
    assert rodada["processados"] == ["renan_live_alfa"]


def test_minimo_vem_do_config(raiz, rodada):
    cfg = {**CFG, "estoque": {"dias_minimos": 5, "longos_por_dia": 1, "shorts_por_dia": 2}}
    cu.CONFIG.write_text(json.dumps(cfg), encoding="utf-8")
    rodada["estoque"] = {"longos": 8, "shorts": 8, "dias": 4.0}
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 5)}
    cu.main([])
    assert rodada["processados"] == ["renan_live_alfa"]          # 4 dias < mínimo 5


def test_trava_impede_rodada_dupla(raiz, rodada):
    cu.TRAVA.parent.mkdir(parents=True, exist_ok=True)
    cu.TRAVA.write_text("123", encoding="utf-8")
    assert cu.main([]) == cu.SAIDA_TRAVADO
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
    def quebra(client, itens, evento=None, em_alta=None):
        raise RuntimeError("API fora")
    monkeypatch.setattr(cu, "avaliar", quebra)
    assert cu.main([]) == 1
    assert banco("SELECT status FROM eventos WHERE agente='curador' AND status='falha'")
    assert not banco("SELECT status FROM eventos WHERE agente='curador' AND status='llm'")
    assert "a" not in json.loads(cu.ESTADO.read_text(encoding="utf-8"))   # reavalia amanhã
    assert "API fora" in cu.RESUMO.read_text(encoding="utf-8")


def test_falha_no_llm_ainda_processa_a_fila(raiz, rodada, monkeypatch):
    cu.gravar_estado({"a": {"decisao": "fila", "prioridade": 6, "motivo": "m", "titulo": "Live Alfa",
                            "canal": "Renan Santos", "url": "https://www.youtube.com/watch?v=a",
                            "data": HOJE.isoformat()}})
    rodada["listar"] = {"renan": [_item("b", "Live Bravo")]}
    monkeypatch.setattr(cu, "avaliar", lambda client, itens: (_ for _ in ()).throw(RuntimeError("x")))
    assert cu.main([]) == 1                                         # avisa a falha...
    assert rodada["processados"] == ["renan_live_alfa"]             # ...mas a fila andou


def test_expirar_fila_ignora_data_malformada():
    estado = {"a": {"decisao": "fila", "data": "ontem"}, "b": {"decisao": "fila", "data": None},
              "c": {"decisao": "fila", "data": (HOJE - timedelta(days=99)).isoformat()}}
    assert cu.expirar_fila(estado, HOJE) == ["c"]
    assert estado["a"]["decisao"] == estado["b"]["decisao"] == "fila"


@pytest.mark.parametrize("conteudo", ['[1, 2]', '{"01": "short_01.mp4"}', '{"01": {"postado": null}}'])
def test_shorts_json_com_formato_estranho_nao_quebra(raiz, conteudo):
    pasta = raiz / "outputs" / "x"
    (pasta / "shorts").mkdir(parents=True)
    (pasta / "shorts" / "shorts.json").write_text(conteudo, encoding="utf-8")
    sh = cu.ler_shorts(pasta)
    assert isinstance(sh, dict) and all(isinstance(v, dict) for v in sh.values())


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
    assert "Entraram na fila" in texto and "Recusados" in texto and "tema fraco" in texto
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

def test_excecao_no_video_vira_falha_e_resumo_sai(raiz, rodada, monkeypatch, banco):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    rodada["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9)}

    def processar(item):
        raise SystemExit("[!] mais de uma pasta pro stem")
    monkeypatch.setattr(cu, "processar", processar)
    assert cu.main([]) == 1
    resumo = cu.RESUMO.read_text(encoding="utf-8")
    assert "SystemExit" in resumo and "Live Alfa" in resumo          # a outra ficou na fila
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


# --- estoque e fila -----------------------------------------------------------------------

def _pasta_com_blocos(raiz, nome, stem, status_por_bloco, shorts=None):
    import _eventos
    pasta = raiz / "outputs" / nome
    (pasta / "shorts").mkdir(parents=True)
    _eventos.upsert_video(stem, pasta=nome)
    for bid, status in status_por_bloco.items():
        _eventos.upsert_bloco(stem, bid, status=status, forcar_status=True)
    registro = {}
    for bid, postado in (shorts or {}).items():
        arq = f"short_{bid:02d}_x.mp4"
        (pasta / "shorts" / arq).touch()
        registro[f"{bid:02d}"] = {"arquivo": arq, **({"postado": "2026-10-22"} if postado else {})}
    (pasta / "shorts" / "shorts.json").write_text(json.dumps(registro), encoding="utf-8")
    return pasta


def _sem_agendado(monkeypatch, ultimo=None):
    import _cobertura
    monkeypatch.setattr(_cobertura, "agenda_canal",
                        lambda agora=None: {"ultimo": ultimo, "futuros": 0})


def test_calcular_estoque_conta_longos_aprovados_e_shorts_nao_postados(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    hoje = date(2026, 10, 22)
    _pasta_com_blocos(raiz, "2026-10-21_renan_a", "renan_a",
                      {1: "aprovado", 2: "agendado", 3: "descartado", 4: "aprovado"},
                      shorts={1: False, 2: False, 3: False, 4: True})
    _pasta_com_blocos(raiz, "2026-09-01_renan_velho", "renan_velho",       # > 15 dias: fora
                      {1: "aprovado"}, shorts={1: False})
    est = cu.calcular_estoque({"estoque": {"longos_por_dia": 1, "shorts_por_dia": 2}}, hoje)
    # longos: blocos 1 e 4; shorts: 1 e 2 (3 descartado, 4 já postado)
    assert est == {"longos": 2, "shorts": 2, "dias_agendados": 0, "dias": 2.0,
                   "coberto_ate": date(2026, 10, 24), "ultimo_agendado": None,
                   "agendados_futuros": 0}


def test_estoque_so_agendados(raiz, monkeypatch):
    _sem_agendado(monkeypatch, date(2026, 10, 27))
    est = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    assert est["dias_agendados"] == 5 and est["dias"] == 5.0 and est["longos"] == 0
    assert est["coberto_ate"] == date(2026, 10, 27)


def test_estoque_agendado_no_passado_conta_zero(raiz, monkeypatch):
    _sem_agendado(monkeypatch, date(2026, 10, 10))
    est = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    assert est["dias_agendados"] == 0 and est["dias"] == 0 and est["coberto_ate"] is None


def test_estoque_ultimo_agendado_hoje_cobre_hoje(raiz, monkeypatch):
    _sem_agendado(monkeypatch, date(2026, 10, 22))
    est = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    assert est["dias"] == 0 and est["coberto_ate"] == date(2026, 10, 22)


def test_estoque_agendados_mais_prontos_somam(raiz, monkeypatch):
    _sem_agendado(monkeypatch, date(2026, 10, 25))
    _pasta_com_blocos(raiz, "2026-10-22_kim_g", "kim_g", {1: "aprovado", 2: "aprovado"})
    est = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    assert est["dias"] == 5.0 and est["coberto_ate"] == date(2026, 10, 27)


def test_estoque_longos_por_dia_divide_prontos(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    _pasta_com_blocos(raiz, "2026-10-22_kim_h", "kim_h", {1: "aprovado", 2: "aprovado", 3: "aprovado"})
    cfg = {"estoque": {"longos_por_dia": 2, "shorts_por_dia": 2}}
    est = cu.calcular_estoque(cfg, date(2026, 10, 22))
    assert est["dias"] == 1.5 and est["coberto_ate"] == date(2026, 10, 24)   # ceil(1.5)


def test_estoque_sem_nada_coberto_ate_none(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    est = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    assert est == {"longos": 0, "shorts": 0, "dias_agendados": 0, "dias": 0.0, "coberto_ate": None,
                   "ultimo_agendado": None, "agendados_futuros": 0}


def test_estoque_shorts_nao_afetam_dias(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    _pasta_com_blocos(raiz, "2026-10-22_kim_b", "kim_b", {1: "aprovado", 2: "aprovado"})
    sem = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    _pasta_com_blocos(raiz, "2026-10-22_kim_i", "kim_i", {1: "aprovado", 2: "aprovado"},
                      shorts={1: False, 2: False})
    com = cu.calcular_estoque(CFG_EST, date(2026, 10, 22))
    assert sem["shorts"] == 0 and com["shorts"] == 2
    assert com["dias"] == sem["dias"] + 2


def test_proximo_da_fila_prioridade_depois_mais_recente():
    estado = {"a": {"decisao": "fila", "prioridade": 8, "data": "2026-10-20"},
              "b": {"decisao": "fila", "prioridade": 8, "data": "2026-10-21"},
              "c": {"decisao": "fila", "prioridade": 5, "data": "2026-10-22"},
              "d": {"decisao": "recusado", "prioridade": 10, "data": "2026-10-22"}}
    assert cu.proximo_da_fila(estado) == "b"
    assert cu.proximo_da_fila({}) is None


def test_expirar_fila_depois_de_15_dias():
    estado = {"a": {"decisao": "fila", "data": "2026-10-01"},
              "b": {"decisao": "fila", "data": "2026-10-10"},
              "c": {"decisao": "recusado", "data": "2026-09-01"}}
    assert cu.expirar_fila(estado, date(2026, 10, 22)) == ["a"]
    assert estado["a"]["decisao"] == "expirado" and estado["b"]["decisao"] == "fila"
    assert estado["c"]["decisao"] == "recusado"


def test_reprocessar_da_fila_reusa_stem_anterior(raiz, rodada):
    cu.gravar_estado({"a": {"decisao": "fila", "prioridade": 6, "motivo": "m", "titulo": "Live Alfa",
                            "canal": "Renan Santos", "url": "https://www.youtube.com/watch?v=a",
                            "data": HOJE.isoformat(), "stem": "renan_live_alfa", "tentativas": 1}})
    (raiz / "outputs" / "2026-10-22_renan_live_alfa").mkdir()      # pasta da tentativa anterior
    cu.main([])
    assert rodada["processados"] == ["renan_live_alfa"]           # não vira renan_live_alfa_2


def test_processar_gera_short_dos_aprovados(raiz, monkeypatch):
    monkeypatch.setattr(cu, "auditoria_aprovada", lambda: True)
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append((script, *a)) or True)
    import _paths, _publicacao
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: raiz / "outputs" / stem)
    monkeypatch.setattr(_publicacao, "aprovados", lambda pasta: [{"id": 4}, {"id": 1}])
    monkeypatch.setattr(_publicacao, "gerar", lambda pasta: (pasta / "publicacao.txt", [1, 2]))
    cu.processar({**_item("a"), "stem": "renan_x"})
    assert ("10_shorts.py", "renan_x", "--bloco=4") in chamadas
    assert ("10_shorts.py", "renan_x", "--bloco=1") in chamadas
    assert [c[0] for c in chamadas][:3] == ["01_baixar.py", "pipeline.py", "11_revisor.py"]


def test_sem_auditoria_nao_gera_short_mas_gera_publicacao(raiz, monkeypatch):
    monkeypatch.setattr(cu, "auditoria_aprovada", lambda: False)
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda script, *a: chamadas.append(script) or True)
    import _paths, _publicacao
    gerar_chamado = []
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: raiz / "outputs" / stem)
    monkeypatch.setattr(_publicacao, "aprovados", lambda pasta: [{"id": 4}, {"id": 1}])
    monkeypatch.setattr(_publicacao, "gerar",
                        lambda pasta: gerar_chamado.append(pasta) or (pasta / "publicacao.txt", [1, 2]))
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert "10_shorts.py" not in chamadas
    assert gerar_chamado and res["ok"] and res["aprovados"] == 2


def test_short_que_falha_vira_aviso(raiz, monkeypatch):
    monkeypatch.setattr(cu, "auditoria_aprovada", lambda: True)
    monkeypatch.setattr(cu, "rodar", lambda script, *a: script != "10_shorts.py")
    import _paths, _publicacao
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: raiz / "outputs" / stem)
    monkeypatch.setattr(_publicacao, "aprovados", lambda pasta: [{"id": 2}])
    monkeypatch.setattr(_publicacao, "gerar", lambda pasta: (None, []))
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert res["ok"] and any("Short do bloco 2" in a for a in res["avisos"])


# --- lacunas extras do estoque/fila ---------------------------------------------------------

def test_estoque_pasta_none_no_banco_cai_no_glob(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    import _eventos
    pasta = _pasta_com_blocos(raiz, "2026-10-21_kim_c", "kim_c", {1: "aprovado"}, shorts={1: False})
    _eventos.upsert_video("kim_c", pasta=None)
    est = cu.calcular_estoque({"estoque": {"longos_por_dia": 1, "shorts_por_dia": 1}}, date(2026, 10, 22))
    assert pasta.exists() and est["longos"] == 1 and est["shorts"] == 1 and est["dias"] == 1.0


def test_estoque_sem_pasta_nenhuma_nao_conta(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    import _eventos
    _eventos.upsert_bloco("fantasma", 1, status="aprovado", forcar_status=True)
    est = cu.calcular_estoque({"estoque": {"longos_por_dia": 1, "shorts_por_dia": 1}}, date(2026, 10, 22))
    assert est["longos"] == 0 and est["shorts"] == 0


def test_estoque_short_postado_nao_conta_e_arquivo_sumido_nao_conta(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    pasta = _pasta_com_blocos(raiz, "2026-10-22_kim_d", "kim_d", {1: "aprovado", 2: "aprovado"},
                              shorts={1: True, 2: False})
    (pasta / "shorts" / "short_02_x.mp4").unlink()
    est = cu.calcular_estoque({"estoque": {"longos_por_dia": 1, "shorts_por_dia": 1}}, date(2026, 10, 22))
    assert est["longos"] == 2 and est["shorts"] == 0 and est["dias"] == 2.0


def test_fila_expirada_nao_e_escolhida(raiz, rodada):
    velho = (HOJE - timedelta(days=cu.DIAS_ARQUIVAR + 2)).isoformat()
    cu.gravar_estado({"a": {"decisao": "fila", "prioridade": 10, "motivo": "m", "titulo": "Velha",
                            "canal": "Renan Santos", "url": "u", "data": velho}})
    cu.main([])
    assert rodada["processados"] == []
    assert cu.ler_estado()["a"]["decisao"] == "expirado"


def test_forcar_com_fila_vazia_nao_processa_nada(raiz, rodada):
    rodada["estoque"] = {"longos": 9, "shorts": 9, "dias": 9.0}
    assert cu.main(["--forcar"]) == 0
    assert rodada["processados"] == []


def test_tentativas_preservadas_ao_voltar_pra_fila(raiz, rodada, monkeypatch):
    cu.gravar_estado({"a": {"decisao": "fila", "prioridade": 6, "motivo": "m", "titulo": "Live Alfa",
                            "canal": "Renan Santos", "url": "u", "data": HOJE.isoformat(),
                            "tentativas": 1}})
    monkeypatch.setattr(cu, "processar", lambda item: {
        "stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
        "ok": False, "erro": "download", "aprovados": 0, "publicacao": None, "avisos": []})
    assert cu.main([]) == 1
    e = cu.ler_estado()["a"]
    assert e["tentativas"] == 2 and e["decisao"] == "fila"


# --- leitura do canal (14_canal) no começo da rodada --------------------------------------

def test_rodada_le_o_canal_antes_do_estoque(raiz, rodada):
    cu.main([])
    assert rodada["canal"][:2] == [("sync", False), "estoque"]


def test_dry_run_le_o_canal_sem_gravar(raiz, rodada):
    cu.main(["--dry-run"])
    assert rodada["canal"][0] == ("sync", True)


def test_aviso_do_canal_vai_pro_resumo(raiz, rodada):
    rodada["aviso_canal"] = "não li o canal do YouTube (sem login)"
    cu.main([])
    assert "não li o canal do YouTube" in cu.RESUMO.read_text(encoding="utf-8")


def test_sincronizar_canal_nunca_derruba(monkeypatch):
    import sys
    import types

    def quebra(**kw):
        raise RuntimeError("precisa de login")
    monkeypatch.setitem(sys.modules, "14_canal", types.SimpleNamespace(sincronizar=quebra))
    assert "precisa de login" in cu.sincronizar_canal()


def test_sincronizar_canal_nao_interativo_e_lista_sem_match(monkeypatch):
    import sys
    import types
    pedidos = []

    def sinc(**kw):
        pedidos.append(kw)
        return {"longos": [1], "shorts": [], "sem_match": [{"titulo": "Vídeo editado"}]}
    monkeypatch.setitem(sys.modules, "14_canal", types.SimpleNamespace(sincronizar=sinc))
    aviso = cu.sincronizar_canal(True)
    assert pedidos == [{"interativo": False, "dry": True}]
    assert "1 vídeo(s)" in aviso and "Vídeo editado" in aviso


# --- estoque: Shorts fora dos dias ----------------------------------------------------------

CFG_EST = {"estoque": {"longos_por_dia": 1, "shorts_por_dia": 2}}


def test_estoque_short_arquivado_nao_conta(raiz, monkeypatch):
    _sem_agendado(monkeypatch)
    pasta = _pasta_com_blocos(raiz, "2026-10-22_kim_f", "kim_f", {1: "aprovado", 2: "aprovado"},
                              shorts={1: False, 2: False})
    reg = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    reg["01"]["arquivado"] = "conteúdo antigo"
    (pasta / "shorts" / "shorts.json").write_text(json.dumps(reg), encoding="utf-8")
    assert cu.calcular_estoque(CFG_EST, date(2026, 10, 22))["shorts"] == 1


def test_texto_estoque_com_e_sem_cobertura():
    t = cu._texto_estoque({"longos": 3, "shorts": 2, "dias_agendados": 2, "dias": 5.0,
                           "coberto_ate": date(2026, 10, 27)})
    assert t.startswith("canal coberto até 27/10 = 5.0 dia(s)")
    assert "2 dia(s) já agendado(s) + 3 longo(s) pronto(s); 2 Short(s) à parte" in t
    vazio = cu._texto_estoque({"longos": 0, "shorts": 0, "dias_agendados": 0, "dias": 0.0,
                               "coberto_ate": None})
    assert vazio.startswith("nada agendado nem pronto = 0.0 dia(s)")
