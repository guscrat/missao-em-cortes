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

## Step 8 — descrições pro YouTube

`uv run py scripts/08_descricao.py <stem>` — <5s, grátis, **sem API** (reaproveita o `blocos.json`).

Gera `descricoes.txt` (na pasta do vídeo) com, pra cada bloco: título sugerido (com contagem de chars, corrigido pelas grafias oficiais), descrição (resumo + ganchos como bullets), créditos do canal, hashtags e lista de tags pronta pra colar no YouTube Studio.

- A URL da fonte ("Conteúdo original") vem de `inputs/<stem>.url` (salva pelo `01_baixar.py`); sem o arquivo, deixa o placeholder `[COLAR URL DA LIVE AQUI]` e avisa no log. Bloco com placeholder **não sobe** (09).
- O link do **nosso** canal (`scripts/_canal.py`) só entra na linha "Inscreva-se". Se o `.url` apontar pro nosso canal, o 08 ignora e o 09 se recusa a subir.
- Repõe o crédito da foto do banco de personagens ao regerar (lê o `colagem.json` da colagem aplicada).
- Edição manual no txt vale: o 09, o 11 e o 14 leem o txt (parser em `scripts/_descricoes.py`).
