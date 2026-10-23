# Runbook — dia D da auditoria da YouTube Data API

Gatilho: o Gu diz **"auditoria aprovada"** (e-mail do YouTube API Services aprovando o
projeto `missao-em-cortes-publisher`). Essa frase autoriza, nesta ordem: virar a flag, **1**
upload de teste e, depois do "ok no Studio" do Gu, a liberação dos Shorts. Release pra
`main` segue o fluxo normal (pede ok à parte). Custo de tudo: US$ 0 (só cota da API).

Tudo roda da **pasta principal** (develop), exceto a mudança da flag, que é código.

## 0. Pré-checagem (simulação, pode rodar quantas vezes quiser)

```
uv run py scripts/dia_d.py checar
```

Nada sobe, nada muda (só registra 1 evento `dia_d` no banco). Confere credenciais do
publisher (projeto certo, token com `youtube.upload`), token de leitura, cota do dia, e roda
o 09 com `--dry-run --como-aprovada` pro teste e pros Shorts: o plano impresso é **o que vai
subir** quando a flag virar. Tem que terminar em `PRONTO`. Se der `NÃO PRONTO`, resolve antes.

## 1. Virar a flag (código → PR)

1. Worktree isolado, branch `chore/auditoria-aprovada` saindo de `origin/develop`.
2. `config/upload.json` → `"auditoria_aprovada": true`.
3. `tests/test_upload.py::test_config_do_repo_esta_travada` passa a esperar `true`
   (renomear pra `test_config_do_repo_esta_liberada`).
4. Testador + revisor → PR pra develop → CI → merge → `git pull --ff-only` na principal.
5. Conferir: `uv run py scripts/dia_d.py checar` → "1. Flag: auditoria_aprovada = true".

A partir daqui o `publicacao.txt` volta a mostrar os Shorts, marcados "sobe pela API" (o Gu
**não** sobe Short à mão).

## 2. Teste: 1 vídeo agendado público

Use o comando que o `checar` mostrou no item 4:

- Há longo aprovado fora do YouTube → `09_upload.py <stem> --bloco=N --max=1` (vai pro dia
  seguinte ao último longo agendado, inclusive os agendados à mão).
- Senão → `09_upload.py todos --shorts --max=1` (o 1º Short da fila; publica em horas).

Sempre o `--dry-run` primeiro (agora **sem** `--como-aprovada`), depois o real. Anotar o
`youtube_id` impresso (`OK https://youtu.be/<id>`).

## 3. Verificação

**Automática** (token só leitura do projeto analytics):

```
uv run py scripts/dia_d.py verificar <youtube_id>
```

- `[OK] agendado: publica em ...` → segue.
- `[ALERTA] privado SEM data` ou `[FALHA]` → **parar**: ver Rollback.

**No Studio (o Gu, no olho)** — studio.youtube.com/video/<id>/edit (o `verificar` imprime o link):

- [ ] Em Conteúdo aparece **Programado** com a data/hora do plano (horário de Brasília).
- [ ] Nenhum aviso de "bloqueado/restrito como privado" nem de violação de política da API.
- [ ] Verificações (direitos autorais) sem pendência.
- [ ] Título, descrição com **Conteúdo original: <URL da fonte>** e tags certos; thumb (longo).
- [ ] Short: aparece na aba Shorts, o título é a manchete do Short e a descrição abre com "Vídeo completo: youtu.be/<longo>".

O Gu responde **"ok no Studio"** → passo 4. Problema → Rollback.

Confirmação final do "público" (no horário agendado + ~30 min): `dia_d.py verificar <id>` →
`[OK] público`. O 14_canal (rodada do Curador) também marca `publicado`/`postado`.

## 4. Liberar os Shorts (2/dia, com vídeo relacionado)

```
uv run py scripts/09_upload.py todos --shorts --dry-run
uv run py scripts/09_upload.py todos --shorts
```

- Horários: `shorts_horarios` do `config/upload.json` (12:00 e 20:00), um plano só com todas
  as lives, cada Short no 1º horário livre **depois do longo dele ir ao ar**.
- Só sobe Short de bloco cujo longo já está no YouTube (API ou à mão, via 14_canal), fora de
  quarentena/descartado/arquivado, com crédito da fonte e sem `revisar: true` (pouco rosto).
- Título = **manchete do próprio Short** (o `texto_thumb` queimado no topo, senão o `tema`; até 60 chars, corta em palavra). O 14 reconhece Short pelo `texto_thumb` exato. Sem thumb (Short não tem).
- Cota: cada Short = 1.600; cabem ~6 por dia. O 09 para antes de estourar; rodar de novo no
  dia seguinte (zera ~4-5h de Brasília) e os que faltam pegam os horários livres.
- Registro: `outputs/<pasta>/youtube_shorts.json` + `youtube_id`/`postado` no `shorts.json`.
- Só Short subido pela API ocupa horário no plano: Short subido à mão (visto só pelo 14) não
  sai do `todos --shorts` e pode colidir no horário. Depois do dia D, nada de Short à mão.

**Vídeo relacionado** — a Data API **não tem** esse campo; é manual no Studio:

```
uv run py scripts/dia_d.py relacionados              # lista Short → longo que falta marcar
uv run py scripts/dia_d.py relacionados --feito=ID,ID   # marca como feito
```

No Studio: editar o Short → Detalhes → **Vídeo relacionado** → escolher o longo. Se o
longo ainda não aparecer (agendado), voltar depois que ele for ao ar.

## Rollback

1. Voltar a flag pra `false` (mesmo fluxo do passo 1, PR `fix/auditoria-retravar`).
2. Avisar o Gu com o `youtube_id` e o que o `verificar`/Studio mostrou.
3. Vídeo bloqueado como privado não tem conserto: apagar no Studio **só com ok do Gu**
   (destrutivo) e limpar o registro (`youtube.json`/`youtube_shorts.json` do bloco) pra ele
   poder subir de novo.
4. Responder o e-mail da auditoria / abrir caso no formulário de compliance.

## Depois do dia D

- Atualizar esta skill (SKILL.md: a trava passa a ser histórica, com a data da aprovação) e
  a memória do projeto.
- Próximo passo (feature nova, perguntar antes): Curador chamar `09_upload.py todos --shorts`
  (e os longos) sozinho na rodada das 17h.
