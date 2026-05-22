# CLAUDE.md — Missão em Cortes

> Contexto do projeto para o Claude Code. Lido automaticamente no início de cada sessão.

## O projeto

Canal de YouTube de cortes de lives, debates e eventos do **Partido Missão (legenda 14)**, partido brasileiro de direita liberal fundado em 2025, ligado ao MBL. O canal pega lives longas (1-2h) das principais figuras do partido (Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias, Amanda Vettorazzo) e gera **2-4 vídeos longos (10-22min) por live**, cada um focado em um tema específico, otimizados para monetização no YouTube Partner Program.

**Nome do canal:** Missão em Cortes  
**Handle proposto:** @missaoemcortes

## Postura editorial

- Simpática ao Partido Missão, mas com independência crítica
- Linha editorial: direita liberal, anti-bolsonarista crítica
- Títulos podem ser ousados/com gancho, **sem distorcer o que foi dito**
- Mantém crédito visual à fonte original (logo MBL/Valete preservado nos cortes)
- Borra overlays desatualizados das lives (contador de membros, QR codes pontuais)

## Stack técnica

- **Python 3.10+** com **uv** (gerenciador de dependências)
- **faster-whisper** — transcrição local (modelo `medium`, GPU NVIDIA via CUDA)
- **Anthropic API** — segmentação temática via `claude-sonnet-4-6` (~$0.20/live)
- **ffmpeg** — corte, blur de overlays, montagem final
- **Pillow (PIL)** — geração programática de cards de contexto
- **yt-dlp** — download das lives do YouTube
- **Canva** — intro, outro e template de thumbnail (externos ao pipeline)

## Estrutura do projeto

```
missao-em-cortes/
├── inputs/                          # Lives baixadas (mp4)
│   └── live_teste.mp4
├── outputs/                          # Tudo gerado pelo pipeline
│   ├── live_teste_transcricao.txt
│   ├── live_teste_blocos.json
│   ├── cortes/                       # corte_NN_<slug>.mp4 (com blur aplicado)
│   ├── cards/                        # card_NN.png e card_NN.mp4
│   └── finalizados/                  # video_NN_<slug>.mp4 (intro+card+corte+outro)
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
| 1 | Download da live | `yt-dlp -f "136+140" -o "inputs/live_teste.mp4" URL` | 1-3min | grátis |
| 2 | Transcrição | `uv run py scripts/02_transcribe.py` | 8-15min (GTX 1650) | grátis (local) |
| 3 | Segmentação via LLM | `uv run py scripts/03_segmentar.py` | 30-90s | ~$0.20 |
| 4 | Cortes + blur | `uv run py scripts/04_cortar.py` | 5-10min | grátis |
| 5 | Cards de contexto | `uv run py scripts/05_cards.py` | <1min | grátis |
| 6 | Montagem final | `uv run py scripts/06_montar.py` | 10-15min | grátis |

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
[Intro 5s] → [Card de contexto 5s] → [Corte 10-22min] → [Outro 5s]
```

Cada parte contribui pro "valor agregado" exigido pelo YouTube Partner Program (que pune `reused content` desde Jul/2025).

## Tratamento de overlays da live original

A live original tem overlays nos cantos (contador de membros, valete.plus, QR code) que ficam desatualizados após o evento. Aplicamos **blur localizado** via ffmpeg em vez de tarja preta:

```
[0:v]split=3[base][a1][a2];
[a1]crop=247:130:1033:20,boxblur=20:1[b1];
[a2]crop=200:160:1080:555,boxblur=20:1[b2];
[base][b1]overlay=1033:20[tmp];
[tmp][b2]overlay=1080:555[outv]
```

Coordenadas pra resolução **1280x720**. Logo do MBL (canto superior esquerdo) é preservado intencionalmente como crédito ético à fonte. **Coordenadas variam conforme a fonte da live** — Arthur do Val (estúdio MBL), Kim Kataguiri (canal próprio), Renan Santos, eventos do partido. Cada um pode demandar mapping diferente.

## Prompt de segmentação (resumo)

Está em `prompts/segmentacao.md`. Objetivo: a LLM recebe a transcrição completa com timestamps e retorna JSON com 2-4 blocos temáticos de 8-15min, com início e fim em pontos naturais (não cortar no meio de frase ou raciocínio), título sugerido, score de potencial viral, ganchos e tags. Modelo: `claude-sonnet-4-6`.

## Estado atual (Maio 2026)

- ✅ Pipeline MVP funcionando ponta-a-ponta
- ✅ 3 cortes gerados a partir de live do Arthur do Val (19/05/2026)
- ✅ Identidade visual mínima pronta
- ✅ Blur de overlays aplicado
- ⏳ Thumbnail final do primeiro vídeo (Canva)
- ⏳ Conta YouTube verificada por SMS (necessário pra >15min upload)
- ⏳ Primeiro vídeo no ar (não listado primeiro, depois público)

## Roadmap pós-MVP

### Curto prazo (próximas semanas)
- Capítulos com timestamps na descrição
- Tipografia animada no intro (motion graphics no Canva)
- Configuração de fonte por canal/speaker (YAML com coordenadas de overlay por fonte)
- Narração própria de 20-30s no início do vídeo (aumenta muito valor agregado pra YPP)

### Médio prazo
- Diarização na transcrição (separar speakers automaticamente)
- Legendas burned-in nos momentos de impacto (aumenta retenção)
- Templates de thumbnail dinâmicos via PIL (com frame do vídeo + texto)
- Geração automática de descrição + tags + capítulos via LLM

### Longo prazo
- Automação de upload via YouTube Data API
- Pipeline em batch (processar várias lives em sequência)
- Detecção automática de overlays via Claude com vision
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

## Notas finais

Este projeto é fruto de uma sessão de desenvolvimento intensa em Maio/2026 onde o pipeline saiu do zero ao MVP funcional em menos de um dia. A filosofia foi sempre cortar escopo, validar rápido e iterar depois — vide as várias coisas marcadas como "pós-MVP" acima. **Não otimizar antes da hora.**
