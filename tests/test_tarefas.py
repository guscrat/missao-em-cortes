"""Tabela tarefas (_eventos), CLI tarefa.py e migração do banco."""
import sqlite3

import pytest

import _eventos
import tarefa
from _eventos import atualizar_tarefa, evento, ler_tarefa, nova_tarefa, tarefa_ativa


def test_nova_tarefa_entra_no_backlog(banco):
    tid = nova_tarefa("Upload via API", branch="feature/upload-api")
    t = ler_tarefa(tid)
    assert (t["titulo"], t["etapa"], t["branch"], t["rodada"]) == \
        ("Upload via API", "backlog", "feature/upload-api", 0)


def test_reprovado_soma_rodada(banco):
    tid = nova_tarefa("x")
    atualizar_tarefa(tid, ultimo_resultado="REPROVADO", reprovou=True)
    atualizar_tarefa(tid, ultimo_resultado="REPROVADO", reprovou=True)
    atualizar_tarefa(tid, ultimo_resultado="APROVADO")
    t = ler_tarefa(tid)
    assert (t["rodada"], t["ultimo_resultado"]) == (2, "APROVADO")


def test_etapa_invalida_falha_alto(banco):
    tid = nova_tarefa("x")
    with pytest.raises(ValueError):
        atualizar_tarefa(tid, etapa="quase-pronto")


def test_tarefa_inexistente_retorna_false(banco):
    assert atualizar_tarefa(999, etapa="fazendo") is False


def test_tarefa_ativa_e_a_mais_recente_em_andamento(banco):
    a, b, c = nova_tarefa("a"), nova_tarefa("b"), nova_tarefa("c")
    atualizar_tarefa(a, etapa="fazendo")
    atualizar_tarefa(b, etapa="testando")
    atualizar_tarefa(c, etapa="pronto")
    assert tarefa_ativa() == b
    atualizar_tarefa(b, etapa="pronto")
    assert tarefa_ativa() == a


def test_banco_fora_do_ar_nao_derruba(banco, monkeypatch, capsys):
    monkeypatch.setattr(_eventos, "conectar", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert nova_tarefa("x") is None
    assert atualizar_tarefa(1, etapa="fazendo") is None
    assert tarefa_ativa() is None
    assert "[aviso] painel" in capsys.readouterr().err


def test_evento_pega_tarefa_da_env(banco, monkeypatch):
    monkeypatch.setenv("MISSAO_TAREFA", "7")
    evento("v", "03_segmentar", "llm", custo_usd=0.2)
    assert banco("SELECT tarefa_id FROM eventos")[0]["tarefa_id"] == 7


def test_migra_banco_antigo_sem_tarefa_id(banco):
    db = _eventos.DB_PATH
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE eventos (id INTEGER PRIMARY KEY, ts TEXT, stem TEXT, bloco_id INT,"
                " agente TEXT, etapa TEXT, status TEXT, mensagem TEXT, tokens_in INT,"
                " tokens_out INT, custo_usd REAL, duracao_s REAL)")
    con.close()
    evento(None, "x", "ok", tarefa_id=3)
    assert banco("SELECT tarefa_id FROM eventos")[0]["tarefa_id"] == 3


# ── CLI ────────────────────────────────────────────────────────────────────

def _cli(capsys, *argv) -> tuple[int, str]:
    code = tarefa.main(list(argv))
    return code, capsys.readouterr().out


def test_cli_fluxo_completo_em_uma_linha(banco, capsys):
    code, out = _cli(capsys, "nova", "Upload via API do YouTube", "--branch", "feature/upload-api")
    assert code == 0 and out.count("\n") == 1 and out.startswith("#1 Upload via API do YouTube")

    _, out = _cli(capsys, "mover", "1", "testando", "--responsavel", "testador")
    assert "testando · testador" in out and out.count("\n") == 1

    _, out = _cli(capsys, "resultado", "1", "reprovado", "--msg", "1 falha em test_upload")
    assert "rodada 1" in out

    _, out = _cli(capsys, "decisao", "1", "Horário padrão de publicação?")
    assert "❓ Horário padrão de publicação?" in out
    assert ler_tarefa(1)["decisao_pendente"] == "Horário padrão de publicação?"

    _cli(capsys, "decisao", "1", "--resolvida")
    assert ler_tarefa(1)["decisao_pendente"] is None

    evs = banco("SELECT agente, etapa, status, tarefa_id FROM eventos ORDER BY id")
    assert {e["agente"] for e in evs} == {"tech-lead"} and {e["tarefa_id"] for e in evs} == {1}
    assert [e["status"] for e in evs] == ["inicio", "ok", "devolvido", "aviso", "ok"]


def test_cli_tarefa_inexistente_sai_com_1(banco, capsys):
    code, out = _cli(capsys, "mover", "42", "fazendo")
    assert code == 1 and "não existe" in out


def test_cli_etapa_invalida_e_recusada(banco):
    with pytest.raises(SystemExit):
        tarefa.main(["mover", "1", "quase-pronto"])


def test_cli_lista(banco, capsys):
    _cli(capsys, "nova", "a")
    _cli(capsys, "nova", "b")
    _cli(capsys, "mover", "2", "pronto")
    _, out = _cli(capsys, "lista")
    assert "#1 a" in out and "#2 b" not in out
    _, out = _cli(capsys, "lista", "--todas")
    assert "#2 b" in out and out.count("\n") == 1


def test_cli_decisao_sem_pergunta_nem_resolvida_falha(banco, capsys):
    nova_tarefa("x")
    with pytest.raises(SystemExit) as e:
        tarefa.main(["decisao", "1"])
    assert e.value.code == 2
    assert ler_tarefa(1)["decisao_pendente"] is None
