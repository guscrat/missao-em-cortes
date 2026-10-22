"""Aba "Time de dev" do painel: o Gu (PO) acompanha o time em nível macro.

Lê `tarefas` (scripts/tarefa.py) e `eventos` (hooks do Claude Code + tarefa.py). Nada de
comando ou diff aqui — só quem está fazendo o quê e o que espera decisão.
"""
import html
import re

import pandas as pd
import streamlit as st

AGENTES = [
    ("tech-lead", "Tech lead", "planeja, implementa e faz o merge"),
    ("testador", "Testador", "roda e escreve os testes"),
    ("revisor-codigo", "Revisor", "revisa o código antes do PR"),
]
JANELA_ATIVO = pd.Timedelta(minutes=10)
LIMITE_ATIVIDADE = 90   # chars da "última atividade" no card (1 linha)
COLUNAS_TAREFA = [("backlog", "Backlog"), ("fazendo", "Fazendo"), ("testando", "Testando"),
                  ("revisando", "Revisando"), ("pronto", "Pronto"), ("bloqueado", "Bloqueado")]


def humanizar(ts: pd.Timestamp, agora: pd.Timestamp) -> str:
    seg = (agora - ts).total_seconds()
    if seg < 60:
        return "agora há pouco"
    if seg < 3600:
        return f"há {int(seg // 60)} min"
    if seg < 86400:
        return f"há {int(seg // 3600)} h"
    if seg < 2 * 86400:
        return "ontem"
    return ts.strftime("%d/%m")


_MD = [
    (re.compile(r"```.*?(```|$)", re.S), " "),              # blocos de código
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),        # [texto](url) → texto
    (re.compile(r"`([^`]*)`"), r"\1"),                      # `código`
    # **negrito**, *itálico*, ~~x~~ — só fora de palavra (2*3*4 e __init__ ficam como estão)
    (re.compile(r"(?<![\w*~])(\*\*|\*|~~)(?=\S)(.+?)(?<=\S)\1(?![\w*~])"), r"\2"),
    (re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)", re.M), ""),  # título, citação, lista
    (re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", re.M), " "),  # separador de tabela
    (re.compile(r"\s*\|\s*"), " · "),                          # células de tabela
]


def texto_limpo(texto: str, limite: int = LIMITE_ATIVIDADE) -> str:
    """Markdown → texto puro numa linha só, cortado com "…" se passar do limite."""
    t = texto if isinstance(texto, str) else ""      # None/NaN do banco viram vazio
    for padrao, troca in _MD:
        t = padrao.sub(troca, t)
    t = re.sub(r"[\s·]*·[\s·]*", " · ", t)          # " · " repetido das tabelas
    t = " ".join(t.split()).strip(" ·")
    if len(t) <= limite:
        return t
    corte = t[:limite - 1]
    if " " in corte[limite // 2:]:                    # não corta palavra ao meio
        corte = corte[:corte.rfind(" ")]
    return corte.rstrip(" ·,;:-") + "…"


def descrever(ev: pd.Series) -> str:
    """Evento → frase pro PO (texto limpo, uma linha)."""
    msg = texto_limpo(ev.get("mensagem") or "")
    if ev["etapa"] == "subagent":
        return msg if ev["status"] == "inicio" else f"terminou: {msg}" if msg else "terminou"
    if ev["etapa"] == "turno":
        return f"respondeu: {msg}" if msg else "terminou o turno"
    return msg or f"{ev['etapa']} · {ev['status']}"


def status_agente(agente: str, eventos: pd.DataFrame, agora: pd.Timestamp) -> tuple[bool, str]:
    """(trabalhando?, última atividade em linguagem humana)."""
    meus = eventos[eventos["agente"] == agente] if not eventos.empty else eventos
    if meus.empty:
        return False, "sem atividade registrada"
    ultimo = meus.sort_values("ts").iloc[-1]
    recente = agora - ultimo["ts"] <= JANELA_ATIVO
    if agente == "tech-lead":
        trabalhando = recente and ultimo["etapa"] != "turno"   # turno fechado = esperando
    else:
        trabalhando = recente and ultimo["status"] == "inicio"
    return trabalhando, f"{humanizar(ultimo['ts'], agora)} · {descrever(ultimo)}"


def decisoes_pendentes(tarefas: pd.DataFrame) -> pd.DataFrame:
    if tarefas.empty:
        return tarefas
    return tarefas[tarefas["decisao_pendente"].fillna("").str.strip() != ""]


def custo_semana_por_tarefa(eventos: pd.DataFrame, tarefas: pd.DataFrame,
                            agora: pd.Timestamp) -> pd.DataFrame:
    if eventos.empty or "tarefa_id" not in eventos:
        return pd.DataFrame()
    semana = eventos[(eventos["ts"] >= agora - pd.Timedelta(days=7))
                     & eventos["tarefa_id"].notna() & (eventos["custo_usd"] > 0)]
    if semana.empty:
        return pd.DataFrame()
    custo = semana.groupby("tarefa_id")["custo_usd"].sum().reset_index()
    titulos = tarefas.set_index("id")["titulo"] if not tarefas.empty else pd.Series(dtype=str)
    custo["tarefa"] = custo["tarefa_id"].map(lambda i: f"#{int(i)} {titulos.get(int(i), '')}")
    return custo[["tarefa", "custo_usd"]].sort_values("custo_usd", ascending=False)


# ── render ─────────────────────────────────────────────────────────────────

CSS = """<style>
.faixa {background:#F5C518; color:#0A0A0A; border-radius:8px; padding:.7rem 1rem; margin-bottom:1rem;}
.faixa b {font-family:'Anton','Impact',sans-serif; font-weight:400; letter-spacing:.03em;}
.faixa div {margin-top:.2rem;}
.ag-nome {font-family:'Anton','Impact',sans-serif; font-size:1.1rem; color:#F2F2F2;}
.ag-st {font-size:.8rem; font-weight:600;}
.ag-st.on {color:#7fdca4;} .ag-st.off {color:#9a9a9a;} .ag-st.voce {color:#F5C518;}
.ag-papel {color:#9a9a9a; font-size:.72rem;}
.ag-ult {font-size:.8rem; margin-top:.35rem; line-height:1.25;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.decisao {color:#F5C518; font-size:.75rem; margin-top:.25rem;}
</style>"""


def faixa_decisoes(tarefas: pd.DataFrame) -> None:
    pend = decisoes_pendentes(tarefas)
    if pend.empty:
        return
    itens = "".join(f"<div>#{int(t.id)} {html.escape(t.titulo)} — "
                    f"<b>{html.escape(t.decisao_pendente)}</b></div>" for t in pend.itertuples())
    st.markdown(f"{CSS}<div class='faixa'><b>ESPERANDO DECISÃO SUA ({len(pend)})</b>{itens}</div>",
                unsafe_allow_html=True)


def _card_agente(nome: str, papel: str, trabalhando: bool, ultima: str, cls: str | None = None) -> None:
    rotulo = {"voce": "● esperando você", "on": "● trabalhando", "off": "○ parado"}
    cls = cls or ("on" if trabalhando else "off")
    with st.container(border=True):
        st.markdown(f"<div class='ag-nome'>{nome}</div><div class='ag-papel'>{papel}</div>"
                    f"<div class='ag-st {cls}'>{rotulo[cls]}</div>"
                    f"<div class='ag-ult' title='{html.escape(ultima, quote=True)}'>{html.escape(ultima)}</div>", unsafe_allow_html=True)


def _card_tarefa(t: pd.Series) -> None:
    with st.container(border=True):
        st.markdown(f"<div class='tit'>#{int(t.id)} {html.escape(t.titulo)}</div>",
                    unsafe_allow_html=True)
        meta = [x for x in (t.responsavel, t.branch) if isinstance(x, str) and x]
        if t.rodada:
            meta.append(f"rodada {int(t.rodada)}")
        st.markdown(f"<div class='meta'>{html.escape(' · '.join(meta))}</div>", unsafe_allow_html=True)
        if isinstance(t.ultimo_resultado, str) and t.ultimo_resultado:
            cls = "publicado" if t.ultimo_resultado.startswith("APROVADO") else "quarentena"
            st.markdown(f"<span class='pill {cls}'>{html.escape(t.ultimo_resultado[:60])}</span>",
                        unsafe_allow_html=True)
        if isinstance(t.decisao_pendente, str) and t.decisao_pendente.strip():
            st.markdown(f"<div class='decisao'>❓ {html.escape(t.decisao_pendente)}</div>",
                        unsafe_allow_html=True)


def aba_time_dev(eventos: pd.DataFrame, tarefas: pd.DataFrame, agora: pd.Timestamp | None = None) -> None:
    agora = agora or pd.Timestamp.now()
    st.markdown(CSS, unsafe_allow_html=True)

    cols = st.columns(len(AGENTES) + 1)
    for col, (agente, nome, papel) in zip(cols, AGENTES):
        with col:
            _card_agente(nome, papel, *status_agente(agente, eventos, agora))
    with cols[-1]:
        n = len(decisoes_pendentes(tarefas))
        _card_agente("Você", "PO: decide o rumo, não revisa código", n > 0,
                     f"{n} decisão(ões) na faixa amarela" if n else "nada pendente",
                     cls="voce" if n else "off")

    st.markdown("<h3>Tarefas</h3>", unsafe_allow_html=True)
    if tarefas.empty:
        st.info("Nenhuma tarefa ainda. O tech lead cria com `scripts/tarefa.py nova`.")
    else:
        kcols = st.columns(len(COLUNAS_TAREFA))
        for col, (etapa, nome) in zip(kcols, COLUNAS_TAREFA):
            itens = tarefas[tarefas["etapa"] == etapa].sort_values("atualizado_em", ascending=False)
            with col:
                st.markdown(f"<div class='col-h'>{nome} · {len(itens)}</div>", unsafe_allow_html=True)
                for _, t in itens.head(10 if etapa == "pronto" else 20).iterrows():
                    _card_tarefa(t)

    custo = custo_semana_por_tarefa(eventos, tarefas, agora)
    if not custo.empty:
        st.markdown("<h3>Custo de API da semana por tarefa</h3>", unsafe_allow_html=True)
        st.dataframe(custo, hide_index=True, width="stretch",
                     column_config={"custo_usd": st.column_config.NumberColumn("custo", format="$%.2f")})
