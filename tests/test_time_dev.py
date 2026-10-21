"""Aba "Time de dev": lógica de status (pura) + smoke do painel com AppTest."""
import pandas as pd
from streamlit.testing.v1 import AppTest

import time_dev
from _eventos import atualizar_tarefa, evento, nova_tarefa

AGORA = pd.Timestamp("2026-10-21 15:00:00")


def _ev(*linhas):
    return pd.DataFrame([{"ts": AGORA - pd.Timedelta(minutes=m), "agente": a, "etapa": e,
                          "status": s, "mensagem": msg, "custo_usd": c, "tarefa_id": t}
                         for m, a, e, s, msg, c, t in linhas])


def test_humanizar():
    assert time_dev.humanizar(AGORA - pd.Timedelta(seconds=20), AGORA) == "agora há pouco"
    assert time_dev.humanizar(AGORA - pd.Timedelta(minutes=7), AGORA) == "há 7 min"
    assert time_dev.humanizar(AGORA - pd.Timedelta(hours=3), AGORA) == "há 3 h"
    assert time_dev.humanizar(AGORA - pd.Timedelta(days=5), AGORA) == "16/10"


def test_subagent_trabalhando_ate_terminar():
    ev = _ev((2, "testador", "subagent", "inicio", "começou: Testador X", 0, None))
    assert time_dev.status_agente("testador", ev, AGORA) == (True, "há 2 min · começou: Testador X")
    ev = _ev((2, "testador", "subagent", "inicio", "começou", 0, None),
             (1, "testador", "subagent", "ok", "APROVADO. 45 passed", 0, None))
    trabalhando, texto = time_dev.status_agente("testador", ev, AGORA)
    assert not trabalhando and texto.endswith("terminou: APROVADO. 45 passed")


def test_subagent_iniciado_ha_muito_tempo_conta_como_parado():
    ev = _ev((30, "revisor-codigo", "subagent", "inicio", "começou", 0, None))
    assert time_dev.status_agente("revisor-codigo", ev, AGORA)[0] is False


def test_tech_lead_parado_depois_do_turno():
    ev = _ev((3, "tech-lead", "tarefa", "ok", "#1 → testando (testador)", 0, 1))
    assert time_dev.status_agente("tech-lead", ev, AGORA)[0]
    ev = _ev((3, "tech-lead", "tarefa", "ok", "#1 → testando", 0, 1),
             (1, "tech-lead", "turno", "ok", "PR aberto", 0, 1))
    assert time_dev.status_agente("tech-lead", ev, AGORA) == (False, "há 1 min · respondeu: PR aberto")


def test_sem_eventos():
    assert time_dev.status_agente("testador", pd.DataFrame(), AGORA) == (False, "sem atividade registrada")


def test_custo_semana_por_tarefa():
    ev = _ev((60, "editor", "03_segmentar", "llm", "", 0.20, 1),
             (120, "editor", "04b_polir", "llm", "", 0.15, 1),
             (60 * 24 * 9, "editor", "03_segmentar", "llm", "", 5.0, 1),   # fora da semana
             (10, "editor", "03_segmentar", "llm", "", 0.30, None))      # sem tarefa
    tarefas = pd.DataFrame([{"id": 1, "titulo": "Polimento novo"}])
    c = time_dev.custo_semana_por_tarefa(ev, tarefas, AGORA)
    assert c.to_dict("records") == [{"tarefa": "#1 Polimento novo", "custo_usd": 0.35}]


def test_decisoes_pendentes_ignora_vazias():
    t = pd.DataFrame([{"id": 1, "decisao_pendente": "Horário?"}, {"id": 2, "decisao_pendente": None},
                      {"id": 3, "decisao_pendente": "  "}])
    assert list(time_dev.decisoes_pendentes(t)["id"]) == [1]


# ── smoke do painel inteiro ────────────────────────────────────────────────

def test_painel_renderiza_aba_time_dev(banco, monkeypatch):
    from _eventos import DB_PATH  # noqa: F401 — banco já aponta pro tmp via fixture
    import _eventos
    tid = nova_tarefa("Upload via API do YouTube", branch="feature/upload-api")
    atualizar_tarefa(tid, etapa="testando", responsavel="testador",
                     decisao_pendente="Horário padrão de publicação?")
    evento(None, "subagent", "inicio", agente="testador", mensagem="começou: Testador", tarefa_id=tid)

    monkeypatch.setenv("MISSAO_DB", str(_eventos.DB_PATH))
    at = AppTest.from_file("../painel/app.py", default_timeout=60).run()
    assert not at.exception
    textos = " ".join(m.value for m in at.markdown)
    assert "ESPERANDO DECISÃO SUA (1)" in textos
    assert "Horário padrão de publicação?" in textos
    assert "#1 Upload via API do YouTube" in textos
    assert "● trabalhando" in textos   # o testador acabou de começar
    assert [t.label for t in at.tabs][-1] == "Time de dev"


def test_painel_com_banco_antigo_sem_tarefas(banco, monkeypatch):
    import _eventos
    import sqlite3
    _eventos.DB_PATH.parent.mkdir(parents=True)
    con = sqlite3.connect(_eventos.DB_PATH)
    con.executescript("CREATE TABLE videos (stem TEXT, pasta TEXT, fonte_url TEXT, status TEXT,"
                      " criado_em TEXT, atualizado_em TEXT);"
                      "INSERT INTO videos VALUES ('v', 'p', NULL, 'segmentado', '2026-10-01', '2026-10-01');"
                      "CREATE TABLE blocos (stem TEXT, bloco_id INT, status TEXT, atualizado_em TEXT);"
                      "CREATE TABLE eventos (id INTEGER, ts TEXT, agente TEXT, etapa TEXT, status TEXT,"
                      " mensagem TEXT, custo_usd REAL, tokens_in INT, tokens_out INT, duracao_s REAL,"
                      " stem TEXT, bloco_id INT);")
    con.close()
    monkeypatch.setenv("MISSAO_DB", str(_eventos.DB_PATH))
    at = AppTest.from_file("../painel/app.py", default_timeout=60).run()
    assert not at.exception


# ── última atividade: texto limpo, uma linha ───────────────────────────────

def test_texto_limpo_tira_markdown_e_junta_linhas():
    md = ("**Pronto!** O PDF está em `evidencias/evidencias.pdf`.\n\n"
          "## Próximos\n- mandar o [formulário](https://x.com)\n> citação\n1. esperar")
    assert time_dev.texto_limpo(md, 200) == ("Pronto! O PDF está em evidencias/evidencias.pdf. "
                                             "Próximos mandar o formulário citação esperar")


def test_texto_limpo_tabela_e_bloco_de_codigo():
    assert time_dev.texto_limpo("| a | b |\n|---|---|\n| 1 | 2 |") == "a · b · 1 · 2"
    assert time_dev.texto_limpo("```py\nprint(1)\n```\nfeito") == "feito"


def test_texto_limpo_nao_estraga_texto_sem_markdown():
    assert time_dev.texto_limpo("snake_case e 2*3*4 e __init__") == "snake_case e 2*3*4 e __init__"
    assert time_dev.texto_limpo("") == ""


def test_texto_limpo_corta_com_reticencias_sem_quebrar_palavra():
    longo = "APROVADO. " + "palavra " * 30
    t = time_dev.texto_limpo(longo, 40)
    assert t.endswith("…") and len(t) <= 40 and "\n" not in t
    assert t[:-1].split()[-1] == "palavra"          # última palavra inteira
    assert time_dev.texto_limpo("curto", 40) == "curto"


def test_card_mostra_atividade_limpa():
    msg = "**APROVADO**\n\n- 102 passed\n- `tests/test_upload.py` ok\n" + "detalhe " * 40
    ev = _ev((1, "testador", "subagent", "ok", msg, 0, 1))
    _, texto = time_dev.status_agente("testador", ev, AGORA)
    assert texto.startswith("há 1 min · terminou: APROVADO 102 passed tests/test_upload.py ok")
    assert texto.endswith("…") and "\n" not in texto and "*" not in texto and "`" not in texto
