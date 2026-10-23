# Banco de personagens (personagens.py)

`uv run py scripts/personagens.py lista|baixar` — US$ 0. Saída em `assets/personagens/<slug>.webp` (sem fundo) + `licencas.json`.

## Licença (o porquê: a thumb é pública e monetizada)

- Só licença aberta do **Wikimedia Commons**, conferida pela API: CC0, domínio público, CC BY e "Attribution" (Agência Senado).
- CC BY-SA fica de fora: a thumb inteira teria que sair em BY-SA (`--aceitar-sa` libera, só com ok do Gu).
- **Nunca** baixa de buscador, jornal ou rede social.

## O que baixa sozinho

- Automático **só a foto oficial do item no Wikidata** (P18, pessoa = ser humano).
- A categoria do Commons não entra sozinha: no 1º teste o "Lula" virou o diagrama do PowerPoint da Lava Jato. Ela só aparece como sugestão pra escolher à mão com `--arquivo="File:..."` (conferir que é a pessoa).
- Foto com ≥400 px e um rosto dominante; recorte rembg salvo em WebP (≤900 px de altura).
- `licencas.json` guarda fonte, arquivo do Commons, licença, autor e a linha `credito` que vai na descrição.
- Apelidos curtos (Flávio, Lula, Kim...) ficam no `APELIDOS` do script.
- `lista` mostra os nomes que mais aparecem nas tags dos blocos (`--outputs=` pra apontar outra pasta).

## Estado (out/2026)

- **No banco:** Lula, Flávio, Kim, Arthur, Renan, André Fernandes, Nikolas e Guto.
- **Sem foto aberta utilizável** (só retrato pequeno do TSE, foto de grupo ou BY-SA): Janones, Pavanato, Lulinha, Amanda e Erika Hilton. Esses entram pela cena da live com o nome escrito.
- rembg baixa o modelo `u2net_human_seg` (~170 MB) sozinho na 1ª vez em `~/.u2net`.
