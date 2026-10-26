"""Painel do Missão em Cortes — acompanha o pipeline e os agentes por responsabilidade.

Uso: uv run streamlit run painel/app.py      (abre em http://localhost:8501)

Só LÊ o banco (state/pipeline.db). Quem escreve são os scripts e agentes via
scripts/_eventos.py. O botão "Sincronizar" roda o scripts/sincronizar_estado.py.
"""
import html
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

import hoje
import visual
from time_dev import aba_time_dev, faixa_decisoes

ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("MISSAO_DB") or ROOT / "state" / "pipeline.db")

# Colunas do kanban = responsabilidades. Cada status de bloco cai em UMA coluna,
# menos "arquivado" (conteúdo antigo que não vai sair): fica fora do kanban e das métricas.
COLUNAS = [
    ("Curadoria", "curador", None),                       # vídeos ainda sem blocos
    ("Edição", "editor", {"segmentado", "cortado"}),
    ("Revisão", "revisor", {"montado", "revisao"}),
    ("Quarentena", "você", {"quarentena"}),
    ("Pronto para publicar", "publicador", {"aprovado"}),
    ("Agendado", "publicador", {"agendado"}),         # já no YouTube com publish_at
    ("Publicado", "analista", {"publicado"}),
    ("Descartado", "revisor", {"descartado"}),          # conteúdo ruim: não sobe
]

st.set_page_config(page_title="Missão em Cortes · painel", page_icon="✂️", layout="wide")


@st.cache_data(ttl=5)
def carregar() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        videos = pd.read_sql("SELECT * FROM videos", con)
        blocos = pd.read_sql("SELECT * FROM blocos", con)
        eventos = pd.read_sql("SELECT * FROM eventos ORDER BY ts DESC LIMIT 2000", con)
        try:   # banco anterior à tabela tarefas (só aparece depois do 1º tarefa.py)
            tarefas = pd.read_sql("SELECT * FROM tarefas", con)
        except pd.errors.DatabaseError:
            tarefas = pd.DataFrame()
    finally:
        con.close()
    if not eventos.empty:
        eventos["ts"] = pd.to_datetime(eventos["ts"])
    return videos, blocos, eventos, tarefas


@st.cache_data(ttl=60)
def carregar_custo_mes(inicio: str) -> pd.DataFrame:
    """Eventos com custo desde o dia 1º (o carregar() só traz os 2000 últimos)."""
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["agente", "custo_usd"])
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql("SELECT agente, custo_usd FROM eventos WHERE ts >= ? AND custo_usd > 0",
                           con, params=(inicio,))
    except pd.errors.DatabaseError:
        return pd.DataFrame(columns=["agente", "custo_usd"])
    finally:
        con.close()


@st.cache_data(ttl=30)
def carregar_custo_lives() -> pd.DataFrame:
    """Custo de API acumulado por live (alerta de US$ 1 / trava de US$ 2)."""
    vazio = pd.DataFrame(columns=["stem", "custo_usd", "ultimo"])
    if not DB_PATH.exists():
        return vazio
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql("SELECT stem, SUM(custo_usd) AS custo_usd, MAX(ts) AS ultimo FROM eventos "
                           "WHERE stem IS NOT NULL AND custo_usd > 0 GROUP BY stem", con)
    except pd.errors.DatabaseError:
        return vazio
    finally:
        con.close()


@st.cache_data(ttl=60)
def carregar_estoque() -> dict | None:
    return hoje.estoque()   # lê outputs/ inteiro: não precisa rodar a cada 10s


def sincronizar() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sincronizar_estado.py")],
                       capture_output=True, text=True, encoding="utf-8")
    carregar.clear()
    carregar_estoque.clear()
    if r.returncode == 0:
        st.toast(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "Sincronizado")
    else:
        st.error(f"Falhou ao sincronizar:\n\n{r.stderr or r.stdout}")


def card_bloco(b: pd.Series) -> None:
    with st.container(border=True):
        if isinstance(b.thumb_path, str) and (ROOT / b.thumb_path).exists():
            st.image(str(ROOT / b.thumb_path), width="stretch")
        st.markdown(f"<div class='tit'>{html.escape(hoje._nome(b))}</div>",
                    unsafe_allow_html=True)
        partes = [f"{b.stem} · #{int(b.bloco_id)}"]
        if pd.notna(b.score):
            partes.append(f"score {b.score:g}")
        if pd.notna(b.duracao_min):
            partes.append(f"{b.duracao_min:.1f}min")
        if isinstance(b.publish_at, str):
            partes.append(f"sai {b.publish_at[:16].replace('T', ' ')}")
        st.markdown(f"<div class='meta'>{' · '.join(partes)}</div>"
                    f"<span class='pill {b.status}'>{b.status}</span>"
                    + (f"<div class='motivo'>{b.motivo}</div>" if isinstance(b.motivo, str) else ""),
                    unsafe_allow_html=True)


def card_video(v: pd.Series) -> None:
    with st.container(border=True):
        st.markdown(f"<div class='tit'>{v.stem}</div>"
                    f"<div class='meta'>criado {str(v.criado_em)[:10]}</div>"
                    f"<span class='pill'>{v.status}</span>", unsafe_allow_html=True)


def esteira(blocos: pd.DataFrame, eventos: pd.DataFrame) -> None:
    """Contagem por etapa em cartões pequenos, em cima do kanban."""
    semana = eventos[eventos["ts"] >= pd.Timestamp.now() - pd.Timedelta(days=7)] \
        if not eventos.empty else eventos
    contar = lambda sts: int(blocos["status"].isin(sts).sum()) if not blocos.empty else 0  # noqa: E731
    visual.grade([
        visual.cartao("Na edição", contar({"segmentado", "cortado"}), "segmentados e cortados"),
        visual.cartao("Aguardando revisão", contar({"montado", "revisao"}), "montados, falta o revisor"),
        visual.cartao("Quarentena", contar({"quarentena"}), "esperando você",
                      tom="alerta" if contar({"quarentena"}) else ""),
        visual.cartao("Prontos p/ publicar", contar({"aprovado"}), "aprovados, fora do YouTube"),
        visual.cartao("Agendados", contar({"agendado"}), "no YouTube com data"),
        visual.cartao("Custo 7 dias", f"${semana['custo_usd'].sum():.2f}" if not semana.empty else "$0.00",
                      "todos os agentes"),
    ])


def kanban(videos: pd.DataFrame, blocos: pd.DataFrame) -> None:
    cols = st.columns(len(COLUNAS))
    com_blocos = set(blocos["stem"]) if not blocos.empty else set()
    for col, (nome, dono, status) in zip(cols, COLUNAS):
        with col:
            if status is None:
                itens = videos[~videos["stem"].isin(com_blocos)
                               & (videos["status"] != "descartado")] if not videos.empty else videos
            else:
                itens = blocos[blocos["status"].isin(status)] if not blocos.empty else blocos
            st.markdown(f"<div class='col-h'>{nome} · {len(itens)}</div>"
                        f"<div class='col-dono'>responsável: {dono}</div>", unsafe_allow_html=True)
            if itens.empty:
                st.caption("—")
                continue
            ordem = "publish_at" if nome == "Agendado" else "atualizado_em"
            for _, item in itens.sort_values(ordem, ascending=nome == "Agendado").head(15).iterrows():
                (card_video if status is None else card_bloco)(item)


def aba_agentes(eventos: pd.DataFrame) -> None:
    if eventos.empty:
        st.info("Nenhum evento ainda. Rode o pipeline ou clique em Sincronizar.")
        return
    dias = st.segmented_control("Período", [7, 30, 90], default=7,
                                format_func=lambda d: f"{d} dias")
    recorte = eventos[eventos["ts"] >= pd.Timestamp.now() - pd.Timedelta(days=dias or 7)]
    for col in ("cache_leitura", "cache_escrita"):   # banco anterior às colunas de cache
        if col not in recorte:
            recorte = recorte.assign(**{col: 0})
    por_agente = (recorte.groupby("agente")
                  .agg(tokens_in=("tokens_in", "sum"), tokens_out=("tokens_out", "sum"),
                       cache_leitura=("cache_leitura", "sum"),
                       custo_usd=("custo_usd", "sum"), eventos=("id", "count"),
                       falhas=("status", lambda s: (s == "falha").sum()))
                  .sort_values("custo_usd", ascending=False))
    por_agente["acerto_cache"] = (por_agente["cache_leitura"]
                                  / por_agente["tokens_in"].where(por_agente["tokens_in"] > 0)).fillna(0)
    cache = hoje.custo_cache(recorte)
    visual.grade([
        visual.cartao("Custo no período", f"${recorte['custo_usd'].sum():.2f}",
                      f"últimos {dias or 7} dias"),
        visual.cartao("Acerto do prompt cache", f"{cache['taxa']:.0%}",
                      f"{cache['leitura']:,} de {cache['tokens_in']:,} tokens de input lidos do cache"
                      .replace(",", "."),
                      ajuda="Parte do input das chamadas de API servida do cache (custa 5-10% do "
                            "preço cheio). Revisor, polimento 04b e escolha de imagens da colagem usam cache.",
                      medidor=cache["taxa"]),
    ])
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("<h3>Custo por agente (US$)</h3>", unsafe_allow_html=True)
        visual.barras(por_agente["custo_usd"], formato=lambda v: f"US$ {v:.2f}", nome="custo")
    with c2:
        st.markdown("<h3>Resumo</h3>", unsafe_allow_html=True)
        st.dataframe(por_agente, width="stretch",
                     column_config={"custo_usd": st.column_config.NumberColumn(format="$%.2f"),
                                    "tokens_in": st.column_config.NumberColumn(format="%d"),
                                    "tokens_out": st.column_config.NumberColumn(format="%d"),
                                    "cache_leitura": st.column_config.NumberColumn(format="%d"),
                                    "acerto_cache": st.column_config.ProgressColumn(
                                        "acerto do cache", format="percent", min_value=0,
                                        max_value=1)})

    st.markdown("<h3>Tempo por etapa (média, min)</h3>", unsafe_allow_html=True)
    ok = recorte[(recorte["status"] == "ok") & recorte["duracao_s"].notna()]
    if ok.empty:
        st.caption("Sem etapas concluídas no período.")
    else:
        visual.barras(ok.groupby("etapa")["duracao_s"].mean() / 60,
                      formato=lambda v: f"{v:.1f} min".replace(".", ","), nome="média")


def aba_timeline(eventos: pd.DataFrame) -> None:
    if eventos.empty:
        st.info("Nenhum evento ainda.")
        return
    agentes = st.multiselect("Agentes", sorted(eventos["agente"].unique()))
    so_falhas = st.toggle("Só falhas e avisos")
    df = eventos
    if agentes:
        df = df[df["agente"].isin(agentes)]
    if so_falhas:
        df = df[df["status"].isin(["falha", "aviso", "devolvido"])]
    st.dataframe(df[["ts", "agente", "etapa", "status", "stem", "bloco_id", "mensagem",
                     "custo_usd", "duracao_s"]].head(300),
                 width="stretch", hide_index=True,
                 column_config={"ts": st.column_config.DatetimeColumn("quando", format="DD/MM HH:mm:ss"),
                                "custo_usd": st.column_config.NumberColumn("custo", format="$%.3f"),
                                "duracao_s": st.column_config.NumberColumn("duração (s)", format="%.0f")})


# ── Página ─────────────────────────────────────────────────────────────────
visual.css()
st.markdown("<p class='marca'>MISSÃO EM CORTES <span>· painel</span></p>"
            "<p class='sub'>Cada coluna é uma responsabilidade. Os cards andam sozinhos "
            "conforme os agentes trabalham.</p>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("<h3>Controles</h3>", unsafe_allow_html=True)
    if st.button("Sincronizar com outputs/", width="stretch"):
        sincronizar()
    auto = st.toggle("Atualizar a cada 10s", value=True)
    visual.seletor_tema()
    st.caption(f"Banco: `{DB_PATH.relative_to(ROOT) if DB_PATH.is_relative_to(ROOT) else DB_PATH}`")


@st.fragment(run_every=10 if auto else None)
def corpo() -> None:
    videos, blocos, eventos, tarefas = carregar()
    agora = pd.Timestamp.now()
    cfg = hoje.config_painel()
    est = carregar_estoque()
    hoje.faixa_alertas(hoje.curador_rodando(eventos, agora)
                       + hoje.alertas_curador(eventos, agora) + hoje.alertas_token(eventos, agora)
                       + hoje.alerta_cota(pct_alerta=cfg["cota_alerta_pct"])
                       + hoje.alertas_custo_live(carregar_custo_lives(), agora,
                                                 cfg["alerta_live_usd"], cfg["trava_live_usd"])
                       + hoje.alertas_operacao(est, hoje.no_ar(blocos, (agora + pd.Timedelta(days=1)).date())))
    faixa_decisoes(tarefas)
    if videos.empty and tarefas.empty:
        st.warning("Banco vazio. Clique em **Sincronizar com outputs/** na barra lateral "
                   "pra importar os vídeos que você já processou.")
        return

    aba_h, aba_k, aba_a, aba_t, aba_d = st.tabs(["Hoje", "Kanban", "Agentes e custo",
                                                 "Linha do tempo", "Time de dev"])
    with aba_h:
        custo = hoje.custo_mes(carregar_custo_mes(agora.strftime("%Y-%m-01")),
                               cfg["orcamento_mensal_usd"], agora)
        hoje.aba_hoje(blocos, tarefas, est, custo, agora)
    with aba_k:
        esteira(blocos, eventos)
        kanban(videos, blocos)
    with aba_a:
        aba_agentes(eventos)
    with aba_t:
        aba_timeline(eventos)
    with aba_d:
        aba_time_dev(eventos, tarefas)


corpo()
