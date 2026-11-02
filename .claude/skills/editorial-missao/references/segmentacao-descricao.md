# Segmentação (03) e descrições (08)

## Step 3 — segmentação via LLM

`uv run py scripts/03_segmentar.py <stem>` — 30-90s, ~$0.20/live, modelo `claude-sonnet-4-6`. Prompt em `prompts/segmentacao.md`.

A LLM recebe a transcrição completa com timestamps e retorna JSON com os **blocos temáticos de 5-30 min** (sem número fixo e sem duração-alvo: o tamanho é o do assunto), cada um sobre UM assunto, com:

- início e fim em pontos naturais (não cortar no meio de frase ou raciocínio); `timestamp_fim` = linha seguinte à frase de encerramento
- `parte` (`null` ou `{"n", "total"}`: assunto de mais de 30 min vira Parte 1/Parte 2, título com "(Parte N)")
- `titulo_sugerido` (frase pro YouTube pensada pra busca de cauda longa: nome completo + tema concreto, de preferência em pergunta — ver SKILL.md, "Títulos")
- `texto_thumb` (2-5 palavras de impacto pra miniatura, distinto do título)
- `tema`, score de potencial viral, ganchos, tags
- `short` (até 3 min, ideal 30-90s, ideia completa terminando numa frase de impacto: `gancho`, `frase_final`)
- `cold_open` (trecho de 15-30s de maior impacto dentro do bloco, com timestamps próprios)

**O LLM não sabe copiar timestamp em transcrição longa** (26/10/2026, live de 3h20 do Renan: errou 2-20 min, e título, frases e tempos de um mesmo bloco se contradiziam; o validador barrou 2 rodadas). Por isso:

- **Janelas de 60 min**: live acima de 70 min é segmentada em sequência; cada chamada recebe só um trecho e devolve os blocos que *terminam* nele; a próxima começa no fim real do último bloco. Bloco que termina a menos de 3 min do fim de uma janela (não a última) sai e vai inteiro pra próxima. Prompt de sistema em cache. ~+25% de input (US$ 0,62 na live de 3h20, 4 chamadas).
- **Âncora pelo texto** (`_fronteira.ancorar`): a frase literal (abertura/encerramento do bloco, `frase` do cold open, `gancho`/`frase_final` do Short) é procurada no words.json a até 12 min do tempo dito (sem acento/pontuação, difflib ≥ 0,7; entre achados parecidos, o mais perto). Desvio > 1 min vira aviso.
- **Regras no código**: com os tempos reais, bloco **< 5 min sai** e sobreposição grande (mesmo assunto nas duas pontas de uma emenda) fica com o de maior `score_potencial`, os dois registrados em `descartados` no blocos.json, com o motivo; cold open fora do bloco usa os primeiros ~22s do Short; ids renumerados em ordem de tempo.
- **Sem bloco de superchat** (26/10/2026): leitura de superchat/chat pulando de assunto sem fio condutor não vira bloco (regra rígida no prompt). Pergunta do chat que puxa um raciocínio sobre um assunto só vira bloco normal. Motivo: na live do 2º turno do Arthur, 2 blocos assim passaram por 04b/04c/06/thumb/editor e o revisor só descartou no fim. O revisor continua descartando o que escapar ("corte sem sentido").
- **Abertura sem propaganda**: depois do encaixe, `_fronteira.pular_propaganda` (`config/propaganda.json`) tira propaganda/patrocínio da live do começo do bloco (aviso no log).
- A resposta paga fica em `segmentacao_bruta.json` com a assinatura (hash da transcrição e do prompt + modelo). **Rodar o 03 de novo reaproveita os blocos já escolhidos por $0** e refaz só âncora/encaixe/validação; só paga se a transcrição mudou, se não há resposta completa ou com `--refazer` (prompt mudou → reaproveita e avisa). Reprocessamento pago usa cache de 1 h na transcrição.

Depois da âncora, o 03 **encaixa os tempos** (bloco, cold open e Short) no fim de frase + pausa mais perto pelo `words.json` (`_fronteira.encaixar`, até 30s no bloco e 10s nos trechos, respeitando 5-30 min e o teto de 175s do Short) e grava os tempos exatos (`HH:MM:SS.ss`), a `duracao_minutos` real e a `faixa_duracao`. Também grava `duracao_min` no banco. Avisa: bloco fora de 5-30 min, sem ponto natural perto; Short inválido/fora do bloco/acima de 3 min é removido (o 10 cai pro cold open).

O 03 valida os timestamps (fim>início, cold_open dentro do bloco, fim≤duração do vídeo). Inválido → salva `blocos_invalido.json` e sai com erro em vez de gravar lixo. Falha de parse → dump em `outputs/_debug/`. Loga custo em $.

Histórico da duração: 8-15 min → 5-7 min (Jun/2026, retenção) → **8-30 min guiado pelo assunto** (26/10/2026: coerência acima da duração, mínimo de 8 pra anúncio no meio) → **5-30 min, sem alvo** (31/10/2026: o anúncio no meio só vale depois do YPP; saiu o aviso de "variar as faixas"). O resumo semanal do 17 compara minutos assistidos por view e retenção por faixa (curto 5-10, médio 10-20, longo 20-30) pra achar o ponto ideal.

### Modelo: fica no Sonnet 4.6 (decisão do Gu, 24/10/2026)

O `claude-sonnet-5-5` foi testado na renan_lula_vire com o mesmo prompt e **perdeu blocos bons**: o 4.6 achou 5 blocos; o 5.5 achou 2 (effort `low`), 4 (`medium`, sem o Pavanato, score 9) e 4 (`high`, sem o "Quem manda na direita se Flávio perder", score 8). Também saíram cortes abaixo de 5 min e títulos com menos gancho; no `high` custou mais (US$ 0.36 × 0.20). O 04b, que só marca trechos pra remover, foi pro 5.5 sem perda.

Se um dia precisar trocar o modelo do 03: **ajuste o `prompts/segmentacao.md` junto** (o prompt foi escrito pro 4.6) e **repita a comparação** numa live já processada antes de trocar: rodar numa cópia da pasta, com `MISSAO_DB` num banco temporário, e pôr lado a lado os blocos (timestamps, tema, título, `score_potencial`) e o custo de cada versão. Só troca se os blocos forem iguais ou melhores.

## Step 8 — descrições pro YouTube

`uv run py scripts/08_descricao.py <stem>` — <5s, grátis, **sem API** (reaproveita o `blocos.json`).

Gera `descricoes.txt` (na pasta do vídeo) com, pra cada bloco: título sugerido (com contagem de chars, corrigido pelas grafias oficiais), descrição (resumo + ganchos como bullets), créditos do canal, hashtags e lista de tags pronta pra colar no YouTube Studio.

- A URL da fonte ("Conteúdo original") vem de `inputs/<stem>.url` (salva pelo `01_baixar.py`); sem o arquivo, deixa o placeholder `[COLAR URL DA LIVE AQUI]` e avisa no log. Bloco com placeholder **não sobe** (09).
- O link do **nosso** canal (`scripts/_canal.py`) só entra na linha "Inscreva-se". Se o `.url` apontar pro nosso canal, o 08 ignora e o 09 se recusa a subir.
- **Capítulos** (desde 28/10/2026, só lives segmentadas daqui pra frente): o 03 pede no mesmo JSON de 3 a 8 `capitulos` por bloco (`titulo` curto e fiel + `frase_de_abertura` literal); `_capitulos.ancorar` acha o tempo real no `words.json` e encaixa no começo de frase, o 1º no início do bloco (~US$ 0,04 a mais de saída por live). O 08 escreve a seção `Capítulos:` logo depois do resumo, no **tempo do vídeo final** (cold open + intro + card medidos no arquivo + jump cuts do polimento, se o vídeo que sobe é o polido), com as regras do YouTube: 1º em 00:00, cada um com ≥ 10s (o que ficaria curto sai), ≥ 3 no total, só corte de 8+ min. Bloco antigo sem `capitulos`: descrição igual a antes. O revisor (11) confere cada título contra o trecho. Os tempos dependem do vídeo montado: polir/remontar depois do 08 → rode o 08 de novo (o reajuste de fronteira do 11 já recalcula sozinho, sobrescrevendo edição manual dos capítulos daquele bloco). A duração de cold open, intro, card e outro é medida com ffprobe nos arquivos que o 06 usou (cold legendado se o vídeo é `_legendado`); as constantes `_capitulos.INTRO_S`/`CARD_S`/`OUTRO_S` (e a janela do cold) só valem se a medição falhar, e o 08 avisa no log.
- Repõe o crédito da foto do banco de personagens ao regerar (lê o `colagem.json` da colagem aplicada).
- Edição manual no txt vale: o 09, o 11 e o 14 leem o txt (parser em `scripts/_descricoes.py`).
