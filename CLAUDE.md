# CLAUDE.md — Missão em Cortes

> Contexto do projeto para o Claude Code. Lido automaticamente no início de cada sessão.

## O projeto

Canal de YouTube de cortes de lives, entrevistas, debates e eventos do **Partido Missão (legenda 14)**, partido brasileiro de direita liberal fundado em 2025, ligado ao MBL. O canal pega vídeos longos (lives de 1-2h ou entrevistas de 30-60min) das principais figuras do partido (Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias, Amanda Vettorazzo) e gera **vários vídeos por fonte**, cada um focado num único ponto, otimizados para monetização no YouTube Partner Program. O alvo de duração é **5-7min por corte** (mudança de Jun/2026 pra melhorar retenção) — cortes curtos e focados num assunto só. Lives longas naturalmente rendem mais blocos.

**Nome do canal:** Missão em Cortes  
**Handle proposto:** @missaoemcortes

## Postura editorial

- Simpática ao Partido Missão, mas com independência crítica
- Linha editorial: direita liberal, anti-bolsonarista crítica
- Títulos podem ser ousados/com gancho, **sem distorcer o que foi dito**
- Mantém crédito visual à fonte original (logo MBL/Valete preservado nos cortes)
- Overlays desatualizados: removidos via zoom programático (`USE_ZOOM`/`ZOOM_CROP` no `04_cortar.py`), sem blur — ver "Tratamento de overlays"

## Stack técnica

- **Python 3.10+** com **uv** (gerenciador de dependências)
- **faster-whisper** — transcrição local (modelo `medium`, GPU NVIDIA via CUDA)
- **Anthropic API** — segmentação temática via `claude-sonnet-4-6` (~$0.20/live)
- **ffmpeg** — corte com fades, montagem final
- **Pillow (PIL)** — geração programática de cards de contexto
- **yt-dlp** — download das lives do YouTube
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
│   │   ├── cortes/                   # corte_NN_<slug>.mp4 + cold_NN_<slug>.mp4 (+ _polido)
│   │   ├── cards/                    # card_NN.png e card_NN.mp4
│   │   ├── thumbs/                   # thumb_NN_a/b/c.png (3 variantes pra escolher)
│   │   └── finalizados/              # video_NN_<slug>.mp4 (cold+intro+card+corte+outro)
│   ├── _calibracao/                  # scratch da calibração de zoom (dev)
│   ├── _debug/                       # dumps de resposta do LLM quando falha o parse
│   └── _old/                         # artefatos legados (pré-reorganização)
├── assets/
│   ├── intro.mp4                     # do Canva, sem áudio
│   ├── intro_norm.mp4                # normalizado com áudio silencioso
│   ├── outro.mp4                     # do Canva, com voz IA ("inscreva-se")
│   ├── outro_norm.mp4
│   └── fonts/Anton-Regular.ttf
├── scripts/                          # Pipeline numerado
│   ├── pipeline.py                   # orquestrador: roda (02)→03→04→(4b)→05→06→07→08 em sequência
│   ├── 01_baixar.py                  # yt-dlp + salva inputs/<stem>.url
│   ├── 02_transcribe.py
│   ├── 03_segmentar.py
│   ├── 04_cortar.py
│   ├── 04b_polir.py                  # opcional: jump cut de silêncios/fillers via LLM
│   ├── 05_cards.py
│   ├── 06_montar.py
│   ├── 07_thumb.py                   # thumbs semi-automáticas (off-pipeline)
│   ├── 08_descricao.py               # gera txt com titulo+descricao+tags pro YouTube
│   ├── calibrar_zoom.py              # off-pipeline: calibra visualmente o ZOOM_CROP anti-overlay
│   ├── _paths.py                     # resolve outputs/<data>_<stem>/ por stem (helper compartilhado)
│   ├── _ffmpeg.py                    # formato canônico (VENC/AENC/SCALE_PAD) compartilhado pelos steps 4/4b/5/6
│   └── _migrar_outputs.py            # one-off: migrou a estrutura antiga pro layout por vídeo
├── prompts/
│   └── segmentacao.md                # Prompt do LLM pra topic segmentation
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
| 5 | Cards de contexto | `uv run py scripts/05_cards.py <stem>` | <1min | grátis |
| 6 | Montagem final | `uv run py scripts/06_montar.py <stem> [--polido]` | ~1-2min (concat copy) | grátis |
| 7* | Thumbs (off-pipeline) | `uv run py scripts/07_thumb.py <stem>` | <1min | grátis |
| 8 | Descrições pro YouTube | `uv run py scripts/08_descricao.py <stem>` | <5s | grátis |

> **Orquestrador:** `uv run py scripts/pipeline.py <stem> [--polir] [--desde=N]` roda os steps 2→8 em sequência (mesmos scripts, para na primeira falha e mostra o `--desde` pra retomar). Sem `--desde`, pula o step 2 se a transcrição já existe. `--polir` inclui o 04b e monta com `--polido`. O download (step 1) fica de fora — rode antes, uma vez.

> **Organização dos outputs:** uma pasta por vídeo em `outputs/<AAAA-MM-DD>_<stem>/` (data de processamento; prefixo ISO faz a ordenação alfabética = cronológica). Os steps 3-8 recebem só o **stem** (ex: `renan_vorcaro`) e o `scripts/_paths.py` resolve a pasta. Se houver mais de uma pasta pro mesmo stem (ambíguo), o script **falha alto** e lista as opções em vez de adivinhar — passe então o nome completo da pasta (ex: `2026-06-03_renan_vorcaro`). O step 2 (transcrição) recebe o caminho do vídeo em `inputs/` e cria/reusa a pasta do stem. Reprocessar um stem **reusa** a mesma pasta (não duplica).

O step 4 gera **dois arquivos por bloco**: `corte_NN_<slug>.mp4` (corte completo, fade out 0.5s) e `cold_NN_<slug>.mp4` (cold open 15-30s, fade in+out 0.4s). Se o JSON não tiver `cold_open`, gera só o corte e loga um aviso.

O step 4b é **opcional** — pra cada `corte_NN_*.mp4` ele: (1) reaproveita os word-level timestamps do `words.json` (gerado no step 2), fatiando pelo intervalo do bloco — **não re-transcreve** (cai pra re-transcrição via whisper só se o words.json não existir), (2) detecta silêncios >3s **programaticamente** (gap entre palavras consecutivas — determinístico, sem API, nunca nos primeiros 30s), (3) manda pro Claude com prompt conservador só o que exige julgamento (fillers extremos e problemas técnicos), funde os intervalos e aplica jump cut via `ffmpeg filter_complex select/aselect` e salva `corte_NN_<slug>_polido.mp4` na mesma pasta. Filtro defensivo descarta intervalos com motivo "ignorar/manter/abaixo do limiar". Suporta `--bloco=N` pra reprocessar só um bloco. Os intervalos ficam em `polimento.json`; `--reaplicar` re-aplica os intervalos salvos aos cortes sem chamar o LLM (útil após re-cortar, ex: mudou o zoom). Cold opens **não** são polidos. Pra usar os polidos na montagem: `06_montar.py <stem> --polido` (gera `video_NN_<slug>_polido.mp4`).

O step 7 é opcional e não afeta a montagem — gera 3 variantes de thumb por bloco (`thumb_NN_a/b/c.png`) com frames extraídos a 25/50/75% do cold open. Você escolhe a melhor variante e finaliza no Canva (colar collage de figuras na metade direita). Layout: frame do speaker deslocado pra direita (`FRAME_X=150`), título adaptativo (fonte 96→64 dependendo do comprimento), gradient escuro embaixo pra contraste.

O step 8 gera `descricoes.txt` (na pasta do vídeo) com, pra cada bloco: título sugerido (com contagem de chars), descrição (resumo + ganchos como bullets), créditos do canal, hashtags e lista de tags pronta pra colar no YouTube Studio. **Sem chamada de API** — reaproveita o que o LLM já produziu no `blocos.json`. A URL da fonte é preenchida automaticamente a partir de `inputs/<stem>.url` (salva pelo `01_baixar.py`); sem o arquivo, deixa o placeholder `[COLAR URL DA LIVE AQUI]` e avisa no log.

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

O `04_cortar.py` remove os overlays via **zoom programático** (`crop` + `scale`), sem blur. Ativado por `USE_ZOOM = True` com o recorte em `ZOOM_CROP` (`crop=w:h:x:y` na fonte 1080p, aplicado antes do `scale=1280:720`). O truque: deslocar o recorte 16:9 pra direita encaixa a janela **entre** os overlays das duas bordas das lives MBL:

- **valete.plus** (círculo, topo-esquerdo) → sai pela esquerda
- **contador de membros** (topo-direito) → sai pela direita
- **QR code / SmartCast** (base-direita) → sai pela direita

A parede neon "Academia MBL" é **cenário do estúdio** (não overlay) e fica. O zoom aplica-se ao corte **e** ao cold open. Valor atual `1476:830:200:100` (zoom ~1.30, mantém 59% do quadro), calibrado na renan_live2.

**Calibração visual:** `uv run py scripts/calibrar_zoom.py <video> [--zoom=..] [--fx=..] [--fy=..]` gera previews antes/depois em `outputs/_calibracao/` pra dialar o recorte numa fonte nova antes de fixar o `ZOOM_CROP`. Se uma live tiver layout diferente, recalibre e ajuste a constante (ou, futuramente, mover pra config por fonte — ver roadmap).

**Alternativa manual:** editar o `corte_NN_*.mp4` no CapCut, salvar de volta na mesma subpasta com o mesmo nome, depois rodar steps 5 e 6.

## Prompt de segmentação (resumo)

Está em `prompts/segmentacao.md`. Objetivo: a LLM recebe a transcrição completa com timestamps e retorna JSON com 2-6 blocos temáticos de 5-7min, com início e fim em pontos naturais (não cortar no meio de frase ou raciocínio), título sugerido, score de potencial viral, ganchos, tags e **`cold_open`** (trecho de 15-30s de maior impacto dentro do bloco, com timestamps próprios). Modelo: `claude-sonnet-4-6`.

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
- ✅ `07_thumb.py` — geração semi-automática de thumb (3 variantes por bloco com frames do cold open + layout adaptativo + gradient pra texto), metade direita preta pro collage no Canva
- ✅ `08_descricao.py` — gera txt com título/descrição/tags/hashtags pronto pra YouTube Studio (sem chamada de API, reaproveita campos do `blocos.json`)
- ✅ `04b_polir.py` — polimento opcional via LLM: re-transcreve word-level, Claude conservador lista intervalos de silêncio/filler/problema técnico, ffmpeg aplica jump cut. `06_montar.py` ganhou flag `--polido`. Custo: ~$0.20/live.
- ✅ arthur_flavio_trump processado (lFJ1DSOjUw0) — 4 vídeos finalizados (+ versões polidas disponíveis), thumbs e descrições geradas (28/05/2026). Polimento removeu ~2min totais de tempo morto.
- ✅ **Cortes mais curtos pra retenção (02/06/2026)**: segmentação reduzida de 8-15min pra **5-7min** (e até 6 blocos por live), com ênfase em UM ponto por corte. Card de contexto 5s→3s (`05_cards.py`). Intro encurtada 5s→3s via trim no `06_montar.py` (`INTRO_SEGUNDOS`, gera `assets/intro_trim.mp4`). Hipótese: vídeos curtos e mais focados num tema só seguram melhor a retenção. Validar com métricas.
- ✅ **Otimização de performance do pipeline (02/06/2026)**: (1) **NVENC** (encoder na GPU) em todos os ffmpeg dos steps 4/4b/5/6 — libera a CPU e acelera; (2) **montagem sem re-encode** — todos os segmentos saem no formato canônico e o `06_montar` concatena com `-c copy` (fallback automático pra re-encode se falhar); (3) **04b não re-transcreve** — reaproveita `words.json` gerado no step 2; (4) `beam_size` da transcrição 5→2. Estimativa: tempo total de ~30-45min pra ~15-25min. Validar na próxima live.
- ✅ **Outputs reorganizados — pasta por vídeo (03/06/2026)**: de `outputs/<tipo>/<stem>/` + arquivos soltos pra `outputs/<AAAA-MM-DD>_<stem>/` (tudo do vídeo num lugar, ordenado por data). Steps 3-8 recebem só o stem; `scripts/_paths.py` resolve a pasta e **falha alto se ambíguo** (nunca roda no vídeo errado). Migração feita com `scripts/_migrar_outputs.py`. Processou 2 vídeos novos hoje: `arthur_flavio_taxar` (E Detalhe, zoom 1.32) e `renan_vorcaro` (live de reação com overlays pesados — crop do Renan, blocos de tela-compartilhada pra revisar manualmente).

- ✅ **QoL e robustez (12/06/2026)**: `scripts/pipeline.py` (orquestrador dos steps 2-8 com `--polir`/`--desde`); `scripts/01_baixar.py` (download + salva `inputs/<stem>.url`, que o `08_descricao.py` usa pra preencher a URL da fonte sozinho); `04b_polir.py` não duplica mais blocos no `polimento.json` em re-runs; `04_cortar.py` sai com exit 1 e resumo se algum ffmpeg falhar; `02_transcribe.py` valida o input antes de carregar o modelo.
- ✅ **Melhorias rodada 2 (12/06/2026)**: `04b` detecta silêncios >3s programaticamente (gap entre palavras, sem API — LLM só avalia fillers/problemas técnicos); `03` valida os timestamps do LLM (fim>início, cold_open dentro do bloco, fim≤duração do vídeo; salva `blocos_invalido.json` e sai com erro em vez de gravar lixo) e loga custo em $; `06` só re-normaliza intro/outro se o asset do Canva mudou e, quando o concat `-c copy` falha, imprime o formato de cada segmento pra apontar o destoante; `scripts/_ffmpeg.py` centraliza VENC/AENC/SCALE_PAD; whisper cai pra CPU se CUDA indisponível (02/04b).

## Roadmap pós-MVP

### Curto prazo (próximas semanas)
- Capítulos com timestamps na descrição
- Tipografia animada no intro (motion graphics no Canva)
- Configuração de fonte por canal/speaker (YAML com coordenadas de overlay por fonte)
- ~~Narração própria de 20-30s no início~~ — substituído pelo cold open automático

### Médio prazo
- Diarização na transcrição (separar speakers automaticamente)
- Legendas burned-in nos momentos de impacto (aumenta retenção)
- ~~Templates de thumbnail dinâmicos via PIL (com frame do vídeo + texto)~~ — implementado em `07_thumb.py` (semi-automático, collage manual no Canva)
- Detecção automática de rosto no frame da thumb (face_recognition) pra escolher melhor variante sem 3 opções
- ~~Geração automática de descrição + tags via LLM~~ — `08_descricao.py` faz isso reaproveitando o LLM do step 3 (sem nova chamada). Capítulos com timestamps ainda pendentes (requer mapeamento de subtópicos dentro de cada bloco).

### Longo prazo
- Automação de upload via YouTube Data API
- Pipeline em batch (processar várias lives em sequência)
- Detecção automática de regiões de overlay via Claude com vision (remoção via zoom já existe via `USE_ZOOM`/`ZOOM_CROP`, calibrada à mão com `calibrar_zoom.py`)
- Métricas: correlacionar score do LLM com views/retenção reais

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
