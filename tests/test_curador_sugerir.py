"""Curador (13) em modo sugerir: sugestões no banco, rede de segurança, --processar, painel.
Tudo falso: sem rede, sem API, sem download, sem Popen real."""
import json
import sys
from datetime import timedelta

import pandas as pd
import pytest

from test_curador import CFG, HOJE, _av, _item, cu, raiz, rodada  # noqa: F401

import _cobertura
import _custo
import _eventos as ev
import _paths
import hoje


def _modo(raiz, modo):
    cfg = {**CFG}
    if modo is None:
        cfg.pop("curador_modo", None)
    else:
        cfg["curador_modo"] = modo
    (raiz / "config" / "canais.json").write_text(json.dumps(cfg), encoding="utf-8")


@pytest.fixture
def sugerir(raiz, rodada):
    _modo(raiz, "sugerir")
    return rodada


def _status(vid):
    return next((s["status"] for s in ev.listar_sugestoes() if s["video_id"] == vid), None)


# --- _eventos: sugestões -----------------------------------------------------------------

def test_gravar_sugestao_cria_e_nao_mexe_no_status_sem_status(banco):
    ev.gravar_sugestao("a", titulo="T", prioridade=7)
    ev.gravar_sugestao("a", status="pedida")
    ev.gravar_sugestao("a", motivo="novo")               # sem status: mantém 'pedida'
    s, = ev.listar_sugestoes()
    assert s["status"] == "pedida" and s["motivo"] == "novo" and s["titulo"] == "T"


def test_gravar_sugestao_valida_campos_e_status(banco):
    with pytest.raises(ValueError):
        ev.gravar_sugestao("a", lixo=1)
    with pytest.raises(ValueError):
        ev.gravar_sugestao("a", status="inventado")


def test_pedir_sugestao_so_de_sugerida_ou_falhou(banco):
    ev.gravar_sugestao("a")
    ev.gravar_sugestao("b", status="falhou", mensagem="erro")
    ev.gravar_sugestao("c", status="processando")
    assert ev.pedir_sugestao("a") and ev.pedir_sugestao("b")
    assert not ev.pedir_sugestao("a")                    # clique duplo
    assert not ev.pedir_sugestao("c") and not ev.pedir_sugestao("zzz")
    assert next(s for s in ev.listar_sugestoes() if s["video_id"] == "b")["mensagem"] is None


def test_listar_sugestoes_ordem_e_filtro(banco):
    ev.gravar_sugestao("a", prioridade=3)
    ev.gravar_sugestao("b", prioridade=9)
    ev.gravar_sugestao("c", prioridade=5, status="processada")
    assert [s["video_id"] for s in ev.listar_sugestoes()] == ["b", "c", "a"]
    assert [s["video_id"] for s in ev.listar_sugestoes(["sugerida"])] == ["b", "a"]


# --- curador_modo ------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,esperado", [
    ({"curador_modo": "automatico"}, "automatico"), ({"curador_modo": "sugerir"}, "sugerir"),
    ({}, "sugerir"), ({"curador_modo": "xpto"}, "sugerir"), ({"curador_modo": None}, "sugerir")])
def test_curador_modo_cfg(cfg, esperado):
    assert _paths.curador_modo(cfg) == esperado


def test_curador_modo_le_arquivo_e_falha_pra_sugerir():
    assert _paths.curador_modo() == "sugerir"            # arquivo inexistente
    _paths.CANAIS_JSON.parent.mkdir(parents=True, exist_ok=True)
    _paths.CANAIS_JSON.write_text("{ruim", encoding="utf-8")
    assert _paths.curador_modo() == "sugerir"
    _paths.CANAIS_JSON.write_text('{"curador_modo": "automatico"}', encoding="utf-8")
    assert _paths.curador_modo() == "automatico"


# --- longos_no_dia -----------------------------------------------------------------------

def test_longos_no_dia_conta_agendado_e_publicado_do_dia(banco):
    amanha = HOJE + timedelta(days=1)
    ev.upsert_bloco("v", 1, status="agendado", publish_at=f"{amanha}T12:00:00-03:00",
                    forcar_status=True)
    ev.upsert_bloco("v", 2, status="publicado", publish_at=f"{amanha}T20:00:00-03:00",
                    forcar_status=True)
    ev.upsert_bloco("v", 3, status="aprovado", publish_at=f"{amanha}T20:00:00-03:00",
                    forcar_status=True)                  # aprovado não conta
    ev.upsert_bloco("v", 4, status="agendado", publish_at=f"{HOJE}T12:00:00-03:00",
                    forcar_status=True)                  # outro dia
    assert _cobertura.longos_no_dia(amanha) == 2
    assert _cobertura.longos_no_dia(HOJE) == 1


def test_longos_no_dia_banco_fora_do_ar_e_zero(monkeypatch):
    def boom():
        raise RuntimeError("sem banco")
    monkeypatch.setattr(ev, "conectar", boom)
    assert _cobertura.longos_no_dia(HOJE) == 0


# --- rodada em modo sugerir --------------------------------------------------------------

def test_sugerir_nao_processa_e_grava_sugestoes(raiz, sugerir):
    sugerir["estoque"] = {"longos": 2, "shorts": 0, "dias": 5.0}     # estoque ok
    sugerir["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    sugerir["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9)}
    assert cu.main([]) == 0
    assert sugerir["processados"] == []
    assert [s["video_id"] for s in ev.listar_sugestoes(["sugerida"])] == ["b", "a"]
    resumo = cu.RESUMO.read_text(encoding="utf-8")
    assert "modo sugerir" in resumo and "Sugestões do Curador" in resumo and "Live Bravo" in resumo
    assert "Entraram na fila" not in resumo


def test_sugerir_estoque_baixo_avisa_sem_processar(raiz, sugerir, banco):
    sugerir["estoque"] = {"longos": 1, "shorts": 0, "dias": 0.5}     # baixo, mas há longo pronto
    sugerir["listar"] = {"renan": [_item("a")]}
    sugerir["avaliacoes"] = {"a": _av(True, 6)}
    assert cu.main([]) == 0
    assert sugerir["processados"] == []
    assert "escolha uma sugestão" in cu.RESUMO.read_text(encoding="utf-8")
    assert not banco("SELECT 1 FROM eventos WHERE etapa='curador_rede'")


def test_sugerir_rede_dispara_sem_longo_pronto_nem_amanha(raiz, sugerir, banco):
    sugerir["estoque"] = {"longos": 0, "shorts": 0, "dias": 0.0}
    sugerir["listar"] = {"renan": [_item("a", "Live Alfa"), _item("b", "Live Bravo")]}
    sugerir["avaliacoes"] = {"a": _av(True, 6), "b": _av(True, 9)}
    assert cu.main([]) == 0
    assert sugerir["processados"] == ["renan_live_bravo"]            # a de maior prioridade
    assert _status("b") == "processada" and _status("a") == "sugerida"
    assert banco("SELECT 1 FROM eventos WHERE etapa='curador_rede' AND status='aviso'")
    assert "ficaria sem vídeo amanhã" in cu.RESUMO.read_text(encoding="utf-8")


def test_sugerir_rede_nao_dispara_com_longo_agendado_amanha(raiz, sugerir, banco):
    amanha = HOJE + timedelta(days=1)
    ev.upsert_bloco("v", 1, status="agendado", publish_at=f"{amanha}T12:00:00-03:00",
                    forcar_status=True)
    sugerir["listar"] = {"renan": [_item("a")]}
    sugerir["avaliacoes"] = {"a": _av(True, 6)}
    assert cu.main([]) == 0
    assert sugerir["processados"] == []


def test_sugerir_pedido_pendente_bloqueia_rede_mas_e_processado(raiz, sugerir, banco):
    ev.gravar_sugestao("p", titulo="Live Pedida", canal="Kim", url="https://x/p",
                       data=HOJE.isoformat(), prioridade=1, status="pedida")
    sugerir["listar"] = {"renan": [_item("a", "Live Alfa")]}
    sugerir["avaliacoes"] = {"a": _av(True, 9)}
    assert cu.main([]) == 0
    assert sugerir["processados"] == ["kim_live_pedida"]             # só o pedido, não a rede
    assert _status("a") == "sugerida" and _status("p") == "processada"
    assert not banco("SELECT 1 FROM eventos WHERE etapa='curador_rede'")


def test_sugerir_modo_evento_nao_processa(raiz, sugerir, monkeypatch):
    sugerir["estoque"] = {"longos": 3, "shorts": 0, "dias": 9.0}
    monkeypatch.setattr(cu, "modo_evento", lambda hoje, cfg: {
        "desde": HOJE - timedelta(days=2), "ate": HOJE + timedelta(days=2), "tema": "2º turno"})
    sugerir["listar"] = {"renan": [_item("a")]}
    sugerir["avaliacoes"] = {"a": _av(True, 9)}
    assert cu.main([]) == 0
    assert sugerir["processados"] == []
    assert "prioriza o tema" in cu.RESUMO.read_text(encoding="utf-8")


def test_sugerir_link_direto_vira_manual_e_processada(raiz, sugerir):
    sugerir["estoque"] = {"longos": 3, "shorts": 0, "dias": 9.0}
    (raiz / "inputs" / "kim_x.url").write_text("https://www.youtube.com/watch?v=ZZZZZZZZZZZ\n",
                                              encoding="utf-8")
    cu.gravar_estado({"ZZZZZZZZZZZ": {"decisao": "fila", "prioridade": 6, "motivo": "m",
                                      "titulo": "Live Z", "canal": "Kim", "url": "u",
                                      "data": HOJE.isoformat()}})
    ev.gravar_sugestao("ZZZZZZZZZZZ", titulo="Live Z")
    assert cu.main([]) == 0
    assert json.loads(cu.ESTADO.read_text(encoding="utf-8"))["ZZZZZZZZZZZ"]["decisao"] == "manual"
    assert _status("ZZZZZZZZZZZ") == "processada"
    assert "link direto" in next(s for s in ev.listar_sugestoes())["mensagem"]


def test_sugerir_fila_expirada_vira_sugestao_expirada(raiz, sugerir):
    sugerir["estoque"] = {"longos": 3, "shorts": 0, "dias": 9.0}
    velho = (HOJE - timedelta(days=30)).isoformat()
    cu.gravar_estado({"v": {"decisao": "fila", "prioridade": 6, "motivo": "m", "titulo": "Velho",
                            "canal": "Kim", "url": "u", "data": velho,
                            "avaliado_em": velho + "T09:00:00"}})
    ev.gravar_sugestao("v", titulo="Velho")
    assert cu.main([]) == 0
    assert _status("v") == "expirada"
    assert sugerir["processados"] == []


def test_espelhar_fila_cria_faltantes_sem_mexer_no_status(banco):
    ev.gravar_sugestao("a", status="pedida")
    cu.espelhar_fila({"a": {"decisao": "fila", "titulo": "A", "prioridade": 5},
                      "b": {"decisao": "fila", "titulo": "B", "prioridade": 4},
                      "c": {"decisao": "recusado", "titulo": "C"}})
    assert {s["video_id"]: s["status"] for s in ev.listar_sugestoes()} == \
        {"a": "pedida", "b": "sugerida"}


def test_automatico_continua_processando(raiz, rodada):
    rodada["listar"] = {"renan": [_item("a", "Live Alfa")]}
    rodada["avaliacoes"] = {"a": _av(True, 6)}
    assert cu.main([]) == 0
    assert rodada["processados"] == ["renan_live_alfa"]


# --- --processar=ID (pedir) --------------------------------------------------------------

def _sug(vid, titulo, **kw):
    ev.gravar_sugestao(vid, titulo=titulo, canal="Renan Santos", url=f"https://x/{vid}",
                       data=HOJE.isoformat(), prioridade=5, motivo="m", **kw)


def test_pedir_processa_e_marca_processada(raiz, sugerir):
    _sug("a", "Live Alfa")
    assert cu.main(["--processar=a"]) == 0
    assert sugerir["processados"] == ["renan_live_alfa"]
    assert _status("a") == "processada"
    assert not cu.TRAVA.exists()


def test_pedir_clique_duplo_nao_processa_de_novo(raiz, sugerir):
    _sug("a", "Live Alfa", status="processada")
    assert cu.main(["--processar=a"]) == 0
    assert cu.main(["--processar=zzz"]) == 0
    assert sugerir["processados"] == []


def test_pedir_com_trava_ocupada_sai_75_e_deixa_pedida(raiz, sugerir):
    _sug("a", "Live Alfa")
    assert cu.pegar_trava()
    assert cu.main(["--processar=a"]) == 75
    assert _status("a") == "pedida" and sugerir["processados"] == []
    assert cu.TRAVA.exists()                          # não soltou a trava de quem não é dele


def test_pedir_processa_na_ordem_do_clique(raiz, sugerir):
    _sug("a", "Live Alfa", status="pedida")
    ev.gravar_sugestao("b", titulo="Live Bravo", canal="Kim", url="u", data=HOJE.isoformat(),
                       prioridade=9, status="pedida")
    # b tem prioridade maior, mas a foi clicada antes (atualizado_em menor)
    ev._executar("ordem", lambda con: con.execute(
        "UPDATE sugestoes SET atualizado_em='2026-01-01T00:00:00' WHERE video_id='a'"))
    assert cu.main(["--processar=a"]) == 0
    assert sugerir["processados"] == ["renan_live_alfa", "kim_live_bravo"]
    assert _status("a") == _status("b") == "processada"


def test_pedir_falha_marca_sugestao_falhou(raiz, sugerir, monkeypatch):
    _sug("a", "Live Alfa")

    def boom(item):
        raise RuntimeError("boom")
    monkeypatch.setattr(cu, "processar", boom)
    assert cu.main(["--processar=a"]) == 1
    s, = ev.listar_sugestoes()
    assert s["status"] == "falhou" and "boom" in s["mensagem"]
    assert ev.pedir_sugestao("a")                      # "Tentar de novo" funciona


def test_pedir_com_outro_processamento_deixa_pedida(raiz, sugerir, monkeypatch):
    _sug("a", "Live Alfa")
    sugerir["ocupado"] = [(1, "02_transcribe.py")]
    monkeypatch.setattr(cu, "resumir_ocupado", lambda o: "transcrição")
    assert cu.main(["--processar=a"]) == 0
    assert _status("a") == "pedida" and sugerir["processados"] == []


def test_processar_chama_checar_orcamento_e_estouro_vira_falha(raiz, monkeypatch, banco):
    chamadas = []

    def checar(stem, etapa):
        chamadas.append((stem, etapa))
        raise _custo.OrcamentoEstourado("estourou")
    monkeypatch.setattr(_custo, "checar_orcamento", checar)
    monkeypatch.setattr(cu, "rodar", lambda *a, **k: pytest.fail("não podia baixar"))
    res = cu.processar_seguro({**_item("a"), "stem": "renan_x"})
    assert chamadas == [("renan_x", "curador")]
    assert not res["ok"] and "OrcamentoEstourado" in res["erro"]


# --- painel ------------------------------------------------------------------------------

AGORA = pd.Timestamp("2026-10-29 12:00:00")


def _evs(*linhas):
    return pd.DataFrame([{"ts": AGORA - pd.Timedelta(hours=h), "agente": "curador", "etapa": e,
                          "status": "aviso", "mensagem": m, "stem": "s"} for h, e, m in linhas])


def test_alerta_rede_recente_antigo_e_vazio():
    assert hoje._alerta_rede(pd.DataFrame(), AGORA) == []
    assert hoje._alerta_rede(_evs((30, "curador_rede", "velho")), AGORA) == []
    assert hoje._alerta_rede(_evs((1, "outra", "x")), AGORA) == []
    (nivel, titulo, det), = hoje._alerta_rede(
        _evs((5, "curador_rede", "antigo"), (1, "curador_rede", "processei X")), AGORA)
    assert nivel == "aviso" and titulo == "Curador processou sozinho" and "processei X" in det


def _est(modo):
    return {"dias": 0.5, "minimo": 2, "modo": modo, "coberto_ate": None}


def test_alertas_operacao_texto_por_modo():
    amanha = pd.DataFrame([{"x": 1}])
    auto = hoje.alertas_operacao(_est("automatico"), amanha)
    sug = hoje.alertas_operacao(_est("sugerir"), amanha)
    assert "próxima rodada" in auto[0][2] and "escolha uma sugestão" not in auto[0][2]
    assert "escolha uma sugestão" in sug[0][2] and "próxima rodada" not in sug[0][2]


def test_disparar_processamento_usa_popen_falso(monkeypatch):
    chamadas = []
    monkeypatch.setattr(hoje.subprocess, "Popen", lambda cmd, **kw: chamadas.append((cmd, kw)))
    assert hoje.disparar_processamento("abc") is None
    cmd, kw = chamadas[0]
    assert cmd[-1] == "--processar=abc" and cmd[-2].endswith("curador_oculto.py")
    assert kw["env"]["MISSAO_CURADOR_LOG"].endswith("curador_pedidos.log")


@pytest.mark.skipif(sys.platform != "win32", reason="breakaway é do Windows")
def test_disparar_processamento_fallback_sem_breakaway(monkeypatch):
    flags = []

    def popen(cmd, **kw):
        flags.append(kw["creationflags"])
        if kw["creationflags"] & 0x01000000:
            raise OSError("access denied")
    monkeypatch.setattr(hoje.subprocess, "Popen", popen)
    assert hoje.disparar_processamento("abc") is None
    assert len(flags) == 2 and flags[0] & 0x01000000 and not flags[1] & 0x01000000


def test_disparar_processamento_devolve_erro_se_todas_falham(monkeypatch):
    def popen(cmd, **kw):
        raise OSError("sem permissão")
    monkeypatch.setattr(hoje.subprocess, "Popen", popen)
    assert "sem permissão" in hoje.disparar_processamento("abc")


# --- sugestão presa em "processando" (processo caiu no meio) ------------------------------

def test_destravar_zumbis_volta_processando_pra_falhou(banco):
    ev.gravar_sugestao("z", status="processando", titulo="Live Z")
    ev.gravar_sugestao("ok", status="sugerida", titulo="Live Ok")
    assert cu.destravar_zumbis() == ["z"]
    por_id = {s["video_id"]: s for s in ev.listar_sugestoes()}
    assert por_id["z"]["status"] == "falhou" and "interrompido" in por_id["z"]["mensagem"]
    assert por_id["ok"]["status"] == "sugerida"
    assert ev.pedir_sugestao("z")                      # "Tentar de novo" volta a funcionar


def test_rodada_destrava_zumbi_ao_pegar_a_trava(raiz, rodada, banco):
    ev.gravar_sugestao("z", status="processando", titulo="Live Z")
    assert cu.main([]) == 0
    assert ev.listar_sugestoes(["falhou"])[0]["video_id"] == "z"
