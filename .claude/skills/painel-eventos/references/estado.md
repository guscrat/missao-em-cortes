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

## Aba "Hoje" (tela inicial do PO)

- `painel/hoje.py`: no ar hoje/amanhã (`publish_at` dos blocos agendado/publicado), fila no YouTube, "canal coberto até DD/MM" (chama o próprio `13_curador.calcular_estoque`: dias até o último longo agendado + prontos; bate com o que o Curador vê às 17h), decisões pendentes (tarefas + quarentena), status da auditoria, custo do mês x orçamento e placar do canal.
- O painel fica dias no ar e o Streamlit só recarrega `painel/`: `hoje.scripts_frescos()` recarrega `_cobertura` → `_publicacao` → `13_curador` quando o arquivo muda no disco, e antes recarrega qualquer helper de `scripts/` já carregado que mudou (ex.: `_eventos` ganhou função nova). Módulo novo de `scripts/` que o painel chame entra em `MODULOS_SCRIPTS` (em ordem de dependência).
- **Faixa de alertas** acima das abas: Curador rodando agora (`state/curador_progresso.json`: "rodando desde HH:MM — etapa X", ou erro se o processo sumiu no meio), falha do Curador (evento `falha` sem `ok` depois na mesma live, na mesma etapa ou no script citado na mensagem, ex. `11_revisor.py falhou` some quando o 11 roda ok à mão; falha de step do pipeline também some com ok de um step igual ou posterior da mesma live; o `pipeline.py` grava `exit N: <última linha do stderr do step>`; Traceback no `state/curador.log` ou log parado depois das 18h), erro de download (`01_baixar` na mensagem da falha), token ausente/sem `refresh_token`/`invalid_grant`, cota (`state/cota_youtube.json` ≥ `cota_alerta_pct`), estoque abaixo do mínimo (modo sugerir: "escolha uma sugestão"), Curador processou sozinho pela rede de segurança (evento `curador_rede`, 24h), nada agendado pra amanhã e live travada por custo (`alertas_custo_live`: ≥ `trava_live_usd` ou o teto liberado em `state/orcamento_lives.json`; só lives com gasto nos últimos 7 dias).
- **Histórico de alertas** (expander logo abaixo da faixa, `historico_alertas`): falhas de 30 dias de todos os agentes (a faixa só mostra as do Curador e de token) com a situação (resolvida em DD/MM ou em aberto, `falhas_com_resolucao`) e lives que passaram de `alerta_live_usd` (`historico_custo_live`: cara / liberada até X / travada). Informativo, por isso fora da faixa: a faixa é só o que pede ação.
- Orçamento e limiar de cota em `config/painel.json` (`orcamento_mensal_usd`, padrão 10; `cota_alerta_pct`, padrão 80; `alerta_live_usd` 1 e `trava_live_usd` 2 por live — a trava é aplicada pelos scripts via `_custo.checar_orcamento`, destrava com `_custo.py liberar <stem> [--ate=X]`). O custo do mês soma `custo_usd` de todos os eventos desde o dia 1º, por agente.
- **Aba Analytics** (`painel/analytics.py`): a coleta mais recente do `17_analytics` (tabelas `metricas_video`, `trafego_video`, `termos_busca`, `termos_canal`; o resumo semanal lê também `trafego_canal` e `views_7d`; impressões/CTR somados de `reach_dia`, o relatório Reach diário; foto diária, acumulado desde a publicação; rodar 2x no dia substitui a foto do dia). Cartões de views/CTR/retenção dos longos, termos de pesquisa da semana, origens de tráfego e tabela por vídeo.
- **Placar do canal:** o Analista (`scripts/15_placar.py`, chamado pelo Curador 1x/dia) grava `state/placar.json` = `{"atualizado": ISO, "inscritos": int, "horas_12m": float, "views_shorts_90d": int}`. Sem o arquivo a seção mostra "—" (metas do YPP: 1.000 inscritos + 4.000 h ou 10 mi de views em Shorts).
- Alerta novo = função pura em `hoje.py` que devolve `[(nivel "erro"|"aviso", título, detalhe)]`, somada na chamada de `faixa_alertas` no `app.py`.

## Visual do painel (`painel/visual.py`)

- **Tema:** grafite (escuro) e creme (claro) em `.streamlit/config.toml` (`[theme.dark]`/`[theme.light]`, widgets nativos) + `visual.TOKENS` (variáveis CSS `--tx`, `--card`, `--acento-tx`... do HTML próprio). Mudou uma cor? Mude nos dois. Nada de cor fixa em `hoje.py`/`time_dev.py`/`app.py`: use `var(--...)`.
- **Seletor Escuro/Claro** na barra lateral: grava a escolha do Streamlit no `localStorage` (`stActiveTheme-<path>-v2`) e recarrega; é o mesmo que o menu ⋮ → Settings.
- **Métrica = cartão:** `visual.cartao(rótulo, valor, contexto, tom=""|"alerta"|"erro"|"ok", ajuda, medidor)` dentro de `visual.grade([...], grande=True)` (o que importa mais) ou `grade([...])` (o resto). Não use `st.metric`. Nos testes, a fixture `cartoes(at)` lê `{rótulo: (valor, contexto)}`.
- **Barras:** `visual.barras(serie, formato)` escreve o valor na ponta de cada barra (sem eixo X).
- **Sugestões do Curador** (aba Hoje, tabela `sugestoes`): a única ação do painel. O botão Processar não escreve no banco: dispara `13_curador.py --processar=<video_id>` (via `curador_oculto`, processo solto do painel, log `state/curador_pedidos.log`), e o 13 marca `pedida` e processa. Pedido parado sem Curador rodando mostra o botão "Disparar". Detalhes na skill `editorial-missao` (`references/curador.md`).
