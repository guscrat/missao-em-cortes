# Step 14 (leitura do canal) e publicacao.txt

## 14_canal.py

`uv run py scripts/14_canal.py [--dry-run]` — `agente="publicador"`, US$ 0.

Lê **todos** os uploads do nosso canal, inclusive privados e agendados, com o token do **projeto de métricas** (`missao-em-cortes-analytics`, `youtube.readonly`, só leitura; nunca o do publisher). Como dono do canal, esse token enxerga o `publishAt` dos agendados.

**Casamento por título** (do `descricoes.txt` e do `blocos.json`, incluindo o título original de antes do editor, normalizado e sem `#hashtags`):

- Título levemente editado no Studio ainda casa por similaridade (≥0,92 e com folga de 0,05 sobre o 2º bloco mais parecido, porque blocos da mesma live têm títulos parecidos); o `texto_thumb` só casa exato.
- Título repetido em 2 blocos não casa (não chuta).
- Dois vídeos do canal no mesmo bloco (reupload): fica o público e, entre iguais, o mais recente.
- Bloco `publicado` nunca volta pra `agendado`.

**Status:**

- Longo (>3 min) público → bloco `publicado`; privado com `publishAt` → `agendado` (com `youtube_id` e `publish_at` em horário de Brasília). Rascunho privado sem data e não listado são ignorados.
- Short (≤3 min) público ou agendado → `postado` + `youtube_id` no `shorts/shorts.json` do bloco (sai do estoque de Shorts; o `10_shorts` preserva os dois se o Short for regerado).

**Outros:**

- Idempotente (só grava e loga o que mudou). Vídeos dos últimos 15 dias sem match são listados pra conferir (no resumo do Curador também).
- Grava `state/canal.json` com o último longo agendado/publicado.
- Rodando pelo Curador (Agendador do Windows) **nunca abre o navegador**: sem login válido, só avisa (`_google.LoginNecessario`).
- O 12 e o 14 compartilham `scripts/_youtube_leitura.py` (client/token/escopos do projeto de métricas e a listagem do canal).

## publicacao.txt (_publicacao.py)

Lista de publicação manual. Gerada pelo Curador; à mão: `uv run py scripts/_publicacao.py <stem>`.

- Só blocos `aprovado` no `revisao.json`, em ordem de score, com arquivo final (prefere `_polido_legendado`), thumb escolhida pelo revisor, Short (se gerado), título/descrição/tags do `descricoes.txt` e dia sugerido às 18h.
- 1 por dia, ou 2 por dia com 3+ aprovados. Começa hoje se rodou antes das 16h, mas **nunca antes do dia seguinte ao último longo agendado/publicado** (`state/canal.json` do 14 + `publish_at` do banco).
- Short à mão (só antes da auditoria, se for o caso): o 14 reconhece pelo título do longo ou pelo `texto_thumb` exato. Pela API (09 `--shorts`), o título é a manchete (`texto_thumb`).
- **Até a auditoria a lista mostra só os longos** (sem linha SHORT). Com a flag `true`, lista os Shorts marcados "sobe pela API": quem sobe é o `09_upload.py todos --shorts`, **nunca à mão** (Short já agendado sai da lista porque ganha `youtube_id` no `shorts.json`).
