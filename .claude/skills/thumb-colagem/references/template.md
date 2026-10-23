# Step 7 — thumb template (07_thumb.py)

`uv run py scripts/07_thumb.py <stem>` — opcional, não afeta a montagem, <1min. Gera 3 variantes por bloco (`thumb_NN_a/b/c.png`).

## Escolha do frame pelo rosto

`scripts/_thumb_rosto.py`, OpenCV Haar, grátis, ~5s por bloco: amostra 10 frames do cold open e 16 do corte, dá nota a cada um (tamanho do rosto x iluminação x nitidez, rosto cortado na borda perde) e as variantes a/b/c são os 3 melhores, sem frames quase iguais. A fila inteira fica em `thumbs/candidatos_NN.json`, de onde o revisor tira o próximo frame (`--proximo`) e o editor refaz a mesma variante (`--variante=`).

## Layout

- O frame **preenche a thumb inteira** (cover 1280x720, sem faixa preta), com o rosto **inteiro** e grande (~40% da altura, zoom de até 1.6x) no **terço direito** (centro em ~78% da largura).
- Título adaptativo à esquerda (fonte 96→64) sobre um degradê escuro que vem da esquerda e para antes do rosto (curva smoothstep de ≥140 px, sem corte reto entre a área preta e a imagem), gradient embaixo pra contraste e espaço entre manchete e subtítulo.

## Sobras de overlay

`_thumb_rosto.detectar_overlays` acha quadros de transmissão/tela de react que sobraram no corte (retângulo de bordas retas que muda ao longo do vídeo, encostado em cenário parado; caixa que pega o rosto de quem fala é descartada) e soma o nosso logo queimado pelo 04 (`assets/logoCanal.png`, canto sup.-dir.). As caixas ficam em `candidatos_NN.json` (`overlays`; fila antiga ganha na hora).

- O recorte foge delas.
- Overlay à esquerda do rosto some no degradê do texto (preto sólido até depois dele).
- O que não dá pra evitar à direita vira mancha escura, e frame nessa situação tem a nota cortada pela metade (vai pro fim das variantes).

## Texto

Campo curto `texto_thumb` do `blocos.json` (2-5 palavras, gerado no step 3); na falta, `tema` (3-6 palavras). **Nunca** o `titulo_sugerido`. Se não couber em 4 linhas, o script **avisa**. Override: `--titulo="TEXTO CURTO"` (exige `--bloco=N`).

## Modo manual (`--bloco=N --t=MM:SS`)

Quando os frames automáticos caem em **tela compartilhada** (lives onde o speaker mostra matéria/pesquisa, ex: `renan_2turn_x_lula`): abra o corte, ache um segundo com o speaker na câmera e rode `uv run py scripts/07_thumb.py <stem> --bloco=N --t=MM:SS` (aceita `MM:SS`, `HH:MM:SS` ou segundos) → `thumb_NN_manual.png`.

- Puxa do **corte completo** por padrão (`corte_NN_*.mp4`, não o `_polido`); `--fonte=cold` puxa do cold open.
- `--bloco=N` sozinho regenera só a/b/c daquele bloco.
- Escolha de thumb pra subir: manual > a > b > c.
- face_recognition segue adiado (manter as 3 variantes).
