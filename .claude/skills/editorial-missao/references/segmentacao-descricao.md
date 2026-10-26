# Segmentação (03) e descrições (08)

## Step 3 — segmentação via LLM

`uv run py scripts/03_segmentar.py <stem>` — 30-90s, ~$0.20/live, modelo `claude-sonnet-4-6`. Prompt em `prompts/segmentacao.md`.

A LLM recebe a transcrição completa com timestamps e retorna JSON com os **blocos temáticos de 8-30 min** (sem número fixo: o tamanho é o do assunto; durações variadas — curtos 8-12, médios 12-20, longos 20-30), cada um sobre UM assunto, com:

- início e fim em pontos naturais (não cortar no meio de frase ou raciocínio); `timestamp_fim` = linha seguinte à frase de encerramento
- `parte` (`null` ou `{"n", "total"}`: assunto de mais de 30 min vira Parte 1/Parte 2, título com "(Parte N)")
- `titulo_sugerido` (frase longa pro YouTube)
- `texto_thumb` (2-5 palavras de impacto pra miniatura, distinto do título)
- `tema`, score de potencial viral, ganchos, tags
- `short` (até 3 min, ideal 30-90s, ideia completa terminando numa frase de impacto: `gancho`, `frase_final`)
- `cold_open` (trecho de 15-30s de maior impacto dentro do bloco, com timestamps próprios)

Depois da resposta, o 03 **encaixa os tempos** (bloco, cold open e Short) no fim de frase + pausa mais perto pelo `words.json` (`_fronteira.encaixar`, até 30s no bloco e 10s nos trechos, respeitando 8-30 min e o teto de 175s do Short) e grava os tempos exatos (`HH:MM:SS.ss`), a `duracao_minutos` real e a `faixa_duracao`. Também grava `duracao_min` no banco. Avisa: bloco fora de 8-30 min, sem ponto natural perto, todos na mesma faixa; Short inválido/fora do bloco/acima de 3 min é removido (o 10 cai pro cold open).

O 03 valida os timestamps (fim>início, cold_open dentro do bloco, fim≤duração do vídeo). Inválido → salva `blocos_invalido.json` e sai com erro em vez de gravar lixo. Falha de parse → dump em `outputs/_debug/`. Loga custo em $.

Histórico da duração: 8-15 min → 5-7 min (Jun/2026, retenção) → **8-30 min guiado pelo assunto** (26/10/2026: coerência acima da duração, mínimo de 8 pra anúncio no meio). O `12_metricas` compara retenção e horas assistidas por faixa pra achar o ponto ideal.

### Modelo: fica no Sonnet 4.6 (decisão do Gu, 24/10/2026)

O `claude-sonnet-5-5` foi testado na renan_lula_vire com o mesmo prompt e **perdeu blocos bons**: o 4.6 achou 5 blocos; o 5.5 achou 2 (effort `low`), 4 (`medium`, sem o Pavanato, score 9) e 4 (`high`, sem o "Quem manda na direita se Flávio perder", score 8). Também saíram cortes abaixo de 5 min e títulos com menos gancho; no `high` custou mais (US$ 0.36 × 0.20). O 04b, que só marca trechos pra remover, foi pro 5.5 sem perda.

Se um dia precisar trocar o modelo do 03: **ajuste o `prompts/segmentacao.md` junto** (o prompt foi escrito pro 4.6) e **repita a comparação** numa live já processada antes de trocar: rodar numa cópia da pasta, com `MISSAO_DB` num banco temporário, e pôr lado a lado os blocos (timestamps, tema, título, `score_potencial`) e o custo de cada versão. Só troca se os blocos forem iguais ou melhores.

## Step 8 — descrições pro YouTube

`uv run py scripts/08_descricao.py <stem>` — <5s, grátis, **sem API** (reaproveita o `blocos.json`).

Gera `descricoes.txt` (na pasta do vídeo) com, pra cada bloco: título sugerido (com contagem de chars, corrigido pelas grafias oficiais), descrição (resumo + ganchos como bullets), créditos do canal, hashtags e lista de tags pronta pra colar no YouTube Studio.

- A URL da fonte ("Conteúdo original") vem de `inputs/<stem>.url` (salva pelo `01_baixar.py`); sem o arquivo, deixa o placeholder `[COLAR URL DA LIVE AQUI]` e avisa no log. Bloco com placeholder **não sobe** (09).
- O link do **nosso** canal (`scripts/_canal.py`) só entra na linha "Inscreva-se". Se o `.url` apontar pro nosso canal, o 08 ignora e o 09 se recusa a subir.
- Repõe o crédito da foto do banco de personagens ao regerar (lê o `colagem.json` da colagem aplicada).
- Edição manual no txt vale: o 09, o 11 e o 14 leem o txt (parser em `scripts/_descricoes.py`).
