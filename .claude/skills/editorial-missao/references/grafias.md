# Grafias oficiais

`config/grafias.json` + `scripts/_grafias.py` (US$ 0): nome, forma curta e grafias erradas conhecidas de cada personagem (ex.: Nikolas Ferreira, nunca "Nicolas").

## Onde entram

- **Editor** (`_editor.py`): recebe a lista no pedido e a saída dele passa pelo `corrigir` (título, texto da thumb, textos da colagem).
- **Revisor** (11): recebe a lista e reprova grafia errada.
- **08_descricao**: corrige o título.
- **Short** (`_descricoes.manchete`): a manchete queimada (10) e o título no YouTube (09) passam pelo `corrigir`; o nome de quem fala sai do `citados`.
- **Colagem** (07b): casa a grafia errada das tags com a foto certa do banco, e as **pessoas citadas** no bloco (pelas grafias) orientam a escolha de cena.

## Regras

- **`nao_trocar`** (por personagem): frases de outra pessoa com a mesma grafia ("Nicolas Maduro", "Nicolas Sarkozy"…) nunca são trocadas, **em qualquer caixa**. É o que protege texto todo em maiúsculas (thumb, manchete do Short), onde não dá pra ver inicial maiúscula. Outra pessoa nova com grafia de personagem → acrescentar aqui.
- Em texto misto, palavra solta seguida de outro nome próprio (inicial maiúscula) também não é trocada.
- Em CAIXA ALTA a grafia é corrigida normalmente ("NICOLAS SERÁ O REI?" → "NIKOLAS SERÁ O REI?").
- Personagem novo recorrente: acrescentar no JSON (nome, curto, erradas).
