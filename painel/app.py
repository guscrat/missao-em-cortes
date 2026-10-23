"""Painel do Missão em Cortes — acompanha o pipeline e os agentes por responsabilidade.

Uso: uv run streamlit run painel/app.py      (abre em http://localhost:8501)

Só LÊ o banco (state/pipeline.db). Quem escreve são os scripts e agentes via
scripts/_eventos.py. O botão "Sincronizar" roda o scripts/sincronizar_estado.py.
"""
import base64
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

import hoje
from time_dev import aba_time_dev, faixa_decisoes

ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("MISSAO_DB") or ROOT / "state" / "pipeline.db")
FONTE_ANTON = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"

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


def _css() -> None:
    fonte = ""
    if FONTE_ANTON.exists():
        b64 = base64.b64encode(FONTE_ANTON.read_bytes()).decode()
        fonte = f"@font-face{{font-family:'Anton';src:url(data:font/ttf;base64,{b64});}}"
    st.markdown(f"""<style>
    {fonte}
    h1, h2, h3, .anton {{ font-family: 'Anton', 'Impact', sans-serif !important;
                         letter-spacing: .02em; font-weight: 400 !important; }}
    .marca {{ font-family:'Anton','Impact',sans-serif; font-size:2.6rem; line-height:1;
              color:#F5C518; margin:0; }}
    .marca span {{ color:#F2F2F2; }}
    .sub {{ color:#9a9a9a; margin:.2rem 0 1.2rem; }}
    .col-h {{ font-family:'Anton','Impact',sans-serif; font-size:1.15rem; color:#F2F2F2;
              border-bottom:2px solid #F5C518; padding-bottom:.2rem; margin-bottom:.1rem; }}
    .col-dono {{ color:#9a9a9a; font-size:.8rem; margin-bottom:.6rem; }}
    .tit {{ font-weight:600; font-size:.88rem; line-height:1.25; margin:.2rem 0; }}
    .meta {{ color:#9a9a9a; font-size:.75rem; }}
    .pill {{ display:inline-block; font-size:.7rem; padding:1px 8px; border-radius:99px;
             margin-top:.3rem; background:#262626; color:#d0d0d0; }}
    .pill.quarentena {{ background:#3a1414; color:#ff8a8a; }}
    .pill.agendado, .pill.aprovado {{ background:#3a3210; color:#F5C518; }}
    .pill.publicado {{ background:#12301f; color:#7fdca4; }}
    .motivo {{ color:#ffb0b0; font-size:.75rem; margin-top:.25rem; }}
    </style>""", unsafe_allow_html=True)


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
        st.markdown(f"<div class='tit'>{b.titulo or b.tema or f'Bloco {b.bloco_id}'}</div>",
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
    por_agente = (recorte.groupby("agente")
                  .agg(tokens_in=("tokens_in", "sum"), tokens_out=("tokens_out", "sum"),
                       custo_usd=("custo_usd", "sum"), eventos=("id", "count"),
                       falhas=("status", lambda s: (s == "falha").sum()))
                  .sort_values("custo_usd", ascending=False))
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("<h3>Custo por agente (US$)</h3>", unsafe_allow_html=True)
        st.bar_chart(por_agente["custo_usd"], color="#F5C518", horizontal=True)
    with c2:
        st.markdown("<h3>Resumo</h3>", unsafe_allow_html=True)
        st.dataframe(por_agente, width="stretch",
                     column_config={"custo_usd": st.column_config.NumberColumn(format="$%.2f"),
                                    "tokens_in": st.column_config.NumberColumn(format="%d"),
                                    "tokens_out": st.column_config.NumberColumn(format="%d")})

    st.markdown("<h3>Tempo por etapa (média, min)</h3>", unsafe_allow_html=True)
    ok = recorte[(recorte["status"] == "ok") & recorte["duracao_s"].notna()]
    if ok.empty:
        st.caption("Sem etapas concluídas no período.")
    else:
        st.bar_chart((ok.groupby("etapa")["duracao_s"].mean() / 60).round(1), color="#F5C518")


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
_css()
st.markdown("<p class='marca'>MISSÃO EM CORTES <span>· painel</span></p>"
            "<p class='sub'>Cada coluna é uma responsabilidade. Os cards andam sozinhos "
            "conforme os agentes trabalham.</p>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("<h3>Controles</h3>", unsafe_allow_html=True)
    if st.button("Sincronizar com outputs/", width="stretch"):
        sincronizar()
    auto = st.toggle("Atualizar a cada 10s", value=True)
    st.caption(f"Banco: `{DB_PATH.relative_to(ROOT) if DB_PATH.is_relative_to(ROOT) else DB_PATH}`")


@st.fragment(run_every=10 if auto else None)
def corpo() -> None:
    videos, blocos, eventos, tarefas = carregar()
    agora = pd.Timestamp.now()
    cfg = hoje.config_painel()
    est = carregar_estoque()
    hoje.faixa_alertas(hoje.alertas_curador(eventos, agora) + hoje.alertas_token(eventos, agora)
                       + hoje.alerta_cota(pct_alerta=cfg["cota_alerta_pct"])
                       + hoje.alertas_operacao(est, hoje.no_ar(blocos, (agora + pd.Timedelta(days=1)).date())))
    faixa_decisoes(tarefas)
    if videos.empty and tarefas.empty:
        st.warning("Banco vazio. Clique em **Sincronizar com outputs/** na barra lateral "
                   "pra importar os vídeos que você já processou.")
        return

    semana = eventos[eventos["ts"] >= pd.Timestamp.now() - pd.Timedelta(days=7)] \
        if not eventos.empty else eventos
    contar = lambda sts: int(blocos["status"].isin(sts).sum()) if not blocos.empty else 0  # noqa: E731
    m = st.columns(6)
    m[0].metric("Na edição", contar({"segmentado", "cortado"}))
    m[1].metric("Aguardando revisão", contar({"montado", "revisao"}))
    m[2].metric("Quarentena", contar({"quarentena"}))
    m[3].metric("Prontos p/ publicar", contar({"aprovado"}))
    m[4].metric("Agendados", contar({"agendado"}))
    m[5].metric("Custo 7 dias", f"${semana['custo_usd'].sum():.2f}" if not semana.empty else "$0.00")

    aba_h, aba_k, aba_a, aba_t, aba_d = st.tabs(["Hoje", "Kanban", "Agentes e custo",
                                                 "Linha do tempo", "Time de dev"])
    with aba_h:
        custo = hoje.custo_mes(carregar_custo_mes(agora.strftime("%Y-%m-01")),
                               cfg["orcamento_mensal_usd"], agora)
        hoje.aba_hoje(blocos, tarefas, est, custo, agora)
    with aba_k:
        kanban(videos, blocos)
    with aba_a:
        aba_agentes(eventos)
    with aba_t:
        aba_timeline(eventos)
    with aba_d:
        aba_time_dev(eventos, tarefas)


corpo()
