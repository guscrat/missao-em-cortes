"""Hook do Claude Code: registra a atividade do time de dev no banco do painel.

Ligado em .claude/settings.json nos eventos SubagentStart, SubagentStop e Stop. Recebe o
JSON do evento no stdin (campos conferidos na doc oficial de hooks):
  SubagentStart → agent_type, agent_id (sem descrição: pescamos o `description` da
                  chamada do Agent no fim do transcript do principal, se der)
  SubagentStop  → agent_type, last_assistant_message (o resultado do subagent)
  Stop          → last_assistant_message (fim do turno do agente principal = tech-lead)

Regras: rápido (<1s), NUNCA sai com código != 0 (exit 2 no Stop/SubagentStop impediria o
agente de parar) e nunca escreve no stdout (vira contexto/decisão pro Claude Code).
"""
import json
import os
import sys
from pathlib import Path

LIMITE_MSG = 120
CAUDA_TRANSCRIPT = 256 * 1024   # só o fim do transcript: a chamada do Agent é recente


def _curto(texto: str | None) -> str:
    return " ".join((texto or "").split())[:LIMITE_MSG]


def _descricao_do_subagent(transcript: str | None, agent_type: str) -> str:
    """Descrição da chamada mais recente do Agent pra esse tipo, lida do fim do transcript.
    Best-effort: o transcript é gravado de forma assíncrona e pode estar atrasado."""
    try:
        with open(os.path.expanduser(transcript), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - CAUDA_TRANSCRIPT))
            linhas = f.read().decode("utf-8", "ignore").splitlines()
        for linha in reversed(linhas):
            if '"Agent"' not in linha and '"Task"' not in linha:
                continue
            try:
                conteudo = json.loads(linha).get("message", {}).get("content", [])
            except ValueError:
                continue
            for item in reversed(conteudo if isinstance(conteudo, list) else []):
                entrada = item.get("input", {}) if isinstance(item, dict) else {}
                if (item.get("type") == "tool_use" and item.get("name") in ("Agent", "Task")
                        and entrada.get("subagent_type", "general-purpose") == agent_type):
                    return entrada.get("description", "")
    except (OSError, TypeError, AttributeError):
        pass
    return ""


def processar(dados: dict) -> None:
    from _eventos import evento, tarefa_ativa

    tipo = dados.get("hook_event_name")
    if tipo == "SubagentStart":
        agente = dados.get("agent_type") or "subagent"
        desc = _descricao_do_subagent(dados.get("transcript_path"), agente)
        evento(None, "subagent", "inicio", agente=agente, tarefa_id=tarefa_ativa(),
               mensagem=_curto(f"começou: {desc}" if desc else "começou"))
    elif tipo == "SubagentStop":
        evento(None, "subagent", "ok", agente=dados.get("agent_type") or "subagent",
               tarefa_id=tarefa_ativa(), mensagem=_curto(dados.get("last_assistant_message")))
    elif tipo == "Stop":
        evento(None, "turno", "ok", agente="tech-lead", tarefa_id=tarefa_ativa(),
               mensagem=_curto(dados.get("last_assistant_message")))


def main() -> None:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import _eventos
        _eventos.BUSY_TIMEOUT_S = 0.5   # banco travado: desiste rápido em vez de segurar o agente
        sys.stderr = open(os.devnull, "w")   # avisos best-effort do _eventos não vazam
        processar(json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}"))
    except Exception:  # noqa: BLE001 — hook nunca pode falhar
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
