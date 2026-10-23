# Step 12 — analista de retenção (12_metricas.py)

`uv run py scripts/12_metricas.py [--desde=AAAA-MM-DD]` — `agente="analista"`, off-pipeline, US$ 0, só leitura.

Compara a **retenção** (% média assistida, a do Studio) dos vídeos **com** legenda karaokê x **sem**, pro resumo semanal.

- Roda no projeto **`missao-em-cortes-analytics`** com client e token próprios (`secrets/analytics_client_secret.json` + `secrets/analytics_token.json`). 1ª vez abre o navegador.
- Lista os vídeos **públicos** do canal (título, data, duração) e puxa views/duração média/% assistida de cada um.
- Um vídeo é "com legenda" se o título bate (normalizado) com um `descricoes.txt` cujo bloco tem `finalizados/video_NN_*_legendado.mp4`. Vale pra upload pela API e pelo Studio.
- Sem match: antes de 21/10/2026 conta como "sem legenda"; depois fica de fora ("sem info", listado pra conferir; título editado no Studio quebra o match).
- Shorts (≤3 min) e vídeos com <20 views ficam de fora.
- Retenção do grupo = média **ponderada por views**.
- Saída no terminal + `state/metricas_retencao.json`.

## Setup do projeto de métricas (uma vez, feito pelo Gu no console)

1. [console.cloud.google.com](https://console.cloud.google.com) → seletor de projeto → **Novo projeto** → nome `missao-em-cortes-analytics` (não mexer no `missao-em-cortes-publisher`).
2. Com o projeto novo selecionado: **APIs e serviços → Biblioteca** → ativar **YouTube Analytics API** e **YouTube Data API v3**.
3. **Google Auth Platform** (tela de consentimento OAuth) → tipo **Externo** → nome do app `Missão em Cortes Métricas`, e-mail de suporte do Gu → em **Acesso a dados**, adicionar só `.../auth/yt-analytics.readonly` e `.../auth/youtube.readonly` → em **Público-alvo**, **Publicar app** (status **Em produção**). App em teste tem token que expira em 7 dias. Em produção o token não expira, e o app segue sem verificação do Google (uso interno), então o login mostra "app não verificado" → **Avançado → continuar**. A política de privacidade desse app é `https://guscrat.github.io/missao-em-cortes/PRIVACY-ANALYTICS.html`.
4. **Clientes → Criar cliente** → tipo **App para computador** → nome `metricas-desktop` → **Baixar JSON** → salvar como `secrets/analytics_client_secret.json` na pasta principal (gitignored; nunca commitar, nunca colar no chat). **Antes de salvar, confira o `project_id` do JSON**: tem que ser `missao-em-cortes-analytics`. Client criado com o projeto errado selecionado sai no `missao-em-cortes-publisher`.
5. Rodar `uv run py scripts/12_metricas.py`: abre o navegador, login com a conta do **canal** (escolher o canal Missão em Cortes se pedir), aceitar os 2 escopos de leitura → grava `secrets/analytics_token.json`. Erro 403 `accessNotConfigured` = faltou o passo 2 (ativar as APIs no projeto analytics; leva alguns minutos pra valer).
