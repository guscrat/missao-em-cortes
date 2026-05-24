# CLAUDE.md — Missão em Cortes

> Contexto do projeto para o Claude Code. Lido automaticamente no início de cada sessão.

## O projeto

Canal de YouTube de cortes de lives, entrevistas, debates e eventos do **Partido Missão (legenda 14)**, partido brasileiro de direita liberal fundado em 2025, ligado ao MBL. O canal pega vídeos longos (lives de 1-2h ou entrevistas de 30-60min) das principais figuras do partido (Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias, Amanda Vettorazzo) e gera **2-4 vídeos por fonte**, cada um focado em um tema específico, otimizados para monetização no YouTube Partner Program. Para lives longas o alvo é 10-22min por corte; para entrevistas curtas os cortes ficam menores (4-6min) — ambos os formatos são válidos.

**Nome do canal:** Missão em Cortes  
**Handle proposto:** @missaoemcortes

## Postura editorial

- Simpática ao Partido Missão, mas com independência crítica
- Linha editorial: direita liberal, anti-bolsonarista crítica
- Títulos podem ser ousados/com gancho, **sem distorcer o que foi dito**
- Mantém crédito visual à fonte original (logo MBL/Valete preservado nos cortes)
- Overlays desatualizados: opção programática via `USE_BLUR` no `04_cortar.py` (boxblur ffmpeg) ou no CapCut com zoom

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
│   └── renan_entrevista.mp4
├── outputs/                          # Tudo gerado pelo pipeline
│   ├── <stem>_transcricao.txt        # ex: renan_entrevista_transcricao.txt
│   ├── <stem>_blocos.json            # ex: renan_entrevista_blocos.json
│   ├── cortes/<stem>/                # corte_NN_<slug>.mp4 + cold_NN_<slug>.mp4
│   ├── cards/                        # card_NN.png e card_NN.mp4
│   └── finalizados/                  # video_NN_<slug>.mp4 (cold+intro+card+corte+outro)
├── assets/
│   ├── intro.mp4                     # do Canva, sem áudio
│   ├── intro_norm.mp4                # normalizado com áudio silencioso
│   ├── outro.mp4                     # do Canva, com voz IA ("inscreva-se")
│   ├── outro_norm.mp4
│   └── fonts/Anton-Regular.ttf
├── scripts/                          # Pipeline numerado
│   ├── 02_transcribe.py
│   ├── 03_segmentar.py
│   ├── 04_cortar.py
│   ├── 05_cards.py
│   └── 06_montar.py
├── prompts/
│   └── segmentacao.md                # Prompt do LLM pra topic segmentation
├── .env                              # ANTHROPIC_API_KEY
└── pyproject.toml
```

## Pipeline (ordem de execução)

| # | Etapa | Script / Comando | Tempo aprox. | Custo |
|---|---|---|---|---|
| 1 | Download | `yt-dlp -f "299+140" -o "inputs/<stem>.mp4" URL` | 1-3min | grátis |
| 2 | Transcrição | `uv run py scripts/02_transcribe.py inputs/<stem>.mp4` | 8-15min (GTX 1650) | grátis (local) |
| 3 | Segmentação via LLM | `uv run py scripts/03_segmentar.py outputs/<stem>_transcricao.txt` | 30-90s | ~$0.20 |
| 4 | Cortes | `uv run py scripts/04_cortar.py outputs/<stem>_blocos.json` | 5-10min | grátis |
| 5 | Cards de contexto | `uv run py scripts/05_cards.py outputs/<stem>_blocos.json` | <1min | grátis |
| 6 | Montagem final | `uv run py scripts/06_montar.py outputs/<stem>_blocos.json` | 10-15min | grátis |

O step 4 gera **dois arquivos por bloco**: `corte_NN_<slug>.mp4` (corte completo, fade out 0.5s) e `cold_NN_<slug>.mp4` (cold open 15-30s, fade in+out 0.4s). Se o JSON não tiver `cold_open`, gera só o corte e loga um aviso.

**Total por live:** ~30-45min de processamento, ~$0.20 de API.

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
[Cold open 15-30s] → [Intro 5s] → [Card de contexto 5s] → [Corte 10-22min] → [Outro 5s]
```

O cold open é o trecho de maior impacto do bloco, exibido antes da intro pra prender o espectador nos primeiros segundos. Se `cold_NN_*.mp4` não existir na pasta de cortes, o `06_montar.py` monta sem ele e loga um aviso.

Cada parte contribui pro "valor agregado" exigido pelo YouTube Partner Program (que pune `reused content` desde Jul/2025).

## Tratamento de overlays da live original

O `04_cortar.py` tem suporte a **blur programático** de overlays via ffmpeg (`filter_complex` + `boxblur=20`). Ativar setando `USE_BLUR = True` no topo do script. As regiões estão em `BLUR_MASKS` como tuplas `(crop_rect, overlay_pos)`, pré-configuradas para as lives MBL:

- Contador de novos membros (topo direito)
- QR code / valete.plus (canto inferior direito)

**Alternativa manual:** editar o `corte_NN_*.mp4` no CapCut com zoom, salvar de volta na mesma subpasta com o mesmo nome, depois rodar steps 5 e 6.

Logo do MBL (canto superior esquerdo) é preservado intencionalmente como crédito ético à fonte.

## Prompt de segmentação (resumo)

Está em `prompts/segmentacao.md`. Objetivo: a LLM recebe a transcrição completa com timestamps e retorna JSON com 2-4 blocos temáticos de 8-15min, com início e fim em pontos naturais (não cortar no meio de frase ou raciocínio), título sugerido, score de potencial viral, ganchos, tags e **`cold_open`** (trecho de 15-30s de maior impacto dentro do bloco, com timestamps próprios). Modelo: `claude-sonnet-4-6`.

## Estado atual (Maio 2026)

- ✅ Pipeline MVP funcionando ponta-a-ponta
- ✅ Scripts aceitam argumento de arquivo (multi-live sem editar código)
- ✅ Identidade visual mínima pronta
- ✅ 1º vídeo publicado: Arthur do Val sobre Penélope (19/05/2026)
- ✅ Conta YouTube verificada
- ✅ Vídeo 01 do Renan (Flávio/STF/rachadinha) — publicado 22/05/2026
- ✅ Cold open implementado no pipeline (prompt + 04_cortar.py + 06_montar.py)
- ✅ Vídeo 02 do Renan (plano de governo / Bolsa Família) — publicado 23/05/2026
- ✅ `04_cortar.py` com blur programático de overlays via ffmpeg (`USE_BLUR` flag + `BLUR_MASKS`)
- ✅ renan_live2 segmentado — 4 blocos: long house/masculinidade, Ciro Nogueira/Piauí, MBL como Roma (score 9), Datafolha/metodologia
- ⏳ Vídeos 03-06 do Renan (renan_live2) — corte + montagem + agendamento pendentes

## Roadmap pós-MVP

### Curto prazo (próximas semanas)
- Capítulos com timestamps na descrição
- Tipografia animada no intro (motion graphics no Canva)
- Configuração de fonte por canal/speaker (YAML com coordenadas de overlay por fonte)
- ~~Narração própria de 20-30s no início~~ — substituído pelo cold open automático

### Médio prazo
- Diarização na transcrição (separar speakers automaticamente)
- Legendas burned-in nos momentos de impacto (aumenta retenção)
- Templates de thumbnail dinâmicos via PIL (com frame do vídeo + texto)
- Geração automática de descrição + tags + capítulos via LLM

### Longo prazo
- Automação de upload via YouTube Data API
- Pipeline em batch (processar várias lives em sequência)
- Detecção automática de regiões de overlay via Claude com vision (blur básico já existe via `USE_BLUR`)
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

## Custos operacionais previstos

| Item | Custo mensal |
|---|---|
| Anthropic API (~20 lives/mês) | ~$4-5 |
| Canva Pro (opcional) | $13 |
| YouTube/domínio | grátis (por enquanto) |
| **Total mínimo** | **~$5/mês** |

## Notas técnicas (Windows)

- Todos os scripts têm `sys.stdout.reconfigure(encoding='utf-8')` no topo — necessário pra emojis e caracteres especiais não quebrarem no terminal Windows (cp1252)
- Permissões do Claude Code ficam em `.claude/settings.local.json` (não commitado)
- Formato de download recomendado: `-f "299+140"` (1080p60 mp4 + m4a 129k)

## Notas finais

Este projeto é fruto de uma sessão de desenvolvimento intensa em Maio/2026 onde o pipeline saiu do zero ao MVP funcional em menos de um dia. A filosofia foi sempre cortar escopo, validar rápido e iterar depois — vide as várias coisas marcadas como "pós-MVP" acima. **Não otimizar antes da hora.**
