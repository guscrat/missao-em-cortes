# CLAUDE.md — Missão em Cortes

> Visão geral + ponteiros. O detalhe mora nas skills de `.claude/skills/` (carregadas sob demanda) e em `docs/`.

## O projeto

Canal de YouTube de cortes de lives, entrevistas, debates e eventos do **Partido Missão (legenda 14)**, partido brasileiro de direita liberal fundado em 2025, ligado ao MBL (Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias, Amanda Vettorazzo). Cada vídeo longo vira **vários cortes de 8-30 min** (o tamanho é o do assunto: **coerência acima da duração**, nunca cortar no meio da fala) + um Short por bloco (até 3 min), otimizados pro YouTube Partner Program.

**Canal:** https://www.youtube.com/channel/UCRJDgbBEndOdbNaiwzFju2g (handle `@missaoemcortes-14`; o `@missaoemcortes` NÃO é nosso).

Postura: simpática ao partido com independência crítica; títulos ousados **sem distorcer a fala**; crédito à fonte sempre.

## Skills (leia a skill antes de mexer na área)

| Skill | Quando |
|---|---|
| `editorial-missao` | título, `texto_thumb`, descrição, segmentação (03/08), revisor (11), editor, grafias, Curador (13) |
| `thumb-colagem` | thumbs: template pelo rosto (07), colagem (07b), banco de personagens/licenças, identidade visual |
| `youtube-compliance` | YPP, crédito da fonte, trava da auditoria, OAuth (2 projetos), upload (09), métricas (12), canal (14), `publicacao.txt` |
| `release` | git flow, as duas pastas, testador/revisor, PR, merge, release pra main, status de sexta |
| `painel-eventos` | banco `state/pipeline.db`, eventos/custo por agente, status de bloco, kanban, arquivamento, `tarefa.py`/hooks |

Docs: `docs/pipeline.md` (detalhes dos steps 4/4b/4c/5/6/10, zoom anti-overlay, formato canônico, dependências, custos) · `docs/historico.md` (estado e roadmap).

## Stack

Python 3.10+ com **uv** · **faster-whisper** `medium` (GPU CUDA, cai pra CPU) · **Anthropic API** (segmentação `claude-sonnet-4-6`; polimento 04b `claude-sonnet-5-5`; revisor/editor/Curador `claude-opus-5-5`; visão da colagem `claude-haiku-5-5`) · **ffmpeg** com NVENC · **Pillow** · **yt-dlp** (sempre `uv run yt-dlp`, com solver JS) · **OpenCV** headless (rosto, Haar) · **rembg** (recorte da colagem) · **Canva** (intro/outro, fora do pipeline) · **Streamlit** (painel).

## Estrutura

```
inputs/           <stem>.mp4 + <stem>.url (URL da fonte, salva pelo 01)
outputs/<AAAA-MM-DD>_<stem>/   uma pasta por vídeo (transcrição, blocos.json, cortes/, thumbs/, shorts/, finalizados/...)
assets/           intro/outro (Canva), fonts/Anton, logoCanal.png, personagens/ (fotos + licencas.json)
config/           zoom.json · canais.json · upload.json · thumb.json · grafias.json
prompts/          segmentacao.md
state/            pipeline.db, curador_resumo.md, canal.json... (gitignored)
secrets/          tokens/clients OAuth (gitignored, repo é público)
painel/           app.py (Streamlit, só lê o banco) + time_dev.py
tests/            pytest, tudo mockado
.claude/          agents/ (testador, revisor-codigo) · skills/ · settings.json (hooks)
```

Scripts (`scripts/`):
- **Pipeline:** `pipeline.py` (orquestrador) · `01_baixar` · `02_transcribe` · `03_segmentar` · `04_cortar` · `04b_polir` · `04c_legendas` · `05_cards` · `06_montar` · `08_descricao`
- **Off-pipeline:** `07_thumb` · `07b_colagem` · `09_upload` · `10_shorts` · `11_revisor` · `12_metricas` · `13_curador` · `14_canal` · `15_placar` · `16_thumb_ab` · `dia_d` · `calibrar_zoom` · `personagens` · `sincronizar_estado` · `tarefa` · `hook_agente` · `curador_oculto` (Agendador → Curador sem janela)
- **Helpers (`_*.py`):** `_paths` (resolve pasta por stem, falha alto se ambíguo) · `_ffmpeg` (formato canônico) · `_eventos` (banco) · `_descricoes` · `_legenda` · `_grafias` · `_editor` · `_colagem` · `_thumb_rosto` · `_publicacao` · `_google` · `_youtube_leitura` · `_canal` · `_fronteira` (ponto de corte natural: fim de frase + pausa, faixas de duração)

## Pipeline

| # | Etapa | Comando | Custo |
|---|---|---|---|
| 1 | Download | `uv run py scripts/01_baixar.py URL <stem>` | grátis |
| 2 | Transcrição | `uv run py scripts/02_transcribe.py inputs/<stem>.mp4` | grátis (local, ~6-12min) |
| 3 | Segmentação | `uv run py scripts/03_segmentar.py <stem>` | ~$0.20 |
| 4 | Cortes (+ cold open) | `uv run py scripts/04_cortar.py <stem>` | grátis |
| 4b* | Polimento (jump cut) | `uv run py scripts/04b_polir.py <stem> [--sem-llm]` | ~$0.18 / $0 |
| 4c | Legenda karaokê (padrão) | `uv run py scripts/04c_legendas.py <stem> [--polido]` | grátis |
| 5 | Cards de contexto | `uv run py scripts/05_cards.py <stem>` | grátis |
| 6 | Montagem final | `uv run py scripts/06_montar.py <stem> [--polido] [--legendado]` | grátis |
| 8 | Descrições | `uv run py scripts/08_descricao.py <stem>` | grátis |

**Orquestrador:** `uv run py scripts/pipeline.py <stem> [--polir] [--sem-llm] [--sem-legendas] [--desde=N] [--bloco=N]` roda 2→8, para na primeira falha e mostra o `--desde` pra retomar (pula o 2 se a transcrição existe; `--desde=4c` retoma do 04c; `--bloco=N` refaz só 4→4b→4c→6 de um bloco). O download fica de fora. Steps 3-8 recebem só o **stem**.

Vídeo final: `[Cold open 15-30s] → [Intro 3s] → [Card 3s] → [Corte 8-30min] → [Outro 5s]`.

Overlays da live saem por **zoom por fonte** (`config/zoom.json`); stem sem entrada roda sem zoom e avisa. Calibrar: `calibrar_zoom.py <video> --salvar=<stem>`, depois `pipeline.py <stem> --desde=4`. Detalhes em `docs/pipeline.md`.

Agentes off-pipeline (detalhes nas skills): Curador 13 às 17h decide o que processar · revisor 11 aprova/quarentena/descarta · 10 gera Shorts · 09 sobe longos e Shorts (`--shorts`, **travado até a auditoria**; dia D: `dia_d.py` + skill) · 12/14/15 só leem o canal (15 = placar do YPP, 1x/dia pelo Curador) · 16 registra o resultado do "Testar e comparar" das thumbs (modo `ab`: a = template, b/c = colagem).

## Regras transversais

- **Custo transparente:** toda chamada de API loga estimativa de custo e registra evento `llm` no banco (skill `painel-eventos`).
- **Perguntar SEMPRE antes de:** publicar no YouTube pela primeira vez numa feature nova · gastar API paga fora de teste · ação destrutiva (apagar arquivo/branch, force push, reset) · mudar segredo/credencial.
- **Pasta principal sempre na `develop`**; código novo em worktree/feature branch (skill `release`).
- Nunca mexer em bloco `agendado`/`publicado`/`arquivado`.

## Identidade visual

Preto onça `#0A0A0A` · **Amarelo 14** `#F5C518` · Branco `#FFFFFF` · fonte **Anton** · marca "MISSÃO EM CORTES" amarelo no canto inferior direito · badge "MISSÃO 14" no superior esquerdo.

## Convenções

- Português brasileiro casual; direto, sem enrolar, humor leve quando couber.
- **MVP sempre:** cortar over-engineering, validar antes de polir, preferir simples (ffmpeg + Python puro). Não otimizar antes da hora.
- Windows: todo script tem `sys.stdout.reconfigure(encoding='utf-8')` no topo (emojis no cp1252). Permissões locais em `.claude/settings.local.json` (não commitado).
