"""Aba "Analytics" do painel: a foto diária do YouTube Analytics por vídeo (17_analytics).

Só LÊ as tabelas metricas_video / trafego_video / termos_busca / termos_canal / em_alta da
coleta mais recente, mais o histórico (views por dia, semana contra semana), views_7d e o
publish_at dos blocos pro diagnóstico do topo. Sem coleta ainda, mostra como rodar.
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import visual

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from _analise_canal import (ROTULO_FAIXA, SEMANAS_7D, fora_da_busca, media_7d,  # noqa: E402
                            minutos_por_faixa)
from _youtube_leitura import MAX_SHORT_S, nome_origem, normalizar  # noqa: E402

VAZIO = {"data": None, "metricas": pd.DataFrame(), "trafego": pd.DataFrame(),
         "termos": pd.DataFrame(), "termos_canal": pd.DataFrame(), "em_alta": pd.DataFrame(),
         "reach_desde": None, "historico": pd.DataFrame(), "trafego_semana": {},
         "trafego_semana_antes": {}, "v7": [], "publicacoes": pd.DataFrame()}

DIAS_HISTORICO = 30       # views por dia: quantos dias de coleta o gráfico mostra
SEMANAS_CADENCIA = 8      # longos publicados por semana: quantas semanas
# Limiares da "leitura" do diagnóstico (chute inicial; ajustar com o canal crescendo)
VARIACAO_RELEVANTE = 0.20     # views da semana ±20% contra a anterior
CONCENTRACAO_ALTA = 0.50      # um vídeo com metade ou mais de todas as views
FORA_DA_BUSCA_BAIXO = 25.0    # % das views que não vêm da busca
LONGOS_MIN_SEMANA = 5         # longos publicados nos últimos 7 dias
DIAS_COLETA_VELHA = 1         # coleta mais velha que isso = o 17 parou de gravar
MIN_VIDEOS_FAIXA = 3          # faixa de duração com menos vídeos não entra na comparação


def _opcional(con, sql: str, params=()) -> pd.DataFrame:
    """read_sql que devolve vazio em banco anterior à tabela."""
    try:
        return pd.read_sql(sql, con, params=params)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return pd.DataFrame()


def _diagnostico(con, data: str) -> dict:
    """Dados do diagnóstico além da foto do dia: histórico de views por vídeo, origens do canal
    na semana (e na de 7+ dias antes), views dos 7 primeiros dias e o publish_at dos blocos."""
    hist = _opcional(con, "SELECT data, youtube_id, views FROM metricas_video "
                          "WHERE data >= date(?, ?)", (data, f"-{DIAS_HISTORICO + 14} days"))
    semana = lambda d: ({} if d is None else {r[0]: r[1] for r in con.execute(   # noqa: E731
        "SELECT origem, views FROM trafego_canal WHERE data = ?", (d,))})
    try:
        ult = con.execute("SELECT MAX(data) FROM trafego_canal").fetchone()[0]
        antes = (con.execute("SELECT MAX(data) FROM trafego_canal WHERE data <= date(?, '-7 days')",
                             (ult,)).fetchone()[0] if ult else None)
        traf, traf_antes = semana(ult), semana(antes)
    except sqlite3.OperationalError:
        traf, traf_antes = {}, {}
    v7 = _opcional(con, "SELECT * FROM views_7d")
    pub = _opcional(con, "SELECT publish_at FROM blocos WHERE status IN ('agendado', 'publicado') "
                         "AND publish_at IS NOT NULL")
    return {"historico": hist, "trafego_semana": traf, "trafego_semana_antes": traf_antes,
            "v7": v7.to_dict("records"), "publicacoes": pub}


def carregar(db_path: Path) -> dict:
    """A coleta mais recente: {data, metricas, trafego, termos, termos_canal, em_alta}
    (DataFrames) + reach_desde (1º dia com impressões do relatório Reach, ou None)."""
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
        try:   # banco anterior às tabelas do Reach
            reach_desde = con.execute("SELECT MIN(dia) FROM reach_dia").fetchone()[0]
        except sqlite3.OperationalError:
            reach_desde = None
        try:   # banco anterior à tabela em_alta
            alta = ler("em_alta")
        except (sqlite3.OperationalError, pd.errors.DatabaseError):
            alta = pd.DataFrame()
        return {**_diagnostico(con, data), "reach_desde": reach_desde, "em_alta": alta,
                "data": data, "metricas": ler("metricas_video"), "trafego": ler("trafego_video"),
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


def tabela_em_alta(em_alta: pd.DataFrame) -> pd.DataFrame:
    """Vídeos antigos em alta, maior fator primeiro; sem tema (Short/sem bloco) = título."""
    if em_alta.empty:
        return em_alta
    df = em_alta.assign(tema=em_alta["tema"].fillna(em_alta["titulo"]),
                        publicado=pd.to_datetime(em_alta["publicado"], utc=True, errors="coerce"))
    return df.sort_values(["fator", "views_semana"], ascending=False)[
        ["tema", "titulo", "publicado", "views_semana", "fator", "views_total"]]


def _dec(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _pct(v: float | None, casas: int = 1) -> str:
    return "—" if v is None else f"{v:.{casas}f}%".replace(".", ",")


# ── diagnóstico do canal (topo da aba) ─────────────────────────────────────

def _views_em(hist: pd.DataFrame, dia: date) -> pd.Series | None:
    """Views acumuladas por vídeo na coleta mais recente até `dia` (None sem coleta até lá)."""
    datas = pd.to_datetime(hist["data"]).dt.date if not hist.empty else pd.Series(dtype=object)
    ate = hist[datas <= dia] if not hist.empty else hist
    if ate.empty:
        return None
    ultima = ate["data"].max()
    return ate[ate["data"] == ultima].set_index("youtube_id")["views"].fillna(0)


def views_semana(hist: pd.DataFrame, data: str) -> tuple[int | None, int | None]:
    """(views nos 7 dias até `data`, views nos 7 dias antes disso), pela diferença do acumulado
    de cada vídeo entre coletas; vídeo que não existia na coleta antiga conta do zero. None
    quando falta a coleta de 7 (ou 14) dias antes."""
    d = date.fromisoformat(data)
    fotos = [_views_em(hist, d - pd.Timedelta(days=7 * i)) for i in range(3)]

    def diff(novo, velho):
        if novo is None or velho is None:
            return None
        return int((novo - velho.reindex(novo.index).fillna(0)).clip(lower=0).sum())
    return diff(fotos[0], fotos[1]), diff(fotos[1], fotos[2])


def views_por_dia(hist: pd.DataFrame, dias: int = DIAS_HISTORICO) -> pd.Series:
    """Views novas por dia (acumulado do canal menos o da coleta do dia anterior), só entre
    coletas de dias seguidos: buraco na coleta não vira um dia falso com várias de uma vez.
    Índice 'dd/mm' do dia da coleta, os últimos `dias`."""
    if hist.empty:
        return pd.Series(dtype=float)
    tot = hist.groupby("data")["views"].sum().sort_index()
    idx = pd.to_datetime(tot.index)
    seguidos = (idx[1:] - idx[:-1]).days == 1
    s = pd.Series((tot.values[1:] - tot.values[:-1])[seguidos], index=idx[1:][seguidos])
    s = s.clip(lower=0).tail(dias)
    s.index = [f"{d:%d/%m}" for d in s.index]
    return s


def concentracao(metricas: pd.DataFrame) -> tuple[float, str] | None:
    """(fração de todas as views que vêm do vídeo mais visto, título dele); None sem views."""
    if metricas.empty or not metricas["views"].fillna(0).sum():
        return None
    top = metricas.sort_values("views", ascending=False).iloc[0]
    return float(top["views"] / metricas["views"].fillna(0).sum()), str(top["titulo"])


def publicados_por_semana(pub: pd.DataFrame, agora: pd.Timestamp,
                          semanas: int = SEMANAS_CADENCIA) -> pd.Series:
    """Longos que foram ao ar em cada uma das últimas `semanas` janelas de 7 dias até `agora`
    (agendado no futuro não conta). Índice 'dd/mm' do 1º dia da janela, da mais antiga pra
    mais nova; a última é a semana corrente."""
    agora = (agora.tz_localize("America/Sao_Paulo") if agora.tzinfo is None else agora).tz_convert("UTC")
    quando = (pd.to_datetime(pub["publish_at"], utc=True, errors="coerce").dropna()
              if not pub.empty else pd.Series(dtype="datetime64[ns, UTC]"))
    saida = {}
    for i in range(semanas - 1, -1, -1):
        fim = agora - pd.Timedelta(days=7 * i)
        ini = fim - pd.Timedelta(days=7)
        saida[f"{ini.tz_convert('America/Sao_Paulo'):%d/%m}"] = int(((quando > ini) & (quando <= fim)).sum())
    s = pd.Series(saida)
    inicio = s.to_numpy().nonzero()[0]
    # semanas zeradas antes da 1ª publicação da janela não dizem nada; a corrente fica sempre
    return s.iloc[min(inicio[0], len(s) - 2) if len(inicio) else len(s) - 2:]


def tabela_faixas(metricas: pd.DataFrame) -> pd.DataFrame:
    """Minutos assistidos por view e retenção por faixa de duração (mesma conta do resumo
    semanal), com rótulo legível."""
    if metricas.empty:
        return pd.DataFrame()
    linhas = minutos_por_faixa(metricas.to_dict("records"))
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df["faixa"] = df["faixa"].map(lambda f: ROTULO_FAIXA.get(f, "todos"))
    df["retencao"] = df["retencao_pct"] / 100
    return df[["faixa", "n", "views", "min_por_view", "retencao"]]


def diagnostico(dados: dict, agora: pd.Timestamp) -> dict:
    """Os números do diagnóstico, já calculados (sem streamlit), pra testar e desenhar."""
    data = dados["data"]
    atual, anterior = views_semana(dados["historico"], data)
    pub = publicados_por_semana(dados["publicacoes"], agora)
    hoje = agora.date()
    n7, media7 = media_7d(dados["v7"], hoje, SEMANAS_7D)
    _, media7_antes = media_7d(dados["v7"], hoje, SEMANAS_7D, desloc=SEMANAS_7D)
    return {"data": data, "dias_coleta": (hoje - date.fromisoformat(data)).days,
            "views_semana": atual, "views_semana_antes": anterior,
            "busca": fora_da_busca(dados["trafego_semana"]),
            "busca_antes": fora_da_busca(dados["trafego_semana_antes"]),
            "concentracao": concentracao(dados["metricas"]),
            "publicados": pub, "longos_semana": int(pub.iloc[-1]) if not pub.empty else 0,
            "longos_semana_antes": int(pub.iloc[-2]) if len(pub) > 1 else None,
            "novos_n": n7, "novos_media": media7, "novos_media_antes": media7_antes,
            "faixas": tabela_faixas(dados["metricas"]),
            "por_dia": views_por_dia(dados["historico"])}


def leitura(d: dict) -> list[tuple[str, str]]:
    """O diagnóstico em frases curtas, (tom, texto), na ordem do que mais pede ação.
    tom: 'erro' | 'alerta' | 'ok' | ''. Limiares no topo do módulo."""
    frases = []
    if d["dias_coleta"] > DIAS_COLETA_VELHA:
        frases.append(("erro", f"A última coleta do Analytics é de {pd.Timestamp(d['data']):%d/%m} "
                               f"({d['dias_coleta']} dias atrás): os números abaixo estão velhos. "
                               "Veja os avisos do 17_analytics na Linha do tempo."))
    if d["longos_semana"] < LONGOS_MIN_SEMANA:
        antes = (f" (semana anterior: {d['longos_semana_antes']})"
                 if d["longos_semana_antes"] is not None else "")
        frases.append(("alerta", f"Só {d['longos_semana']} longo(s) foram ao ar nos últimos 7 "
                                 f"dias{antes}. Com o canal vivendo de busca, cada vídeo a menos "
                                 "é uma chance a menos de aparecer."))
    a, b = d["views_semana"], d["views_semana_antes"]
    if a is not None and b:
        var = (a - b) / b
        if var <= -VARIACAO_RELEVANTE:
            frases.append(("alerta", f"As views caíram {abs(var):.0%} na semana ({a} contra {b})."))
        elif var >= VARIACAO_RELEVANTE:
            frases.append(("ok", f"As views subiram {var:.0%} na semana ({a} contra {b})."))
    c = d["concentracao"]
    if c and c[0] >= CONCENTRACAO_ALTA:
        frases.append(("alerta", f"{c[0]:.0%} de todas as views vêm de um vídeo só "
                                 f"({c[1][:60]}). O canal depende dele: o tema dele é o que "
                                 "já provou trazer busca."))
    if d["busca"] and d["busca"]["fora_pct"] < FORA_DA_BUSCA_BAIXO:
        frases.append(("", f"Só {d['busca']['fora_pct']:.0f}% das views da semana vêm de fora da "
                           "busca: o YouTube ainda não recomenda o canal. Títulos com os termos "
                           "que as pessoas pesquisam seguem sendo o motor."))
    fx = d["faixas"]
    if not fx.empty:
        fx = fx[(fx["faixa"] != "todos") & (fx["n"] >= MIN_VIDEOS_FAIXA)]
        if len(fx) > 1:
            ret, mpv = fx.loc[fx["retencao"].idxmax()], fx.loc[fx["min_por_view"].idxmax()]
            texto = f"Quem segura mais o público são os cortes da faixa {ret['faixa']} ({ret['retencao']:.0%} de retenção)"
            texto += ("." if ret["faixa"] == mpv["faixa"] else
                      f"; os da faixa {mpv['faixa']} rendem mais minutos por view "
                      f"({_dec(mpv['min_por_view'])} min). Coerência acima da duração.")
            frases.append(("", texto))
    if d["novos_media"] is not None:
        antes = (f" (nas {SEMANAS_7D} semanas antes: {_dec(d['novos_media_antes'])})"
                 if d["novos_media_antes"] is not None else "")
        frases.append(("", f"Vídeos novos fazem em média {_dec(d['novos_media'])} views nos 7 "
                           f"primeiros dias{antes}, em {d['novos_n']} longo(s)."))
    return frases


_ICONE = {"erro": "🔴 ", "alerta": "🟡 ", "ok": "🟢 ", "": ""}


def secao_diagnostico(dados: dict, agora: pd.Timestamp) -> None:
    d = diagnostico(dados, agora)
    st.markdown("<h3>Diagnóstico do canal</h3>", unsafe_allow_html=True)
    frases = leitura(d)
    if frases:
        st.markdown("\n".join(f"- {_ICONE[t]}{texto}" for t, texto in frases))
    a, b = d["views_semana"], d["views_semana_antes"]
    var = f"{(a - b) / b:+.0%} contra a semana anterior ({b})" if a is not None and b else \
        "sem coleta de 7 dias antes pra comparar"
    busca = d["busca"]
    c = d["concentracao"]
    visual.grade([
        visual.cartao("Views nos últimos 7 dias", "—" if a is None else f"{a}", var,
                      tom="alerta" if a is not None and b and (a - b) / b <= -VARIACAO_RELEVANTE else "",
                      ajuda="Diferença do acumulado de cada vídeo entre a coleta de hoje e a de 7 "
                            "dias antes (longos e Shorts)."),
        visual.cartao("Longos no ar (7 dias)", f"{d['longos_semana']}",
                      f"semana anterior: {d['longos_semana_antes']}"
                      if d["longos_semana_antes"] is not None else "",
                      tom="alerta" if d["longos_semana"] < LONGOS_MIN_SEMANA else "",
                      ajuda="Blocos agendados/publicados cujo horário de ir ao ar caiu nos últimos 7 dias."),
        visual.cartao("Fora da busca", _pct(busca["fora_pct"], 0) if busca else "—",
                      (f"recomendação: {_pct(busca['recomendacao_pct'], 0)}"
                       + (f" · antes {_pct(d['busca_antes']['fora_pct'], 0)}" if d["busca_antes"] else ""))
                      if busca else "sem origens de tráfego da semana",
                      ajuda="% das views da semana que não vieram da busca do YouTube. Recomendação = "
                            "início/feed, sugeridos e Shorts: o sinal de que o algoritmo começou a empurrar."),
        visual.cartao("Vídeo novo, 7 primeiros dias",
                      "—" if d["novos_media"] is None else _dec(d["novos_media"]),
                      f"média de views · {d['novos_n']} longo(s) das últimas {SEMANAS_7D} semanas",
                      ajuda="Views que cada longo fez do dia da publicação até o 7º dia."),
        visual.cartao("Vídeo mais visto", "—" if not c else _pct(100 * c[0], 0),
                      "das views do canal" if c else "",
                      tom="alerta" if c and c[0] >= CONCENTRACAO_ALTA else "",
                      ajuda=f"Quanto do total vem de um vídeo só: {c[1]}" if c else ""),
    ])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<h4>Views novas por dia</h4>", unsafe_allow_html=True)
        if d["por_dia"].empty:
            st.caption("Precisa de pelo menos 2 coletas em dias seguidos.")
        else:
            visual.colunas(d["por_dia"], nome="views")
            st.caption("Pela data da coleta; o Analytics atrasa ~2 dias. Dia sem coleta fica de fora.")
    with c2:
        st.markdown("<h4>Longos no ar por semana</h4>", unsafe_allow_html=True)
        visual.colunas(d["publicados"], nome="longos")
        st.caption("Janelas de 7 dias até agora (a última é a semana corrente), pelo 1º dia.")
    if not d["faixas"].empty:
        st.markdown("<h4>Por faixa de duração (longos)</h4>", unsafe_allow_html=True)
        st.dataframe(d["faixas"], width="stretch", hide_index=True, column_config={
            "faixa": st.column_config.TextColumn("faixa"),
            "n": st.column_config.NumberColumn("vídeos", format="%d"),
            "views": st.column_config.NumberColumn(format="%d"),
            "min_por_view": st.column_config.NumberColumn("min assistidos por view", format="%.1f"),
            "retencao": st.column_config.NumberColumn("retenção", format="percent")})
        st.caption("Acumulado desde a publicação; duração do corte, sem cold open, intro, card e outro.")


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
    reach = (f"impressões/CTR desde {pd.Timestamp(dados['reach_desde']):%d/%m} (relatório Reach)"
             if dados.get("reach_desde") else "impressões/CTR: o 1º relatório Reach sai ~48h depois "
             "de criar o job")
    st.caption(f"Coleta de {pd.Timestamp(dados['data']):%d/%m/%Y} · acumulado desde a publicação "
               f"de cada vídeo · o Analytics atrasa ~2 dias · {reach}")
    secao_diagnostico(dados, pd.Timestamp.now(tz="America/Sao_Paulo"))
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
    st.markdown("<h3>Vídeos antigos em alta</h3>", unsafe_allow_html=True)
    alta = tabela_em_alta(dados["em_alta"])
    if alta.empty:
        st.caption("Nenhum vídeo com mais de 30 dias disparou na última semana.")
    else:
        st.dataframe(alta, width="stretch", hide_index=True, column_config={
            "tema": st.column_config.TextColumn("tema", width="medium"),
            "titulo": st.column_config.TextColumn("título", width="large"),
            "publicado": st.column_config.DatetimeColumn("publicado", format="DD/MM/YY"),
            "views_semana": st.column_config.NumberColumn("views na semana", format="%d"),
            "fator": st.column_config.NumberColumn("x o ritmo de antes", format="%.1fx"),
            "views_total": st.column_config.NumberColumn("views no total", format="%d")})
        st.caption("Publicados há 30+ dias com 3x+ as views semanais de antes (mín. 50 na semana). "
                   "O Curador dá prioridade a lives novas sobre esses temas.")
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
