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

## Checagem 0a — abertura sem propaganda (código, $0, antes da fronteira)

`conferir_abertura` → `_fronteira.pular_propaganda` com os termos de `config/propaganda.json` (`termos` abrem uma propaganda se aparecem nos primeiros 30s; `continua` só emendam uma já aberta, a até 40s uma da outra; desiste se passar de 2,5 min). Achou → o início vai pra 1ª frase depois da propaganda, grava no `blocos.json`/banco (`gravar_tempos`) e refaz o bloco (`pipeline.py --bloco=N`). Sem a propaganda o corte fica < 8 min ou falhou ao refazer → `quarentena`. Resultado em `revisao.json` → `abertura` (`pulado_s`, `trecho`). O `--dry-run` só mostra.

## Checagem 0 — fronteira (código, $0, antes da chamada paga)

`_fronteira.checar`: no que se ouve no vídeo (janela do 04), a 1ª palavra abre frase e a última fecha frase com pausa depois (≥ 0,5s; ou sem pontuação e ≥ 1,2s)? Reprovou → `_fronteira.encaixar` leva a ponta reprovada pro ponto natural mais perto (até 30s, sem sair de 8-30 min), grava no `blocos.json` (tempos, `duracao_minutos`, `faixa_duracao`) e no banco, e refaz o bloco com `pipeline.py <pasta> --bloco=N` (04 → 04b → 04c → 06, com as mesmas flags com que ele foi feito; o 04b com LLM custa ~US$ 0,03). Sem ponto natural perto, falha ao refazer ou continua reprovado → `quarentena` com o motivo (sem gastar a chamada do revisor). O `--dry-run` mostra a checagem sem reajustar. Resultado em `revisao.json` → `fronteira` (`ultimas`, `pausa_depois_s`, `reajuste_s`).

## Checagens (JSON estruturado)

1. **Título fiel à fala** — gancho ousado ok, distorção não; e **nunca destacar palavrão nem termo que soe como ofensa a um grupo**, mesmo que esteja na fala. Grafia fora da oficial reprova.
2. **Thumb ok** — a thumb **final**: rosto inteiro, visível e iluminado, sem sombra/degradê em cima, texto legível e coerente, sem tela compartilhada.
3. **Tela compartilhada** — maior parte do corte mostra tela em vez de gente.
4. **Corte sem sentido** — o trecho não se sustenta sozinho.
5. **`momentos_fora`** — os itens de "Principais momentos" da descrição (lidos do `descricoes.txt`) que **não** estão na transcrição do trecho (fala de outro momento da live, inventada ou distorcida; paráfrase fiel do trecho passa). Não muda o status: o código (`limpar_momentos`) tira esses itens do `descricoes.txt` (só essas linhas; sem nenhum sobra, sai o cabeçalho) e dos `ganchos` do `blocos.json`. Registro em `revisao.json` → `momentos_removidos`. Se 2+ e mais da metade estavam fora, o bloco aprovado vai pra `quarentena` (sinal de tempos do bloco trocados). A transcrição conferida exclui o campo `remover` do bloco (o que o 04b corta).

## Decisão (código, não modelo)

- **Conteúdo ruim** (tela compartilhada ou corte sem sentido) → `descartado` com o motivo. Não sobe, não passa pelo editor, não chama o Gu.
- **Título reprovado** → o **agente editor** (`_editor.py`, `agente="editor"`, ~US$ 0,01/reescrita, só texto) reescreve título + `texto_thumb` a partir do problema apontado e da transcrição. Grava no `descricoes.txt` (só o título daquele bloco, via `_descricoes.trocar_titulo`) e no `blocos.json` (originais em `titulo_original`/`texto_thumb_original`). Refaz a thumb escolhida (mesma variante, via `07_thumb.py --variante=`) e o Short do bloco, se existir. O revisor reavalia. **No máximo 2 reescritas**: se o título reprovar nas 2, fica em `quarentena` com "decisão do Gu" (faixa amarela na tarefa do `MISSAO_TAREFA`). **Só aí o Gu é chamado.** Thumb manual não é refeita sozinha (o script avisa).
- **Só a thumb reprovada** → `07_thumb.py --bloco=N --proximo` põe na `thumb_NN_a` o próximo frame com rosto da fila (`thumbs/candidatos_NN.json`) e o revisor reavalia **só a thumb** (~US$ 0,01 por troca, effort low). No máximo 3 trocas (`MAX_TROCAS_THUMB`); nenhum frame serviu → `descartado`. Thumb **manual** reprovada fica em `quarentena` (refazer com `07_thumb.py --t=`).
- Tudo ok → `aprovado`. Recusa do modelo vira quarentena ("revisar à mão").

## Seta/círculo na thumb (desde 26/10/2026)

`CRITERIO_THUMB` (vale pro revisor completo e pro `checar_thumb`): seta ou círculo destacando uma pessoa só passa se der pra ter **certeza, sem reconhecer rosto**, de que é a pessoa citada no texto da thumb/título: é o apresentador, ou o nome dela está **escrito** na cena destacada. Nome de outra pessoa na cena, ou nada escrito que confirme → **reprova** (na dúvida, reprova). Origem: a colagem pôs a seta no Kim numa thumb sobre o Marçal.

## Modo `ab` da clássica (padrão desde 26/10/2026)

`config/thumb.json` → `"modo": "ab"`: a/b/c são 3 clássicas com frames e textos diferentes (skill `thumb-colagem`, `template.md`). `texto_da_thumb` lê o texto de cada letra da fila (`candidatos_NN.json` → `textos`) e manda os 3 separados por " | ": **todos** precisam ser fiéis. Bloco aprovado → `conferir_classica_ab` confere a arte de b e c (~US$ 0,01 cada); reprovada vira `thumb_NN_<l>_reprovada.png` e sai do "Testar e comparar" (o bloco segue aprovado). Título reescrito pelo editor: a thumb escolhida é refeita e as outras letras também (`refazer_classica_ab`), com o `texto_thumb` novo.

> As seções de colagem abaixo valem pra quando a colagem voltar (v2). Hoje ela está **pausada**.

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
