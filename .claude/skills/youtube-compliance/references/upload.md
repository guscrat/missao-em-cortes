# Step 9 — upload (09_upload.py)

`uv run py scripts/09_upload.py <stem> [--dry-run] [--bloco=N] [--max=N] [--teste]` — off-pipeline, US$ 0. **Sempre rode `--dry-run` antes.**

## O que faz

- Sobe os `finalizados/video_NN_*.mp4` como **privados com `publishAt`** (agendamento público, publica sozinho no horário). Preferência de arquivo: `_polido_legendado` > `_legendado` > `_polido` > original.
- Título/descrição/tags do `descricoes.txt` (edição manual no txt vale) e a thumb escolhida (manual > a > b > c; >2 MB vira JPEG).
- Slots de `config/upload.json` (padrão 1/dia às 18h, horário de Brasília), continuando depois do último agendado em **qualquer** vídeo.
- Não sobe bloco em `quarentena`, `descartado` ou `arquivado`, nem com `[COLAR URL DA LIVE AQUI]`.

## Idempotência

Registro à prova de falha em `outputs/<pasta>/youtube.json`; com ele e o `youtube_id` do banco, não re-sobe, e se só a thumb falhou, tenta só a thumb. Grava no banco `youtube_id` + `status=agendado` + `publish_at` e eventos com `agente="publicador"`.

## Cota

Upload ≈1600 + thumb 50 de 10.000/dia (zera à meia-noite do Pacífico), contada em `state/cota_youtube.json`. O script para **antes** de estourar.

## Trava da auditoria

Com `"auditoria_aprovada": false` o 09 **recusa** upload real (exit 1 e explica; o `--dry-run` mostra o plano marcado como TRAVADO).

Exceção — **upload de teste** (`--bloco=N --teste`, pra screencast/validação): sobe privado, sem data, com `[TESTE]` no título, registrado à parte em `outputs/<pasta>/youtube_teste.json`. **Não** conta como upload real (não grava `youtube_id`/status no banco nem ocupa slot), então o bloco continua liberado pro upload de verdade.

Quando a auditoria for aprovada, mude a flag pra `true` e o 09 passa a subir privado + `publishAt`. Login OAuth em `scripts/_google.py` (token por uso, escopo mínimo).
