# Step 13 — agente Curador

`uv run py scripts/13_curador.py [--dry-run] [--sem-pipeline] [--forcar]`

`agente="curador"`, off-pipeline, roda **1x por dia às 17h**. **Verifica** os canais de `config/canais.json` (abas streams + videos) todo dia, mas só **processa** quando falta estoque.

## Modo sugerir (padrão desde 29/10/2026, decisão do Gu)

`config/canais.json` → `"curador_modo": "sugerir" | "automatico"` (`_paths.curador_modo()`; ausente ou outro valor = `sugerir`, o que não gasta sem o Gu).

- **sugerir:** a rodada das 17h lê, avalia e prioriza como sempre, mas **não baixa nem processa**. O que vale vira sugestão no banco (tabela `sugestoes`: título, canal, duração, prioridade, motivo, link; status `sugerida → pedida → processando → processada | falhou`, `expirada` com a fila). O Gu escolhe no painel (aba Hoje → **Sugestões do Curador** → **Processar**), que dispara `13_curador.py --processar=<video_id>` pelo `curador_oculto` (sem janela, log em `state/curador_pedidos.log`). Esse processo pega a mesma trava (`state/curador.lock`), espera outro processamento terminar (`esperar_livre`), checa o orçamento da live e processa os pedidos na ordem do clique, um por vez. Trava ocupada (rodada das 17h no meio) → sai com 75 e a rodada processa os pedidos antes de terminar. O resumo do dia lista as sugestões em aberto.
- **Estoque baixo** (cobertura < `dias_minimos`): só alerta, no painel e no resumo ("estoque baixo, escolha uma sugestão"). Não processa sozinho.
- **Rede de segurança:** se na rodada não houver nenhum longo pronto pra publicar (`aprovado`) nem agendado pra amanhã (`_cobertura.longos_no_dia`), o Curador processa sozinho a sugestão de maior prioridade (mesma trava e orçamento) e grava o evento `curador_rede` → alerta "Curador processou sozinho: processei X porque o canal ficaria sem vídeo amanhã" no painel (24h) e no resumo. Com pedido do Gu pendente, a rede não dispara (o pedido cobre).
- **Modo evento** no sugerir só prioriza o tema; não processa sozinho.
- **Link direto** continua valendo (`01_baixar` + `pipeline.py` à mão): sugestão cujo vídeo já virou stem sai da fila (`processado por link direto`).
- `--forcar` processa 1 da fila nos dois modos. **automatico:** o fluxo abaixo, como antes.

## 1. Achar vídeos novos

Só os dos últimos `dias` (padrão 3) que nunca foram vistos. "Visto" = id em `inputs/*.url`, no banco ou já avaliado em `state/curadoria.json`. Antes de gastar, filtro grátis: duração entre `duracao_min` e `duracao_max` (20-240 min) e nada de live em andamento/agendada (volta no dia seguinte).

## 2. Avaliar

Os novos vão numa **única** chamada pro Claude (`claude-opus-5-5`, effort low, ~US$ 0,02-0,05/rodada), que decide `vale`, `prioridade` (1-10) e `motivo` (a frase que aparece no painel). O que vale entra na **fila**. Os recusados nunca são reavaliados.

## 2b. Já cortado pelos canais de corte grandes? (31/10/2026)

O espaço do canal está no que os canais de corte grandes do ecossistema **não** cortam: convidados menores, entrevistas em outros canais, podcasts. Duas peças:

- **Prompt do Claude** (`SISTEMA`): entrevista, podcast, participação em outro canal ou convidado menos conhecido tem prioridade maior que a live principal do mesmo dia.
- **Checagem no código** ($0, `cortes_publicados` + `marcar_cortados`): `config/canais.json` → `canais_corte` (`[{nome, url}]`, os canais de corte grandes) e `cortes_por_canal` (padrão 30). A cada rodada, depois da avaliação, o Curador lista os `cortes_por_canal` vídeos mais recentes de cada um **com o yt-dlp** (aba videos, flat) e lê a descrição de cada corte novo (1 vez só, cache em `state/cortes_terceiros.json`) atrás de links de vídeo do YouTube. Live da fila citada na descrição de um corte = já cortada.
  - **Nunca pela API do YouTube**: os projetos Google (publisher e analytics) declaram que não acessam dados de outros canais (skill `youtube-compliance`). Só yt-dlp, como a leitura dos canais monitorados.
  - Já cortada → `cortado_por` = "Canal X (2), Canal Y (1)" (no `curadoria.json`, na sugestão do banco e no painel: "já cortado por …"; conferido e ninguém cortou = "ninguém cortou ainda") e a prioridade cai `PENALIDADE_CORTADO` (3, mín. 1) a partir da do Claude (`prioridade_llm`). Refeito pra **fila inteira** a cada rodada (o corte costuma sair 1-2 dias depois da live); se o corte some da listagem, a prioridade volta.
  - Limite: só pega corte que credita a live com link na descrição. Corte sem link passa como "ninguém cortou".
  - `canais_corte` vazio = não confere (o painel não mostra nada). Falha na checagem vira aviso no resumo; a fila segue com a prioridade de antes.
- **Entrevistas em outros canais** só entram se o canal estiver em `canais` (as fontes monitoradas). Fonte nova = acrescentar lá (com `prefixo` e `zoom`).

## 3. Estoque

Estoque = **dias de canal coberto** (decisão do Gu, 22/10/2026):

dias = (último longo agendado no canal − hoje) + longos prontos ÷ `longos_por_dia` → "canal coberto até DD/MM".

- **Fonte única: `scripts/_cobertura.py`** (`agenda_canal()` + `cobertura()`), usada pelo Curador, pelo `_publicacao` e pelo painel ("Canal coberto até" e "Fila no YouTube"). Se dois deles discordarem, o bug está lá.
- Último longo agendado = `agenda_canal()["ultimo"]`: o maior entre `state/canal.json` (`ultimo_longo`, do 14_canal) e o `publish_at` dos blocos agendado/publicado no banco. Já passou (ou nada agendado) = 0.
- Longo pronto = bloco `aprovado` (coluna "Pronto para publicar") de live dos últimos 15 dias (`DIAS_ARQUIVAR`).
- **Shorts não entram nos dias** (com ou sem auditoria): só aparecem no resumo, "à parte".
- Mínimo em `config/canais.json` → `estoque.dias_minimos` (padrão 2). O painel (aba Hoje) chama a mesma função e mostra "Canal coberto até DD/MM", com alerta abaixo do mínimo.

## 4. Processar

Só se a cobertura estiver **abaixo do mínimo** (ou com `--forcar`). Processa **1 vídeo**, o de maior prioridade da fila (empate: o mais recente):

`01_baixar` → `pipeline.py --polir` (o 07 dentro dele faz as 3 clássicas do "Testar e comparar" no modo `ab`, ~US$ 0,01/bloco) → `11_revisor` → `10_shorts` (só dos aprovados, $0) → `publicacao.txt`. A colagem (07b) está **pausada** desde 26/10/2026 (`config/thumb.json` → `"colagem": "pausada"`): o Curador não chama.

Custa ~US$ 0,65 por vídeo. O resto continua na fila; item com mais de 15 dias vira `expirado`.

## Modo evento (ex.: 2º turno)

`config/canais.json` → `modo_evento: true` + `modo_evento_desde` / `modo_evento_ate` (inclusive) + `modo_evento_tema`. Lido por `_paths.modo_evento()`; depois do `ate` **desliga sozinho** (a flag pode continuar `true` no arquivo). Enquanto ligado:

- O Claude recebe o tema no pedido: prioridade 9-10 pro tema (ex.: reação ao resultado), previsão de antes do resultado com prioridade baixa.
- Toda rodada processa **1 vídeo da fila com data ≥ `desde` e prioridade ≥ 6** (`PRIORIDADE_EVENTO`), mesmo com o canal coberto. Sem vídeo do evento na fila, vale a regra normal do estoque (fila antiga só com cobertura abaixo do mínimo).
- O `publicacao.txt` ignora o último agendado: datas a partir de hoje (antes das 16h) ou amanhã, **na frente** dos agendados, com aviso pra empurrar no Studio o longo do mesmo dia. Não mexe em bloco agendado nenhum.
- O resumo do Curador mostra "Modo evento até DD/MM".

## Detalhes

- **O que já subiu sai do estoque sozinho:** no começo de cada rodada, o Curador roda o `14_canal` (skill `youtube-compliance`), que marca o que o Gu publicou/agendou no Studio. Se a leitura falhar (sem login, sem rede), a rodada segue com o estoque como estava e o resumo avisa.
- **Zoom:** o `zoom` do canal é copiado pro `config/zoom.json` do stem novo. Canal com `zoom: null` (Kim) é processado sem zoom e o resumo avisa pra calibrar e re-cortar com `--desde=4`. Estúdio diferente do padrão do canal também pede conferência.
- **Falha:** erro num vídeo não derruba a rodada. Se nem baixou, volta pra fila (no máximo 3 tentativas → `falhou`). Se falhou depois do download, fica `escolhido` e o resumo mostra o erro. Retomar com `pipeline.py <stem> --desde=N`.
- **Saída:** `state/curador_resumo.md` (estoque início/fim, prontos com o caminho do `publicacao.txt`, falhas, escolhido, fila, recusados com motivo, avisos; às sextas, os termos de pesquisa da semana) e eventos no painel. Todo dia, depois do placar (15), roda a coleta do Analytics por vídeo (`17_analytics`); às sextas grava também `state/analytics_semanal.md`. A coleta marca os **vídeos antigos em alta** (publicados há 30+ dias, ≥ 50 views na semana e ≥ 3x a média semanal de antes; tabela `em_alta`, com `blocos.tema`): os temas (até 5) vão no pedido ao Claude — live nova sobre um deles ganha +2 de prioridade e o motivo cita o tema — e aparecem no resumo do dia. A fila já avaliada não é reavaliada. O resumo semanal de sexta lê esse arquivo. Log do agendamento em `state/curador.log`.
- **Trava:** `state/curador.lock` (criação atômica) impede duas rodadas ao mesmo tempo; trava com mais de 12h é considerada morta e liberada.

## Agendamento (Agendador de Tarefas do Windows)

Todo dia às 17:00; se o PC estiver desligado, roda assim que ligar (`-StartWhenAvailable`). Roda **sem janela**: o Agendador chama o `pythonw.exe` da venv com `scripts/curador_oculto.py`, que dispara o `uv run py scripts/13_curador.py` com console invisível (ffmpeg/yt-dlp herdam, nada pisca) e joga a saída no `state/curador.log`. Registrar uma vez, no PowerShell, apontando pra **pasta principal**:

```powershell
$raiz = "C:\Users\gusta\Downloads\projetos\missao-em-cortes"
$a = New-ScheduledTaskAction -Execute "$raiz\.venv\Scripts\pythonw.exe" -Argument "scripts\curador_oculto.py" -WorkingDirectory $raiz
$t = New-ScheduledTaskTrigger -Daily -At 17:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Action $a -Trigger $t -Settings $s -Description "Missão em Cortes: agente Curador (13_curador.py, sem janela)"
```

Tarefa já registrada com o `cmd.exe` antigo (janela preta): `Set-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Action $a`.

**Progresso no painel:** o 13 grava `state/curador_progresso.json` (`rodando`, `pid`, `desde`, `etapa`, `stem`, `atualizado`) a cada etapa, e a faixa do painel mostra "Curador rodando desde 17:00 — etapa X" (na etapa `pipeline`, junta o step do pipeline daquele vídeo). Falhas viram alerta: rodada que quebrou (evento `curador_rodada` `falha`, gravado pelo 13 ou pelo `curador_oculto` quando o processo morre ou nem começa) e progresso "rodando" com o processo sumido (PC desligou no meio). Trava ocupada sai com código 75 e não conta como falha.

**Nunca dois processamentos ao mesmo tempo:** além do `state/curador.lock` (Curador x Curador), antes de baixar o vídeo escolhido o 13 procura na lista de processos qualquer script pesado rodando (`PESADOS_RE`: 01-08, `10_shorts`, `11_revisor`, `pipeline.py`; vale pipeline manual ou de outra sessão). Achou: espera até `ESPERA_OCUPADO_MIN` (30 min, checando a cada 60s, etapa "esperando outro processamento terminar" no painel). Continuou ocupado: pula o processamento (a avaliação dos novos já rodou), o vídeo fica na fila sem gastar tentativa, evento `curador_pulado` `aviso` → alerta "Curador pulou o processamento" no painel (some quando sai um `curador_pipeline` depois) e aviso no resumo. Se não der pra listar os processos, segue sem checar (só avisa no log). Pra adiar uma rodada avulsa já agendada: `Disable-ScheduledTask -TaskName "<nome>"`.

Conferir: `Get-ScheduledTask -TaskName "MissaoEmCortes-Curador" | Get-ScheduledTaskInfo`. Rodar agora: `Start-ScheduledTask -TaskName "MissaoEmCortes-Curador"`. Remover: `Unregister-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Confirm:$false`.
