# Step 7b — thumb colagem (07b_colagem.py)

> **PAUSADA desde 26/10/2026** (`config/thumb.json` → `"colagem": "pausada"`). A v1 pôs a seta no Kim numa thumb sobre o Marçal e o resultado geral não ficou bom. A thumb que sobe é a clássica (07, ver `template.md`). O 07b sai com código 3 sem fazer nada; `--forcar` roda mesmo assim, só pra desenvolver a v2. O Curador não chama mais.
>
> **Regras da v2 (quando voltar):**
> 1. **Só imagens do próprio vídeo.** Sem o banco de fotos estáticas de personagens (`assets/personagens/`) como cena.
> 2. **Seta/círculo só com certeza de quem é:** o apresentador, ou uma cena com o **nome da pessoa escrito na tela** (legenda, tarja, crachá, @ do post) que bate com quem o texto cita. **Na dúvida, sem seta.**
> 3. O revisor já reprova seta/círculo em pessoa que não dá pra confirmar que é a citada no texto (`CRITERIO_THUMB` do 11).
>
> Abaixo, como a v1 funciona (referência pra v2).

`uv run py scripts/07b_colagem.py <stem> [--bloco=N] [--sem-llm] [--sem-editor] [--aplicar] [--saida=DIR]`

`agente="editor"`, ~US$ 0,03/bloco, ~US$ 0,15/live. Gera 3 variantes a/b/c pro "Testar e comparar" do Studio. Núcleo em `scripts/_colagem.py`.

## Layout

- 2 cenas lado a lado no fundo: à esquerda o **assunto**, preenchendo; à direita o **contexto** como cartão inteiro com borda branca, legível, sobre ele mesmo desfocado.
- Círculo (a/c) ou seta (b) vermelha no rosto-chave da cena (Haar).
- Apresentador **recortado sem fundo** (rembg, local, modelo `u2net_human_seg`) à direita com contorno branco. Rosto ocupa ~42% da altura (cabeça ~45-50%, `ROSTO_APRES`), ampliando o frame até 3x.
- Texto grande em 2 linhas com contorno preto grosso: `*palavra*` em amarelo 14, `[Nome]` em vermelho.

## Cenas

1. Primeiro a **tela compartilhada** da própria live: a caixa de react que o `detectar_overlays` acha, ou frame inteiro sem rosto que **não** seja o estúdio (frame parecido com os do apresentador é ele virado de lado).
2. Faltou, completa com o **banco de personagens** citados nas tags/tema/título do bloco. O apresentador da live nunca vira cena dele mesmo.

## Escolha (visão)

Uma chamada `claude-haiku-5-5` (~US$ 0,0005) ordena ~6 expressões do apresentador (da fila do 07) e escolhe a cena do assunto e a de contexto, descrevendo cada uma **só pelo que está escrito nela** (legenda, púlpito, @ do post; **nunca reconhece rosto**). Põe expressão **forte** (surpresa, indignação, riso, apontar) na frente da neutra. Recebe as **pessoas citadas** no bloco (pelas grafias oficiais) e prefere a cena da live em que o nome de uma delas aparece **escrito** — é assim que entra quem não tem foto aberta no banco.

## Texto

O editor (`_editor.texto_colagem`, opus, ~US$ 0,03) escreve 3 opções, de preferência em pergunta, com as mesmas regras de título (fiel à fala, sem palavrão/ofensa), e só põe `[Nome]` se a cena destacada é dessa pessoa. Saída passa pelo `_grafias.corrigir`.

## Fallback

Sem rosto bom, sem recorte ou sem 2 cenas → o bloco fica com a thumb do template (07). Live sem fila do 07 (antiga) tem a fila calculada em memória.

Registro em `thumbs/colagem/colagem.json` (cenas, textos, créditos, custo). **Nunca** mexe em bloco agendado/publicado/arquivado; `--saida=DIR` é prévia fora do `outputs/` e ignora essa trava.

## Modos (`config/thumb.json` → `colagem`)

- **`teste`**: o Curador roda o 07b no fim de cada vídeo novo em `thumbs/colagem/`, **sem mexer** nas thumbs que sobem; o resumo aponta a pasta pra comparar.
- **`ab`** (atual, desde 26/10/2026): teste A/B com dado. O Curador roda `07b --ab` **antes** do revisor: só as variantes b/c da colagem viram `thumb_NN_b/c` (b = seta, c = círculo com outra expressão) e `thumb_NN_a` fica no **template**. Crédito da foto na descrição igual ao padrão. O revisor avalia a `a` e confere a arte de b/c (reprovou → b/c voltam pro template; ver `editorial-missao/references/revisor-editor.md`). O `publicacao.txt` lista as 3 thumbs de cada vídeo, marcadas template/colagem, pra subir no **"Testar e comparar"** do Studio. Bloco sem colagem (fallback) sobe 3 templates e não conta no placar.
  - **Resultado:** o YouTube não expõe o "Testar e comparar" na API, então é à mão: `uv run py scripts/16_thumb_ab.py registrar <stem> <vídeo> <a|b|c|empate> [--a=% --b=% --c=%]` (estilo de cada letra lido das thumbs na hora → `state/thumb_ab.json`, evento `analista`). `16_thumb_ab.py placar` mostra template x colagem (só testes mistos) e sugere o padrão a partir de 5 testes com vencedor e ≥ 2/3 das vitórias; o mesmo placar sai no resumo do Curador.
- **`padrao`**: o Curador roda com `--aplicar` **antes** do revisor. A colagem vira `thumb_NN_a/b/c.png` e o crédito da foto do banco entra no fim da descrição do bloco (`_descricoes.trocar_creditos`, que troca o crédito antigo se a colagem for refeita com outra foto). O `08_descricao` **repõe** o crédito ao regerar o txt. Interação com o revisor: ver `editorial-missao/references/revisor-editor.md`.
- **`desligado`** (ou sem o arquivo): nada.

Virar pra `padrao` (ou `desligado`, se o template ganhar): pelo placar do `16_thumb_ab.py` + ok do Gu.
