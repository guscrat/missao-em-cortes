# Step 11 — agente revisor de conteúdo + agente editor

`uv run py scripts/11_revisor.py <stem> [--bloco=N] [--dry-run] [--sem-editor]`

`agente="revisor"`, off-pipeline, **API paga**: ~US$ 0,05/bloco, ~US$ 0,25/live com `claude-opus-5-5`.

## Entrada (uma chamada com visão por bloco com corte)

- O título que vai pro YouTube (do `descricoes.txt`, edição manual vale; na falta, `titulo_sugerido`)
- O `texto_thumb`
- A transcrição do trecho (`words.json`)
- A thumb escolhida (manual > a > b > c)
- 6 frames do corte completo
- A lista de grafias oficiais

## Checagens (JSON estruturado)

1. **Título fiel à fala** — gancho ousado ok, distorção não; e **nunca destacar palavrão nem termo que soe como ofensa a um grupo**, mesmo que esteja na fala. Grafia fora da oficial reprova.
2. **Thumb ok** — a thumb **final**: rosto inteiro, visível e iluminado, sem sombra/degradê em cima, texto legível e coerente, sem tela compartilhada.
3. **Tela compartilhada** — maior parte do corte mostra tela em vez de gente.
4. **Corte sem sentido** — o trecho não se sustenta sozinho.

## Decisão (código, não modelo)

- **Conteúdo ruim** (tela compartilhada ou corte sem sentido) → `descartado` com o motivo. Não sobe, não passa pelo editor, não chama o Gu.
- **Título reprovado** → o **agente editor** (`_editor.py`, `agente="editor"`, ~US$ 0,01/reescrita, só texto) reescreve título + `texto_thumb` a partir do problema apontado e da transcrição. Grava no `descricoes.txt` (só o título daquele bloco, via `_descricoes.trocar_titulo`) e no `blocos.json` (originais em `titulo_original`/`texto_thumb_original`). Refaz a thumb escolhida (mesma variante, via `07_thumb.py --variante=`) e o Short do bloco, se existir. O revisor reavalia. **No máximo 2 reescritas**: se o título reprovar nas 2, fica em `quarentena` com "decisão do Gu" (faixa amarela na tarefa do `MISSAO_TAREFA`). **Só aí o Gu é chamado.** Thumb manual não é refeita sozinha (o script avisa).
- **Só a thumb reprovada** → `07_thumb.py --bloco=N --proximo` põe na `thumb_NN_a` o próximo frame com rosto da fila (`thumbs/candidatos_NN.json`) e o revisor reavalia **só a thumb** (~US$ 0,01 por troca, effort low). No máximo 3 trocas (`MAX_TROCAS_THUMB`); nenhum frame serviu → `descartado`. Thumb **manual** reprovada fica em `quarentena` (refazer com `07_thumb.py --t=`).
- Tudo ok → `aprovado`. Recusa do modelo vira quarentena ("revisar à mão").

## Thumb colagem aplicada (modo `padrao` do 07b)

O revisor reconhece a colagem aplicada (cópia idêntica em `thumbs/colagem/`, `_colagem.colagem_aplicada`), confere os textos das **3 variantes** contra a fala (números, fatos e nomes têm que bater; grafia fora da oficial reprova) e aceita cena de tela ao fundo nesse formato.

- Título reprovado: o editor reescreve e a colagem é refeita com o texto novo (`07b --bloco=N --aplicar --sem-editor`, que usa o `texto_thumb` do bloco e sai com 2 se a colagem não sair); se não sair, as 3 variantes voltam pro template.
- Colagem reprovada só na arte: as 3 variantes voltam pro template (`_editor.voltar_template`, que também tira o crédito da foto da descrição) e o bloco é revisado de novo com o texto do template (+~US$ 0,05); se a thumb do template reprovar, segue a troca de frame normal (`--proximo`).

## Modo `ab` (teste A/B template x colagem)

`thumb_NN_a` é o template e `b`/`c` são colagem (`07b --ab`). O revisor avalia a `a` como sempre (troca de frame normal se reprovar) e confere os textos das 3 variantes (`texto_da_thumb`: o da colagem onde ela foi aplicada, o `texto_thumb` no resto). Bloco aprovado: confere também a **arte** de b e c (`conferir_colagem_ab`, ~US$ 0,01 cada); reprovou → b/c voltam pro template (`voltar_template(..., ("b", "c"))`, tira o crédito) e o bloco segue aprovado, só sai do teste. Título reescrito pelo editor: a `a` é refeita no template e b/c com `07b --ab --sem-editor` (não saiu → template).

## Outros detalhes

- `--sem-editor` desliga as reescritas. `--dry-run` mostra a fila e o custo estimado sem chamar a API.
- O `09_upload` **não sobe** bloco em `quarentena`, `descartado` ou `arquivado`.
- Fallback de refusal do servidor ligado (`fallbacks: "default"`).
- **Nunca** mexe em bloco `agendado`/`publicado`/`arquivado`.
- Detalhes em `outputs/<pasta>/revisao.json`; custo por bloco no banco (evento `llm`).
- Thumb regerada de bloco **já aprovado** o Gu revisa no olho; vídeo novo usa o revisor normal.

## Editor também escreve os textos da colagem

`_editor.texto_colagem` (opus, ~US$ 0,03): 3 opções, de preferência em pergunta, com as mesmas regras de título (fiel à fala, sem palavrão/ofensa); só põe `[Nome]` se a cena destacada é dessa pessoa. Ver skill `thumb-colagem`.
