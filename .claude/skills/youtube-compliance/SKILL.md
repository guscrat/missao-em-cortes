---
name: youtube-compliance
description: Regras do YouTube e da Google API pro canal Missão em Cortes — monetização (YPP / reused content), crédito obrigatório da fonte, trava da auditoria da API (auditoria_aprovada em config/upload.json), os dois projetos OAuth separados (publisher x analytics), cota, e os scripts que falam com o YouTube — upload (09_upload.py), métricas de retenção (12_metricas.py), leitura do nosso canal (14_canal.py, _youtube_leitura.py, _google.py) e a lista de publicação manual (_publicacao.py / publicacao.txt). Use sempre que o pedido tocar em subir vídeo, agendar, publishAt, Shorts no YouTube, token/login/OAuth, 403, cota, escopos, analytics, "o que já foi publicado", link do canal, ou em qualquer dúvida do tipo "isso pode dar strike/desmonetizar?".
---

# YouTube compliance — Missão em Cortes

## Canal

- **Nosso canal:** https://www.youtube.com/channel/UCRJDgbBEndOdbNaiwzFju2g (handle `@missaoemcortes-14`). O handle `@missaoemcortes` **NÃO é nosso** — nunca usar. ID/URL em `scripts/_canal.py`, e ele só aparece na linha "Inscreva-se", **nunca como fonte**.
- Na dúvida sobre qualquer link de conta do Gu, pergunte em vez de chutar.

## Monetização (YPP)

O YouTube pune *reused content* desde Jul/2025. O que nos mantém elegíveis é o **valor agregado** de cada vídeo: cold open, intro, card de contexto, corte focado, legenda karaokê, outro, thumb própria. Não remova essas camadas pra "economizar" sem falar com o Gu.

## Crédito da fonte (obrigatório)

- Logo MBL/Valete preservado no corte; overlays desatualizados saem por zoom (sem blur).
- URL da live original na descrição (vem de `inputs/<stem>.url`). Bloco com `[COLAR URL DA LIVE AQUI]` **não sobe**; `.url` apontando pro nosso canal → o 09 se recusa.
- Foto de terceiro na thumb: só licença aberta e crédito na descrição (skill `thumb-colagem`).

## Upload liberado (06/11/2026) — ex-trava da auditoria

**O YouTube encerrou a revisão em 06/11/2026** sem auditoria: segundo eles, vídeo enviado pela API **não fica privado automaticamente** e a cota padrão (10 mil/dia) basta, sem pedir extra. Por isso `"auditoria_aprovada": true` em `config/upload.json` — o nome ficou por compatibilidade; leia como **"upload liberado"**. A liberação seguiu o runbook do dia D (`references/dia-d.md`) com um ajuste do Gu: o teste foi **1 longo + 1 Short** reais agendados públicos, e Shorts (12h/20h) e agendamento automático dos longos só depois do ok dele no YouTube. Se um vídeo da API aparecer travado como privado, é o Rollback do runbook.

Histórico (até 06/11/2026): vídeo enviado por projeto de API **não auditado** fica **bloqueado como privado** no YouTube: não dá pra publicar nem recorrer, só reenviando (queima o vídeo). Por isso `"auditoria_aprovada": false` em `config/upload.json` faz o 09 **recusar** upload real. Exceção: upload de teste (`--bloco=N --teste`). Até a auditoria, Curador e `publicacao.txt` trabalham **só com longos**: o Curador nem gera Short (o `10_shorts` roda à mão no dia D) e eles sobem pela API depois. A flag é lida por `_paths.auditoria_aprovada()`. Virar pra `true` só quando a auditoria for aprovada, seguindo o **runbook do dia D** (`references/dia-d.md`): quando o Gu disser "auditoria aprovada", é executar ele.

## Dois projetos OAuth, nunca misturar

| Projeto Google Cloud | Uso | Credenciais (em `secrets/`, gitignored, repo público) | Escopos |
|---|---|---|---|
| `missao-em-cortes-publisher` | upload (09) | `youtube_client_secret.json` + `youtube_token.json` | upload |
| `missao-em-cortes-analytics` | métricas (12/15/17, inclusive o job Reach da Reporting API) e leitura do canal (14) | `analytics_client_secret.json` + `analytics_token.json` | `yt-analytics.readonly` + `youtube.readonly` |

- **Nunca** ativar a Analytics API no publisher: a auditoria dele declara só upload.
- `_google.credenciais` recusa token feito com client de outro projeto (compara o `client_id`).
- Os **dois apps ficam "Em produção"** (Google Auth Platform → Público-alvo). Em teste, tokens expiram em 7 dias.
- Segredo nunca é commitado nem colado no chat. Mudar credencial = perguntar ao Gu antes.

## Outros canais: só yt-dlp, nunca a API (31/10/2026)

Os dois projetos Google declaram (auditoria e políticas de privacidade) que **só acessam dados do nosso canal**. Qualquer leitura de canal de terceiros — os canais monitorados pelo Curador (`canais`) e os canais de corte grandes (`canais_corte`, pra saber se uma live já foi cortada, pelo link na descrição ou pelo título) — é feita com o **yt-dlp** (`uv run yt-dlp` / `yt_dlp` no Python), nunca com a Data API, a Analytics nem a Reporting API. Nada de `search.list`, `videos.list` ou `channels.list` com id de outro canal, nem com o token do publisher nem com o do analytics.

## Fontes de terceiros: risco de reivindicação (01/11/2026)

Flow Podcast e Inteligência Ltda são fontes do Curador (`"terceiros": true` em `config/canais.json`), mas o conteúdo não é do ecossistema MBL/Missão e o dono pode reivindicar (Content ID / strike). Por isso: só episódio com alguém do grupo, a sugestão aparece com ⚠ "fonte de terceiros: risco de reivindicação de direitos", **o Gu decide caso a caso** (botão Processar) e nada disso é processado sozinho (rede de segurança, automático, evento). Crédito da fonte continua obrigatório (URL do episódio na descrição). Detalhe em `editorial-missao/references/curador.md` (2c).

## Métricas que guiam a estratégia (31/10/2026)

O resumo semanal (`17_analytics semanal`, sextas) abre com a **métrica principal: minutos assistidos por view**, com a retenção ao lado, **por faixa de duração** do corte (curto 3-10, médio 10-20, longo 20-30, abaixo de 5, acima de 30). Junto: as **views de cada vídeo novo nos 7 primeiros dias** (média das últimas 4 semanas x as 4 anteriores) e a **% de views que não vem da busca** (últimos 7 dias x semana anterior, com a fatia de recomendação: início/feed, sugeridos e Shorts) — o sinal de que o algoritmo começou a recomendar. Detalhe em `references/metricas.md`.

## Sempre perguntar antes de

Publicar no YouTube pela primeira vez numa feature nova · rodar upload real (sempre `--dry-run` antes).

## Onde está o detalhe

- `references/dia-d.md` — **runbook do dia D** da auditoria: `dia_d.py checar` (simulação), virar a flag, teste com 1 vídeo, verificação (script + Studio), liberação dos Shorts (`09 todos --shorts`, 2/dia) e vídeo relacionado, rollback.
- `references/upload.md` — 09: slots, idempotência, cota, upload de teste, Shorts (`--shorts`).
- `references/metricas.md` — 12: regra com/sem legenda + **setup do projeto analytics passo a passo**; 15: placar do canal pro YPP.
- `references/canal-e-publicacao.md` — 14 (casamento por título, status) e `publicacao.txt`.
