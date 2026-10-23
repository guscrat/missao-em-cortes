# Grafias oficiais

`config/grafias.json` + `scripts/_grafias.py` (US$ 0): nome, forma curta e grafias erradas conhecidas de cada personagem (ex.: Nikolas Ferreira, nunca "Nicolas").

## Onde entram

- **Editor** (`_editor.py`): recebe a lista no pedido e a saída dele passa pelo `corrigir` (título, texto da thumb, textos da colagem).
- **Revisor** (11): recebe a lista e reprova grafia errada.
- **08_descricao**: corrige o título.
- **Colagem** (07b): casa a grafia errada das tags com a foto certa do banco, e as **pessoas citadas** no bloco (pelas grafias) orientam a escolha de cena.

## Regras

- Palavra solta seguida de outro nome próprio ("Nicolas Maduro") não é trocada.
- Pendente (tarefa #35): essa proteção ainda diferencia caixa — "NICOLAS MADURO" em caixa alta não é protegido. Fazer junto com a próxima mudança nas grafias.
- Personagem novo recorrente: acrescentar no JSON (nome, curto, erradas).
