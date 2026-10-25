---
name: painel-eventos
description: Camada de estado e painel do Missão em Cortes — banco SQLite state/pipeline.db (tabelas videos, blocos, eventos, tarefas), escrita via scripts/_eventos.py, status de bloco (auto x decisão), kanban, arquivamento de conteúdo antigo (sincronizar_estado.py), eventos e custo por agente, hooks dos subagents (hook_agente.py) e o painel Streamlit (painel/app.py, painel/time_dev.py). Use sempre que for criar um agente ou script novo (ele precisa registrar eventos e custo), chamar LLM em código, mudar/ler status de bloco, mexer no painel ou no kanban, entender por que algo sumiu do painel/estoque (arquivado?), ou fazer backfill do banco — mesmo que o pedido não cite o banco.
---

# Painel e eventos — Missão em Cortes

O painel (`uv run streamlit run painel/app.py`) **só lê** o banco `state/pipeline.db` (SQLite, WAL, gitignored). Tudo o que o Gu enxerga — kanban, custo por agente, timeline, time de dev — vem dos eventos e status que os scripts gravam. Script que não registra é invisível pro PO.

## Regras pra qualquer código novo

1. **Escrita é best-effort:** use `scripts/_eventos.py` (`evento()`, `upsert_video()`, `upsert_bloco()`). Falha de banco vira aviso no stderr, **nunca exceção** — o pipeline não pode cair por causa do painel.
2. Registre `inicio` / `ok` / `falha` com o próprio nome em `agente` ∈ `pipeline | curador | editor | revisor | publicador | analista`. É o que alimenta o "custo por agente".
3. Chamou LLM? Registre evento `llm` com `tokens_in`, `tokens_out`, `custo_usd`, e logue o custo estimado no terminal (transparência de custo é regra do projeto). Calcule com `scripts/_custo.py` (`uso(resp, modelo)`; tabela oficial de preços com escrita/leitura de prompt cache — modelo novo entra lá, conferido na página de preços) e passe `**_custo.cache(resp)` no evento: alimenta o "acerto do prompt cache" da aba Agentes e custo. Prefixo fixo e repetido em < 5 min (instruções, grafias) vai primeiro com `cache_control` no fim; só cacheia acima do mínimo do modelo (512 tokens no Opus/Sonnet/Haiku 5.5, 1024 no Sonnet 4.6).
4. Status de **decisão** só é setado por agente com `forcar_status=True`; o `sincronizar_estado.py` **nunca rebaixa** um status de decisão.

## Status de bloco

- **AUTO** (derivados dos arquivos): `segmentado` → `cortado` → `montado`.
- **DECISÃO**: `revisao`, `aprovado`, `quarentena`, `descartado`, `agendado`, `publicado`, `arquivado`.
- Kanban: `aprovado` → **Pronto para publicar**; `agendado` (no YouTube com `publish_at`) → **Agendado**. A métrica "Agendados" do topo conta só `agendado`.
- `arquivado` some do kanban e das métricas, o 09 não sobe e o 11 não revisa.

## Onde está o detalhe

- `references/estado.md` — arquivamento de conteúdo antigo, sincronização/backfill, tarefas e hooks do time de dev, aba "Hoje" (alertas, orçamento, contrato do `state/placar.json`).
- Comandos do `tarefa.py`: skill `release` (`references/fluxo-agentes.md`).
