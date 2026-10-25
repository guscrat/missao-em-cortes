# Segmentação (03) e descrições (08)

## Step 3 — segmentação via LLM

`uv run py scripts/03_segmentar.py <stem>` — 30-90s, ~$0.20/live, modelo `claude-sonnet-4-6`. Prompt em `prompts/segmentacao.md`.

A LLM recebe a transcrição completa com timestamps e retorna JSON com **2-6 blocos temáticos de 5-7min** (até 6 por live; lives longas rendem mais blocos), cada um focado em UM ponto, com:

- início e fim em pontos naturais (não cortar no meio de frase ou raciocínio)
- `titulo_sugerido` (frase longa pro YouTube)
- `texto_thumb` (2-5 palavras de impacto pra miniatura, distinto do título)
- `tema`, score de potencial viral, ganchos, tags
- `cold_open` (trecho de 15-30s de maior impacto dentro do bloco, com timestamps próprios)

O 03 valida os timestamps (fim>início, cold_open dentro do bloco, fim≤duração do vídeo). Inválido → salva `blocos_invalido.json` e sai com erro em vez de gravar lixo. Falha de parse → dump em `outputs/_debug/`. Loga custo em $.

Por que 5-7min: mudança de Jun/2026 pra retenção — cortes curtos e focados num assunto só. Validar com o `12_metricas`.

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
