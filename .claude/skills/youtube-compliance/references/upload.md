# Step 9 — upload (09_upload.py)

`uv run py scripts/09_upload.py <stem> [--dry-run] [--bloco=N] [--max=N] [--teste]` — off-pipeline, US$ 0. **Sempre rode `--dry-run` antes.**

## O que faz

- Sobe os `finalizados/video_NN_*.mp4` como **privados com `publishAt`** (agendamento público, publica sozinho no horário). Preferência de arquivo: `_polido_legendado` > `_legendado` > `_polido` > original.
- Título/descrição/tags do `descricoes.txt` (edição manual no txt vale) e a thumb escolhida (manual > a > b > c; >2 MB vira JPEG).
- Slots de `config/upload.json` (padrão 1/dia às 18h, horário de Brasília), continuando depois do último longo agendado/publicado em **qualquer** vídeo: os `youtube.json` (API) **e** o que foi agendado à mão (`_cobertura.agenda_canal`, a mesma fonte do Curador).
- Não sobe bloco em `quarentena`, `descartado` ou `arquivado`, nem com `[COLAR URL DA LIVE AQUI]`.

## Idempotência

Registro à prova de falha em `outputs/<pasta>/youtube.json`; com ele e o `youtube_id` do banco, não re-sobe, e se só a thumb falhou, tenta só a thumb. Grava no banco `youtube_id` + `status=agendado` + `publish_at` e eventos com `agente="publicador"`.

## Cota

Upload ≈1600 + thumb 50 de 10.000/dia (zera à meia-noite do Pacífico), contada em `state/cota_youtube.json`. O script para **antes** de estourar.

## Trava da auditoria

Com `"auditoria_aprovada": false` o 09 **recusa** upload real (exit 1 e explica; o `--dry-run` mostra o plano marcado como TRAVADO).

Exceção — **upload de teste** (`--bloco=N --teste`, pra screencast/validação): sobe privado, sem data, com `[TESTE]` no título, registrado à parte em `outputs/<pasta>/youtube_teste.json`. **Não** conta como upload real (não grava `youtube_id`/status no banco nem ocupa slot), então o bloco continua liberado pro upload de verdade.

Quando a auditoria for aprovada, mude a flag pra `true` e o 09 passa a subir privado + `publishAt`. Login OAuth em `scripts/_google.py` (token por uso, escopo mínimo).

## Shorts (`--shorts`)

`uv run py scripts/09_upload.py <stem>|todos --shorts [--bloco=N] [--max=N] [--dry-run]` — mesma trava da auditoria (sem `--teste`).

- Sobe `shorts/short_NN_*.mp4` (do 10) privado + `publishAt` nos `shorts_horarios` do config (`["12:00", "20:00"]` = 2/dia). `todos` faz **um plano só** com todas as lives que têm `shorts/shorts.json`.
- Cada Short vai pro 1º horário livre (não ocupado por outro Short) **a partir da ida do longo ao ar**; só sobe se o longo do bloco já tem `youtube_id` (`youtube.json` ou banco, inclusive agendado à mão e marcado pelo 14).
- Não sobe: bloco em quarentena/descartado/arquivado, `revisar: true` no `shorts.json` (pouco rosto), sem crédito da fonte.
- Título = manchete do Short (`texto_thumb`, senão `tema`; até 60 chars, corta em palavra; regra única em `_descricoes.manchete`, a mesma que o 10 queima e o 14 casa exato; usar o tema gera aviso). Sem manchete, não sobe. Descrição do longo com `▶️ Vídeo completo: https://youtu.be/<longo>` no topo; sem thumb.
- Registro em `outputs/<pasta>/youtube_shorts.json` (com `longo_id` e `relacionado_ok`) + `youtube_id`/`postado` no `shorts.json` (tira do estoque e do `publicacao.txt`).
- **Vídeo relacionado** não existe na Data API: marcado à mão no Studio; a lista sai de `dia_d.py relacionados`.

## Simulação (`--como-aprovada`)

Só com `--dry-run`: mostra o plano como se a flag já fosse `true` (é o que o `dia_d.py checar` usa). Sem `--dry-run`, recusa.
