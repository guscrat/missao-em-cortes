"""Modo evento (config/canais.json): _paths.modo_evento, Curador (13) e publicacao.txt."""
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import _cobertura
import _paths
import _publicacao as pub

_spec = importlib.util.spec_from_file_location(
    "curador_ev", Path(__file__).parent.parent / "scripts" / "13_curador.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)

CFG_EV = {"modo_evento": True, "modo_evento_desde": "2026-10-25",
          "modo_evento_ate": "2026-10-27", "modo_evento_tema": "reação ao 2º turno"}


# --- _paths.modo_evento -------------------------------------------------------------------

def test_modo_evento_ligado_no_intervalo_inclusive():
    for dia in (date(2026, 10, 25), date(2026, 10, 26), date(2026, 10, 27)):
        assert _paths.modo_evento(dia, CFG_EV) == {
            "desde": date(2026, 10, 25), "ate": date(2026, 10, 27), "tema": "reação ao 2º turno"}


def test_modo_evento_antes_do_desde_e_depois_do_ate():
    assert _paths.modo_evento(date(2026, 10, 24), CFG_EV) is None
    assert _paths.modo_evento(date(2026, 10, 28), CFG_EV) is None   # flag true, mas expirou


@pytest.mark.parametrize("cfg", [
    {**CFG_EV, "modo_evento": False},
    {k: v for k, v in CFG_EV.items() if k != "modo_evento"},
    {**CFG_EV, "modo_evento": "true"},                    # só o booleano true liga
    {**CFG_EV, "modo_evento_ate": "27/10/2026"},          # data ruim
    {k: v for k, v in CFG_EV.items() if k != "modo_evento_ate"},
    {},
])
def test_modo_evento_desligado(cfg):
    assert _paths.modo_evento(date(2026, 10, 26), cfg) is None


def test_modo_evento_tema_padrao():
    cfg = {k: v for k, v in CFG_EV.items() if k != "modo_evento_tema"}
    assert _paths.modo_evento(date(2026, 10, 26), cfg)["tema"] == "evento"


def test_modo_evento_le_canais_json_quando_sem_cfg(tmp_path, monkeypatch):
    arq = tmp_path / "canais.json"
    monkeypatch.setattr(_paths, "CANAIS_JSON", arq)
    assert _paths.modo_evento(date(2026, 10, 26)) is None            # arquivo ausente
    arq.write_text(json.dumps(CFG_EV), encoding="utf-8")
    assert _paths.modo_evento(date(2026, 10, 26))["ate"] == date(2026, 10, 27)
    arq.write_text("lixo", encoding="utf-8")
    assert _paths.modo_evento(date(2026, 10, 26)) is None


# --- Curador ------------------------------------------------------------------------------

HOJE = date.today()
CFG = {"dias": 3, "duracao_min": 20, "duracao_max": 240, "max_por_dia": 1, "por_canal": 8,
       "canais": [{"nome": "Renan Santos", "url": "https://www.youtube.com/@renan",
                   "prefixo": "renan", "zoom": "1696:954:16:0"}]}


def _item(vid, titulo, dias_atras=0):
    return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "titulo": titulo,
            "duracao_s": 90 * 60, "data": (HOJE - timedelta(days=dias_atras)).isoformat(),
            "live_status": "was_live", "canal": "Renan Santos", "prefixo": "renan",
            "zoom": "1696:954:16:0"}


def _fila(titulo, dias_atras, prioridade):
    return {"decisao": "fila", "prioridade": prioridade, "motivo": "m", "titulo": titulo,
            "canal": "Renan Santos", "url": "https://www.youtube.com/watch?v=x",
            "data": (HOJE - timedelta(days=dias_atras)).isoformat()}


@pytest.fixture
def rodada(tmp_path, monkeypatch, banco):
    for d in ("config", "inputs", "outputs"):
        (tmp_path / d).mkdir()
    cfg = {**CFG, "modo_evento": True,
           "modo_evento_desde": (HOJE - timedelta(days=1)).isoformat(),
           "modo_evento_ate": (HOJE + timedelta(days=1)).isoformat(),
           "modo_evento_tema": "reação ao 2º turno"}
    (tmp_path / "config" / "canais.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "config" / "zoom.json").write_text("{}", encoding="utf-8")
    for nome, valor in (("ROOT", tmp_path), ("CONFIG", tmp_path / "config" / "canais.json"),
                        ("ZOOM_JSON", tmp_path / "config" / "zoom.json"),
                        ("INPUTS", tmp_path / "inputs"), ("OUTPUTS", tmp_path / "outputs"),
                        ("ESTADO", tmp_path / "state" / "curadoria.json"),
                        ("RESUMO", tmp_path / "state" / "curador_resumo.md"),
                        ("TRAVA", tmp_path / "state" / "curador.lock"),
                        ("PROGRESSO", tmp_path / "state" / "curador_progresso.json")):
        monkeypatch.setattr(cu, nome, valor)
    reg = {"listar": [], "avaliacoes": {}, "processados": [], "evento": "nunca",
           "estoque": {"longos": 9, "shorts": 9, "dias": 9.0}}
    monkeypatch.setattr(cu, "calcular_estoque", lambda cfg, hoje=None: dict(reg["estoque"]))
    monkeypatch.setattr(cu, "sincronizar_canal", lambda dry=False: None)
    monkeypatch.setattr(cu, "atualizar_placar", lambda: None)
    monkeypatch.setattr(cu, "listar_canal", lambda canal, n: reg["listar"])
    monkeypatch.setattr(cu, "detalhar", lambda item: item)

    def avaliar(client, itens, evento=None):
        reg["evento"] = evento
        return {i["id"]: reg["avaliacoes"][i["id"]] for i in itens
                if i["id"] in reg["avaliacoes"]}, (1000, 100, 0.006)
    monkeypatch.setattr(cu, "avaliar", avaliar)

    def processar(item):
        reg["processados"].append(item["stem"])
        return {"stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
                "ok": True, "aprovados": 1, "publicacao": "pub.txt", "avisos": []}
    monkeypatch.setattr(cu, "processar", processar)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: object())
    return reg


def _av(prioridade):
    return {"vale": True, "prioridade": prioridade, "motivo": "m"}


def test_evento_estoque_cheio_processa_so_item_do_evento_e_ignora_fila_antiga(rodada):
    cu.gravar_estado({"velho": _fila("Live Velha", 5, 10)})          # prioridade maior, mas antiga
    rodada["listar"] = [_item("novo", "Live Resultado", dias_atras=0)]
    rodada["avaliacoes"] = {"novo": _av(7)}
    assert cu.main([]) == 0
    assert rodada["processados"] == ["renan_live_resultado"]
    assert rodada["evento"]["tema"] == "reação ao 2º turno"          # evento chega no avaliar
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["velho"]["decisao"] == "fila"


def test_evento_item_novo_de_prioridade_baixa_nao_fura_o_estoque(rodada):
    rodada["listar"] = [_item("novo", "Previsao Velha", dias_atras=0)]
    rodada["avaliacoes"] = {"novo": _av(cu.PRIORIDADE_EVENTO - 1)}
    assert cu.main([]) == 0
    assert rodada["processados"] == []
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["novo"]["decisao"] == "fila"


def test_evento_sem_item_novo_e_estoque_cheio_nao_processa(rodada):
    cu.gravar_estado({"velho": _fila("Live Velha", 5, 10)})
    assert cu.main([]) == 0
    assert rodada["processados"] == []


def test_evento_sem_item_novo_e_estoque_baixo_usa_regra_normal(rodada):
    rodada["estoque"] = {"longos": 0, "shorts": 0, "dias": 0.0}
    cu.gravar_estado({"velho": _fila("Live Velha", 5, 10)})
    assert cu.main([]) == 0
    assert rodada["processados"] == ["renan_live_velha"]


def test_sem_evento_estoque_cheio_nao_processa_nem_o_novo(rodada):
    cu.CONFIG.write_text(json.dumps({**CFG, "modo_evento": False}), encoding="utf-8")
    rodada["listar"] = [_item("novo", "Live Resultado")]
    rodada["avaliacoes"] = {"novo": _av(9)}
    assert cu.main([]) == 0
    assert rodada["processados"] == [] and rodada["evento"] is None


def test_proximo_da_fila_com_desde():
    estado = {"a": _fila("A", 5, 10), "b": _fila("B", 0, 3), "c": _fila("C", 0, 6),
              "d": {"decisao": "recusado", "data": HOJE.isoformat(), "prioridade": 10}}
    assert cu.proximo_da_fila(estado) == "a"
    assert cu.proximo_da_fila(estado, HOJE - timedelta(days=1)) == "c"
    assert cu.proximo_da_fila(estado, HOJE + timedelta(days=1)) is None


def test_montar_pedido_com_e_sem_evento():
    ev = {"desde": date(2026, 10, 25), "ate": date(2026, 10, 27), "tema": "reação ao 2º turno"}
    com = cu.montar_pedido([_item("a", "Live")], ev)
    assert "MODO EVENTO até 27/10" in com and "reação ao 2º turno" in com
    assert "id=a" in com
    sem = cu.montar_pedido([_item("a", "Live")])
    assert "MODO EVENTO" not in sem and "id=a" in sem


def test_resumo_mostra_linha_do_modo_evento(rodada):
    base = {"quando": "2026-10-25T09:00:00", "custo": 0.0, "escolhidos": [], "fila": [],
            "recusados": [], "processados": []}
    ev = {"desde": date(2026, 10, 25), "ate": date(2026, 10, 27), "tema": "reação ao 2º turno"}
    assert "**Modo evento** até 27/10 (reação ao 2º turno)" in cu.escrever_resumo(
        {**base, "modo_evento": ev})
    assert "Modo evento" not in cu.escrever_resumo({**base, "modo_evento": None})
    assert "Modo evento" not in cu.escrever_resumo(base)


# --- publicacao.txt -----------------------------------------------------------------------

@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(_cobertura, "CANAL_JSON", tmp_path / "canal.json")
    monkeypatch.setattr(pub, "auditoria_aprovada", lambda: False)
    p = tmp_path / "2026-10-26_renan_x"
    (p / "finalizados").mkdir(parents=True)
    (p / "revisao.json").write_text(json.dumps({"01": {"status": "aprovado"}}), encoding="utf-8")
    (p / "blocos.json").write_text(json.dumps({"blocos": [
        {"id": 1, "score_potencial": 8, "duracao_minutos": 7.0, "titulo_sugerido": "sug"}]}),
        encoding="utf-8")
    (p / "finalizados" / "video_01_a.mp4").touch()
    return p


def test_publicacao_modo_evento_ignora_ultimo_agendado_e_avisa(pasta, monkeypatch):
    monkeypatch.setattr(pub, "ultimo_agendado", lambda: date(2026, 10, 30))
    monkeypatch.setattr(pub, "modo_evento", lambda hoje=None, cfg=None: {
        "desde": date(2026, 10, 25), "ate": date(2026, 10, 27), "tema": "t"})
    texto = pub.gerar(pasta, datetime(2026, 10, 26, 9))[0].read_text(encoding="utf-8")
    assert "26/10 18h" in texto
    assert "31/10" not in texto
    assert "MODO EVENTO (até 27/10)" in texto and "empurre o agendado no Studio" in texto


def test_publicacao_sem_evento_continua_depois_do_agendado(pasta, monkeypatch):
    monkeypatch.setattr(pub, "ultimo_agendado", lambda: date(2026, 10, 30))
    monkeypatch.setattr(pub, "modo_evento", lambda hoje=None, cfg=None: None)
    texto = pub.gerar(pasta, datetime(2026, 10, 26, 9))[0].read_text(encoding="utf-8")
    assert "31/10 18h" in texto and "MODO EVENTO" not in texto


def test_publicacao_modo_evento_pelo_canais_json(pasta, tmp_path, monkeypatch):
    arq = tmp_path / "config" / "canais.json"
    arq.parent.mkdir()
    arq.write_text(json.dumps(CFG_EV), encoding="utf-8")
    monkeypatch.setattr(_paths, "CANAIS_JSON", arq)
    monkeypatch.setattr(pub, "ultimo_agendado", lambda: date(2026, 10, 30))
    texto = pub.gerar(pasta, datetime(2026, 10, 26, 9))[0].read_text(encoding="utf-8")
    assert "26/10 18h" in texto and "MODO EVENTO" in texto
