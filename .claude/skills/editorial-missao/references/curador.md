# Step 13 — agente Curador

`uv run py scripts/13_curador.py [--dry-run] [--sem-pipeline] [--forcar]`

`agente="curador"`, off-pipeline, roda **1x por dia às 17h**. **Verifica** os canais de `config/canais.json` (abas streams + videos) todo dia, mas só **processa** quando falta estoque.

## 1. Achar vídeos novos

Só os dos últimos `dias` (padrão 3) que nunca foram vistos. "Visto" = id em `inputs/*.url`, no banco ou já avaliado em `state/curadoria.json`. Antes de gastar, filtro grátis: duração entre `duracao_min` e `duracao_max` (20-240 min) e nada de live em andamento/agendada (volta no dia seguinte).

## 2. Avaliar

Os novos vão numa **única** chamada pro Claude (`claude-opus-5-5`, effort low, ~US$ 0,02-0,05/rodada), que decide `vale`, `prioridade` (1-10) e `motivo` (a frase que aparece no painel). O que vale entra na **fila**. Os recusados nunca são reavaliados.

## 3. Estoque

Estoque = **dias de canal coberto** (decisão do Gu, 22/10/2026):

dias = (último longo agendado no canal − hoje) + longos prontos ÷ `longos_por_dia` → "canal coberto até DD/MM".

- Último longo agendado = `_publicacao.ultimo_agendado()`: o maior entre `state/canal.json` (`ultimo_longo`, do 14_canal) e o `publish_at` dos blocos agendado/publicado no banco. Já passou (ou nada agendado) = 0.
- Longo pronto = bloco `aprovado` (coluna "Pronto para publicar") de live dos últimos 15 dias (`DIAS_ARQUIVAR`).
- **Shorts não entram nos dias** (com ou sem auditoria): só aparecem no resumo, "à parte".
- Mínimo em `config/canais.json` → `estoque.dias_minimos` (padrão 2). O painel (aba Hoje) chama a mesma função e mostra "Canal coberto até DD/MM", com alerta abaixo do mínimo.

## 4. Processar

Só se a cobertura estiver **abaixo do mínimo** (ou com `--forcar`). Processa **1 vídeo**, o de maior prioridade da fila (empate: o mais recente):

`01_baixar` → `pipeline.py --polir` → `11_revisor` → `10_shorts` (só dos aprovados, $0) → `publicacao.txt` → `07b_colagem` (modo `teste`, ~US$ 0,15, em `thumbs/colagem/`; no modo `padrao` roda com `--aplicar` **antes** do revisor).

Custa ~US$ 0,65 por vídeo (+0,15 da colagem). O resto continua na fila; item com mais de 15 dias vira `expirado`.

## Detalhes

- **O que já subiu sai do estoque sozinho:** no começo de cada rodada, o Curador roda o `14_canal` (skill `youtube-compliance`), que marca o que o Gu publicou/agendou no Studio. Se a leitura falhar (sem login, sem rede), a rodada segue com o estoque como estava e o resumo avisa.
- **Zoom:** o `zoom` do canal é copiado pro `config/zoom.json` do stem novo. Canal com `zoom: null` (Kim) é processado sem zoom e o resumo avisa pra calibrar e re-cortar com `--desde=4`. Estúdio diferente do padrão do canal também pede conferência.
- **Falha:** erro num vídeo não derruba a rodada. Se nem baixou, volta pra fila (no máximo 3 tentativas → `falhou`). Se falhou depois do download, fica `escolhido` e o resumo mostra o erro. Retomar com `pipeline.py <stem> --desde=N`.
- **Saída:** `state/curador_resumo.md` (estoque início/fim, prontos com o caminho do `publicacao.txt`, falhas, escolhido, fila, recusados com motivo, avisos) e eventos no painel. O resumo semanal de sexta lê esse arquivo. Log do agendamento em `state/curador.log`.
- **Trava:** `state/curador.lock` (criação atômica) impede duas rodadas ao mesmo tempo; trava com mais de 12h é considerada morta e liberada.

## Agendamento (Agendador de Tarefas do Windows)

Todo dia às 17:00; se o PC estiver desligado, roda assim que ligar (`-StartWhenAvailable`). Registrar uma vez, no PowerShell, apontando pra **pasta principal**:

```powershell
$a = New-ScheduledTaskAction -Execute "cmd.exe" -Argument '/c cd /d "C:\Users\gusta\Downloads\projetos\missao-em-cortes" && "C:\Users\gusta\.local\bin\uv.exe" run py scripts\13_curador.py >> state\curador.log 2>&1'
$t = New-ScheduledTaskTrigger -Daily -At 17:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Action $a -Trigger $t -Settings $s -Description "Missão em Cortes: agente Curador (13_curador.py)"
```

Conferir: `Get-ScheduledTask -TaskName "MissaoEmCortes-Curador" | Get-ScheduledTaskInfo`. Rodar agora: `Start-ScheduledTask -TaskName "MissaoEmCortes-Curador"`. Remover: `Unregister-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Confirm:$false`.
