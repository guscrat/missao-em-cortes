# Pipeline — detalhes técnicos dos steps

> Referência puxada do CLAUDE.md. Leia quando for mexer num step de vídeo (04, 04b, 04c, 05, 06, 10), no zoom anti-overlay ou no formato canônico. Thumbs (07/07b) estão na skill `thumb-colagem`; revisor/editor/Curador na `editorial-missao`; upload/métricas/canal na `youtube-compliance`.

## Organização dos outputs

Uma pasta por vídeo em `outputs/<AAAA-MM-DD>_<stem>/` (data de processamento; prefixo ISO faz a ordenação alfabética = cronológica). Os steps 3-8 recebem só o **stem** (ex: `renan_vorcaro`) e o `scripts/_paths.py` resolve a pasta. Se houver mais de uma pasta pro mesmo stem (ambíguo), o script **falha alto** e lista as opções em vez de adivinhar — passe então o nome completo da pasta (ex: `2026-06-03_renan_vorcaro`). O step 2 (transcrição) recebe o caminho do vídeo em `inputs/` e cria/reusa a pasta do stem. Reprocessar um stem **reusa** a mesma pasta (não duplica).

Conteúdo de cada pasta:

```
outputs/<AAAA-MM-DD>_<stem>/
├── transcricao.txt
├── words.json                # word-level timestamps (reaproveitado pelo 04b/04c/10)
├── blocos.json
├── polimento.json            # intervalos de jump cut do 04b
├── descricoes.txt            # titulo+descricao+tags por bloco pro YouTube
├── revisao.json              # veredito e checagens do agente revisor (step 11)
├── cortes/                   # corte_NN_<slug>.mp4 + cold_NN_<slug>.mp4 (+ _polido)
│   └── legendados/           # cortes com legenda karaokê (mesmo nome) + legenda_NN.ass (step 4c)
├── cards/                    # card_NN.png e card_NN.mp4
├── thumbs/                   # thumb_NN_a/b/c.png (+ candidatos_NN.json)
│   └── colagem/              # thumb colagem (07b) + colagem.json
├── shorts/                   # short_NN_<slug>.mp4 (9:16) + short_NN.ass + shorts.json (step 10)
└── finalizados/              # video_NN_<slug>.mp4 (cold+intro+card+corte+outro)
```

Outras pastas em `outputs/`: `_calibracao/` (scratch da calibração de zoom), `_debug/` (dumps de resposta do LLM quando falha o parse), `_old/` (artefatos legados).

## Step 4 — Cortes

Gera **dois arquivos por bloco**: `corte_NN_<slug>.mp4` (corte completo, fade out 0.5s) e `cold_NN_<slug>.mp4` (cold open 15-30s, fade in+out 0.4s). Se o JSON não tiver `cold_open`, gera só o corte e loga um aviso. Sai com exit 1 e resumo se algum ffmpeg falhar.

## Tratamento de overlays da live original (zoom)

O `04_cortar.py` remove os overlays via **zoom programático** (`crop` + `scale`), sem blur. O recorte é **por fonte**, lido de `config/zoom.json` pelo stem (`{"<stem>": "crop=w:h:x:y"}` na fonte 1080p, aplicado antes do `scale=1280:720`). Stem **sem entrada** no config roda SEM zoom (só scale+pad) e loga um aviso — é o motivo nº1 de um corte sair com os overlays aparecendo: faltou cadastrar a fonte. O truque do recorte: deslocar a janela 16:9 pra direita encaixa-a **entre** os overlays das duas bordas das lives MBL:

- **valete.plus** (círculo, topo-esquerdo) → sai pela esquerda
- **contador de membros** (topo-direito) → sai pela direita
- **QR code / SmartCast** (base-direita) → sai pela direita

A parede neon "Academia MBL" é **cenário do estúdio** (não overlay) e fica. O zoom aplica-se ao corte **e** ao cold open. Fontes com o mesmo estúdio/enquadramento podem **reaproveitar** o mesmo valor (ex: `renan_live2`/`renan_vorcaro`/`renan_2turn_x_lula` = `1476:830:200:100`, zoom ~1.30); fonte com layout diferente precisa calibrar.

**Calibração visual:** `uv run py scripts/calibrar_zoom.py <video> [--zoom=..] [--fx=..] [--fy=..] [--salvar=<stem>]` gera previews antes/depois em `outputs/_calibracao/` pra dialar o recorte numa fonte nova; `--salvar=<stem>` grava direto no `config/zoom.json`. Depois de cadastrar/calibrar, re-corte com `uv run py scripts/pipeline.py <stem> --desde=4` (não re-transcreve nem re-segmenta).

**Alternativa manual:** editar o `corte_NN_*.mp4` no CapCut, salvar de volta na mesma subpasta com o mesmo nome, depois rodar steps 5 e 6.

## Step 4b — Polimento (jump cut, opcional)

Pra cada `corte_NN_*.mp4` ele: (1) reaproveita os word-level timestamps do `words.json` (gerado no step 2), fatiando pelo intervalo do bloco — **não re-transcreve** (cai pra re-transcrição via whisper só se o words.json não existir), (2) detecta silêncios >3s **programaticamente** (gap entre palavras consecutivas — determinístico, sem API, nunca nos primeiros 30s), (3) manda pro Claude com prompt conservador só o que exige julgamento (fillers extremos e problemas técnicos), funde os intervalos e aplica jump cut via `ffmpeg filter_complex select/aselect` e salva `corte_NN_<slug>_polido.mp4` na mesma pasta. Filtro defensivo descarta intervalos com motivo "ignorar/manter/abaixo do limiar".

- `--bloco=N` reprocessa só um bloco; `--sem-llm` roda **só a parte programática** (silêncios) sem chamar o Claude — custo $0, abre mão dos cortes de fillers/problemas técnicos.
- Os intervalos ficam em `polimento.json` (re-runs não duplicam blocos); `--reaplicar` re-aplica os intervalos salvos aos cortes sem chamar o LLM (útil após re-cortar, ex: mudou o zoom).
- Cold opens **não** são polidos. Pra usar os polidos na montagem: `06_montar.py <stem> --polido` (gera `video_NN_<slug>_polido.mp4`).
- Whisper cai pra CPU se CUDA indisponível (02/04b).

## Step 4c — Legenda karaokê

**Grátis** (sem API) e roda **por padrão** no pipeline desde 21/10/2026 (`--sem-legendas` desliga por live). Reprocessar live antiga com `--desde=4` gera as legendas; `--desde=5`/`6` sem legendados falha alto e pede `--desde=4c` ou `--sem-legendas`.

Queima legenda estilo **karaokê** nos cortes completos pra segurar retenção. Fatia o `words.json` pelo intervalo do bloco (mesmo padding do 04), agrupa em linhas curtas (até 4 palavras / 26 chars, quebra em pausa >0.7s e fim de frase), gera um `.ass` com `\k` (palavra falada acende em **amarelo 14**, o resto fica branco, Anton 72px com contorno preto, centralizada embaixo) e queima com o filtro `ass` do ffmpeg (libass) no formato canônico. Núcleo compartilhado com o 10 em `scripts/_legenda.py`.

- Com `--polido` legenda o `_polido` e **remapeia** os tempos pelos intervalos do `polimento.json` (palavra num trecho removido some, as seguintes recuam).
- Saída em `cortes/legendados/` com o **mesmo nome** do corte. A subpasta é de propósito, porque os globs `corte_NN_*.mp4` dos outros steps não enxergam os legendados.
- Errou uma palavra? Edite o `legenda_NN.ass` (`legenda_NN_polido.ass` com `--polido`) e rode de novo com `--so-queimar` (não regera o .ass).
- Cold opens não são legendados.
- Montagem: `06_montar.py <stem> --legendado [--polido]` → `video_NN_<slug>[_polido]_legendado.mp4`; o 09 prefere `_polido_legendado` > `_legendado` > `_polido` > original.

## Steps 5 e 6 — Card e montagem

- `05_cards.py`: card de contexto de 3s (sem metadados de evento/data).
- `06_montar.py`: `[cold open] → [intro 3s, trim via INTRO_SEGUNDOS → assets/intro_trim.mp4] → [card 3s] → [corte] → [outro 5s]`. Sem `cold_NN_*.mp4` monta sem ele e avisa. Só re-normaliza intro/outro se o asset do Canva mudou.

## Formato canônico

Todo o pipeline (steps 4, 4b, 5, 6) produz vídeo **1280x720, 30fps, yuv420p, H.264 via NVENC (GPU), áudio AAC 44100 Hz stereo**. Isso é o que permite o `06_montar` concatenar com `-c copy` (instantâneo) em vez de re-encodar o vídeo inteiro. Se algum segmento sair fora do padrão, o montar imprime o formato de cada segmento (pra apontar o destoante), detecta a falha do `-c copy` e cai automaticamente pro fallback de re-encode (`filter_complex`). As constantes `VENC`/`AENC`/`SCALE_PAD` vivem em `scripts/_ffmpeg.py` (compartilhado) — pra trocar pra CPU/libx264, edite só lá: `["-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p"]`.

## Step 10 — Shorts 9:16

`uv run py scripts/10_shorts.py <stem> [--bloco=N]` — **off-pipeline** e **grátis**: gera um **Short 9:16** (1080x1920, 30fps, NVENC) por bloco a partir do **cold open**. Recorta direto do vídeo **original** (`inputs/<stem>.mp4`, 1080p), porque o `cold_NN.mp4` é 720p e ficaria borrado esticado.

- A janela 9:16 usa a altura toda da área anti-overlay do `config/zoom.json` e fica **sempre dentro dela**, então os overlays continuam fora (stem sem zoom: quadro inteiro + aviso).
- A posição horizontal segue o rosto de quem fala: OpenCV detecta rostos a cada 0.5s, agrupa por posição e, entre os que aparecem em ≥30% dos frames, escolhe o **mais perto do centro do quadro** (quem filma mantém o palestrante no centro). O critério "maior rosto" perdia pra foto no telão, e o "rosto que mais mexe" perdia pra quem bebia água na mesa.
- Queima o `texto_thumb` como manchete no topo (caixa preta, amarelo 14), a legenda karaokê grande (3 palavras por linha, 110px) e a marca MISSÃO EM CORTES.
- Saída em `outputs/<pasta>/shorts/` + `shorts.json` (crop e taxa de rosto). Taxa de rosto <30% = provável tela compartilhada/plateia: o script avisa e marca `revisar: true`.
- Preserva `postado`/`youtube_id` (do 14) e `arquivado` ao regerar.
- Tempo: ~1min por Short (a detecção domina). Upload de Shorts ainda é manual.

## Dependências externas

- **Conta Anthropic API** (`.env` com `ANTHROPIC_API_KEY`) — créditos pré-pagos
- **Conta YouTube verificada** — necessário pra upload >15min
- **Canva (free ou Pro)** — pra intro/outro/thumbnail
- **GTX 1650 ou superior** — pra rodar faster-whisper em GPU (cai pra CPU se sem GPU, mas é 4-5x mais lento)
- **ffmpeg + cuDNN/cuBLAS no PATH** — no Windows, requer `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` instalados via uv
- **NVENC** — os steps 4/4b/5/6 encodam via `h264_nvenc`. A GTX 1650 (Turing) suporta. Sem NVENC, troque `VENC` em `scripts/_ffmpeg.py` (ver formato canônico)
- **yt-dlp** com solver JS (`yt-dlp[default]`, Node no PATH). Sem isso o YouTube devolve 403 no download. Formato recomendado: `-f "299+140"` (1080p60 mp4 + m4a 129k)

## Custos operacionais previstos

| Item | Custo mensal |
|---|---|
| Anthropic API (~20 lives/mês, com polimento) | ~$8-9 |
| Canva Pro (opcional) | $13 |
| YouTube/domínio | grátis (por enquanto) |
| **Total mínimo** | **~$5/mês** |

**Tempos aproximados por step (GTX 1650):** download 1-3min · transcrição ~6-12min · segmentação 30-90s · cortes ~2-4min (NVENC) · polimento ~3-6min · legenda ~1-2min/corte · cards <1min · montagem ~1-2min (concat copy) · thumbs <1min · descrições <5s.

**Total por live:** ~15-25min de processamento, ~$0.20 de API no pipeline base (estimativa pós-otimização NVENC/concat-copy). Com Curador completo (polir + revisor + colagem) ~US$ 0,65-0,80 por vídeo.
