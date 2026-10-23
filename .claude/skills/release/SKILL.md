---
name: release
description: Fluxo de desenvolvimento e entrega do Missão em Cortes — git flow (main/develop/feature/fix/hotfix), as duas pastas (principal sempre na develop x worktree de dev), commits Conventional em pt-BR, subagents testador e revisor-codigo, PR pra develop, merge pelo tech lead, release pra main com ok do Gu, CI e status de sexta. Use sempre que for começar uma tarefa de código nova, criar branch, commitar, abrir/mergear PR, fazer release ou hotfix, mexer no CI, atualizar a pasta principal depois de merge, ou mandar o "status" semanal — mesmo que o pedido seja só "implementa X" (todo código passa por esse fluxo).
---

# Release — fluxo de dev do Missão em Cortes

**Papéis:** o Gu é o **PO** (tarefas macro; não revisa código nem aprova PR). O Claude Code é o **tech lead**: planeja, implementa, testa, revisa e mergeia em `develop`.

## Regras que não podem falhar

1. **Pasta principal (`missao-em-cortes/`) fica sempre na `develop`.** Nunca trocar de branch lá: isso remove `painel/` do disco e derruba o Streamlit. Código novo é feito no worktree de dev (`../missao-em-cortes-dev/`) ou num worktree isolado em `.claude/worktrees/`.
2. Nunca commitar em `main`/`develop` direto; nunca force push. Uma frente por `feature/<nome>` / `fix/<nome>` saindo de `origin/develop`.
3. PR pra `develop` só com **testador APROVADO + revisor-codigo APROVADO**. Com CI verde, o tech lead mergeia (`gh pr merge --squash --delete-branch`) sem perguntar.
4. **Release pra `main`** só com "ok" do Gu, depois de um resumo de produto (o que muda no canal, risco, custo) em até 5 linhas.
5. Depois de cada merge: `git pull --ff-only` na pasta principal (+ `uv sync` se o `pyproject.toml` mudou). Se estiver num worktree isolado, sair dele antes.
6. `tarefa.py` roda **sempre da pasta principal** (é lá que está o banco do painel).

## Ciclo de uma tarefa

```
tarefa.py nova "..." --branch feature/x       → backlog
tarefa.py mover N fazendo --responsavel tech-lead
implementar + commits pequenos
tarefa.py mover N testando --responsavel testador     → subagent testador
tarefa.py mover N revisando --responsavel revisor-codigo → subagent revisor-codigo
(reprovou? corrigir e repetir, máx. 3 rodadas; não resolveu → explicar pro Gu em linguagem de produto)
PR pra develop → CI verde → merge → pull na principal
tarefa.py mover N pronto  (+ resultado)
```

Ao terminar qualquer trabalho, mova os cards relacionados pra **pronto** com resultado.

## Sempre perguntar antes de

Publicar no YouTube pela primeira vez numa feature nova · gastar API paga fora de teste · ação destrutiva (apagar arquivo/branch, force push, reset) · mudar segredo/credencial. Pergunta pro Gu = `tarefa.py decisao N "pergunta?"` **e** no chat.

## Onde está o detalhe

- `references/git-flow.md` — branches, commits, CI, hotfix, revert.
- `references/fluxo-agentes.md` — duas pastas, worktree de dev, comandos do `tarefa.py`, descrição do PR, status de sexta.
