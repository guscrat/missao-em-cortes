---
name: thumb-colagem
description: Thumbnails do Missão em Cortes — o template pelo rosto (07_thumb.py, _thumb_rosto.py), a thumb "colagem" estilo canal de react (07b_colagem.py, _colagem.py, modo em config/thumb.json) e o banco de fotos de personagens com licença aberta (personagens.py, assets/personagens/licencas.json). Use sempre que o pedido envolver miniatura, thumb, frame escolhido, rosto cortado/escuro na thumb, sobra de overlay na thumb, texto da thumb estourando, modo manual (--t=), troca de frame (--proximo), colagem (cenas, círculo/seta, recorte rembg), virar a colagem de teste pra padrão, ou baixar/creditar foto de político — mesmo que o usuário só diga "a capa do vídeo ficou ruim".
---

# Thumbs — Missão em Cortes

1. **Clássica / template** (`07_thumb.py`) — frame do vídeo escolhido pelo rosto + manchete à esquerda. **É o padrão** (desde 26/10/2026) e o que o revisor troca sozinho (`--proximo`). Em **modo `ab`** (`config/thumb.json` → `"modo": "ab"`, ligado): `a/b/c` são 3 versões da clássica com **frames e textos diferentes** (`a` = `texto_thumb`, `b`/`c` = alternativas do editor), as 3 sobem no "Testar e comparar" do Studio e o resultado é registrado com `16_thumb_ab.py`. `"modo": "classica"` = 3 frames com o mesmo texto.
2. **Colagem** (`07b_colagem.py`) — **PAUSADA** (`"colagem": "pausada"`): a v1 pôs a seta no Kim numa thumb sobre o Marçal. O 07b sai com 3 sem fazer nada (`--forcar` só pra desenvolver a v2). Regras da v2 em `references/colagem.md`.

## Identidade visual

- Preto onça `#0A0A0A` · **Amarelo 14** `#F5C518` (cor oficial do partido) · Branco `#FFFFFF`
- Fonte **Anton** (`assets/fonts/Anton-Regular.ttf`), CAPS estratégico, primeira linha amarela, resto branco
- Marca "MISSÃO EM CORTES" amarelo no canto inferior direito; badge "MISSÃO 14" amarelo sobre preto no canto superior esquerdo

## Regras que sempre valem

- Texto vem do `texto_thumb` (2-5 palavras) → fallback `tema`. **Nunca** o `titulo_sugerido`: frase longa estourava e era truncada no meio ("...ZEMA E É"). Se não couber em 4 linhas, **avisar**, não cortar em silêncio.
- Rosto **inteiro**, grande, iluminado, sem sombra/degradê em cima, e nada de tela compartilhada como imagem principal do template — é exatamente o que o revisor reprova.
- Overlays da live que sobraram no corte não podem aparecer (o recorte foge deles).
- **Nunca** mexer em bloco `agendado`/`publicado`/`arquivado`.
- Foto de terceiro só com licença aberta conferida (CC0, PD, CC BY). Crédito vai na descrição.
- Thumb regerada de bloco **já aprovado**: o Gu revisa no olho, sem passar pelo revisor.
- **Seta/círculo só com certeza de quem é**: o apresentador, ou cena com o nome da pessoa escrito na tela. Na dúvida, sem seta. O revisor reprova seta/círculo em pessoa que não dá pra confirmar que é a citada no texto.

## Comandos rápidos

```
uv run py scripts/07_thumb.py <stem> [--sem-llm]             # a/b/c de todos os blocos (modo ab: 3 frames + 3 textos)
uv run py scripts/07_thumb.py <stem> --bloco=N --t=MM:SS     # manual (tela compartilhada)
uv run py scripts/07_thumb.py <stem> --bloco=N --titulo="TEXTO CURTO"
uv run py scripts/07b_colagem.py <stem> [--bloco=N] [--aplicar | --ab] [--saida=DIR] --forcar   # PAUSADA
uv run py scripts/16_thumb_ab.py registrar <stem> <vídeo> <a|b|c|empate>   # resultado do Testar e comparar
uv run py scripts/16_thumb_ab.py placar
uv run py scripts/personagens.py lista|baixar
```

## Onde está o detalhe

- `references/template.md` — 07: escolha do frame pelo rosto, layout, overlays, modo manual, fila `candidatos_NN.json`, modo ab (3 frames + 3 textos).
- `references/colagem.md` — 07b (pausada; regras da v2 no topo): layout, cenas, escolha por visão (Haiku), textos do editor, fallback, modos teste/ab/padrão, placar do A/B (16) e interação com revisor/descrição.
- `references/personagens.md` — banco de fotos: regras de licença, o que baixa sozinho, quem está/não está no banco.
