# CLAUDE.md — Missão em Cortes

> Contexto do projeto para o Claude Code. Lido automaticamente no início de cada sessão.

## O projeto

Canal de YouTube de cortes de lives, entrevistas, debates e eventos do **Partido Missão (legenda 14)**, partido brasileiro de direita liberal fundado em 2025, ligado ao MBL. O canal pega vídeos longos (lives de 1-2h ou entrevistas de 30-60min) das principais figuras do partido (Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias, Amanda Vettorazzo) e gera **vários vídeos por fonte**, cada um focado num único ponto, otimizados para monetização no YouTube Partner Program. O alvo de duração é **5-7min por corte** (mudança de Jun/2026 pra melhorar retenção) — cortes curtos e focados num assunto só. Lives longas naturalmente rendem mais blocos.

**Nome do canal:** Missão em Cortes  
**Canal:** https://www.youtube.com/channel/UCRJDgbBEndOdbNaiwzFju2g (handle `@missaoemcortes-14`; o handle `@missaoemcortes` NÃO é nosso, não usar)

## Postura editorial

- Simpática ao Partido Missão, mas com independência crítica
- Linha editorial: direita liberal, anti-bolsonarista crítica
- Títulos podem ser ousados/com gancho, **sem distorcer o que foi dito**
- Mantém crédito visual à fonte original (logo MBL/Valete preservado nos cortes)
- Overlays desatualizados: removidos via zoom programático por fonte (`config/zoom.json`, lido pelo `04_cortar.py`), sem blur — ver "Tratamento de overlays"

## Stack técnica

- **Python 3.10+** com **uv** (gerenciador de dependências)
- **faster-whisper** — transcrição local (modelo `medium`, GPU NVIDIA via CUDA)
- **Anthropic API** — segmentação temática via `claude-sonnet-4-6` (~$0.20/live)
- **ffmpeg** — corte com fades, montagem final
- **Pillow (PIL)** — geração programática de cards de contexto
- **yt-dlp** — download das lives do YouTube
- **OpenCV (headless, 4.x)** — detecção de rosto pro crop dos Shorts (Haar, local, sem modelo pra baixar)
- **rembg** (onnxruntime CPU) — recorte do apresentador sem fundo na thumb colagem (modelo `u2net_human_seg`, ~170 MB, baixa sozinho na 1ª vez em `~/.u2net`)
- **Canva** — intro, outro e template de thumbnail (externos ao pipeline)

## Estrutura do projeto

```
missao-em-cortes/
├── inputs/                          # Vídeos baixados (mp4)
│   ├── live_teste.mp4
│   ├── renan_entrevista.mp4
│   └── <stem>.url                    # URL da fonte (salva pelo 01_baixar, lida pelo 08)
├── outputs/                          # Tudo gerado pelo pipeline — UMA PASTA POR VÍDEO
│   ├── <AAAA-MM-DD>_<stem>/          # ex: 2026-06-03_renan_vorcaro/ (data = processamento)
│   │   ├── transcricao.txt
│   │   ├── words.json                # word-level timestamps (reaproveitado pelo 04b)
│   │   ├── blocos.json
│   │   ├── polimento.json            # intervalos de jump cut do 04b
│   │   ├── descricoes.txt            # titulo+descricao+tags por bloco pro YouTube
│   │   ├── revisao.json              # veredito e checagens do agente revisor (step 11)
│   │   ├── cortes/                   # corte_NN_<slug>.mp4 + cold_NN_<slug>.mp4 (+ _polido)
│   │   │   └── legendados/           # cortes com legenda karaokê (mesmo nome) + legenda_NN.ass (step 4c)
│   │   ├── cards/                    # card_NN.png e card_NN.mp4
│   │   ├── thumbs/                   # thumb_NN_a/b/c.png (3 variantes pra escolher)
│   │   │   └── colagem/              # thumb colagem (07b): thumb_NN_a/b/c.png + colagem.json (cenas, textos, créditos, custo)
│   │   ├── shorts/                   # short_NN_<slug>.mp4 (9:16) + short_NN.ass + shorts.json (step 10)
│   │   └── finalizados/              # video_NN_<slug>.mp4 (cold+intro+card+corte+outro)
│   ├── _calibracao/                  # scratch da calibração de zoom (dev)
│   ├── _debug/                       # dumps de resposta do LLM quando falha o parse
│   └── _old/                         # artefatos legados (pré-reorganização)
├── assets/
│   ├── intro.mp4                     # do Canva, sem áudio
│   ├── intro_norm.mp4                # normalizado com áudio silencioso
│   ├── outro.mp4                     # do Canva, com voz IA ("inscreva-se")
│   ├── outro_norm.mp4
│   ├── fonts/Anton-Regular.ttf
│   └── personagens/                  # banco da thumb colagem: <slug>.webp sem fundo + licencas.json (licença e crédito de cada foto)
├── scripts/                          # Pipeline numerado
│   ├── pipeline.py                   # orquestrador: roda (02)→03→04→(4b)→05→06→07→08 em sequência
│   ├── 01_baixar.py                  # yt-dlp + salva inputs/<stem>.url
│   ├── 02_transcribe.py
│   ├── 03_segmentar.py
│   ├── 04_cortar.py
│   ├── 04b_polir.py                  # opcional: jump cut de silêncios/fillers via LLM
│   ├── 04c_legendas.py               # legenda karaokê burned-in (words.json → .ass → ffmpeg), $0 — LIGADA por padrão no pipeline
│   ├── 05_cards.py
│   ├── 06_montar.py
│   ├── 07_thumb.py                   # thumbs semi-automáticas (off-pipeline)
│   ├── 07b_colagem.py                # thumb "colagem" estilo react: recorte rembg + 2 cenas + círculo/seta + texto 2 linhas (Curador; modo em config/thumb.json)
│   ├── _colagem.py                   # núcleo da colagem: candidatos de expressão/cena, escolha por visão (Haiku), layout
│   ├── personagens.py                # banco de fotos com licença aberta (Wikidata/Commons → assets/personagens/)
│   ├── _grafias.py                   # grafias oficiais (config/grafias.json): corrigir, lista pro prompt, pessoas citadas
│   ├── 08_descricao.py               # gera txt com titulo+descricao+tags pro YouTube
│   ├── 12_metricas.py                # retenção COM legenda x SEM (YouTube Analytics, só leitura) pro resumo semanal (off-pipeline)
│   ├── 13_curador.py                 # agente Curador: acha vídeos novos dos canais, escolhe (LLM) e dispara o pipeline (1x/dia, off-pipeline)
│   ├── _publicacao.py                # lista de publicação manual (publicacao.txt: aprovados por score + Short + dia sugerido)
│   ├── 14_canal.py                   # lê o NOSSO canal (só leitura) e marca o que já foi publicado/agendado → painel e estoque do Curador
│   ├── _youtube_leitura.py           # client/token do projeto de métricas + listagem do canal (12 e 14)
│   ├── 11_revisor.py                 # agente revisor (Claude com visão) + loop do editor: aprovado / quarentena / descartado (off-pipeline)
│   ├── _editor.py                    # agente editor: reescreve título + texto_thumb reprovados (chamado pelo 11)
│   ├── 10_shorts.py                  # Shorts 9:16 dos cold opens: crop no rosto + manchete + legenda karaokê (off-pipeline)
│   ├── 09_upload.py                  # sobe pro YouTube como privado agendado (publishAt) + thumb; travado até a auditoria (off-pipeline)
│   ├── calibrar_zoom.py              # off-pipeline: calibra o crop anti-overlay (--salvar grava em config/zoom.json)
│   ├── _canal.py                     # ID/URL do NOSSO canal (só no "Inscreva-se"; nunca como fonte)
│   ├── _paths.py                     # resolve outputs/<data>_<stem>/ por stem (helper compartilhado)
│   ├── _descricoes.py                # parser do descricoes.txt + trocar_titulo (compartilhado pelo 09/11/12 e pelo editor)
│   ├── _google.py                    # login OAuth do YouTube (token por uso, escopo mínimo) — 09 e 12
│   ├── _legenda.py                   # núcleo da legenda karaokê (.ass) compartilhado pelo 04c e pelo 10
│   ├── _ffmpeg.py                    # formato canônico (VENC/AENC/SCALE_PAD) compartilhado pelos steps 4/4b/5/6
│   ├── _migrar_outputs.py            # one-off: migrou a estrutura antiga pro layout por vídeo
│   ├── _eventos.py                   # estado/eventos em SQLite (state/pipeline.db) — best-effort, nunca derruba o pipeline
│   ├── sincronizar_estado.py         # backfill/reconciliação do banco a partir de outputs/ (idempotente)
│   ├── tarefa.py                     # CLI das tarefas do time de dev (nova/mover/resultado/decisao/lista)
│   └── hook_agente.py                # hook do Claude Code: atividade dos subagents/tech-lead → banco
├── painel/
│   ├── app.py                        # painel Streamlit (só LÊ o banco): kanban, custo por agente, timeline
│   └── time_dev.py                   # aba "Time de dev": status dos agentes, tarefas, decisões pro Gu
├── state/                            # pipeline.db (gitignored)
├── tests/                            # pytest (conftest com outputs/ e banco falsos; tudo mockado)
├── .claude/agents/                   # subagents do time de dev: testador, revisor-codigo
├── .claude/settings.json             # hooks SubagentStart/SubagentStop/Stop → scripts/hook_agente.py
├── .github/workflows/ci.yml          # CI: uv sync + pytest em todo PR e push pra develop/main
├── prompts/
│   └── segmentacao.md                # Prompt do LLM pra topic segmentation
├── config/
│   ├── zoom.json                     # crop anti-overlay por stem (lido pelo 04_cortar.py)
│   ├── canais.json                   # canais que o Curador monitora + zoom padrão por canal + limites (dias, duração) + estoque mínimo
│   ├── upload.json                   # trava da auditoria (auditoria_aprovada), agendamento do 09 e custos de cota
│   ├── thumb.json                    # modo da thumb colagem: desligado | teste | padrao
│   └── grafias.json                  # grafias oficiais dos personagens (editor, revisor, 08 e colagem)
├── secrets/                          # youtube_client_secret.json + youtube_token.json (upload, projeto publisher) + analytics_client_secret.json + analytics_token.json (métricas, projeto analytics) — gitignored
├── .env                              # ANTHROPIC_API_KEY
└── pyproject.toml
```

## Pipeline (ordem de execução)

| # | Etapa | Script / Comando | Tempo aprox. | Custo |
|---|---|---|---|---|
| 1 | Download | `uv run py scripts/01_baixar.py URL <stem>` | 1-3min | grátis |
| 2 | Transcrição | `uv run py scripts/02_transcribe.py inputs/<stem>.mp4` | ~6-12min (GTX 1650) | grátis (local) |
| 3 | Segmentação via LLM | `uv run py scripts/03_segmentar.py <stem>` | 30-90s | ~$0.20 |
| 4 | Cortes | `uv run py scripts/04_cortar.py <stem>` | ~2-4min (NVENC) | grátis |
| 4b* | Polimento (jump cut) | `uv run py scripts/04b_polir.py <stem>` | ~3-6min (sem re-transcrever) | ~$0.20 |
| 4c* | Legenda karaokê | `uv run py scripts/04c_legendas.py <stem> [--polido]` | ~1-2min/corte (NVENC) | grátis |
| 5 | Cards de contexto | `uv run py scripts/05_cards.py <stem>` | <1min | grátis |
| 6 | Montagem final | `uv run py scripts/06_montar.py <stem> [--polido] [--legendado]` | ~1-2min (concat copy) | grátis |
| 7* | Thumbs (off-pipeline) | `uv run py scripts/07_thumb.py <stem>` | <1min | grátis |
| 8 | Descrições pro YouTube | `uv run py scripts/08_descricao.py <stem>` | <5s | grátis |

> **Orquestrador:** `uv run py scripts/pipeline.py <stem> [--polir] [--sem-llm] [--sem-legendas] [--desde=N]` roda os steps 2→8 em sequência (mesmos scripts, para na primeira falha e mostra o `--desde` pra retomar). Sem `--desde`, pula o step 2 se a transcrição já existe. `--polir` inclui o 04b e monta com `--polido`; `--sem-llm` faz o 04b rodar grátis (só silêncios programáticos, sem API). A legenda karaokê (04c) roda **por padrão** desde 21/10/2026 e a montagem usa `--legendado`; `--sem-legendas` desliga numa live específica (`--desde=4c` retoma do 04c). O download (step 1) fica de fora — rode antes, uma vez.

> **Organização dos outputs:** uma pasta por vídeo em `outputs/<AAAA-MM-DD>_<stem>/` (data de processamento; prefixo ISO faz a ordenação alfabética = cronológica). Os steps 3-8 recebem só o **stem** (ex: `renan_vorcaro`) e o `scripts/_paths.py` resolve a pasta. Se houver mais de uma pasta pro mesmo stem (ambíguo), o script **falha alto** e lista as opções em vez de adivinhar — passe então o nome completo da pasta (ex: `2026-06-03_renan_vorcaro`). O step 2 (transcrição) recebe o caminho do vídeo em `inputs/` e cria/reusa a pasta do stem. Reprocessar um stem **reusa** a mesma pasta (não duplica).

O step 4 gera **dois arquivos por bloco**: `corte_NN_<slug>.mp4` (corte completo, fade out 0.5s) e `cold_NN_<slug>.mp4` (cold open 15-30s, fade in+out 0.4s). Se o JSON não tiver `cold_open`, gera só o corte e loga um aviso.

O step 4b é **opcional** — pra cada `corte_NN_*.mp4` ele: (1) reaproveita os word-level timestamps do `words.json` (gerado no step 2), fatiando pelo intervalo do bloco — **não re-transcreve** (cai pra re-transcrição via whisper só se o words.json não existir), (2) detecta silêncios >3s **programaticamente** (gap entre palavras consecutivas — determinístico, sem API, nunca nos primeiros 30s), (3) manda pro Claude com prompt conservador só o que exige julgamento (fillers extremos e problemas técnicos), funde os intervalos e aplica jump cut via `ffmpeg filter_complex select/aselect` e salva `corte_NN_<slug>_polido.mp4` na mesma pasta. Filtro defensivo descarta intervalos com motivo "ignorar/manter/abaixo do limiar". Suporta `--bloco=N` pra reprocessar só um bloco e `--sem-llm` pra rodar **só a parte programática** (silêncios) sem chamar o Claude — custo $0, abre mão dos cortes de fillers/problemas técnicos. Os intervalos ficam em `polimento.json`; `--reaplicar` re-aplica os intervalos salvos aos cortes sem chamar o LLM (útil após re-cortar, ex: mudou o zoom). Cold opens **não** são polidos. Pra usar os polidos na montagem: `06_montar.py <stem> --polido` (gera `video_NN_<slug>_polido.mp4`).

O step 4c é **grátis** (sem API) e roda **por padrão** no pipeline (`--sem-legendas` desliga por live). Reprocessar live antiga com `--desde=4` gera as legendas; `--desde=5`/`6` sem legendados falha alto e pede `--desde=4c` ou `--sem-legendas`. O que ele faz: queima legenda estilo **karaokê** nos cortes completos pra segurar retenção. Fatia o `words.json` pelo intervalo do bloco (mesmo padding do 04), agrupa em linhas curtas (até 4 palavras / 26 chars, quebra em pausa >0.7s e fim de frase), gera um `.ass` com `\k` (palavra falada acende em **amarelo 14**, o resto fica branco, Anton 72px com contorno preto, centralizada embaixo) e queima com o filtro `ass` do ffmpeg (libass) no formato canônico. Com `--polido` legenda o `_polido` e **remapeia** os tempos pelos intervalos do `polimento.json` (palavra num trecho removido some, as seguintes recuam). Saída em `cortes/legendados/` com o **mesmo nome** do corte. A subpasta é de propósito, porque os globs `corte_NN_*.mp4` dos outros steps não enxergam os legendados. Errou uma palavra? Edite o `legenda_NN.ass` (`legenda_NN_polido.ass` com `--polido`) e rode de novo com `--so-queimar` (não regera o .ass). Cold opens não são legendados. Montagem: `06_montar.py <stem> --legendado [--polido]` → `video_NN_<slug>[_polido]_legendado.mp4`; o 09 prefere `_polido_legendado` > `_legendado` > `_polido` > original.

O step 10 (`uv run py scripts/10_shorts.py <stem> [--bloco=N]`) é **off-pipeline** e **grátis**: gera um **Short 9:16** (1080x1920, 30fps, NVENC) por bloco a partir do **cold open**. Recorta direto do vídeo **original** (`inputs/<stem>.mp4`, 1080p), porque o `cold_NN.mp4` é 720p e ficaria borrado esticado. A janela 9:16 usa a altura toda da área anti-overlay do `config/zoom.json` e fica **sempre dentro dela**, então os overlays continuam fora (stem sem zoom: quadro inteiro + aviso). A posição horizontal segue o rosto de quem fala: OpenCV detecta rostos a cada 0.5s, agrupa por posição e, entre os que aparecem em ≥30% dos frames, escolhe o **mais perto do centro do quadro** (quem filma mantém o palestrante no centro). O critério "maior rosto" perdia pra foto no telão, e o "rosto que mais mexe" perdia pra quem bebia água na mesa. Queima o `texto_thumb` como manchete no topo (caixa preta, amarelo 14), a legenda karaokê grande (3 palavras por linha, 110px) e a marca MISSÃO EM CORTES. Saída em `outputs/<pasta>/shorts/` + `shorts.json` (crop e taxa de rosto). Taxa de rosto <30% = provável tela compartilhada/plateia: o script avisa e marca `revisar: true`. Tempo: ~1min por Short (a detecção domina). Upload de Shorts ainda é manual.

O step 11 (`uv run py scripts/11_revisor.py <stem> [--bloco=N] [--dry-run] [--sem-editor]`) é o **agente revisor de conteúdo** (`agente="revisor"`, off-pipeline, **API paga**: ~US$ 0,05/bloco, ~US$ 0,25/live com `claude-opus-5-5`). Pra cada bloco com corte, faz **uma** chamada com visão. Manda o título que vai pro YouTube (do `descricoes.txt`, edição manual vale; na falta, `titulo_sugerido`), o `texto_thumb`, a transcrição do trecho (`words.json`), a thumb escolhida (manual > a > b > c) e 6 frames do corte completo. Volta JSON estruturado com 4 checagens: **título fiel à fala** (gancho ousado ok, distorção não; e **nunca destacar palavrão nem termo que soe como ofensa a um grupo**, mesmo que esteja na fala), **thumb ok** (a thumb **final**: rosto inteiro, visível e iluminado, sem sombra/degradê em cima, texto legível e coerente, sem tela compartilhada), **tela compartilhada** (maior parte do corte mostra tela em vez de gente) e **corte sem sentido** (o trecho não se sustenta sozinho). Quem decide é o **código**, pela regra de produto da quarentena:

- **Conteúdo ruim** (tela compartilhada ou corte sem sentido) → `descartado` com o motivo. Não sobe, não passa pelo editor, não chama o Gu.
- **Título reprovado** → o **agente editor** (`_editor.py`, `agente="editor"`, ~US$ 0,01/reescrita, só texto) reescreve título + `texto_thumb` a partir do problema apontado e da transcrição. Grava no `descricoes.txt` (só o título daquele bloco) e no `blocos.json` (originais em `titulo_original`/`texto_thumb_original`). Refaz a thumb escolhida (mesma variante, via `07_thumb.py --variante=`) e o Short do bloco, se existir. O revisor reavalia. São **no máximo 2 reescritas**: se o título reprovar nas 2, fica em `quarentena` com "decisão do Gu" (faixa amarela na tarefa do `MISSAO_TAREFA`). **Só aí o Gu é chamado.** Thumb manual não é refeita sozinha (o script avisa).
- **Só a thumb reprovada** → troca o frame **sozinho**: `07_thumb.py --bloco=N --proximo` põe na `thumb_NN_a` o próximo frame com rosto da fila (`thumbs/candidatos_NN.json`) e o revisor reavalia **só a thumb** (~US$ 0,01 por troca, effort low). São no máximo 3 trocas (`MAX_TROCAS_THUMB`); nenhum frame serviu → `descartado`. Thumb **manual** reprovada fica em `quarentena` (foi escolhida à mão: refazer com `07_thumb.py --t=`).
- Tudo ok → `aprovado`. Recusa do modelo vira quarentena ("revisar à mão").

`--sem-editor` desliga as reescritas. O `09_upload` **não sobe** bloco em `quarentena`, `descartado` ou `arquivado`. Fallback de refusal do servidor ligado (`fallbacks: "default"`). **Nunca** mexe em bloco `agendado`/`publicado`/`arquivado`. Detalhes em `outputs/<pasta>/revisao.json`; custo por bloco no banco (evento `llm`). `--dry-run` mostra a fila e o custo estimado sem chamar a API.

O step 12 (`uv run py scripts/12_metricas.py [--desde=AAAA-MM-DD]`) é o **analista de retenção** (`agente="analista"`, off-pipeline, US$ 0). Compara a **retenção** (% média assistida, a do Studio) dos vídeos **com** legenda karaokê x **sem**, pro resumo semanal. Só leitura, num **projeto do Google Cloud separado** (`missao-em-cortes-analytics`), com client e token **próprios** (`secrets/analytics_client_secret.json` + `secrets/analytics_token.json`, escopos `yt-analytics.readonly` + `youtube.readonly`). **Nunca** ativar a Analytics API no projeto `missao-em-cortes-publisher` (o do upload): a auditoria dele declara só upload. O `_google.credenciais` recusa token feito com o client de outro projeto (compara o `client_id`) e pede login de novo. 1ª vez abre o navegador. Lista os vídeos **públicos** do canal (título, data, duração) e puxa views/duração média/% assistida de cada um. Um vídeo é "com legenda" se o título bate (normalizado) com um `descricoes.txt` cujo bloco tem `finalizados/video_NN_*_legendado.mp4`. Vale pra upload pela API e pelo Studio. Sem match: antes de 21/10/2026 conta como "sem legenda"; depois fica de fora ("sem info", listado pra conferir; título editado no Studio quebra o match). Shorts (≤3 min) e vídeos com <20 views ficam de fora. Retenção do grupo = média **ponderada por views**. Saída no terminal + `state/metricas_retencao.json`.

**Setup do projeto de métricas (uma vez, feito pelo Gu no console):**
1. [console.cloud.google.com](https://console.cloud.google.com) → seletor de projeto → **Novo projeto** → nome `missao-em-cortes-analytics` (não mexer no `missao-em-cortes-publisher`).
2. Com o projeto novo selecionado: **APIs e serviços → Biblioteca** → ativar **YouTube Analytics API** e **YouTube Data API v3**.
3. **Google Auth Platform** (tela de consentimento OAuth) → tipo **Externo** → nome do app `Missão em Cortes Métricas`, e-mail de suporte do Gu → em **Acesso a dados**, adicionar só `.../auth/yt-analytics.readonly` e `.../auth/youtube.readonly` → em **Público-alvo**, **Publicar app** (status **Em produção**). App em teste tem token que expira em 7 dias. Em produção o token não expira, e o app segue sem verificação do Google (uso interno), então o login mostra "app não verificado" → **Avançado → continuar**. A política de privacidade desse app é `https://guscrat.github.io/missao-em-cortes/PRIVACY-ANALYTICS.html`.
4. **Clientes → Criar cliente** → tipo **App para computador** → nome `metricas-desktop` → **Baixar JSON** → salvar como `secrets/analytics_client_secret.json` na pasta principal (gitignored; nunca commitar, nunca colar no chat). **Antes de salvar, confira o `project_id` do JSON**: tem que ser `missao-em-cortes-analytics`. Client criado com o projeto errado selecionado sai no `missao-em-cortes-publisher`.
5. Rodar `uv run py scripts/12_metricas.py`: abre o navegador, login com a conta do **canal** (escolher o canal Missão em Cortes se pedir), aceitar os 2 escopos de leitura → grava `secrets/analytics_token.json`. Erro 403 `accessNotConfigured` = faltou o passo 2 (ativar as APIs no projeto analytics; leva alguns minutos pra valer).

> **Os dois apps OAuth ficam "Em produção"** (status em Google Auth Platform → Público-alvo): o `missao-em-cortes-publisher` (upload, 09) e o `missao-em-cortes-analytics` (métricas, 12). Nenhum volta pra "Em teste", senão os tokens passam a expirar em 7 dias.

O step 13 (`uv run py scripts/13_curador.py [--dry-run] [--sem-pipeline] [--forcar]`) é o **agente Curador** (`agente="curador"`, off-pipeline, roda **1x por dia às 17h**). Ele **verifica** os canais de `config/canais.json` (abas streams + videos) todo dia, mas só **processa** quando falta estoque.

1. **Achar vídeos novos:** só os dos últimos `dias` (padrão 3) que nunca foram vistos. "Visto" = id em `inputs/*.url`, no banco ou já avaliado em `state/curadoria.json`. Antes de gastar, aplica um filtro grátis: duração entre `duracao_min` e `duracao_max` (20-240 min) e nada de live em andamento/agendada (volta no dia seguinte).
2. **Avaliar:** os novos vão numa **única** chamada pro Claude (`claude-opus-5-5`, effort low, ~US$ 0,02-0,05/rodada), que decide `vale`, `prioridade` (1-10) e `motivo` (a frase que aparece no painel). O que vale entra na **fila**. Os recusados nunca são reavaliados.
3. **Estoque:** dias de estoque = min(longos prontos ÷ `longos_por_dia`, Shorts prontos ÷ `shorts_por_dia`). Longo pronto = bloco `aprovado` (coluna "Pronto para publicar"). Short pronto = Short gerado de bloco aprovado/agendado/publicado e ainda não marcado como postado nem arquivado. Só conta live dos últimos 15 dias (`DIAS_ARQUIVAR`). Os limites ficam em `config/canais.json` → `estoque` (padrão: mínimo 2 dias, 1 longo + 2 Shorts por dia). **Até a auditoria (`auditoria_aprovada: false` no `config/upload.json`) o estoque conta só os longos** (dias = longos ÷ `longos_por_dia`; os Shorts seguem sendo gerados e aparecem no resumo como "fora da conta"). Quando a flag virar `true`, volta sozinho pra conta com Shorts. A flag é lida por `_paths.auditoria_aprovada()`.
4. **Processar:** só se o estoque estiver **abaixo do mínimo** (ou com `--forcar`). Aí processa **1 vídeo**, o de maior prioridade da fila (empate: o mais recente): `01_baixar` → `pipeline.py --polir` → `11_revisor` → `10_shorts` (só dos aprovados, $0) → `publicacao.txt` → `07b_colagem` (modo `teste`, ~US$ 0,15, em `thumbs/colagem/`; no modo `padrao` roda com `--aplicar` antes do revisor). Custa ~US$ 0,65 por vídeo (+0,15 da colagem). O resto continua na fila, e item da fila com mais de 15 dias vira `expirado`.

- **O que já subiu sai do estoque sozinho:** no começo de cada rodada (antes da conta do estoque), o Curador roda o `14_canal` (ver abaixo), que lê o canal e marca o que o Gu publicou ou agendou no Studio. Nada de registro manual. Se a leitura falhar (sem login, sem rede), a rodada segue com o estoque como estava e o resumo avisa.
- **Zoom:** o `zoom` do canal é copiado pro `config/zoom.json` do stem novo (como o `calibrar_zoom --salvar`). Canal com `zoom: null` (Kim) é processado sem zoom, e o resumo avisa pra calibrar e re-cortar com `--desde=4`. Estúdio diferente do padrão do canal também pede conferência.
- **Falha:** erro num vídeo não derruba a rodada. Se o vídeo nem chegou a baixar, ele volta pra fila e é tentado de novo, no máximo 3 vezes (`falhou`). Se a falha veio depois do download, o vídeo fica `escolhido` e o resumo mostra o erro. Retomar com `pipeline.py <stem> --desde=N`.
- **Saída:** `state/curador_resumo.md` (estoque no início/fim, prontos pra publicar com o caminho do `publicacao.txt`, falhas, escolhido, fila, recusados com motivo, avisos) e eventos no painel. O resumo semanal de sexta lê o `curador_resumo.md`. O log do agendamento vai pra `state/curador.log`.
- **Trava:** `state/curador.lock` (criação atômica) impede duas rodadas ao mesmo tempo. Trava com mais de 12h é considerada morta e é liberada.
- **`publicacao.txt`** (`scripts/_publicacao.py`, dá pra rodar à mão: `uv run py scripts/_publicacao.py <stem>`): só blocos `aprovado` no `revisao.json`, em ordem de score, com arquivo final (prefere `_polido_legendado`), thumb escolhida pelo revisor, Short (se gerado), título/descrição/tags do `descricoes.txt` e dia sugerido às 18h. É 1 por dia, ou 2 por dia com 3+ aprovados. Começa hoje se rodou antes das 16h, mas **nunca antes do dia seguinte ao último longo agendado/publicado** (`state/canal.json` do 14 + `publish_at` do banco). O cabeçalho pede pra subir o Short com o **mesmo título** do vídeo (pode pôr `#shorts`), porque é pelo título que o 14 reconhece. **Até a auditoria a lista mostra só os longos** (sem linha SHORT; os Shorts sobem pela API depois da auditoria). Com a flag `true`, volta a listar os Shorts.

O step 14 (`uv run py scripts/14_canal.py [--dry-run]`, `agente="publicador"`, US$ 0) lê **todos** os uploads do nosso canal, inclusive privados e agendados, com o token do **projeto de métricas** (`missao-em-cortes-analytics`, `youtube.readonly`, só leitura; nunca o do publisher). Como dono do canal, esse token enxerga o `publishAt` dos agendados. Casa cada vídeo com um bloco local **pelo título** (do `descricoes.txt` e do `blocos.json`, incluindo o título original de antes do editor, normalizado e sem `#hashtags`). Título levemente editado no Studio ainda casa por similaridade (≥0,92 e com folga de 0,05 sobre o 2º bloco mais parecido, porque blocos da mesma live têm títulos parecidos), e o `texto_thumb` só casa exato. Título repetido em 2 blocos não casa (não chuta). Dois vídeos do canal no mesmo bloco (reupload): fica o público e, entre iguais, o mais recente. Bloco `publicado` nunca volta pra `agendado`.
- Longo (>3 min) público → bloco `publicado`; privado com `publishAt` → `agendado` (com `youtube_id` e `publish_at` em horário de Brasília). Rascunho privado sem data e não listado são ignorados.
- Short (≤3 min) público ou agendado → `postado` + `youtube_id` no `shorts/shorts.json` do bloco (sai do estoque de Shorts; o `10_shorts` preserva os dois se o Short for regerado).
- É idempotente (só grava e loga o que mudou). Vídeos dos últimos 15 dias sem match são listados pra conferir (no resumo do Curador também).
- Grava `state/canal.json` com o último longo agendado/publicado. Rodando pelo Curador (Agendador do Windows) **nunca abre o navegador**: sem login válido, só avisa (`_google.LoginNecessario`).
- O 12 e o 14 compartilham `scripts/_youtube_leitura.py` (client/token/escopos do projeto de métricas e a listagem do canal).
- **yt-dlp:** precisa da versão com solver JS (`yt-dlp[default]`, Node no PATH). Sem isso o YouTube devolve 403 no download.

**Agendamento (Agendador de Tarefas do Windows):** todo dia às 17:00. Se o PC estiver desligado no horário, roda assim que ligar (`-StartWhenAvailable`). Registrar uma vez, no PowerShell, apontando pra **pasta principal**:

```powershell
$a = New-ScheduledTaskAction -Execute "cmd.exe" -Argument '/c cd /d "C:\Users\gusta\Downloads\projetos\missao-em-cortes" && "C:\Users\gusta\.local\bin\uv.exe" run py scripts\13_curador.py >> state\curador.log 2>&1'
$t = New-ScheduledTaskTrigger -Daily -At 17:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Action $a -Trigger $t -Settings $s -Description "Missão em Cortes: agente Curador (13_curador.py)"
```

Conferir: `Get-ScheduledTask -TaskName "MissaoEmCortes-Curador" | Get-ScheduledTaskInfo`. Rodar agora: `Start-ScheduledTask -TaskName "MissaoEmCortes-Curador"`. Remover: `Unregister-ScheduledTask -TaskName "MissaoEmCortes-Curador" -Confirm:$false`.

O step 7 é opcional e não afeta a montagem — gera 3 variantes de thumb por bloco (`thumb_NN_a/b/c.png`). Os frames são escolhidos **pelo rosto** (`scripts/_thumb_rosto.py`, OpenCV Haar, grátis, ~5s por bloco): amostra 10 frames do cold open e 16 do corte, dá nota a cada um (tamanho do rosto x iluminação x nitidez, rosto cortado na borda perde) e as variantes a/b/c são os 3 melhores, sem frames quase iguais. A fila inteira fica em `thumbs/candidatos_NN.json`, que é de onde o revisor tira o próximo frame (`--proximo`) e o editor refaz a mesma variante (`--variante=`). Layout: o frame **preenche a thumb inteira** (cover 1280x720, sem faixa preta), com o rosto **inteiro** e grande (~40% da altura, zoom de até 1.6x) no **terço direito** (centro em ~78% da largura). Título adaptativo à esquerda (fonte 96→64) sobre um degradê escuro que vem da esquerda e para antes do rosto (curva smoothstep de ≥140 px, sem corte reto entre a área preta e a imagem), gradient embaixo pra contraste e espaço entre manchete e subtítulo. **Sobras de overlay:** o `_thumb_rosto.detectar_overlays` acha quadros de transmissão/tela de react que sobraram no corte (retângulo de bordas retas que muda ao longo do vídeo, encostado em cenário parado; caixa que pega o rosto de quem fala é descartada) e soma o nosso logo queimado pelo 04 (`assets/logoCanal.png`, canto sup.-dir.). As caixas ficam em `candidatos_NN.json` (`overlays`; fila antiga ganha na hora). O recorte foge delas; overlay à esquerda do rosto some no degradê do texto (fica preto sólido até depois dele); o que não dá pra evitar à direita vira mancha escura, e frame nessa situação tem a nota cortada pela metade (vai pro fim das variantes).

**Texto da thumb:** usa o campo curto `texto_thumb` do `blocos.json` (2-5 palavras de impacto, gerado pelo LLM no step 3); na falta dele (vídeos segmentados antes desse campo), cai pro `tema` (3-6 palavras). **Nunca** usa o `titulo_sugerido` — esse é o título do YouTube (frase longa de até 70 chars), que estourava a thumb e era truncado no meio da frase (gerava incoerência tipo "...ZEMA E É"). Se o texto ainda assim não couber em 4 linhas, o script **avisa** (não corta em silêncio). Override manual: `--titulo="TEXTO CURTO"` (exige `--bloco=N`) força o texto de um bloco — útil pra punchar a thumb de vídeos sem `texto_thumb`.

**Modo manual (`--bloco=N --t=MM:SS`):** quando os frames automáticos caem em **tela compartilhada** (lives onde o speaker mostra matéria/pesquisa, ex: `renan_2turn_x_lula`), as 3 variantes saem ruins. Aí você abre o corte, acha um segundo com o speaker na câmera e gera uma thumb daquele frame: `uv run py scripts/07_thumb.py <stem> --bloco=N --t=MM:SS` (aceita `MM:SS`, `HH:MM:SS` ou segundos puros) → salva `thumb_NN_manual.png`. Puxa do **corte completo** por padrão (mais momentos na câmera que o cold open curto; usa o `corte_NN_*.mp4`, não o `_polido`); `--fonte=cold` puxa do cold open. `--bloco=N` sozinho (sem `--t`) regenera só as variantes a/b/c daquele bloco. É a alternativa ao face_recognition, que segue adiado.

O step 7b (`uv run py scripts/07b_colagem.py <stem> [--bloco=N] [--sem-llm] [--sem-editor] [--aplicar] [--saida=DIR]`, `agente="editor"`, ~US$ 0,03/bloco, ~US$ 0,15/live) gera a **thumb colagem** estilo canal de react, 3 variantes a/b/c pro "Testar e comparar" do Studio. **Layout:** 2 cenas lado a lado no fundo (à esquerda o assunto, preenchendo; à direita o contexto como **cartão** inteiro com borda branca, legível, sobre ele mesmo desfocado), círculo (a/c) ou seta (b) vermelha no rosto-chave da cena (Haar), o apresentador **recortado sem fundo** (rembg, local) à direita com contorno branco, e texto grande em 2 linhas com contorno preto grosso (`*palavra*` em amarelo 14, `[Nome]` em vermelho). **Cenas:** primeiro a **tela compartilhada** da própria live (a caixa de react que o `detectar_overlays` acha, ou frame inteiro sem rosto que **não** seja o estúdio: frame parecido com os do apresentador é ele virado de lado); faltou, completa com o **banco de personagens** citados nas tags/tema/título do bloco (o apresentador da live nunca vira cena dele mesmo). **Escolha:** uma chamada de visão `claude-haiku-5-5` (~US$ 0,0005) ordena ~6 expressões do apresentador (da fila do 07) e escolhe a cena do assunto e a de contexto, descrevendo cada uma **só pelo que está escrito nela** (legenda, púlpito, @ do post; nunca reconhece rosto). **Texto:** o editor (`_editor.texto_colagem`, opus, ~US$ 0,03) escreve 3 opções, de preferência em pergunta, com as mesmas regras de título (fiel à fala, sem palavrão/ofensa), e só põe `[Nome]` se a cena destacada é dessa pessoa. **Fallback:** sem rosto bom, sem recorte ou sem 2 cenas, o bloco fica com a thumb do template atual (07). Live sem fila do 07 (antiga) tem a fila calculada em memória. Registro em `thumbs/colagem/colagem.json` (cenas, textos, créditos, custo). **Nunca** mexe em bloco agendado/publicado/arquivado; `--saida=DIR` é prévia fora do `outputs/` e ignora essa trava.
- **Modo** (`config/thumb.json` → `colagem`): `teste` (atual) = o Curador roda o 07b no fim de cada vídeo novo em `thumbs/colagem/`, **sem mexer** nas thumbs que sobem, e o resumo aponta a pasta pra comparar; `padrao` = o Curador roda com `--aplicar` **antes** do revisor: a colagem vira `thumb_NN_a/b/c.png` e o crédito da foto do banco entra no fim da descrição do bloco (`_descricoes.trocar_creditos`, que troca o crédito antigo se a colagem for refeita com outra foto). O `08_descricao` **repõe** o crédito ao regerar o txt (lê o `colagem.json` da colagem aplicada). O revisor reconhece a colagem aplicada (cópia idêntica em `thumbs/colagem/`, `_colagem.colagem_aplicada`), confere os textos das **3 variantes** contra a fala (números, fatos e nomes têm que bater; grafia fora da oficial reprova) e aceita cena de tela ao fundo nesse formato. Título reprovado: o editor reescreve e a colagem é refeita com o texto novo (`07b --bloco=N --aplicar --sem-editor`, que usa o `texto_thumb` do bloco e sai com 2 se a colagem não sair); se não sair, as 3 variantes voltam pro template atual. Thumb reprovada (só ela) segue a troca de frame do 07 (`--proximo`), ou seja, volta pro template. `desligado` (ou sem o arquivo) = nada.
- **Apresentador e expressão:** o rosto do apresentador ocupa ~42% da altura (a cabeça fica com ~45-50%, `ROSTO_APRES`), ampliando o frame até 3x. O Haiku põe expressão **forte** (surpresa, indignação, riso, apontar) na frente da neutra. Recebe também as **pessoas citadas** no bloco (pelas grafias oficiais) e prefere a cena da live em que o nome de uma delas aparece **escrito**: é assim que entra quem não tem foto aberta no banco.
- **Grafias oficiais** (`config/grafias.json` + `scripts/_grafias.py`, US$ 0): nome, forma curta e grafias erradas conhecidas de cada personagem (ex.: Nikolas Ferreira, nunca "Nicolas"). O editor recebe a lista no pedido e a saída dele passa pelo `corrigir` (título, texto da thumb, textos da colagem); o revisor recebe a lista e reprova grafia errada; o `08_descricao` corrige o título; a colagem casa a grafia errada das tags com a foto certa do banco. Palavra solta seguida de outro nome próprio ("Nicolas Maduro") não é trocada. Personagem novo recorrente: acrescentar no JSON.
- **Banco de personagens** (`uv run py scripts/personagens.py lista|baixar`, US$ 0): só licença aberta do **Wikimedia Commons**, conferida pela API: CC0, domínio público, CC BY e "Attribution" (Agência Senado). CC BY-SA fica de fora (a thumb inteira teria que sair em BY-SA; `--aceitar-sa` libera). Nunca baixa de buscador, jornal ou rede social. Automático **só a foto oficial do item no Wikidata** (P18, pessoa = ser humano). A categoria do Commons não entra sozinha, porque no 1º teste o "Lula" virou o diagrama do PowerPoint da Lava Jato; ela só aparece como sugestão pra escolher à mão com `--arquivo="File:..."` (conferir que é a pessoa). Foto com ≥400 px e um rosto dominante; recorte rembg salvo em WebP (≤900 px de altura). `licencas.json` guarda fonte, arquivo do Commons, licença, autor e a linha `credito` que vai na descrição. Apelidos curtos (Flávio, Lula, Kim...) ficam no `APELIDOS` do script. `lista` mostra os nomes que mais aparecem nas tags dos blocos (`--outputs=` pra apontar outra pasta). No banco hoje (out/2026): Lula, Flávio, Kim, Arthur, Renan, André Fernandes, Nikolas e Guto. Sem foto aberta utilizável (só retrato pequeno do TSE, foto de grupo ou BY-SA): Janones, Pavanato, Lulinha, Amanda e Erika Hilton. Esses entram pela cena da live com o nome escrito.

O step 8 gera `descricoes.txt` (na pasta do vídeo) com, pra cada bloco: título sugerido (com contagem de chars), descrição (resumo + ganchos como bullets), créditos do canal, hashtags e lista de tags pronta pra colar no YouTube Studio. **Sem chamada de API** — reaproveita o que o LLM já produziu no `blocos.json`. A URL da fonte ("Conteúdo original") é preenchida automaticamente a partir de `inputs/<stem>.url` (salva pelo `01_baixar.py`); sem o arquivo, deixa o placeholder `[COLAR URL DA LIVE AQUI]` e avisa no log. O link do **nosso** canal (`scripts/_canal.py`) só entra na linha "Inscreva-se" — se o `.url` apontar pro nosso canal, o 08 ignora e o 09 se recusa a subir (crédito da fonte é obrigatório).

O step 9 (`uv run py scripts/09_upload.py <stem> [--dry-run] [--bloco=N] [--max=N] [--teste]`) é **off-pipeline**: sobe os `finalizados/video_NN_*.mp4` (prefere `_polido`) como **privados com `publishAt`** (agendamento público, publica sozinho no horário), usando título/descrição/tags do `descricoes.txt` (edição manual no txt vale) e a thumb escolhida (manual > a > b > c; >2 MB vira JPEG). Os slots saem de `config/upload.json` (padrão 1/dia às 18h, horário de Brasília) e continuam depois do último agendado em **qualquer** vídeo. O registro à prova de falha fica em `outputs/<pasta>/youtube.json`; com isso e com o `youtube_id` do banco, o script é **idempotente**: não re-sobe, e se só a thumb falhou, tenta só a thumb. Bloco com `[COLAR URL DA LIVE AQUI]` **não sobe** (crédito da fonte é obrigatório). Cota: upload ≈1600 + thumb 50 de 10.000/dia (zera à meia-noite do Pacífico), contada em `state/cota_youtube.json`; o script para **antes** de estourar. Custo US$ 0. Grava no banco `youtube_id` + `status=agendado` + `publish_at` e eventos com `agente="publicador"`. Credenciais em `secrets/` (gitignored, repo é público). **Sempre rode `--dry-run` antes.**

> **Trava da auditoria (`"auditoria_aprovada"` no `config/upload.json`, padrão `false`):** vídeo enviado por projeto de API **não auditado** fica **bloqueado como privado** no YouTube: não dá pra publicar nem recorrer, só reenviando (queima o vídeo). Com a flag `false`, o 09 **recusa** qualquer upload real (sai com exit 1 e explica o motivo; o `--dry-run` mostra o plano marcado como TRAVADO). A única exceção é o upload de **teste** (`--bloco=N --teste`, pra screencast/validação): sobe privado, sem data, com `[TESTE]` no título, registrado à parte em `outputs/<pasta>/youtube_teste.json`. Ele **não** conta como upload real (não grava `youtube_id`/status no banco nem ocupa slot), então o bloco continua liberado pro upload de verdade. Quando a auditoria for aprovada, mude a flag pra `true` e o 09 passa a subir privado + `publishAt`.

**Total por live:** ~15-25min de processamento, ~$0.20 de API (estimativa pós-otimização NVENC/concat-copy — validar na próxima live processada).

> **Formato canônico:** todo o pipeline (steps 4, 4b, 5, 6) produz vídeo **1280x720, 30fps, yuv420p, H.264 via NVENC (GPU), áudio AAC 44100 Hz stereo**. Isso é o que permite o `06_montar` concatenar com `-c copy` (instantâneo) em vez de re-encodar o vídeo inteiro. Se algum segmento sair fora do padrão, o montar imprime o formato de cada segmento (pra apontar o destoante), detecta a falha do `-c copy` e cai automaticamente pro fallback de re-encode (`filter_complex`). As constantes `VENC`/`AENC`/`SCALE_PAD` vivem em `scripts/_ffmpeg.py` (compartilhado) — pra trocar pra CPU/libx264, edite só lá.

## Identidade visual

- **Preto onça:** `#0A0A0A`
- **Amarelo 14:** `#F5C518` (cor oficial do partido)
- **Branco:** `#FFFFFF`
- **Fonte principal:** Anton (sans-serif bold condensada)
- **Marca do canal:** "MISSÃO EM CORTES" amarelo, canto inferior direito
- **Badge partido:** "MISSÃO 14" amarelo sobre preto, canto superior esquerdo
- **Tipografia em thumbnails:** Anton bold, sentence/CAPS estratégico, primeira linha amarela, restante branco

## Estrutura do vídeo final

```
[Cold open 15-30s] → [Intro 3s] → [Card de contexto 3s] → [Corte 5-7min] → [Outro 5s]
```

O cold open é o trecho de maior impacto do bloco, exibido antes da intro pra prender o espectador nos primeiros segundos. Se `cold_NN_*.mp4` não existir na pasta de cortes, o `06_montar.py` monta sem ele e loga um aviso.

Cada parte contribui pro "valor agregado" exigido pelo YouTube Partner Program (que pune `reused content` desde Jul/2025).

## Tratamento de overlays da live original

O `04_cortar.py` remove os overlays via **zoom programático** (`crop` + `scale`), sem blur. O recorte é **por fonte**, lido de `config/zoom.json` pelo stem (`{"<stem>": "crop=w:h:x:y"}` na fonte 1080p, aplicado antes do `scale=1280:720`). Stem **sem entrada** no config roda SEM zoom (só scale+pad) e loga um aviso — é o motivo nº1 de um corte sair com os overlays aparecendo: faltou cadastrar a fonte. O truque do recorte: deslocar a janela 16:9 pra direita encaixa-a **entre** os overlays das duas bordas das lives MBL:

- **valete.plus** (círculo, topo-esquerdo) → sai pela esquerda
- **contador de membros** (topo-direito) → sai pela direita
- **QR code / SmartCast** (base-direita) → sai pela direita

A parede neon "Academia MBL" é **cenário do estúdio** (não overlay) e fica. O zoom aplica-se ao corte **e** ao cold open. Fontes com o mesmo estúdio/enquadramento podem **reaproveitar** o mesmo valor (ex: `renan_live2`/`renan_vorcaro`/`renan_2turn_x_lula` = `1476:830:200:100`, zoom ~1.30); fonte com layout diferente precisa calibrar.

**Calibração visual:** `uv run py scripts/calibrar_zoom.py <video> [--zoom=..] [--fx=..] [--fy=..] [--salvar=<stem>]` gera previews antes/depois em `outputs/_calibracao/` pra dialar o recorte numa fonte nova; `--salvar=<stem>` grava direto no `config/zoom.json`. Depois de cadastrar/calibrar, re-corte com `uv run py scripts/pipeline.py <stem> --desde=4` (não re-transcreve nem re-segmenta).

**Alternativa manual:** editar o `corte_NN_*.mp4` no CapCut, salvar de volta na mesma subpasta com o mesmo nome, depois rodar steps 5 e 6.

## Prompt de segmentação (resumo)

Está em `prompts/segmentacao.md`. Objetivo: a LLM recebe a transcrição completa com timestamps e retorna JSON com 2-6 blocos temáticos de 5-7min, com início e fim em pontos naturais (não cortar no meio de frase ou raciocínio), título sugerido (frase longa pro YouTube), **`texto_thumb`** (2-5 palavras de impacto pra miniatura, distinto do título), score de potencial viral, ganchos, tags e **`cold_open`** (trecho de 15-30s de maior impacto dentro do bloco, com timestamps próprios). Modelo: `claude-sonnet-4-6`.

## Estado atual (Maio 2026)

- ✅ Pipeline MVP funcionando ponta-a-ponta
- ✅ Scripts aceitam argumento de arquivo (multi-live sem editar código)
- ✅ Identidade visual mínima pronta
- ✅ 1º vídeo publicado: Arthur do Val sobre Penélope (19/05/2026)
- ✅ Conta YouTube verificada
- ✅ Vídeo 01 do Renan (Flávio/STF/rachadinha) — publicado 22/05/2026
- ✅ Cold open implementado no pipeline (prompt + 04_cortar.py + 06_montar.py)
- ✅ Vídeo 02 do Renan (plano de governo / Bolsa Família) — publicado 23/05/2026
- ✅ `04_cortar.py` com remoção de overlays via **zoom programático** (`USE_ZOOM`/`ZOOM_CROP`) — substituiu o blur. Recorte 16:9 deslocado pra direita tira valete.plus (esq) + contador/QR (dir) sem blur. Calibrado com `scripts/calibrar_zoom.py` (02/06/2026)
- ✅ renan_live2 segmentado — 4 blocos: long house/masculinidade, Ciro Nogueira/Piauí, MBL como Roma (score 9), Datafolha/metodologia
- ⏳ Vídeos 03-06 do Renan (renan_live2) — corte + montagem + agendamento pendentes
- ✅ `05_cards.py` simplificado — removidos metadados de evento/data do card de contexto
- ✅ `07_thumb.py` — geração semi-automática de thumb (3 variantes por bloco com frames do cold open + layout adaptativo + gradient pra texto); desde 22/10/2026 a imagem cobre a thumb inteira (rosto grande no terço direito) e foge das sobras de overlay
- ✅ `08_descricao.py` — gera txt com título/descrição/tags/hashtags pronto pra YouTube Studio (sem chamada de API, reaproveita campos do `blocos.json`)
- ✅ `04b_polir.py` — polimento opcional via LLM: re-transcreve word-level, Claude conservador lista intervalos de silêncio/filler/problema técnico, ffmpeg aplica jump cut. `06_montar.py` ganhou flag `--polido`. Custo: ~$0.20/live.
- ✅ arthur_flavio_trump processado (lFJ1DSOjUw0) — 4 vídeos finalizados (+ versões polidas disponíveis), thumbs e descrições geradas (28/05/2026). Polimento removeu ~2min totais de tempo morto.
- ✅ **Cortes mais curtos pra retenção (02/06/2026)**: segmentação reduzida de 8-15min pra **5-7min** (e até 6 blocos por live), com ênfase em UM ponto por corte. Card de contexto 5s→3s (`05_cards.py`). Intro encurtada 5s→3s via trim no `06_montar.py` (`INTRO_SEGUNDOS`, gera `assets/intro_trim.mp4`). Hipótese: vídeos curtos e mais focados num tema só seguram melhor a retenção. Validar com métricas.
- ✅ **Otimização de performance do pipeline (02/06/2026)**: (1) **NVENC** (encoder na GPU) em todos os ffmpeg dos steps 4/4b/5/6 — libera a CPU e acelera; (2) **montagem sem re-encode** — todos os segmentos saem no formato canônico e o `06_montar` concatena com `-c copy` (fallback automático pra re-encode se falhar); (3) **04b não re-transcreve** — reaproveita `words.json` gerado no step 2; (4) `beam_size` da transcrição 5→2. Estimativa: tempo total de ~30-45min pra ~15-25min. Validar na próxima live.
- ✅ **Outputs reorganizados — pasta por vídeo (03/06/2026)**: de `outputs/<tipo>/<stem>/` + arquivos soltos pra `outputs/<AAAA-MM-DD>_<stem>/` (tudo do vídeo num lugar, ordenado por data). Steps 3-8 recebem só o stem; `scripts/_paths.py` resolve a pasta e **falha alto se ambíguo** (nunca roda no vídeo errado). Migração feita com `scripts/_migrar_outputs.py`. Processou 2 vídeos novos hoje: `arthur_flavio_taxar` (E Detalhe, zoom 1.32) e `renan_vorcaro` (live de reação com overlays pesados — crop do Renan, blocos de tela-compartilhada pra revisar manualmente).

- ✅ **QoL e robustez (12/06/2026)**: `scripts/pipeline.py` (orquestrador dos steps 2-8 com `--polir`/`--desde`); `scripts/01_baixar.py` (download + salva `inputs/<stem>.url`, que o `08_descricao.py` usa pra preencher a URL da fonte sozinho); `04b_polir.py` não duplica mais blocos no `polimento.json` em re-runs; `04_cortar.py` sai com exit 1 e resumo se algum ffmpeg falhar; `02_transcribe.py` valida o input antes de carregar o modelo.
- ✅ **Melhorias rodada 2 (12/06/2026)**: `04b` detecta silêncios >3s programaticamente (gap entre palavras, sem API — LLM só avalia fillers/problemas técnicos); `03` valida os timestamps do LLM (fim>início, cold_open dentro do bloco, fim≤duração do vídeo; salva `blocos_invalido.json` e sai com erro em vez de gravar lixo) e loga custo em $; `06` só re-normaliza intro/outro se o asset do Canva mudou e, quando o concat `-c copy` falha, imprime o formato de cada segmento pra apontar o destoante; `scripts/_ffmpeg.py` centraliza VENC/AENC/SCALE_PAD; whisper cai pra CPU se CUDA indisponível (02/04b).
- ✅ **Zoom por fonte + thumb manual (13/06/2026)**: `renan_2turn_x_lula` processado (live 2º turno x Lula, 3 blocos, `Lab_UcxeEDs`) reaproveitando o zoom do `renan_live2` (`1476:830:200:100`) — entrada nova no `config/zoom.json`, re-corte com `pipeline.py --desde=4 --polir`. **`07_thumb.py` ganhou modo manual** (`--bloco=N --t=MM:SS [--fonte=corte|cold]`): pra lives com tela compartilhada onde os frames automáticos (25/50/75% do cold open) caem na tela em vez do speaker, você escolhe o segundo na mão e gera `thumb_NN_manual.png` do corte completo. `--bloco` sozinho regenera só a/b/c daquele bloco.
- ✅ **Texto da thumb curto e impactante (13/06/2026)**: a thumb usava o `titulo_sugerido` (título de YouTube, frase longa) — estourava o layout e era truncado no meio da frase ("...ZEMA E É", incoerente). Agora: (1) prompt de segmentação gera `texto_thumb` (2-5 palavras de impacto, distinto do título); (2) `07_thumb.py` prefere `texto_thumb` → `tema`, **nunca** o `titulo_sugerido`, e **avisa** em vez de truncar em silêncio; (3) override manual `--titulo="..."` (exige `--bloco`) pra punchar thumbs de vídeos sem `texto_thumb`. Aplicado no `renan_2turn_x_lula` via `--titulo` (esse vídeo foi segmentado antes do campo existir).

## Roadmap pós-MVP

### Curto prazo (próximas semanas)
- Capítulos com timestamps na descrição
- Tipografia animada no intro (motion graphics no Canva)
- ~~Configuração de fonte por canal/speaker (coordenadas de overlay por fonte)~~ — feito pro zoom anti-overlay em `config/zoom.json` (crop por stem). Outras configs por fonte (ex: zoom de speaker) ainda podem migrar pra cá.
- ~~Narração própria de 20-30s no início~~ — substituído pelo cold open automático

### Médio prazo
- Diarização na transcrição (separar speakers automaticamente)
- ~~Legendas burned-in nos momentos de impacto (aumenta retenção)~~ — karaokê no vídeo inteiro via `04c_legendas.py` (Out/2026)
- ~~Templates de thumbnail dinâmicos via PIL (com frame do vídeo + texto)~~ — implementado em `07_thumb.py` (semi-automático, collage manual no Canva)
- Detecção automática de rosto no frame da thumb (face_recognition) pra escolher melhor variante sem 3 opções
- ~~Geração automática de descrição + tags via LLM~~ — `08_descricao.py` faz isso reaproveitando o LLM do step 3 (sem nova chamada). Capítulos com timestamps ainda pendentes (requer mapeamento de subtópicos dentro de cada bloco).

### Longo prazo
- Automação de upload via YouTube Data API
- Pipeline em batch (processar várias lives em sequência)
- Detecção automática de regiões de overlay via Claude com vision (remoção via zoom já existe via `USE_ZOOM`/`ZOOM_CROP`, calibrada à mão com `calibrar_zoom.py`)
- Métricas: correlacionar score do LLM com views/retenção reais

## Painel e camada de estado (Out/2026)

- **`state/pipeline.db`** (SQLite, WAL): tabelas `videos`, `blocos` e `eventos`. Escrita via `scripts/_eventos.py` (`evento()`, `upsert_video()`, `upsert_bloco()`); toda escrita é **best-effort** — falha de banco vira aviso no stderr, nunca exceção.
- **Status de bloco**: AUTO (`segmentado` → `cortado` → `montado`, derivados dos arquivos) e DECISÃO (`revisao`, `aprovado`, `quarentena`, `descartado`, `agendado`, `publicado`, `arquivado`, setados por agente com `forcar_status=True`). O `sincronizar_estado.py` **nunca rebaixa** um status de decisão.
- **Kanban**: `aprovado` cai em **Pronto para publicar** e `agendado` (já no YouTube com `publish_at`) em **Agendado**. A métrica "Agendados" do topo conta só `agendado`.
- **Arquivado = conteúdo antigo**: o `sincronizar_estado.py` (botão Sincronizar do painel) arquiva sozinho os blocos de live com **mais de 15 dias** (data da pasta `outputs/<AAAA-MM-DD>_<stem>/`) que ainda não foram pro YouTube, com motivo "conteúdo antigo". Agendado, publicado e descartado não são tocados. Os Shorts não postados da live velha ganham `"arquivado": "conteúdo antigo"` no `shorts/shorts.json` (saem do estoque; o `10_shorts` preserva a marca ao regerar). Arquivado some do kanban e das métricas, o 09 não sobe e o 11 não revisa. Pra resgatar um bloco, mude o status à mão no banco, mas a próxima sincronização arquiva de novo se a live continuar velha.
- **Eventos**: todo step/agente registra `inicio`/`ok`/`falha` (+ `llm` com tokens e custo). Campo `agente` ∈ `pipeline | curador | editor | revisor | publicador | analista` — é o que alimenta o "custo por agente" do painel.
- **Regra pra agentes novos**: registrar evento com o próprio nome em `agente` e, se chamar LLM, `tokens_in`/`tokens_out`/`custo_usd`.
- Rodar: `uv run streamlit run painel/app.py`.

## Git flow

- **`main`**: só o que está rodando "em produção" (o que publica no canal). Recebe merge de `release/*` ou `hotfix/*`, nunca commit direto.
- **`develop`**: integração. Toda feature nasce daqui e volta pra cá via PR.
- **`feature/<nome>`**: uma frente por branch (ex: `feature/painel-estado`, `feature/upload-api`, `feature/agente-revisor`).
- **`fix/<nome>`**: bug em `develop`. **`hotfix/<nome>`**: bug em `main`, sai de `main` e volta pra `main` + `develop`.
- **Commits**: Conventional Commits em português — `feat(escopo):`, `fix(escopo):`, `chore:`, `docs:`, `refactor:`. Escopos usuais: `pipeline`, `estado`, `painel`, `upload`, `agentes`, `thumb`, `shorts`.
- **Claude Code**: sempre trabalhar numa branch `feature/*`/`fix/*` a partir de `develop`; nunca commitar em `main`/`develop` direto; commits pequenos e atômicos; abrir PR pra `develop` no fim da frente.
- **CI** (`.github/workflows/ci.yml`): `uv sync --locked` + `uv run pytest -q` em todo PR e push pra `develop`/`main`. As duas branches são protegidas e exigem CI verde.

## Fluxo de desenvolvimento com agentes

**Papéis:** o Gu é o **PO**: passa tarefas macro, não revisa código nem aprova PR. O Claude Code (agente principal) é o **tech lead**: planeja, implementa e aprova.

**Duas pastas (o painel nunca cai):**
- `missao-em-cortes/` (principal) fica **sempre na `develop`**. Aqui rodam o painel, o pipeline e os scripts reais, com `inputs/`, `outputs/` e `state/` reais. **Nunca trocar de branch aqui.** Trocar removia `painel/` do disco no meio do uso, e o Streamlit caía.
- `../missao-em-cortes-dev/` é o **worktree de dev**: toda `feature/*`/`fix/*`/`docs/*` é criada, editada, testada e commitada lá (`git -C ../missao-em-cortes-dev ...`, `uv run --directory ../missao-em-cortes-dev pytest -q`). Ele não tem `inputs/`/`outputs/`/`state/`. Os testes usam fixtures, e execução com dados reais roda na principal depois do merge.
- O Claude Code é **aberto na pasta principal**, e `tarefa.py` roda **sempre de lá**: é lá que fica o banco que o painel lê, e os hooks (`$CLAUDE_PROJECT_DIR`) gravam nele.
- Nova frente: `git -C ../missao-em-cortes-dev switch -c feature/x origin/develop` (depois de `git fetch`). Se o worktree não existir, recrie com `git worktree add ../missao-em-cortes-dev -b feature/x develop` + `uv sync` lá dentro (o uv cria hardlinks do cache, então não ocupa disco extra).
- Depois de cada merge em develop: `git pull --ff-only` na principal (+ `uv sync` se o `pyproject.toml` mudou). O painel recarrega uma vez, já com a versão nova.

1. **Implementar** numa `feature/*` (ou `fix/*`) saindo de `develop`. PRs pequenos e focados.
2. **Testar:** chamar o subagent `testador` (roda `uv run pytest -q` e escreve testes pro código novo/alterado, sempre com mock).
3. **Revisar:** chamar o subagent `revisor-codigo` (revisa `git diff develop...HEAD` contra as regras deste arquivo).
4. **Corrigir** se algum reprovar e chamar de novo, no **máximo 3 rodadas**. Se não resolver, parar e explicar o problema pro Gu em linguagem de produto.
5. **PR pra `develop`** só com os dois APROVADOS. A descrição tem: o que mudou (3-5 linhas), como foi testado, custo de API estimado da feature e "decisões pendentes para o Gu".
6. **Merge em `develop` é do tech lead:** com testador APROVADO + revisor APROVADO + CI verde, `gh pr merge --squash --delete-branch` sem perguntar.
7. **Quebrou depois do merge?** Primeiro `git revert` (numa `fix/*`, via PR), depois investigar.
8. **Release pra `main`:** mandar pro Gu um resumo de produto (o que muda pro canal, risco, custo) em até 5 linhas, sem detalhe técnico, e **esperar o "ok"**.

**Tarefas no painel:** toda tarefa macro do Gu vira uma linha em `tarefas` via `scripts/tarefa.py`; mova a etapa a cada transição (implementar → testador → revisor → merge):

```
uv run py scripts/tarefa.py nova "Upload via API do YouTube" --branch feature/upload-api   # → #N, backlog
uv run py scripts/tarefa.py mover N fazendo --responsavel tech-lead
uv run py scripts/tarefa.py mover N testando --responsavel testador
uv run py scripts/tarefa.py resultado N APROVADO|REPROVADO --msg "..."                  # REPROVADO soma rodada
uv run py scripts/tarefa.py mover N revisando --responsavel revisor-codigo
uv run py scripts/tarefa.py mover N pronto                                             # depois do merge
```

Pergunta pro Gu = `tarefa.py decisao N "pergunta?"` (faixa amarela no painel), **além** de perguntar no chat; quando ele responder, `tarefa.py decisao N --resolvida`. A atividade dos subagents e o fim de cada turno do tech-lead entram sozinhos via hooks (`.claude/settings.json` → `scripts/hook_agente.py`, penduram na tarefa ativa). Gasto de API paga dentro de uma tarefa: rode o script com `MISSAO_TAREFA=N` pra o custo cair nela.

**Perguntar SEMPRE antes de:** publicar no YouTube pela primeira vez numa feature nova · gastar API paga fora de teste · ação destrutiva (apagar arquivo/branch, force push, reset) · mudar segredo/credencial.

**Status:** toda sexta (ou quando o Gu pedir "status"), um resumo em linguagem de produto: o que foi entregue, o que quebrou e foi corrigido, custo de API da semana e próximas entregas.

## Convenções pra colaboração com Claude Code

- **Idioma:** português brasileiro casual
- **Filosofia:** MVP sempre — cortar over-engineering, validar antes de polir
- **Decisões técnicas:** preferir simples a sofisticado; ffmpeg + Python puro batem qualquer SaaS sofisticado pra esse caso
- **Tom:** direto, sem enrolar, com humor leve quando couber
- **Sobre custos:** transparência sempre — toda chamada de API deve ter estimativa de custo no log

## Dependências externas

- **Conta Anthropic API** (`.env` com `ANTHROPIC_API_KEY`) — créditos pré-pagos
- **Conta YouTube verificada** — necessário pra upload >15min
- **Canva (free ou Pro)** — pra intro/outro/thumbnail
- **GTX 1650 ou superior** — pra rodar faster-whisper em GPU (cai pra CPU se sem GPU, mas é 4-5x mais lento)
- **ffmpeg + cuDNN/cuBLAS no PATH** — pro pipeline rodar (no Windows, requer `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` instalados via uv)
- **NVENC (encoder H.264 na GPU)** — os steps 4/4b/5/6 encodam via `h264_nvenc`. A GTX 1650 (Turing) suporta. Se rodar numa máquina sem NVENC, troque `VENC` em `scripts/_ffmpeg.py` pra `["-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p"]`

## Custos operacionais previstos

| Item | Custo mensal |
|---|---|
| Anthropic API (~20 lives/mês, com polimento) | ~$8-9 |
| Canva Pro (opcional) | $13 |
| YouTube/domínio | grátis (por enquanto) |
| **Total mínimo** | **~$5/mês** |

## Notas técnicas (Windows)

- Todos os scripts têm `sys.stdout.reconfigure(encoding='utf-8')` no topo — necessário pra emojis e caracteres especiais não quebrarem no terminal Windows (cp1252)
- Permissões do Claude Code ficam em `.claude/settings.local.json` (não commitado)
- Formato de download recomendado: `-f "299+140"` (1080p60 mp4 + m4a 129k)

## Notas finais

Este projeto é fruto de uma sessão de desenvolvimento intensa em Maio/2026 onde o pipeline saiu do zero ao MVP funcional em menos de um dia. A filosofia foi sempre cortar escopo, validar rápido e iterar depois — vide as várias coisas marcadas como "pós-MVP" acima. **Não otimizar antes da hora.**
