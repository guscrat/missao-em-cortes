"""Identidade visual do painel: tema grafite/creme, cartões de métrica e barras com rótulo.

O tema nativo (widgets, tabelas, abas) vem do .streamlit/config.toml ([theme.dark] grafite,
[theme.light] creme). O HTML próprio do painel usa as variáveis CSS daqui (--tx, --card...),
escolhidas pelo tema ativo no navegador (st.context.theme.type).

Seletor da barra lateral: o Streamlit guarda a escolha do menu ⋮ → Settings no localStorage
(chave stActiveTheme-<path>-v2 = "Light"|"Dark"). O seletor grava essa chave e recarrega a
página, então o tema nativo e o nosso trocam juntos.
"""
import base64
import html
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
FONTE_ANTON = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
AMARELO = "#F5C518"

# Mesmos valores do .streamlit/config.toml (bg, sidebar, texto, borda) + os do HTML próprio.
TOKENS = {
    "dark": {"bg": "#1B1C20", "card": "#25272C", "borda": "#363940", "tx": "#ECEDEF",
             "tx2": "#C3C6CD", "mudo": "#A2A6AE", "acento": AMARELO, "acento-tx": AMARELO,
             "acento-bg": "#3A3416", "erro-bg": "#3B2022", "erro-tx": "#FFB8B8",
             "erro-borda": "#E5534B", "ok-tx": "#86D9A8", "trilho": "#363940"},
    "light": {"bg": "#F3EFE6", "card": "#FBF8F1", "borda": "#DCD4C4", "tx": "#1E1E1E",
              "tx2": "#45474C", "mudo": "#5F6268", "acento": AMARELO, "acento-tx": "#7A5E00",
              "acento-bg": "#F6E9BC", "erro-bg": "#F7E0DC", "erro-tx": "#8E1F17",
              "erro-borda": "#D0453A", "ok-tx": "#1D7A46", "trilho": "#E4DDCF"},
}
TEMAS = {"Escuro": "dark", "Claro": "light"}
CHAVE_TEMA = {"dark": "Dark", "light": "Light"}   # o que o Streamlit grava no localStorage


def tema_ativo() -> str:
    """'dark' | 'light' (o navegador ainda não informou → dark, o padrão do canal)."""
    try:
        tipo = st.context.theme.type
    except AttributeError:   # AppTest / versão sem st.context.theme
        tipo = None
    return tipo if tipo in TOKENS else "dark"


def seletor_tema() -> None:
    """Escuro/Claro na barra lateral. Trocar = gravar a escolha do Streamlit e recarregar."""
    atual = tema_ativo()
    rotulo_atual = next(r for r, t in TEMAS.items() if t == atual)
    escolha = st.segmented_control("Tema", list(TEMAS), default=rotulo_atual,
                                   help="Também dá pra trocar no menu ⋮ → Settings.")
    if escolha and TEMAS[escolha] != atual:
        valor = CHAVE_TEMA[TEMAS[escolha]]
        st.html(f"<script>localStorage.setItem(`stActiveTheme-${{window.location.pathname}}-v2`,"
                f" JSON.stringify('{valor}')); window.location.reload();</script>",
                unsafe_allow_javascript=True)


def css() -> None:
    """Variáveis do tema + estilos compartilhados (marca, cartões, kanban)."""
    tk = TOKENS[tema_ativo()]
    variaveis = ";".join(f"--{k}:{v}" for k, v in tk.items())
    fonte = ""
    if FONTE_ANTON.exists():
        b64 = base64.b64encode(FONTE_ANTON.read_bytes()).decode()
        fonte = f"@font-face{{font-family:'Anton';src:url(data:font/ttf;base64,{b64});}}"
    st.markdown(f"""<style>
    {fonte}
    :root {{ {variaveis}; }}
    /* amarelo como TEXTO nativo (aba ativa, botão do seletor): âmbar escuro no tema claro */
    [data-testid="stTab"][aria-selected="true"] p,
    button[aria-checked="true"] p {{ color:var(--acento-tx) !important; }}
    h1, h2, h3, .anton {{ font-family: 'Anton', 'Impact', sans-serif !important;
                         letter-spacing: .02em; font-weight: 400 !important; }}
    .marca {{ font-family:'Anton','Impact',sans-serif; font-size:2.6rem; line-height:1;
              color:var(--acento-tx); margin:0; }}
    .marca span {{ color:var(--tx); }}
    .sub {{ color:var(--tx2); margin:.2rem 0 1.2rem; }}
    .col-h {{ font-family:'Anton','Impact',sans-serif; font-size:1.15rem; color:var(--tx);
              border-bottom:2px solid var(--acento); padding-bottom:.2rem; margin-bottom:.1rem; }}
    .col-dono {{ color:var(--tx2); font-size:.8rem; margin-bottom:.6rem; }}
    .tit {{ font-weight:600; font-size:.88rem; line-height:1.25; margin:.2rem 0; }}
    .meta {{ color:var(--tx2); font-size:.75rem; }}
    .pill {{ display:inline-block; font-size:.7rem; padding:1px 8px; border-radius:99px;
             margin-top:.3rem; background:var(--trilho); color:var(--tx2); }}
    .pill.quarentena {{ background:var(--erro-bg); color:var(--erro-tx); }}
    .pill.agendado, .pill.aprovado, .pill.nova {{ background:var(--acento-bg); color:var(--acento-tx); }}
    .pill.publicado {{ color:var(--ok-tx); }}
    .motivo {{ color:var(--erro-tx); font-size:.75rem; margin-top:.25rem; }}

    .grade {{ display:grid; gap:12px; margin:.2rem 0 1.4rem; }}
    .grade.g {{ grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); }}
    .grade.p {{ grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); }}
    .ct {{ background:var(--card); border:1px solid var(--borda); border-radius:12px;
           padding:12px 14px; min-width:0; }}
    .grade.g .ct {{ padding:18px 20px; border-radius:14px; }}
    .ct-r {{ color:var(--tx2); font-size:.8rem; font-weight:600; }}
    .grade.g .ct-r {{ font-size:.9rem; }}
    .ct-r abbr {{ text-decoration:none; color:var(--mudo); cursor:help; margin-left:.25rem; }}
    .ct-v {{ color:var(--tx); font-size:1.65rem; font-weight:600; line-height:1.15;
             margin:.25rem 0 .2rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .grade.g .ct-v {{ font-size:3rem; margin:.35rem 0 .3rem; }}
    .ct-v small {{ color:var(--mudo); font-size:.5em; font-weight:400; }}
    .ct-c {{ color:var(--mudo); font-size:.78rem; line-height:1.3; }}
    .grade.g .ct-c {{ font-size:.88rem; }}
    .ct.alerta {{ border-color:var(--acento); box-shadow:inset 4px 0 0 var(--acento); }}
    .ct.alerta .ct-c {{ color:var(--acento-tx); font-weight:600; }}
    .ct.erro {{ border-color:var(--erro-borda); box-shadow:inset 4px 0 0 var(--erro-borda); }}
    .ct.erro .ct-c {{ color:var(--erro-tx); font-weight:600; }}
    .ct.ok .ct-c {{ color:var(--ok-tx); }}
    .medidor {{ height:6px; border-radius:99px; background:var(--trilho); margin:.5rem 0 .2rem;
                overflow:hidden; }}
    .medidor span {{ display:block; height:100%; border-radius:99px; background:var(--acento); }}
    </style>""", unsafe_allow_html=True)


def cartao(rotulo: str, valor, contexto: str = "", tom: str = "", ajuda: str = "",
           medidor: float | None = None) -> str:
    """Um cartão: rótulo em cima, número grande, contexto embaixo. `valor` já vem
    formatado (pode ter <small>); rótulo/contexto/ajuda são escapados aqui.
    tom: '' | 'alerta' (amarelo) | 'erro' | 'ok'. medidor: 0-1 desenha a barrinha."""
    dica = f"<abbr title='{html.escape(ajuda, quote=True)}'>ⓘ</abbr>" if ajuda else ""
    barra = (f"<div class='medidor'><span style='width:{100 * min(max(medidor, 0), 1):.1f}%'></span></div>"
             if medidor is not None else "")
    return (f"<div class='ct {tom}'><div class='ct-r'>{html.escape(rotulo)}{dica}</div>"
            f"<div class='ct-v'>{valor}</div>{barra}<div class='ct-c'>{html.escape(contexto)}</div></div>")


def grade(cartoes: list[str], grande: bool = False) -> None:
    """Cartões alinhados numa grade responsiva. grande=True: o que importa mais."""
    st.markdown(f"<div class='grade {'g' if grande else 'p'}'>{''.join(cartoes)}</div>",
                unsafe_allow_html=True)


def barras(serie: pd.Series, formato=lambda v: f"US$ {v:.2f}", nome: str = "valor") -> None:
    """Barras horizontais com o valor escrito na ponta de cada uma (sem eixo X)."""
    if serie.empty:
        return
    tk = TOKENS[tema_ativo()]
    df = serie.rename_axis("item").reset_index(name="v")
    df["rotulo"] = df["v"].map(formato)
    topo = float(df["v"].max()) or 1.0
    base = alt.Chart(df).encode(
        y=alt.Y("item:N", sort="-x", title=None,
                axis=alt.Axis(domain=False, ticks=False, labelColor=tk["tx2"], labelFontSize=13,
                              labelPadding=8, labelLimit=200)),
        x=alt.X("v:Q", axis=None, scale=alt.Scale(domain=[0, topo * 1.25])),
        tooltip=[alt.Tooltip("item:N", title=" "), alt.Tooltip("rotulo:N", title=nome)])
    graf = (base.mark_bar(color=tk["acento"], cornerRadiusEnd=4, height={"band": 0.68})
            + base.mark_text(align="left", dx=6, color=tk["tx"], fontSize=13, fontWeight=600)
            .encode(text="rotulo:N"))
    st.altair_chart(graf.properties(height=24 + 38 * len(df), background="transparent")
                    .configure_view(stroke=None), width="stretch", theme=None)
