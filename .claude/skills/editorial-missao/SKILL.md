---
name: editorial-missao
description: Linha editorial do canal Missão em Cortes (cortes do Partido Missão/MBL) e os agentes que decidem conteúdo. Use sempre que for escrever, avaliar ou mudar título de vídeo, texto_thumb, descrição/tags (08), o prompt de segmentação (03, prompts/segmentacao.md), o revisor de conteúdo (11_revisor.py), o editor (_editor.py), as grafias oficiais (config/grafias.json, _grafias.py), a regra de quarentena/descartado, ou o Curador (13_curador.py — escolha de vídeos, estoque, fila, agendamento das 17h). Use também quando a dúvida for "esse título distorce a fala?", "esse corte se sustenta sozinho?" ou "qual canal/personagem o canal cobre?", mesmo que o pedido não cite nenhum script.
---

# Editorial — Missão em Cortes

O canal pega lives/entrevistas longas das figuras do Partido Missão (legenda 14) — Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias, Amanda Vettorazzo — e gera vários cortes de **8 a 30 min**, cada um sobre **um único assunto**, mais um Short por bloco. Tudo o que é texto público (título, thumb, descrição) segue as regras abaixo, e os agentes (revisor, editor, Curador) existem pra aplicá-las sem o Gu precisar olhar cada vídeo.

## Regra nº 1: coerência acima da duração (26/10/2026, alta prioridade)

O tamanho do corte é o tamanho do assunto. Nunca cortar no meio da fala.

- **Longos: faixa flexível de 8 a 30 min**, guiada pelo assunto. Mínimo de 8 (vídeo de 8+ min pode ter anúncio no meio depois da monetização), máximo de 30. Assunto que passa de 30 min vira **Parte 1 e Parte 2** (campo `parte`, título termina com "(Parte N)"), divididas num ponto natural — nunca no meio.
- **Varie as durações**: curtos de 8-12, médios de 12-20, longos de 20-30. O 03 avisa se todos os blocos de uma live caem na mesma faixa.
- **Início e fim sempre em ponto natural**: fim de frase ou de raciocínio, pelos tempos das palavras (`words.json`) e as pausas. Quem garante é código (`scripts/_fronteira.py`, $0): o 03 encaixa os tempos do LLM no fim de frase + pausa mais perto (até 30s); o padding do 04 não vaza pra frase vizinha; o 04b nunca parte palavra, não mexe nos primeiros 30s nem nos últimos 20s (a frase de impacto que fecha o vídeo).
  - Fim natural = palavra termina com `.` `!` `?` e tem ≥ 0,5s de pausa depois; ou não tem pontuação e a pausa é ≥ 1,2s (whisper às vezes não pontua). Vírgula ou reticências + pausa **não** é fim.
- **Shorts: até 3 min** (limite do YouTube), **ideal 30-90s**, sempre fechando uma ideia completa — gancho, desenvolvimento e conclusão — e terminando numa **frase de impacto**. Campo `short` do bloco (o 10 usa ele; blocos antigos sem `short` usam o cold open).
- **Revisor (11) reprova** corte que começa ou termina no meio de frase (confere as últimas palavras e se há pausa depois, antes da chamada paga). Reprovou → **reajusta o ponto de corte sozinho** e refaz o bloco (`pipeline.py --bloco=N`); sem ponto natural a até 30s → `quarentena`.
- **Duração no banco**: `blocos.duracao_min` (real, dos tempos encaixados) + `blocos.faixa_duracao` (`curto`/`medio`/`longo`/`fora`). O Analista (12) mostra retenção e horas assistidas por faixa; os antigos de 5-7 min aparecem como `fora` (linha de base). O objetivo é achar a duração ideal pro nosso público.

## Postura

- Simpática ao Partido Missão, mas com **independência crítica**. Linha: direita liberal, anti-bolsonarista crítica.
- Títulos podem ser ousados/com gancho, **sem distorcer o que foi dito**. A fidelidade é o que protege o canal (e o partido) de virar fábrica de clickbait falso.
- **Nunca destacar palavrão nem termo que soe como ofensa a um grupo**, mesmo que esteja na fala — no título isso vira o assunto do vídeo e queima a monetização.
- Crédito à fonte sempre: logo MBL/Valete preservado no corte, URL da live na descrição (ver skill `youtube-compliance`).

## Texto público de cada bloco

| Campo | O que é | Regra |
|---|---|---|
| `titulo_sugerido` | título do YouTube | frase de até ~70 chars, gancho fiel à fala |
| `texto_thumb` | miniatura | 2-5 palavras de impacto, **distinto** do título; nunca usar o título na thumb (estoura e trunca) |
| `tema` | fallback do `texto_thumb` | 3-6 palavras |
| `cold_open` | 15-30s de maior impacto dentro do bloco | timestamps próprios, abre o vídeo antes da intro |
| `short` | o Short do bloco: até 3 min, ideal 30-90s | ideia completa (gancho → desenvolvimento → frase de impacto), `frase_final` literal |
| `parte` | `null` ou `{"n": 1, "total": 2}` | assunto de mais de 30 min dividido; título com "(Parte N)" |

Nomes próprios sempre na **grafia oficial** (`config/grafias.json`, ex.: Nikolas Ferreira, nunca "Nicolas"). Detalhes em `references/grafias.md`.

## Estrutura do vídeo final

```
[Cold open 15-30s] → [Intro 3s] → [Card de contexto 3s] → [Corte 8-30min] → [Outro 5s]
```

Cada parte soma "valor agregado" pro YouTube Partner Program, que pune *reused content* desde Jul/2025.

## Regra de produto da quarentena (resumo)

Quem decide é o **código**, a partir das checagens do revisor:

- Corte começa/termina no meio de frase → reajusta sozinho e refaz o bloco; sem ponto natural perto → `quarentena`.
- Conteúdo ruim (tela compartilhada dominante ou corte sem sentido) → `descartado`. Não chama o Gu.
- Título reprovado → editor reescreve (máx. 2 vezes); reprovou nas 2 → `quarentena` com "decisão do Gu".
- Só a thumb reprovada → troca de frame sozinha (máx. 3); thumb manual reprovada → `quarentena`.
- Tudo ok → `aprovado` (vira "Pronto para publicar").

**O Gu só é chamado em quarentena.** Nunca mexer em bloco `agendado`/`publicado`/`arquivado`.

## Onde está o detalhe

- `references/revisor-editor.md` — step 11 completo (entrada, checagens, loop do editor, colagem aplicada, custos, flags).
- `references/segmentacao-descricao.md` — prompt de segmentação (03) e gerador de descrições (08).
- `references/grafias.md` — grafias oficiais: onde entram e como acrescentar personagem.
- `references/curador.md` — agente Curador (13): fila, estoque, processamento, falhas, agendamento no Windows.

Ao mexer em qualquer prompt de LLM: logue custo estimado e registre evento com o `agente` certo (skill `painel-eventos`).
