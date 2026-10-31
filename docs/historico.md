# Histórico e roadmap

> Puxado do CLAUDE.md. O que mudou e quando (o detalhe está no `git log`), e o que ficou pra depois.

## Estado (Maio-Out/2026)

- ✅ Pipeline MVP funcionando ponta-a-ponta
- ✅ Scripts aceitam argumento de arquivo (multi-live sem editar código)
- ✅ Identidade visual mínima pronta
- ✅ 1º vídeo publicado: Arthur do Val sobre Penélope (19/05/2026)
- ✅ Conta YouTube verificada
- ✅ Vídeo 01 do Renan (Flávio/STF/rachadinha) — publicado 22/05/2026
- ✅ Cold open implementado no pipeline (prompt + 04_cortar.py + 06_montar.py)
- ✅ Vídeo 02 do Renan (plano de governo / Bolsa Família) — publicado 23/05/2026
- ✅ `04_cortar.py` com remoção de overlays via **zoom programático** — substituiu o blur. Calibrado com `scripts/calibrar_zoom.py` (02/06/2026)
- ✅ renan_live2 segmentado — 4 blocos: long house/masculinidade, Ciro Nogueira/Piauí, MBL como Roma (score 9), Datafolha/metodologia
- ⏳ Vídeos 03-06 do Renan (renan_live2) — corte + montagem + agendamento pendentes
- ✅ `05_cards.py` simplificado — removidos metadados de evento/data do card de contexto
- ✅ `07_thumb.py` — thumb semi-automática (3 variantes por bloco); desde 22/10/2026 a imagem cobre a thumb inteira (rosto grande no terço direito) e foge das sobras de overlay
- ✅ `08_descricao.py` — txt com título/descrição/tags/hashtags pronto pro YouTube Studio (sem API)
- ✅ `04b_polir.py` — polimento opcional via LLM + flag `--polido` no `06_montar.py`. ~$0.20/live
- ✅ arthur_flavio_trump processado (lFJ1DSOjUw0) — 4 vídeos finalizados (28/05/2026). Polimento removeu ~2min de tempo morto
- ✅ **Cortes mais curtos pra retenção (02/06/2026)**: segmentação de 8-15min pra **5-7min** (até 6 blocos por live), UM ponto por corte. Card 5s→3s, intro 5s→3s (`INTRO_SEGUNDOS`). Hipótese: vídeos curtos e focados seguram melhor a retenção. Validar com métricas.
- ✅ **Performance (02/06/2026)**: NVENC nos steps 4/4b/5/6; montagem com `-c copy`; 04b reaproveita `words.json`; `beam_size` 5→2. Estimativa ~30-45min → ~15-25min por live.
- ✅ **Outputs reorganizados — pasta por vídeo (03/06/2026)**: `outputs/<AAAA-MM-DD>_<stem>/`, `_paths.py` falha alto se ambíguo. Migração via `scripts/_migrar_outputs.py`. Processados `arthur_flavio_taxar` (E Detalhe, zoom 1.32) e `renan_vorcaro` (live de reação com overlays pesados).
- ✅ **QoL e robustez (12/06/2026)**: `pipeline.py` (orquestrador), `01_baixar.py` (+ `inputs/<stem>.url`), 04b sem duplicar blocos, 04 com exit 1 em falha, 02 valida input.
- ✅ **Rodada 2 (12/06/2026)**: 04b detecta silêncios programaticamente; 03 valida timestamps (salva `blocos_invalido.json`) e loga custo; 06 só re-normaliza intro/outro se mudou e aponta segmento destoante; `_ffmpeg.py` centraliza VENC/AENC/SCALE_PAD; whisper cai pra CPU.
- ✅ **Zoom por fonte + thumb manual (13/06/2026)**: `renan_2turn_x_lula` (`Lab_UcxeEDs`) reaproveitando zoom `1476:830:200:100`; `07_thumb.py --bloco=N --t=MM:SS`.
- ✅ **Texto da thumb curto (13/06/2026)**: `texto_thumb` no prompt de segmentação; 07 nunca usa `titulo_sugerido`; override `--titulo=`.
- ✅ **Out/2026**: painel + camada de estado (SQLite), upload via API (travado até a auditoria), revisor + editor, legenda karaokê padrão (21/10), Shorts, métricas de retenção, Curador por estoque às 17h, 14_canal (detecta publicados), thumbs pelo rosto (22/10), thumb colagem (modo teste) + grafias oficiais.
- ✅ **Estratégia de crescimento (31/10/2026)**: longos de **5-30 min sem alvo** (mínimo de 8 só depois do YPP); títulos de busca de cauda longa (nome completo + tema concreto, pergunta quando cabe); Curador marca a live já cortada pelos canais de corte grandes (yt-dlp, `canais_corte`) e prioriza o que eles não cortam; resumo semanal abre com minutos por view por faixa, % fora da busca e views nos 7 primeiros dias.
- ✅ **Coerência acima da duração (26/10/2026)**: longos de 5-7 → **8-30 min guiados pelo assunto** (curto 8-12, médio 12-20, longo 20-30; >30 vira Parte 1/2), Shorts até 3 min fechando uma ideia, início/fim encaixados em fim de frase + pausa (`_fronteira.py`), revisor reprova e reajusta fronteira sozinho, `faixa_duracao` no banco e retenção/horas por faixa no 12. Hipótese: 8+ min habilita anúncio no meio e o assunto inteiro segura mais horas assistidas.

## Roadmap pós-MVP

### Curto prazo
- Capítulos com timestamps na descrição
- Tipografia animada no intro (motion graphics no Canva)
- Outras configs por fonte (ex: zoom de speaker) podem migrar pro `config/` (o zoom anti-overlay já está em `config/zoom.json`)

### Médio prazo
- Diarização na transcrição (separar speakers automaticamente)
- Detecção automática de rosto pra escolher a melhor variante sem 3 opções (face_recognition segue adiado; hoje é OpenCV Haar)
- Capítulos com timestamps (requer mapear subtópicos dentro de cada bloco)

### Longo prazo
- Pipeline em batch (processar várias lives em sequência)
- Detecção automática de regiões de overlay via Claude com visão (hoje calibrada à mão com `calibrar_zoom.py`)
- Métricas: correlacionar score do LLM com views/retenção reais

### Feito (saiu do roadmap)
- Legendas burned-in → karaokê no vídeo inteiro (`04c_legendas.py`)
- Thumbnails dinâmicas via PIL → `07_thumb.py` e `07b_colagem.py`
- Descrição + tags via LLM → `08_descricao.py` (reaproveita o step 3)
- Upload via YouTube Data API → `09_upload.py`
- Narração própria no início → substituída pelo cold open automático
