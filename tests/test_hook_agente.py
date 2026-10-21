"""hook_agente.py: grava eventos dos hooks do Claude Code, nunca falha, nunca imprime."""
import json
import os
import subprocess
import sys
from pathlib import Path

import hook_agente
from _eventos import atualizar_tarefa, nova_tarefa

HOOK = Path(__file__).parent.parent / "scripts" / "hook_agente.py"


def _transcript(tmp_path, *chamadas):
    """JSONL no formato do transcript: mensagens do assistant com tool_use do Agent."""
    linhas = [json.dumps({"type": "user", "message": {"content": "oi"}})]
    for tipo, desc in chamadas:
        linhas.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "chamando"},
            {"type": "tool_use", "name": "Agent",
             "input": {"description": desc, "subagent_type": tipo, "prompt": "..."}}]}}))
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(linhas), encoding="utf-8")
    return str(p)


def test_subagent_start_pega_descricao_do_transcript(banco, tmp_path):
    tr = _transcript(tmp_path, ("testador", "Testador da feature X"),
                     ("revisor-codigo", "Revisor da feature X"))
    hook_agente.processar({"hook_event_name": "SubagentStart", "agent_type": "testador",
                           "agent_id": "a1", "transcript_path": tr})
    ev = banco("SELECT agente, etapa, status, mensagem FROM eventos")[0]
    assert ev == {"agente": "testador", "etapa": "subagent", "status": "inicio",
                  "mensagem": "começou: Testador da feature X"}


def test_subagent_start_sem_transcript_cai_pra_comecou(banco):
    hook_agente.processar({"hook_event_name": "SubagentStart", "agent_type": "Explore",
                           "transcript_path": "/nao/existe.jsonl"})
    assert banco("SELECT mensagem FROM eventos")[0]["mensagem"] == "começou"


def test_subagent_stop_grava_resultado_curto_na_tarefa_ativa(banco):
    tid = nova_tarefa("x")
    atualizar_tarefa(tid, etapa="testando")
    hook_agente.processar({"hook_event_name": "SubagentStop", "agent_type": "testador",
                           "last_assistant_message": "APROVADO.\n" + "x" * 500})
    ev = banco("SELECT agente, status, mensagem, tarefa_id FROM eventos WHERE etapa='subagent'")[0]
    assert ev["agente"] == "testador" and ev["status"] == "ok" and ev["tarefa_id"] == tid
    assert ev["mensagem"].startswith("APROVADO. x") and len(ev["mensagem"]) == 120


def test_stop_vira_tech_lead(banco):
    hook_agente.processar({"hook_event_name": "Stop", "last_assistant_message": "PR #5 mergeado"})
    ev = banco("SELECT agente, etapa, mensagem FROM eventos")[0]
    assert ev == {"agente": "tech-lead", "etapa": "turno", "mensagem": "PR #5 mergeado"}


def test_evento_desconhecido_e_ignorado(banco):
    import _eventos
    hook_agente.processar({"hook_event_name": "PreToolUse"})
    assert not _eventos.DB_PATH.exists()   # nem chegou a abrir o banco


def _rodar(stdin: bytes, db: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "MISSAO_DB": str(db)}
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                          env=env, timeout=10)


def test_processo_real_exit_0_e_stdout_vazio(tmp_path):
    db = tmp_path / "pipeline.db"
    r = _rodar(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "ok"}).encode(), db)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    assert db.exists()


def test_processo_real_com_lixo_nao_falha(tmp_path):
    for entrada in (b"", b"{lixo", b"\xff\xfe", b"[]"):
        r = _rodar(entrada, tmp_path / "x.db")
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_processo_real_com_banco_impossivel_nao_falha(tmp_path):
    bloqueio = tmp_path / "arquivo"
    bloqueio.write_text("")
    r = _rodar(b'{"hook_event_name": "Stop"}', bloqueio / "pipeline.db")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_settings_json_liga_os_tres_hooks_sem_derrubar():
    cfg = json.loads((HOOK.parent.parent / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for nome in ("SubagentStart", "SubagentStop", "Stop"):
        cmd = cfg["hooks"][nome][0]["hooks"][0]["command"]
        assert "hook_agente.py" in cmd and cmd.endswith("|| true") and ">/dev/null" in cmd


def test_processo_real_json_valido_de_tipo_errado(tmp_path):
    for entrada in (b"[1,2]", b"42", b'"texto"', b"null", b"true",
                    b'{"hook_event_name": ["Stop"]}', b'{"hook_event_name": "Stop", "last_assistant_message": 5}',
                    b'{"hook_event_name": "SubagentStart", "transcript_path": 7, "agent_type": {"a": 1}}'):
        r = _rodar(entrada, tmp_path / "t.db")
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b""), entrada


def test_hook_demora_menos_de_1s(tmp_path):
    import time
    ini = time.perf_counter()
    r = _rodar(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "ok"}).encode(),
               tmp_path / "t.db")
    assert r.returncode == 0 and time.perf_counter() - ini < 1.0


def test_transcript_com_linhas_corrompidas(banco, tmp_path):
    bom = _transcript(tmp_path, ("testador", "Desc boa"))
    p = tmp_path / "sujo.jsonl"
    p.write_text('{"Agent" quebrado\n[1,"Agent"]\n"Task"\n{"message": 5, "Agent": 1}\n'
                 + Path(bom).read_text(encoding="utf-8") + "\n{lixo \"Agent\"", encoding="utf-8")
    assert hook_agente._descricao_do_subagent(str(p), "testador") == "Desc boa"
    assert hook_agente._descricao_do_subagent(str(p), "outro") == ""
