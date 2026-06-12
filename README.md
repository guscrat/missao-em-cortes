# Missão em Cortes

Pipeline local que transforma lives e entrevistas longas (1-2h) do **Partido Missão (14)** em vários cortes de 5-7 minutos prontos pro YouTube: transcrição local na GPU, segmentação temática via Claude, corte/montagem com ffmpeg e geração semi-automática de thumbs e descrições.

Estrutura de cada vídeo final:

```
[Cold open 15-30s] → [Intro 3s] → [Card de contexto 3s] → [Corte 5-7min] → [Outro 5s]
```

## Requisitos

- **Python 3.11+** com [uv](https://docs.astral.sh/uv/)
- **ffmpeg** no PATH
- **GPU NVIDIA** (GTX 1650+) — whisper cai pra CPU se faltar, mas é 4-5x mais lento; pro encode sem NVENC, troque o `VENC` em `scripts/_ffmpeg.py`
- **Conta Anthropic API** (segmentação + polimento, ~$0.20-0.40 por live)

## Setup

```powershell
uv sync
```

Crie um `.env` na raiz com:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Uso

```powershell
# 1. Baixar a live (salva inputs/<stem>.mp4 + a URL pra usar nas descrições)
uv run py scripts/01_baixar.py <URL> <stem>

# 2. Rodar o pipeline inteiro (transcrição → segmentação → cortes → montagem → thumbs → descrições)
uv run py scripts/pipeline.py <stem> --polir
```

Saída em `outputs/<AAAA-MM-DD>_<stem>/finalizados/` — um `video_NN_<slug>.mp4` por bloco temático, mais `thumbs/` e `descricoes.txt` na mesma pasta.

Cada step também roda sozinho (`scripts/02_transcribe.py` a `08_descricao.py`); o `pipeline.py` aceita `--desde=N` pra retomar do meio (ex: `--desde=4` depois de recalibrar o zoom) e `--polir` pra incluir o jump cut de silêncios/fillers (step 4b).

**Fonte nova (estúdio/layout diferente):** calibre o zoom anti-overlay antes do corte com `uv run py scripts/calibrar_zoom.py <video> --zoom=N --fx=F --fy=F --salvar=<stem>` — sem entrada no `config/zoom.json`, o corte sai sem zoom e os overlays da live original aparecem.

## O que continua manual

- Escolher a variante de thumb (a/b/c) e finalizar o collage no Canva
- Revisar `descricoes.txt` e subir os vídeos no YouTube Studio
- Revisar blocos com tela compartilhada (o zoom é calibrado pro enquadramento padrão)

## Documentação

Contexto completo do projeto — decisões técnicas, identidade visual, formato canônico, roadmap e estado atual — em [`CLAUDE.md`](CLAUDE.md).
