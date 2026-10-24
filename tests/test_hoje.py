"""Aba "Hoje" do painel: funções puras (tmp_path/mocks, nunca o state/ real) + smoke AppTest."""
import json
import os
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

import hoje

AGORA = pd.Timestamp("2026-10-22 12:00:00")
DIA = datetime(2026, 10, 22).date()


def _blocos(*linhas):
    return pd.DataFrame([{"stem": "v", "bloco_id": i, "status": s, "publish_at": p, "titulo": f"T{i}"}
                         for i, (s, p) in enumerate(linhas, 1)])


def _ev(*linhas):
    """(horas_atras, agente, etapa, status, mensagem, stem)"""
    return pd.DataFrame([{"ts": AGORA - pd.Timedelta(hours=h), "agente": a, "etapa": e, "status": s,
                          "mensagem": m, "stem": st_} for h, a, e, s, m, st_ in linhas])


# ── no_ar / fila_youtube ───────────────────────────────────────────────────

def test_no_ar_fusos_e_status():
    df = _blocos(("agendado", "2026-10-22T18:00:00-03:00"),
                 ("publicado", "2026-10-22T23:30:00Z"),      # 20:30 em Brasília
                 ("agendado", "2026-10-23T01:00:00Z"),       # 22/10 22:00 em Brasília
                 ("agendado", "2026-10-22T09:00:00"),        # sem fuso = local
                 ("aprovado", "2026-10-22T10:00:00-03:00"),  # status errado
                 ("agendado", "2026-10-23T08:00:00-03:00"),  # outro dia
                 ("agendado", None))
    r = hoje.no_ar(df, DIA)
    assert list(r["bloco_id"]) == [4, 1, 2, 3]
    assert [q.hour for q in r["quando"]] == [9, 18, 20, 22]


def test_no_ar_vazio_ou_sem_coluna():
    assert hoje.no_ar(pd.DataFrame(), DIA).empty
    assert hoje.no_ar(pd.DataFrame([{"status": "agendado"}]), DIA).empty


def test_scripts_frescos_recarrega_quando_o_arquivo_muda(tmp_path, monkeypatch):
    """Módulos falsos em tmp: mudou o arquivo (mtime) → o painel passa a usar a versão nova,
    e quem depende do recarregado também recarrega."""
    import sys
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    base, dep = scripts / "zz_base.py", scripts / "zz_dep.py"
    base.write_text("V = 1\n", encoding="utf-8")
    dep.write_text("import zz_base\nV = zz_base.V * 10\n", encoding="utf-8")
    (scripts / "13_curador.py").write_text("V = 0\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "13_curador", raising=False)
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.setattr(hoje, "ROOT", tmp_path)
    monkeypatch.setattr(hoje, "MODULOS_SCRIPTS", ["zz_base", "zz_dep", "13_curador"])
    monkeypatch.setattr(hoje, "_MTIMES", {})
    try:
        hoje.scripts_frescos()
        assert sys.modules["zz_dep"].V == 10
        sys.modules["zz_dep"].MARCA = True           # sem mudança no disco: não recarrega
        hoje.scripts_frescos()
        assert getattr(sys.modules["zz_dep"], "MARCA", False)
        base.write_text("V = 2\n", encoding="utf-8")  # muda só a base
        st_ = base.stat()
        os.utime(base, (st_.st_atime, st_.st_mtime + 10))
        hoje.scripts_frescos()
        assert sys.modules["zz_base"].V == 2
        assert sys.modules["zz_dep"].V == 20          # dependente recarregou
    finally:
        for n in ("zz_base", "zz_dep", "13_curador"):
            sys.modules.pop(n, None)


# ── decisoes ───────────────────────────────────────────────────────────────

def test_decisoes_tarefas_e_quarentena():
    t = pd.DataFrame([{"id": 1, "titulo": "Upload", "decisao_pendente": "Horário?"},
                      {"id": 2, "titulo": "X", "decisao_pendente": None},
                      {"id": 3, "titulo": "Y", "decisao_pendente": "  "}])
    b = pd.DataFrame([{"stem": "v", "bloco_id": 2, "status": "quarentena", "titulo": "Polêmico",
                       "motivo": "fala dura"},
                      {"stem": "v", "bloco_id": 3, "status": "quarentena", "titulo": None, "motivo": None},
                      {"stem": "v", "bloco_id": 4, "status": "aprovado", "titulo": "ok", "motivo": None}])
    r = hoje.decisoes(t, b)
    assert r[0] == ("Tarefa #1 · Upload", "Horário?")
    assert r[1] == ("Quarentena · Polêmico (v #2)", "fala dura")
    assert r[2][0] == "Quarentena · bloco 3 (v #3)" and "aprovar ou descartar" in r[2][1]
    assert len(r) == 3
    assert hoje.decisoes(pd.DataFrame(), pd.DataFrame()) == []


# ── alertas do curador ─────────────────────────────────────────────────────

def test_curador_falha_sem_ok_posterior(tmp_path):
    ev = _ev((5, "curador", "13_curador", "falha", "boom", "a"),
             (3, "curador", "13_curador", "falha", "boom2", "b"),
             (2, "curador", "13_curador", "ok", "recuperou", "b"),       # b resolvido
             (1, "outro", "x", "falha", "nao e curador", "c"))
    r = hoje.alertas_curador(ev, AGORA, log=tmp_path / "nao_existe.log")
    assert len(r) == 1 and r[0][:2] == ("erro", "Curador falhou") and "boom" in r[0][2]


def test_curador_falha_antiga_ignorada(tmp_path):
    ev = _ev((60, "curador", "13_curador", "falha", "velha", "a"))
    assert hoje.alertas_curador(ev, AGORA, log=tmp_path / "x.log") == []


def test_curador_erro_de_download(tmp_path):
    ev = _ev((1, "curador", "13_curador", "falha", "falhou 01_baixar: privado", "live1"))
    r = hoje.alertas_curador(ev, AGORA, log=tmp_path / "x.log")
    assert r[0][1] == "Erro de download" and "live1" in r[0][2]


def _log(tmp_path, texto, dt):
    p = tmp_path / "curador.log"
    p.write_text(texto, encoding="utf-8")
    ts = dt.timestamp()
    os.utime(p, (ts, ts))
    return p


def test_curador_nao_rodou_hoje(tmp_path):
    log = _log(tmp_path, "ok\n", datetime(2026, 10, 21, 17, 0))
    agora = pd.Timestamp("2026-10-22 18:30:00")
    assert hoje.alertas_curador(pd.DataFrame(), agora, log=log)[0][1] == "Curador não rodou hoje"
    # antes das 18h ainda não alerta
    assert hoje.alertas_curador(pd.DataFrame(), pd.Timestamp("2026-10-22 17:30:00"), log=log) == []
    # rodou hoje às 17h: ok
    log = _log(tmp_path, "ok\n", datetime(2026, 10, 22, 17, 2))
    assert hoje.alertas_curador(pd.DataFrame(), agora, log=log) == []


def test_curador_traceback_nas_ultimas_40_linhas(tmp_path):
    texto = "Traceback (most recent call last):\n" + "linha\n" * 10
    log = _log(tmp_path, texto, datetime(2026, 10, 22, 17, 2))
    r = hoje.alertas_curador(pd.DataFrame(), pd.Timestamp("2026-10-22 18:30:00"), log=log)
    assert r[0][1] == "Curador quebrou na última rodada"
    # traceback fora das últimas 40 linhas não conta
    log = _log(tmp_path, texto + "linha\n" * 50, datetime(2026, 10, 22, 17, 2))
    assert hoje.alertas_curador(pd.DataFrame(), pd.Timestamp("2026-10-22 18:30:00"), log=log) == []


def test_curador_traceback_so_da_ultima_rodada(tmp_path):
    agora = pd.Timestamp("2026-10-22 18:30:00")
    quebrou = "Curador · 4 canais\nTraceback (most recent call last):\nErro\n"
    rodada_boa = "Curador · 4 canais\nEstoque pronto: 4 longo(s)\n"
    log = _log(tmp_path, quebrou + rodada_boa, datetime(2026, 10, 22, 17, 2))
    assert hoje.alertas_curador(pd.DataFrame(), agora, log=log) == []
    log = _log(tmp_path, rodada_boa + quebrou, datetime(2026, 10, 22, 17, 2))
    assert hoje.alertas_curador(pd.DataFrame(), agora, log=log)[0][1] == "Curador quebrou na última rodada"


# ── tokens ─────────────────────────────────────────────────────────────────

def test_token_ausente_e_sem_refresh(tmp_path):
    (tmp_path / "youtube_token.json").write_text(json.dumps({"token": "x"}))
    r = hoje.alertas_token(pd.DataFrame(), AGORA, secrets=tmp_path)
    titulos = [a[1] for a in r]
    assert "Token do YouTube (publicar) vai vencer" in titulos
    assert "Login do YouTube Analytics ausente" in titulos


def test_token_ok_sem_alertas(tmp_path):
    for n in ("youtube_token.json", "analytics_token.json"):
        (tmp_path / n).write_text(json.dumps({"refresh_token": "r"}))
    assert hoje.alertas_token(pd.DataFrame(), AGORA, secrets=tmp_path) == []


def test_token_invalid_grant_ate_ok_posterior(tmp_path):
    for n in ("youtube_token.json", "analytics_token.json"):
        (tmp_path / n).write_text(json.dumps({"refresh_token": "r"}))
    ev = _ev((30, "upload", "09_upload", "falha", "RefreshError: invalid_grant", "v"))
    r = hoje.alertas_token(ev, AGORA, secrets=tmp_path)
    assert [a[1] for a in r] == ["Token vencido/recusado"]
    ev = _ev((30, "upload", "09_upload", "falha", "invalid_grant", "v"),
             (2, "upload", "09_upload", "ok", "subiu", "v"))
    assert hoje.alertas_token(ev, AGORA, secrets=tmp_path) == []
    ev = _ev((30, "upload", "09_upload", "falha", "disco cheio", "v"))
    assert hoje.alertas_token(ev, AGORA, secrets=tmp_path) == []


# ── cota ───────────────────────────────────────────────────────────────────

def _cota(tmp_path, dia, usadas, limite=10_000):
    c = tmp_path / "cota.json"
    c.write_text(json.dumps({"dia_pacifico": dia, "usadas": usadas}))
    u = tmp_path / "upload.json"
    u.write_text(json.dumps({"cota_limite_dia": limite}))
    return c, u


def test_cota_niveis(tmp_path):
    agora = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)   # 08:00 PDT, dia 22
    c, u = _cota(tmp_path, "2026-10-22", 7000)
    assert hoje.alerta_cota(agora, c, u, 80) == []
    c, u = _cota(tmp_path, "2026-10-22", 8000)
    assert hoje.alerta_cota(agora, c, u, 80)[0][0] == "aviso"
    c, u = _cota(tmp_path, "2026-10-22", 10000)
    r = hoje.alerta_cota(agora, c, u, 80)
    assert r[0][0] == "erro" and "10.000" in r[0][2]


def test_cota_de_outro_dia_pacifico_ou_ausente(tmp_path):
    # 03:00 UTC de 23/10 ainda é dia 22 no Pacífico
    agora = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)
    c, u = _cota(tmp_path, "2026-10-22", 9000)
    assert len(hoje.alerta_cota(agora, c, u, 80)) == 1
    # 12:00 UTC de 23/10 já virou
    assert hoje.alerta_cota(datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc), c, u, 80) == []
    assert hoje.alerta_cota(agora, tmp_path / "nada.json", u, 80) == []


def test_cota_limite_padrao_sem_upload_json(tmp_path):
    c, _ = _cota(tmp_path, "2026-10-22", 9000)
    agora = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
    assert hoje.alerta_cota(agora, c, tmp_path / "nada.json", 80)[0][0] == "aviso"


# ── operação, custo, placar, config ────────────────────────────────────────

def test_alertas_operacao():
    vazio = pd.DataFrame()
    cheio = pd.DataFrame([{"x": 1}])
    r = hoje.alertas_operacao({"dias": 1.5, "minimo": 3}, vazio)
    assert [a[1] for a in r] == ["Estoque baixo", "Nada agendado pra amanhã"]
    assert "nada agendado nem pronto" in r[0][2]
    r = hoje.alertas_operacao({"dias": 1.5, "minimo": 3, "coberto_ate": date(2026, 10, 24)}, vazio)
    assert "canal coberto só até 24/10" in r[0][2] and "1.5 dia(s), mínimo 3" in r[0][2]
    assert hoje.alertas_operacao({"dias": 3, "minimo": 3}, cheio) == []
    assert [a[1] for a in hoje.alertas_operacao(None, vazio)] == ["Nada agendado pra amanhã"]


def test_custo_mes_projecao_e_agentes():
    ev = pd.DataFrame({"agente": ["editor", "curador", "editor", "zero"],
                       "custo_usd": [1.0, 0.5, 0.5, 0.0]})
    c = hoje.custo_mes(ev, 10.0, pd.Timestamp("2026-10-10 12:00"))
    assert c["gasto"] == 2.0 and c["pct"] == 20.0
    assert abs(c["projecao"] - 2.0 / 10 * 31) < 1e-9
    assert dict(c["por_agente"]) == {"editor": 1.5, "curador": 0.5}   # "zero" fora
    vazio = hoje.custo_mes(pd.DataFrame(columns=["agente", "custo_usd"]), 10.0, pd.Timestamp("2026-02-14"))
    assert vazio["gasto"] == 0 and vazio["projecao"] == 0 and vazio["por_agente"].empty
    assert hoje.custo_mes(ev, 0, pd.Timestamp("2026-10-10"))["pct"] == 0


def test_custo_mes_fevereiro_tem_28_dias():
    ev = pd.DataFrame({"agente": ["a"], "custo_usd": [1.0]})
    assert hoje.custo_mes(ev, 10, pd.Timestamp("2026-02-14"))["projecao"] == 1.0 / 14 * 28


def test_placar(tmp_path):
    r = hoje.placar(tmp_path / "nada.json")
    assert r["inscritos"] == (None, 1000) and r["atualizado"] is None
    p = tmp_path / "placar.json"
    p.write_text(json.dumps({"atualizado": "2026-11-01T10:00:00-03:00", "inscritos": 312,
                             "horas_12m": "x", "views_shorts_90d": 5.5}))
    r = hoje.placar(p)
    assert r["inscritos"] == (312, 1000) and r["horas_12m"] == (None, 4000)
    assert r["views_shorts_90d"] == (5.5, 10_000_000) and r["atualizado"].startswith("2026-11-01")


def test_config_painel(tmp_path, monkeypatch):
    monkeypatch.setattr(hoje, "CONFIG_PAINEL", tmp_path / "nada.json")
    assert hoje.config_painel() == {"orcamento_mensal_usd": 10.0, "cota_alerta_pct": 80}
    p = tmp_path / "painel.json"
    p.write_text(json.dumps({"orcamento_mensal_usd": 25, "lixo": 1}))
    monkeypatch.setattr(hoje, "CONFIG_PAINEL", p)
    assert hoje.config_painel() == {"orcamento_mensal_usd": 25, "cota_alerta_pct": 80}
    p.write_text("{quebrado")
    assert hoje.config_painel()["orcamento_mensal_usd"] == 10.0


# ── smoke do painel com a aba Hoje ─────────────────────────────────────────

def test_painel_aba_hoje(banco, monkeypatch, tmp_path, cartoes):
    import _eventos
    from _eventos import upsert_bloco
    amanha = (datetime.now() + pd.Timedelta(days=1)).strftime("%Y-%m-%dT18:00:00")
    upsert_bloco("v", 1, status="agendado", forcar_status=True, titulo="Sai amanhã", publish_at=amanha)
    upsert_bloco("v", 2, status="quarentena", forcar_status=True, titulo="Em dúvida")
    for n in ("youtube_token.json", "analytics_token.json"):
        (tmp_path / n).write_text(json.dumps({"refresh_token": "r"}))
    monkeypatch.setattr(hoje, "estoque", lambda: {"dias": 0.5, "minimo": 3, "coberto_ate": date(2026, 10, 24)})
    monkeypatch.setattr(hoje, "STATE", tmp_path / "state_falso")
    monkeypatch.setattr(hoje, "SECRETS", tmp_path)
    monkeypatch.setattr(hoje, "UPLOAD_JSON", tmp_path / "upload_falso.json")
    monkeypatch.setattr(hoje, "CONFIG_PAINEL", tmp_path / "painel_falso.json")
    monkeypatch.setenv("MISSAO_DB", str(_eventos.DB_PATH))
    st.cache_data.clear()
    at = AppTest.from_file("../painel/app.py", default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.tabs][0] == "Hoje"
    c = cartoes(at)
    assert c["Vai ao ar hoje"] == ("0", "nada hoje") and c["Amanhã"] == ("1", "18h00")
    assert c["Canal coberto até"] == ("24/10", "0,5 dia(s) · abaixo do mínimo (3)")
    assert "Estoque" not in c and c["Auditoria YouTube"][0] == "pendente"
    assert c["Decisões pendentes"] == ("1", "1 em quarentena")
    textos = " ".join(m.value for m in at.markdown)
    assert "<div class='ct alerta'><div class='ct-r'>Canal coberto até" in textos   # abaixo do mínimo
    assert "Estoque baixo" in textos and "Sai amanhã" in textos and "Quarentena · Em dúvida" in textos
    assert "canal coberto só até 24/10" in textos
    assert "Nada agendado pra amanhã" not in textos
    st.cache_data.clear()
