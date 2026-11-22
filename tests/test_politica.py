"""Portão de política (_politica.py) e quem o usa: 03, pipeline, Curador e revisor.
Cliente Anthropic falso: nunca chama API, nunca baixa vídeo."""
import importlib.util
import io
import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _custo
import _politica
from test_curador import _item, cu, raiz  # noqa: F401

RAIZ = Path(__file__).parent.parent
SCRIPTS = RAIZ / "scripts"

_spec = importlib.util.spec_from_file_location("revisor_pol", SCRIPTS / "11_revisor.py")
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


# -- compactar ---------------------------------------------------------------

def test_compactar_agrupa_por_minuto_e_tira_relogio_e_speaker():
    t = ("[00:00:05] Speaker 1: oi gente\n[00:00:40] Speaker 2: bora\n"
         "[00:01:10] sem speaker aqui\n[01:13:00] Arthur: fim\n")
    assert _politica.compactar(t).splitlines() == [
        "[0] oi gente bora", "[1] sem speaker aqui", "[73] fim"]


def test_compactar_respeita_max_chars_e_amostra_comeco_meio_e_fim():
    t = "\n".join(f"[{m // 60:02d}:{m % 60:02d}:00] Speaker 1: " + f"fala{m} " * 5
              for m in range(200))
    saida = _politica.compactar(t, max_chars=1500)
    assert len(saida) <= 1500
    mins = [int(l[1:l.index("]")]) for l in saida.splitlines() if l.startswith("[")]
    assert mins[0] == 0 and mins[-1] >= 150 and any(60 < m < 140 for m in mins)


def test_compactar_vazio():
    assert _politica.compactar("") == ""


# -- checar / ler / marcar ---------------------------------------------------

TRANSCR = "[00:00:01] Speaker 1: o PL racha sobre o Flávio\n"


class _Msgs:
    def __init__(self, texto, stop="end_turn"):
        self.chamadas = 0
        self.texto, self.stop = texto, stop

    def create(self, **kw):
        self.chamadas += 1
        self.kw = kw
        return SimpleNamespace(
            model="claude-haiku-5-5", stop_reason=self.stop,
            content=[SimpleNamespace(type="text", text=self.texto)],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=50,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0))


@pytest.fixture
def live(tmp_path, monkeypatch, banco):
    pasta = tmp_path / "outputs" / "2026-11-22_x"
    pasta.mkdir(parents=True)
    (pasta / "transcricao.txt").write_text(TRANSCR, encoding="utf-8")
    msgs = _Msgs(json.dumps({"passa": True, "temas": ["racha no PL"], "minutos": 30,
                             "motivo": "tem racha"}))
    monkeypatch.setattr(_politica, "_cliente", lambda: SimpleNamespace(messages=msgs))
    return pasta, msgs


def test_checar_grava_json_e_registra_evento_llm(live, banco):
    pasta, msgs = live
    v = _politica.checar("x", pasta)
    assert v["passa"] is True and v["temas"] == ["racha no PL"] and v["minutos"] == 30
    assert json.loads((pasta / "politica.json").read_text(encoding="utf-8"))["passa"] is True
    ev = banco("SELECT * FROM eventos WHERE etapa='03_politica'")
    assert len(ev) == 1 and ev[0]["status"] == "llm" and ev[0]["agente"] == "curador"
    assert msgs.kw["model"] == "claude-haiku-5-5"


def test_checar_mesma_transcricao_nao_chama_de_novo(live):
    pasta, msgs = live
    _politica.checar("x", pasta)
    _politica.checar("x", pasta)
    assert msgs.chamadas == 1


def test_checar_transcricao_diferente_chama_de_novo(live):
    pasta, msgs = live
    _politica.checar("x", pasta)
    (pasta / "transcricao.txt").write_text(TRANSCR + "[00:02:00] mais uma fala\n", encoding="utf-8")
    _politica.checar("x", pasta)
    assert msgs.chamadas == 2


def test_checar_chama_orcamento_e_estouro_nao_chama_api(live, monkeypatch):
    pasta, msgs = live
    visto = []

    def boom(stem, etapa):
        visto.append((stem, etapa))
        raise _custo.OrcamentoEstourado("estourou")
    monkeypatch.setattr(_custo, "checar_orcamento", boom)
    with pytest.raises(_custo.OrcamentoEstourado):
        _politica.checar("x", pasta)
    assert visto == [("x", "03_politica")] and msgs.chamadas == 0


def test_checar_recusa_levanta(live):
    pasta, msgs = live
    msgs.stop = "refusal"
    with pytest.raises(RuntimeError, match="recusou"):
        _politica.checar("x", pasta)
    assert not (pasta / "politica.json").exists()


def test_duracao_min_e_o_ultimo_minuto_com_fala():
    assert _politica.duracao_min("") == 0
    assert _politica.duracao_min("[00:00:05] a\n[02:41:10] Speaker 1: b\n[01:00:00] c\n") == 161


def test_decidir_modelo_passa_com_poucos_minutos_reprova():
    v = _politica.decidir({"passa": True, "temas": ["x"], "minutos": 25, "motivo": "tem"}, 162)
    assert v["passa"] is False and v["duracao_min"] == 162 and v["minutos"] == 25
    assert "só ~25 de 162 min" in v["motivo"] and "mínimo 65" in v["motivo"]
    assert v["motivo"].endswith(": tem")


def test_decidir_modelo_passa_com_minutos_suficientes_passa():
    v = _politica.decidir({"passa": True, "temas": ["x"], "minutos": 70, "motivo": "tem"}, 162)
    assert v["passa"] is True and v["motivo"] == "tem"


def test_decidir_live_curta_usa_piso_de_15_minutos():
    assert _politica.decidir({"passa": True, "minutos": 14}, 20)["passa"] is False
    assert _politica.decidir({"passa": True, "minutos": 15}, 20)["passa"] is True


def test_decidir_modelo_nao_passa_reprova_e_mantem_motivo():
    v = _politica.decidir({"passa": False, "temas": [], "minutos": 100, "motivo": "variedades"}, 120)
    assert v["passa"] is False and v["motivo"] == "variedades"


def test_checar_reprova_pelo_codigo_com_minutos_incoerentes_com_a_duracao(live):
    pasta, msgs = live
    (pasta / "transcricao.txt").write_text(
        "[00:00:01] Speaker 1: oi\n[02:00:00] Speaker 1: tchau\n", encoding="utf-8")
    v = _politica.checar("x", pasta)       # modelo diz passa com 30 min de 120
    assert v["passa"] is False and v["duracao_min"] == 120
    assert _politica.ler(pasta)["passa"] is False


def test_ler_sem_arquivo_ou_invalido(tmp_path):
    assert _politica.ler(tmp_path) is None
    (tmp_path / "politica.json").write_text("{lixo", encoding="utf-8")
    assert _politica.ler(tmp_path) is None
    (tmp_path / "politica.json").write_text('{"x": 1}', encoding="utf-8")
    assert _politica.ler(tmp_path) is None


def test_marcar_sem_politica_e_ler(tmp_path):
    _politica.marcar_sem_politica(tmp_path, "zero blocos")
    v = _politica.ler(tmp_path)
    assert v["passa"] is False and v["motivo"] == "zero blocos"


def test_marcar_sem_politica_preserva_temas_do_veredito(tmp_path):
    (tmp_path / "politica.json").write_text(
        json.dumps({"passa": True, "temas": ["a"], "minutos": 5, "motivo": "ok"}), encoding="utf-8")
    _politica.marcar_sem_politica(tmp_path, "nenhum bloco")
    v = _politica.ler(tmp_path)
    assert v["passa"] is False and v["temas"] == ["a"] and v["motivo"] == "nenhum bloco"


# -- Curador -----------------------------------------------------------------

@pytest.fixture
def pasta_curador(raiz, monkeypatch):
    import _paths
    pasta = raiz / "outputs" / "2026-11-22_renan_x"
    pasta.mkdir(parents=True)
    monkeypatch.setattr(_paths, "achar_pasta", lambda stem: pasta)
    return pasta


def test_curador_portao_reprovou_nao_e_falha(pasta_curador, monkeypatch, banco):
    _politica.marcar_sem_politica(pasta_curador, "papo de futebol")
    chamadas = []
    monkeypatch.setattr(cu, "rodar", lambda s, *a: chamadas.append(s) or s != "pipeline.py")
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert chamadas == ["01_baixar.py", "pipeline.py"]     # revisor nao roda
    assert "erro" not in res and res["sem_politica"] == "papo de futebol" and not res["ok"]
    assert not banco("SELECT 1 FROM eventos WHERE agente='curador' AND status='falha'")
    assert banco("SELECT 1 FROM eventos WHERE etapa='curador_pipeline' AND status='ok'")


def test_curador_pipeline_falhou_sem_politica_json_continua_falha(pasta_curador, monkeypatch, banco):
    monkeypatch.setattr(cu, "rodar", lambda s, *a: s != "pipeline.py")
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert "sem_politica" not in res and "pipeline.py falhou" in res["erro"]
    assert banco("SELECT 1 FROM eventos WHERE agente='curador' AND status='falha'")


def test_curador_pipeline_falhou_com_portao_aprovado_continua_falha(pasta_curador, monkeypatch, banco):
    (pasta_curador / "politica.json").write_text(
        json.dumps({"passa": True, "temas": [], "minutos": 9, "motivo": "ok"}), encoding="utf-8")
    monkeypatch.setattr(cu, "rodar", lambda s, *a: s != "pipeline.py")
    res = cu.processar({**_item("a"), "stem": "renan_x"})
    assert "sem_politica" not in res and "erro" in res


def test_curador_processar_escolhido_expira_a_sugestao(pasta_curador, monkeypatch, banco):
    _politica.marcar_sem_politica(pasta_curador, "papo de futebol")
    monkeypatch.setattr(cu, "rodar", lambda s, *a: s != "pipeline.py")
    cu.gravar_sugestao("a", titulo="Live Alfa", canal="Renan Santos", url="https://x/a",
                       data="2026-11-21", prioridade=5, motivo="m")
    e = {"titulo": "Live Alfa", "canal": "Renan Santos", "url": "https://x/a", "prefixo": "renan",
         "zoom": None, "decisao": "fila", "motivo": "m", "stem": "renan_x"}
    estado = {"a": e}
    rodada = {"escolhidos": [], "fila": [e], "processados": []}
    res = cu.processar_escolhido({"canais": []}, estado, "a", rodada, "teste")
    assert "sem_politica" in res and e["decisao"] == "sem_politica"
    s, = cu.listar_sugestoes()
    assert s["status"] == "expirada" and "descartada no portão: papo de futebol" in s["mensagem"]


# -- Revisor -----------------------------------------------------------------

OK = {"titulo_fiel": True, "titulo_problema": "", "thumb_ok": True, "thumb_problema": "",
      "tela_compartilhada": False, "tela_problema": "", "corte_sem_sentido": False,
      "sentido_problema": ""}


def test_revisor_fora_de_pauta_descarta():
    est, motivo = rv.decidir({**OK, "fora_de_pauta": True, "pauta_problema": "futebol"})
    assert est == "descartado" and "fora de pauta: futebol" in motivo


def test_revisor_sem_o_campo_fora_de_pauta_aprova_como_antes():
    assert rv.decidir(OK) == ("aprovado", None)
    assert rv.decidir({**OK, "fora_de_pauta": False, "pauta_problema": ""}) == ("aprovado", None)


def test_revisor_schema_exige_os_campos_novos():
    assert {"fora_de_pauta", "pauta_problema"} <= set(rv.SCHEMA["required"])


# -- pipeline.py -------------------------------------------------------------

def _rodar_pipeline(monkeypatch, argv, codigo_03):
    cmds = []

    class FakePopen:
        def __init__(self, cmd, *a, **k):
            self.script = Path(cmd[1]).name
            cmds.append((self.script, list(cmd[2:])))
            self.stderr = io.BufferedReader(io.BytesIO(b""))

        def wait(self):
            return codigo_03 if self.script == "03_segmentar.py" else 0

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "stem_x", "--desde=3", *argv])
    saida = None
    try:
        runpy.run_path(str(SCRIPTS / "pipeline.py"), run_name="__main__")
    except SystemExit as e:
        saida = e
    return cmds, saida


def test_pipeline_03_exit_4_sai_4_com_evento_ok(monkeypatch, banco):
    cmds, saida = _rodar_pipeline(monkeypatch, [], 4)
    assert saida is not None and saida.code == _politica.EXIT_SEM_POLITICA == 4
    assert [s for s, _ in cmds] == ["03_segmentar.py"]
    ev = banco("SELECT status FROM eventos WHERE etapa='03_segmentar' AND agente='pipeline'")
    assert "ok" in [e["status"] for e in ev] and "falha" not in [e["status"] for e in ev]


def test_pipeline_03_outro_exit_continua_falha(monkeypatch, banco):
    _, saida = _rodar_pipeline(monkeypatch, [], 1)
    assert saida is not None and saida.code != 4
    assert banco("SELECT 1 FROM eventos WHERE etapa='03_segmentar' AND status='falha'")


def test_pipeline_repassa_sem_portao_ao_03(monkeypatch, banco):
    cmds, _ = _rodar_pipeline(monkeypatch, ["--sem-portao"], 0)
    assert "--sem-portao" in dict(cmds)["03_segmentar.py"]
    cmds, _ = _rodar_pipeline(monkeypatch, [], 0)
    assert "--sem-portao" not in dict(cmds)["03_segmentar.py"]


# -- guarda editorial: a regua nos 3 prompts ---------------------------------

def test_regua_de_politica_esta_no_03_no_curador_e_no_revisor():
    seg = (RAIZ / "prompts" / "segmentacao.md").read_text(encoding="utf-8")
    assert "Só política" in seg and '"blocos": []' in seg
    for nome, texto in (("03", seg), ("curador", cu.SISTEMA), ("revisor", rv.SISTEMA)):
        for termo in ("futebol", "teoria", "relacionamento"):
            assert termo in texto, (nome, termo)
    assert _politica.CRITERIO in cu.SISTEMA and _politica.CRITERIO in rv.SISTEMA
    assert "Vorcaro" in _politica.CRITERIO


def test_03_so_roda_o_portao_no_caminho_pago_e_respeita_sem_portao():
    fonte = (SCRIPTS / "03_segmentar.py").read_text(encoding="utf-8")
    assert '"--sem-portao" in sys.argv' in fonte
    assert fonte.index("_politica.checar") > fonte.index('if acao == "reaproveitar"')
    assert "sys.exit(_politica.EXIT_SEM_POLITICA)" in fonte
