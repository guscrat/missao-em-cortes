# Git flow

- **`main`**: só o que está rodando "em produção" (o que publica no canal). Recebe merge de `release/*` ou `hotfix/*`, nunca commit direto.
- **`develop`**: integração. Toda feature nasce daqui e volta pra cá via PR.
- **`feature/<nome>`**: uma frente por branch (ex: `feature/painel-estado`, `feature/upload-api`, `feature/agente-revisor`).
- **`fix/<nome>`**: bug em `develop`. **`hotfix/<nome>`**: bug em `main`, sai de `main` e volta pra `main` + `develop`.
- **`docs/<nome>`**: só documentação.

## Commits

Conventional Commits em português — `feat(escopo):`, `fix(escopo):`, `chore:`, `docs:`, `refactor:`. Escopos usuais: `pipeline`, `estado`, `painel`, `upload`, `agentes`, `thumb`, `shorts`. Commits pequenos e atômicos.

## CI

`.github/workflows/ci.yml`: `uv sync --locked` + `uv run pytest -q` em todo PR e push pra `develop`/`main`. As duas branches são protegidas e exigem CI verde. Testes ficam em `tests/` (conftest com `outputs/` e banco falsos; tudo mockado — nunca baixar vídeo, rodar whisper/ffmpeg pesado ou chamar API paga em teste).

## Quebrou depois do merge?

Primeiro `git revert` (numa `fix/*`, via PR), depois investigar.

## Release pra main

Mandar pro Gu um resumo de produto (o que muda pro canal, risco, custo) em até 5 linhas, sem detalhe técnico, e **esperar o "ok"**.
