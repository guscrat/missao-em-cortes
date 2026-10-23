# Fluxo de desenvolvimento com agentes

## Duas pastas (o painel nunca cai)

- `missao-em-cortes/` (principal) fica **sempre na `develop`**. Aqui rodam o painel, o pipeline e os scripts reais, com `inputs/`, `outputs/` e `state/` reais. **Nunca trocar de branch aqui.** Trocar removia `painel/` do disco no meio do uso, e o Streamlit caía.
- `../missao-em-cortes-dev/` é o **worktree de dev**: toda `feature/*`/`fix/*`/`docs/*` é criada, editada, testada e commitada lá (`git -C ../missao-em-cortes-dev ...`, `uv run --directory ../missao-em-cortes-dev pytest -q`). Ele não tem `inputs/`/`outputs/`/`state/`. Os testes usam fixtures; execução com dados reais roda na principal depois do merge.
- Sessões em background podem usar um worktree isolado em `.claude/worktrees/<nome>` no lugar do de dev (mesmas regras).
- O Claude Code é **aberto na pasta principal**, e `tarefa.py` roda **sempre de lá**: é lá que fica o banco que o painel lê, e os hooks (`$CLAUDE_PROJECT_DIR`) gravam nele.
- Nova frente: `git fetch` + `git -C ../missao-em-cortes-dev switch -c feature/x origin/develop`. Se o worktree não existir, recrie com `git worktree add ../missao-em-cortes-dev -b feature/x develop` + `uv sync` lá dentro (o uv cria hardlinks do cache, então não ocupa disco extra).
- `gh pr merge --delete-branch` apaga a branch que o worktree de dev está usando: dê `git -C ../missao-em-cortes-dev switch --detach` antes do merge.
- Depois de cada merge em develop: `git pull --ff-only` na principal (+ `uv sync` se o `pyproject.toml` mudou). O painel recarrega uma vez, já com a versão nova.

## Passo a passo

1. **Implementar** numa `feature/*` (ou `fix/*`) saindo de `develop`. PRs pequenos e focados.
2. **Testar:** subagent `testador` (roda `uv run pytest -q` e escreve testes pro código novo/alterado, sempre com mock).
3. **Revisar:** subagent `revisor-codigo` (revisa `git diff develop...HEAD` contra as regras do projeto).
4. **Corrigir** se algum reprovar e chamar de novo, no **máximo 3 rodadas**. Se não resolver, parar e explicar o problema pro Gu em linguagem de produto.
5. **PR pra `develop`** só com os dois APROVADOS. Descrição: o que mudou (3-5 linhas), como foi testado, custo de API estimado da feature e "decisões pendentes para o Gu".
6. **Merge em `develop` é do tech lead:** testador + revisor APROVADOS + CI verde → `gh pr merge --squash --delete-branch` sem perguntar.
7. **Quebrou depois do merge?** `git revert` numa `fix/*` via PR, depois investigar.
8. **Release pra `main`:** resumo de produto em até 5 linhas e **esperar o "ok"** do Gu.

## Tarefas no painel (`scripts/tarefa.py`)

Toda tarefa macro do Gu vira uma linha em `tarefas`; mova a etapa a cada transição:

```
uv run py scripts/tarefa.py nova "Upload via API do YouTube" --branch feature/upload-api   # → #N, backlog
uv run py scripts/tarefa.py mover N fazendo --responsavel tech-lead
uv run py scripts/tarefa.py mover N testando --responsavel testador
uv run py scripts/tarefa.py resultado N APROVADO|REPROVADO --msg "..."                  # REPROVADO soma rodada
uv run py scripts/tarefa.py mover N revisando --responsavel revisor-codigo
uv run py scripts/tarefa.py mover N pronto                                             # depois do merge
uv run py scripts/tarefa.py lista
```

- Pergunta pro Gu = `tarefa.py decisao N "pergunta?"` (faixa amarela no painel), **além** de perguntar no chat; quando ele responder, `tarefa.py decisao N --resolvida`.
- A atividade dos subagents e o fim de cada turno do tech-lead entram sozinhos via hooks (`.claude/settings.json` → `scripts/hook_agente.py`, penduram na tarefa ativa).
- Gasto de API paga dentro de uma tarefa: rode o script com `MISSAO_TAREFA=N` pro custo cair nela.

## Status (toda sexta, ou quando o Gu pedir "status")

Resumo em linguagem de produto: o que foi entregue, o que quebrou e foi corrigido, custo de API da semana e próximas entregas. Fontes: `state/curador_resumo.md`, `12_metricas` (retenção com x sem legenda), custo por agente no painel.
