"""Tarefas macro do time de dev — o que o Gu (PO) acompanha na aba "Time de dev" do painel.

Uso (saída sempre em 1 linha):
    uv run py scripts/tarefa.py nova "Upload via API do YouTube" --branch feature/upload-api
    uv run py scripts/tarefa.py mover <id> testando --responsavel testador
    uv run py scripts/tarefa.py resultado <id> REPROVADO --msg "1 falha em test_upload"
    uv run py scripts/tarefa.py decisao <id> "Horário padrão de publicação?"
    uv run py scripts/tarefa.py decisao <id> --resolvida
    uv run py scripts/tarefa.py lista [--todas]

Etapas: backlog → fazendo → testando → revisando → pronto (+ bloqueado).
Cada comando também vira um evento (agente = tech-lead, quem move as tarefas), que
alimenta a linha do tempo. A atividade real dos subagents vem dos hooks (hook_agente.py).
"""
import argparse
import sys
sys.stdout.reconfigure(encoding='utf-8')

from _eventos import (ETAPAS_TAREFA, atualizar_tarefa, evento, ler_tarefa, listar_tarefas,
                      nova_tarefa)

RESULTADOS = ["APROVADO", "REPROVADO"]


def _linha(t: dict) -> str:
    partes = [f"#{t['id']} {t['titulo']}", t["etapa"]]
    if t.get("responsavel"):
        partes.append(t["responsavel"])
    if t.get("branch"):
        partes.append(t["branch"])
    if t.get("rodada"):
        partes.append(f"rodada {t['rodada']}")
    if t.get("decisao_pendente"):
        partes.append(f"❓ {t['decisao_pendente']}")
    return " · ".join(partes)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tarefa.py", description="Tarefas do time de dev")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("nova")
    p.add_argument("titulo")
    p.add_argument("--branch")
    p = sub.add_parser("mover")
    p.add_argument("id", type=int)
    p.add_argument("etapa", choices=ETAPAS_TAREFA)
    p.add_argument("--responsavel")
    p = sub.add_parser("resultado")
    p.add_argument("id", type=int)
    p.add_argument("resultado", type=str.upper, choices=RESULTADOS)
    p.add_argument("--msg", default="")
    p = sub.add_parser("decisao")
    p.add_argument("id", type=int)
    p.add_argument("pergunta", nargs="?")
    p.add_argument("--resolvida", action="store_true")
    p = sub.add_parser("lista")
    p.add_argument("--todas", action="store_true", help="inclui as prontas")
    return ap


def main(argv: list[str]) -> int:
    a = _parser().parse_args(argv)

    if a.cmd == "nova":
        tid = nova_tarefa(a.titulo, branch=a.branch)
        if tid is None:
            print("[!] tarefa não registrada (banco indisponível — veja o aviso acima)")
            return 0
        evento(None, "tarefa", "inicio", agente="tech-lead", tarefa_id=tid,
               mensagem=f"criou #{tid}: {a.titulo}")
        print(_linha(ler_tarefa(tid) or {"id": tid, "titulo": a.titulo, "etapa": "backlog"}))
        return 0

    if a.cmd == "lista":
        tarefas = listar_tarefas(incluir_prontas=a.todas)
        print(" | ".join(_linha(t) for t in tarefas) or "nenhuma tarefa aberta")
        return 0

    if a.cmd == "mover":
        campos = {"etapa": a.etapa, **({"responsavel": a.responsavel} if a.responsavel else {})}
        achou = atualizar_tarefa(a.id, **campos)
        msg = f"#{a.id} → {a.etapa}" + (f" ({a.responsavel})" if a.responsavel else "")
        status = "ok"
    elif a.cmd == "resultado":
        texto = a.resultado + (f": {a.msg}" if a.msg else "")
        achou = atualizar_tarefa(a.id, ultimo_resultado=texto, reprovou=a.resultado == "REPROVADO")
        msg, status = f"#{a.id} {texto}", "aprovado" if a.resultado == "APROVADO" else "devolvido"
    else:  # decisao
        if not a.resolvida and not a.pergunta:
            _parser().error("decisao precisa da pergunta ou de --resolvida")
        achou = atualizar_tarefa(a.id, decisao_pendente=None if a.resolvida else a.pergunta)
        msg = f"#{a.id} decisão resolvida" if a.resolvida else f"#{a.id} pergunta pro Gu: {a.pergunta}"
        status = "ok" if a.resolvida else "aviso"

    if achou is False:
        print(f"[!] tarefa #{a.id} não existe")
        return 1
    if achou is None:
        print("[!] tarefa não atualizada (banco indisponível — veja o aviso acima)")
        return 0
    t = ler_tarefa(a.id)
    evento(None, "tarefa", status, agente="tech-lead", tarefa_id=a.id, mensagem=msg)
    print(_linha(t) if t else msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
