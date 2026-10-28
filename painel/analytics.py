"""Aba "Analytics" do painel: a foto diária do YouTube Analytics por vídeo (17_analytics).

Só LÊ as tabelas metricas_video / trafego_video / termos_busca / termos_canal da coleta
mais recente. Sem coleta ainda, mostra como rodar.
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

import visual

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from _youtube_leitura import MAX_SHORT_S, nome_origem, normalizar  # noqa: E402

VAZIO = {"data": None, "metricas": pd.DataFrame(), "trafego": pd.DataFrame(),
         "termos": pd.DataFrame(), "termos_canal": pd.DataFrame()}


def carregar(db_path: Path) -> dict:
    """A coleta mais recente: {data, metricas, trafego, termos, termos_canal} (DataFrames)."""
    if not db_path.exists():
        return dict(VAZIO)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        data = con.execute("SELECT MAX(data) FROM metricas_video").fetchone()[0]
        if not data:
            return dict(VAZIO)
        ler = lambda tabela, d=data: pd.read_sql(   # noqa: E731
            f"SELECT * FROM {tabela} WHERE data = ?", con, params=(d,))
        canal = con.execute("SELECT MAX(data) FROM termos_canal").fetchone()[0]
        return {"data": data, "metricas": ler("metricas_video"), "trafego": ler("trafego_video"),
                "termos": ler("termos_busca"),
                "termos_canal": ler("termos_canal", canal) if canal else pd.DataFrame()}
    except (sqlite3.OperationalError, pd.errors.DatabaseError):   # banco anterior às tabelas
        return dict(VAZIO)
    finally:
        con.close()


def resumo(metricas: pd.DataFrame) -> dict:
    """Números do topo, só dos vídeos longos: views, CTR ponderado por impressões e retenção
    ponderada por views (None quando não há dado)."""
    longos = metricas[metricas["duracao_s"] > MAX_SHORT_S] if not metricas.empty else metricas
    if longos.empty:
        return {"videos": 0, "views": 0, "impressoes": None, "ctr_pct": None, "retencao_pct": None}
    com_imp = longos[longos["impressoes"].fillna(0) > 0]
    com_ret = longos[longos["retencao_pct"].notna() & (longos["views"] > 0)]
    imp = int(com_imp["impressoes"].sum()) if not com_imp.empty else None
    return {"videos": len(longos), "views": int(longos["views"].fillna(0).sum()),
            "impressoes": imp,
            "ctr_pct": (float((com_imp["ctr_pct"] * com_imp["impressoes"]).sum() / imp)
                        if imp else None),
            "retencao_pct": (float((com_ret["retencao_pct"] * com_ret["views"]).sum()
                                   / com_ret["views"].sum()) if not com_ret.empty else None)}


def origens(trafego: pd.DataFrame) -> pd.Series:
    """Views somadas por origem de tráfego, com nome legível, da maior pra menor."""
    if trafego.empty:
        return pd.Series(dtype=float)
    serie = trafego.groupby("origem")["views"].sum().sort_values(ascending=False)
    serie.index = [nome_origem(o) for o in serie.index]
    return serie


def tabela_videos(metricas: pd.DataFrame, termos: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por vídeo (mais views primeiro) com o termo de busca que mais trouxe views."""
    if metricas.empty:
        return metricas
    top = (termos.sort_values("views", ascending=False).drop_duplicates("youtube_id")
           .set_index("youtube_id")["termo"] if not termos.empty else pd.Series(dtype=str))
    df = metricas.assign(
        tipo=metricas["duracao_s"].map(lambda s: "Short" if s <= MAX_SHORT_S else "longo"),
        termo_top=metricas["youtube_id"].map(top),
        publicado=pd.to_datetime(metricas["publicado"], utc=True, errors="coerce"),
        ctr=metricas["ctr_pct"] / 100, retencao=metricas["retencao_pct"] / 100)
    return df.sort_values("views", ascending=False)[
        ["titulo", "tipo", "publicado", "views", "impressoes", "ctr", "retencao", "assistido_s",
         "termo_top"]]


def _pct(v: float | None, casas: int = 1) -> str:
    return "—" if v is None else f"{v:.{casas}f}%".replace(".", ",")


def aba_analytics(db_path: Path) -> None:
    dados = carregar(db_path)
    if not dados["data"]:
        st.info("Sem coleta do Analytics ainda. O Curador coleta 1x/dia; pra rodar agora: "
                "`uv run py scripts/17_analytics.py`")
        return
    r = resumo(dados["metricas"])
    num = lambda n: f"{n:,}".replace(",", ".")   # noqa: E731
    visual.grade([
        visual.cartao("Views (longos)", num(r["views"]), f"{r['videos']} vídeo(s) públicos"),
        visual.cartao("CTR da miniatura", _pct(r["ctr_pct"]),
                      f"{num(r['impressoes'])} impressões" if r["impressoes"] else "sem impressões",
                      ajuda="Cliques ÷ impressões da thumb no YouTube, ponderado pelas impressões."),
        visual.cartao("Retenção média", _pct(r["retencao_pct"], 0), "% média assistida",
                      ajuda="Média ponderada por views da % do vídeo que a pessoa assiste."),
    ])
    st.caption(f"Coleta de {pd.Timestamp(dados['data']):%d/%m/%Y} · acumulado desde a publicação "
               "de cada vídeo · o Analytics atrasa ~2 dias")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("<h3>Termos de pesquisa da semana</h3>", unsafe_allow_html=True)
        tc = dados["termos_canal"]
        if tc.empty:
            st.caption("Nenhuma view vinda da busca do YouTube nos últimos 7 dias.")
        else:
            visual.barras(tc.sort_values("views", ascending=False).head(10)
                          .set_index("termo")["views"],
                          formato=lambda v: f"{v:.0f} views", nome="views")
            st.caption("O Editor recebe esses termos ao reescrever títulos.")
    with c2:
        st.markdown("<h3>Origens de tráfego</h3>", unsafe_allow_html=True)
        serie = origens(dados["trafego"])
        if serie.empty:
            st.caption("Sem dados de tráfego.")
        else:
            visual.barras(serie.head(8), formato=lambda v: f"{v:.0f} views", nome="views")
    st.markdown("<h3>Por vídeo</h3>", unsafe_allow_html=True)
    busca = st.text_input("Filtrar por título", "")
    df = tabela_videos(dados["metricas"], dados["termos"])
    if busca:
        df = df[df["titulo"].map(normalizar).str.contains(normalizar(busca), regex=False)]
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "titulo": st.column_config.TextColumn("título", width="large"),
        "publicado": st.column_config.DatetimeColumn("publicado", format="DD/MM/YY"),
        "views": st.column_config.NumberColumn(format="%d"),
        "impressoes": st.column_config.NumberColumn("impressões", format="%d"),
        "ctr": st.column_config.NumberColumn("CTR", format="percent"),
        "retencao": st.column_config.NumberColumn("retenção", format="percent"),
        "assistido_s": st.column_config.NumberColumn("duração média (s)", format="%.0f"),
        "termo_top": st.column_config.TextColumn("termo de busca top")})
