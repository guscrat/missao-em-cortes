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
- **Fila pelo mais recente (06/11/2026)**: a fila é ordenada por **data da live** (pasta) mais nova e depois **score** (`prioridade_short`), não por ordem de chegada. Os horários são percorridos em ordem e cada um vai pro Short de maior prioridade que já pode sair (`slots_shorts`): Short novo passa na frente, o antigo pega o horário que o novo ainda não pode usar e continua na fila enquanto não ficar datado (checagem de atualidade). `--max` pega os N de maior prioridade. `--dry-run --atualidade` mostra a checagem (paga) sem arquivar.
- **Ritmo até o último longo (10/11/2026, ideia do Gu)**: na rodada da fila inteira (`todos --shorts` sem `--bloco`/`--max`, a das 17h50 e a do fim do Processar), com `"shorts_replanejar": true`, os Shorts **já agendados pela API que ainda não foram ao ar** (depois da antecedência de 2h) entram no plano junto com os novos. Shorts/dia = `ceil(total ÷ dias até o último longo agendado)` (`ritmo_shorts`), entre o mínimo (`shorts_horarios`, 2) e a maior grade de `shorts_grades` (`{"3": 12/16/20h, "4": 10/13/16/20h}`). Assim o estoque de Shorts acaba junto com o de longos, e o Short novo (prioridade) fica com as 20h do dia do longo dele. Quem mudou de horário é **reagendado** (`videos.update` só do `status`: privado + `publishAt`, 50 unidades, `cota_update`), antes dos uploads; o novo horário vai pro `youtube_shorts.json` e pro `postado` do `shorts.json` + evento "Short reagendado". Reagendar que falha deixa o Short onde estava e o novo que ia pegar aquele horário espera a próxima rodada. O `--dry-run` mostra "Ritmo" e a lista `reagendar DD/MM HH:MM → DD/MM HH:MM`. Reagendado pra mais tarde não repassa pela checagem de atualidade (na prática eles adiantam). Shorts agendados à mão no Studio (sem `youtube_shorts.json`) não se mexem.
- Cada Short só sai num horário livre (não ocupado por outro Short) **a partir da ida do longo ao ar**; só sobe se o longo do bloco já tem `youtube_id` (`youtube.json` ou banco, inclusive agendado à mão e marcado pelo 14).
- **Atualidade (06/11/2026)**: no envio real, antes de subir, cada Short passa por `_atualidade.checar_short` na data do horário dele (~US$ 0,002, Sonnet 5.5); datado → `"arquivado": true` + motivo no `shorts.json` e sai do plano; checagem que falha → não sobe nesta rodada. O `--dry-run` não paga. Regra na skill `editorial-missao`.
- Não sobe: bloco em quarentena/descartado/arquivado, `revisar: true` no `shorts.json` (pouco rosto ou sem ponto natural; o motivo vem em `motivo_revisar`), trecho do Short que começa ou termina no meio da frase (revisor de fronteira, $0, `fronteira_short`), `"arquivado": true` + `"motivo"` no `shorts.json` (Short datado: arquiva só o Short, o bloco do longo publicado fica como está), sem crédito da fonte.
- Título = "MANCHETE | quem fala" (`_descricoes.titulo_short`, até 60 chars, corta a manchete e nunca o nome). Manchete (`_descricoes.manchete`) = `texto_thumb`, senão `tema` (com aviso), com grafias oficiais também em CAIXA ALTA; é o que o 10 queima. Quem fala = `speakers_principais` casado nas grafias, senão o dono do canal. Sem manchete ou sem quem fala, não sobe. O 14 casa exato. Descrição do longo com `▶️ Vídeo completo: https://youtu.be/<longo>` no topo; sem thumb.
- Registro em `outputs/<pasta>/youtube_shorts.json` (com `longo_id`) + `youtube_id`/`postado` no `shorts.json` (tira do estoque e do `publicacao.txt`).
- O Short leva pro longo pelo link "Vídeo completo" no topo da descrição. O campo "vídeo relacionado" não existe na Data API nem aparece no Studio do canal: o Gu dispensou (10/11/2026).
- **Rodada diária no Agendador (07/11/2026)**: a tarefa `MissaoEmCortes-Shorts` roda todo dia às **17:50** (depois do Curador; `-StartWhenAvailable`) o `scripts/shorts_oculto.py` sem janela, que chama `09_upload.py todos --shorts` e loga em `state/shorts.log`. Sobe o que couber na cota (~6/dia), com a checagem de atualidade, e para sozinha quando a fila zera (rodada sem nada não gasta). Toda rodada real da fila inteira (sem `--bloco`/`--max`/`--dry-run`, à mão ou pela tarefa) grava `state/shorts_fila.json` (`enviados`, `falhas`, `faltam` = prontos que não subiram) + evento `09_shorts_rodada` (`falha` se algum upload falhou). Se o 09 quebrar antes disso (token, rede), o `shorts_oculto` registra a falha com a última linha do log. Painel: cartão **Shorts na fila** (aba Hoje) + alertas "Upload de Shorts falhou" (some na próxima rodada ok) e "Upload de Shorts parado" (fila > 0 e nenhuma rodada há 26h). Registrar, no PowerShell, apontando pra **pasta principal**:

```powershell
$raiz = "C:\Users\gusta\Downloads\projetos\missao-em-cortes"
$a = New-ScheduledTaskAction -Execute "$raiz\.venv\Scripts\pythonw.exe" -Argument "scripts\shorts_oculto.py" -WorkingDirectory $raiz
$t = New-ScheduledTaskTrigger -Daily -At 17:50
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MissaoEmCortes-Shorts" -Action $a -Trigger $t -Settings $s -Description "Missão em Cortes: sobe a fila de Shorts (09_upload todos --shorts, sem janela)"
```

Conferir: `Get-ScheduledTask -TaskName "MissaoEmCortes-Shorts" | Get-ScheduledTaskInfo`. Rodar agora: `Start-ScheduledTask -TaskName "MissaoEmCortes-Shorts"`. Pausar: `Disable-ScheduledTask -TaskName "MissaoEmCortes-Shorts"`.

## Simulação (`--como-aprovada`)

Só com `--dry-run`: mostra o plano como se a flag já fosse `true` (é o que o `dia_d.py checar` usa). Sem `--dry-run`, recusa.

## Screencast da auditoria (`--demo`)

`09_upload.py --demo=<etapa> [--lang=en]` (código em `scripts/_demo_auditoria.py`), encadeado com pausas e narração em inglês por `scripts/demo_auditoria.ps1` (`-Preparar` antes de gravar: só corta o clipe, local). Etapas: preparar · plano · login (revoga o token do publisher pra tela de consentimento aparecer) · upload (privado, `[TEST]`, `--agendar` manda `publishAt`) · thumb · update · status. Não toca no banco de blocos nem nos `youtube*.json`; registro em `state/demo_auditoria/demo.json`. O escopo `youtube.upload` cobre `videos.insert` e `thumbnails.set`, **não** `videos.update` nem `videos.list`: a etapa update se pula sozinha e explica (o demo foi gravado só com upload; desde 10/11/2026 o publisher também tem `youtube.force-ssl` pro reagendar). Roteiro: `docs/auditoria/screencast_script.md`.
