# Camada de estado (Out/2026)

## Banco

- `state/pipeline.db` (SQLite, WAL): tabelas `videos`, `blocos`, `eventos` e `tarefas`.
- Escrita via `scripts/_eventos.py` (`evento()`, `upsert_video()`, `upsert_bloco()`); toda escrita é **best-effort** — falha de banco vira aviso no stderr, nunca exceção.
- Eventos: todo step/agente registra `inicio`/`ok`/`falha` (+ `llm` com tokens e custo). Campo `agente` ∈ `pipeline | curador | editor | revisor | publicador | analista`.
- Regra pra agentes novos: registrar evento com o próprio nome em `agente` e, se chamar LLM, `tokens_in`/`tokens_out`/`custo_usd`.

## Sincronização e backfill

`scripts/sincronizar_estado.py` (botão **Sincronizar** do painel) reconcilia o banco a partir de `outputs/` — idempotente, nunca rebaixa status de decisão.

## Arquivado = conteúdo antigo

- O `sincronizar_estado.py` arquiva sozinho os blocos de live com **mais de 15 dias** (data da pasta `outputs/<AAAA-MM-DD>_<stem>/`) que ainda não foram pro YouTube, com motivo "conteúdo antigo". Agendado, publicado e descartado não são tocados.
- Os Shorts não postados da live velha ganham `"arquivado": "conteúdo antigo"` no `shorts/shorts.json` (saem do estoque; o `10_shorts` preserva a marca ao regerar).
- Arquivado some do kanban e das métricas, o 09 não sobe e o 11 não revisa.
- Pra resgatar um bloco, mude o status à mão no banco — mas a próxima sincronização arquiva de novo se a live continuar velha.

## Time de dev no painel

- `painel/time_dev.py` (aba "Time de dev"): status dos agentes, tarefas, decisões pro Gu.
- Tarefas via `scripts/tarefa.py` (nova/mover/resultado/decisao/lista), rodando **da pasta principal**.
- Hooks em `.claude/settings.json` (SubagentStart/SubagentStop/Stop) → `scripts/hook_agente.py`: atividade dos subagents (`testador`, `revisor-codigo`) e fim de turno do tech-lead entram no banco, pendurados na tarefa ativa.
- `MISSAO_TAREFA=N` no ambiente faz o custo de API de um script cair na tarefa N (e a quarentena do revisor vira faixa amarela nela).
