"""Aba "Hoje" do painel (tela inicial do PO) + faixa de alertas.

Responde em 10 segundos: o que vai ao ar hoje/amanhã, quantos dias de estoque tem, o que
espera decisão, se a auditoria do YouTube saiu, quanto do orçamento do mês já foi e o
placar do canal rumo ao YPP. Só LÊ: banco, config/ e state/.

Alertas (faixa acima das abas, aparece em qualquer aba):
  - falha do Curador (evento de falha, Traceback no state/curador.log ou não rodou às 17h)
  - erro de download (01_baixar falhou dentro do Curador)
  - token do YouTube/Analytics ausente, sem refresh_token ou recusado (invalid_grant)
  - cota diária do YouTube perto do limite (state/cota_youtube.json, gravado pelo 09)
  - estoque abaixo de dias_minimos e nada agendado pra amanhã

Placar do canal: o Analista grava state/placar.json; até lá a seção fica com o espaço vazio.
  {"atualizado": "2026-11-01T10:00:00-03:00", "inscritos": 312,
   "horas_12m": 845.5, "views_shorts_90d": 120000}
"""
import html
import importlib
import json
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))   # o estoque vem do próprio Curador (13)

CONFIG_PAINEL = ROOT / "config" / "painel.json"
UPLOAD_JSON = ROOT / "config" / "upload.json"
STATE = ROOT / "state"
SECRETS = ROOT / "secrets"

FUSO = ZoneInfo("America/Sao_Paulo")
FUSO_COTA = ZoneInfo("America/Los_Angeles")   # a cota do YouTube vira à meia-noite do Pacífico
HORA_CURADOR = time(17, 0)
FOLGA_CURADOR = timedelta(hours=1)            # 18h sem rodada de hoje = não rodou
JANELA_FALHA = timedelta(hours=48)
JANELA_TOKEN = timedelta(days=7)
TOKENS = [("YouTube (publicar)", "youtube_token.json"), ("YouTube Analytics", "analytics_token.json")]
RE_TOKEN = re.compile(r"invalid_grant|RefreshError|token.*(expir|venc|revog|inv[aá]lid)|"
                      r"unauthorized", re.I)
YPP = {"inscritos": 1000, "horas_12m": 4000, "views_shorts_90d": 10_000_000}
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MODULOS_SCRIPTS = ["_cobertura", "_publicacao", "13_curador"]
_MTIMES: dict[str, float] = {}
PADRAO = {"orcamento_mensal_usd": 10.0, "cota_alerta_pct": 80}


def ler_json(path: Path) -> dict:
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def config_painel() -> dict:
    return {**PADRAO, **{k: v for k, v in ler_json(CONFIG_PAINEL).items() if k in PADRAO}}


def _local(valor) -> datetime | None:
    """publish_at (ISO, com ou sem fuso) → datetime no horário de Brasília (sem tzinfo)."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(FUSO).replace(tzinfo=None) if dt.tzinfo else dt


def no_ar(blocos: pd.DataFrame, dia: date) -> pd.DataFrame:
    """Blocos agendados/publicados que saem no dia, em ordem de horário (coluna `quando`)."""
    if blocos.empty or "publish_at" not in blocos:
        return pd.DataFrame()
    df = blocos[blocos["status"].isin({"agendado", "publicado"})].copy()
    df["quando"] = df["publish_at"].map(_local)
    df = df[df["quando"].map(lambda q: q is not None and q.date() == dia)]
    return df.sort_values("quando")


def scripts_frescos() -> object:
    """13_curador com a versão do disco. O painel fica dias no ar e o Streamlit só recarrega
    o que muda em painel/: sem isto, depois de um merge o Curador das 17h (processo novo)
    e o painel (módulo antigo na memória) passam a contar diferente. Ordem = dependência."""
    mudou = False
    for nome in MODULOS_SCRIPTS:
        mtime = (ROOT / "scripts" / f"{nome}.py").stat().st_mtime
        modulo = sys.modules.get(nome)
        if modulo is None:
            importlib.import_module(nome)
        elif mudou or _MTIMES.get(nome) != mtime:
            importlib.reload(modulo)
            mudou = True               # quem importa o módulo recarregado recarrega também
        _MTIMES[nome] = mtime
    return sys.modules["13_curador"]


def estoque() -> dict | None:
    """O mesmo estoque que o Curador usa às 17h (13_curador.calcular_estoque → _cobertura)
    + o mínimo. Traz também a fila do YouTube (agendados_futuros, ultimo_agendado)."""
    try:
        curador = scripts_frescos()
        cfg = curador.carregar_config()
        est = curador.calcular_estoque(cfg)
        return {**est, "minimo": cfg["estoque"]["dias_minimos"]}
    except Exception as e:  # noqa: BLE001 — painel nunca cai por causa do estoque
        print(f"[aviso] não calculei o estoque ({e})", file=sys.stderr)
        return None


def _nome(b) -> str:
    """titulo > tema > 'bloco N' (NaN do pandas é truthy: checa o tipo)."""
    for campo in ("titulo", "tema"):
        v = getattr(b, campo, None)
        if isinstance(v, str) and v.strip():
            return v
    return f"bloco {b.bloco_id}"


def decisoes(tarefas: pd.DataFrame, blocos: pd.DataFrame) -> list[tuple[str, str]]:
    """[(o quê, pergunta/motivo)]: perguntas do time de dev + blocos em quarentena."""
    itens = []
    if not tarefas.empty and "decisao_pendente" in tarefas:
        for t in tarefas[tarefas["decisao_pendente"].fillna("").str.strip() != ""].itertuples():
            itens.append((f"Tarefa #{int(t.id)} · {t.titulo}", t.decisao_pendente))
    if not blocos.empty:
        for b in blocos[blocos["status"] == "quarentena"].itertuples():
            nome = _nome(b)
            motivo = getattr(b, "motivo", None)
            itens.append((f"Quarentena · {nome} ({b.stem} #{int(b.bloco_id)})",
                          motivo if isinstance(motivo, str) and motivo else
                          "o revisor ficou em dúvida: aprovar ou descartar?"))
    return itens


# ── alertas: (nível "erro"|"aviso", título, detalhe) ──────────────────────

def _falhas_sem_ok(eventos: pd.DataFrame, desde: pd.Timestamp) -> pd.DataFrame:
    """Falhas recentes que não foram seguidas por um ok da mesma etapa+stem."""
    if eventos.empty:
        return eventos
    ev = eventos[eventos["ts"] >= desde].sort_values("ts")
    ultimo = ev[ev["status"].isin({"ok", "falha"})] \
        .groupby([ev["etapa"], ev["stem"].fillna("")]).tail(1)
    return ultimo[ultimo["status"] == "falha"]


def alertas_curador(eventos: pd.DataFrame, agora: pd.Timestamp,
                    log: Path | None = None) -> list[tuple[str, str, str]]:
    log = log or STATE / "curador.log"
    saida = []
    falhas = _falhas_sem_ok(eventos[eventos["agente"] == "curador"] if not eventos.empty
                            else eventos, agora - JANELA_FALHA)
    for f in falhas.itertuples():
        msg = f.mensagem if isinstance(f.mensagem, str) else ""
        quando = f.ts.strftime("%d/%m %Hh%M")
        if "01_baixar" in msg:
            saida.append(("erro", "Erro de download",
                          f"{f.stem} não baixou ({quando}). Vídeo privado/removido ou yt-dlp "
                          f"desatualizado — o Curador tenta o próximo da fila amanhã."))
        else:
            alvo = f" em {f.stem}" if isinstance(f.stem, str) and f.stem else ""
            saida.append(("erro", "Curador falhou", f"{msg or f.etapa}{alvo} ({quando})"))
    try:
        rodou = datetime.fromtimestamp(log.stat().st_mtime)
        linhas = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return saida
    inicios = [i for i, linha in enumerate(linhas) if linha.startswith("Curador · ")]
    cauda = linhas[inicios[-1]:] if inicios else linhas[-40:]   # só a última rodada
    hora_hoje = datetime.combine(agora.date(), HORA_CURADOR)
    if agora >= hora_hoje + FOLGA_CURADOR and rodou < hora_hoje - timedelta(minutes=5):
        saida.append(("erro", "Curador não rodou hoje",
                      f"última rodada {rodou:%d/%m %Hh%M}. Confira o Agendador de Tarefas do Windows."))
    elif any("Traceback" in linha for linha in cauda):
        saida.append(("erro", "Curador quebrou na última rodada",
                      f"{rodou:%d/%m %Hh%M} · veja o fim do state/curador.log"))
    return saida


def alertas_token(eventos: pd.DataFrame, agora: pd.Timestamp,
                  secrets: Path | None = None) -> list[tuple[str, str, str]]:
    secrets = secrets or SECRETS
    saida = []
    for nome, arquivo in TOKENS:
        dados = ler_json(secrets / arquivo)
        if not dados:
            saida.append(("erro", f"Login do {nome} ausente",
                          f"secrets/{arquivo} não existe: precisa refazer o login OAuth."))
        elif not dados.get("refresh_token"):
            saida.append(("erro", f"Token do {nome} vai vencer",
                          "sem refresh_token: o acesso cai em 1h. Refaça o login OAuth."))
    if not eventos.empty:
        falhas = _falhas_sem_ok(eventos, agora - JANELA_TOKEN)
        for f in falhas.itertuples():
            if isinstance(f.mensagem, str) and RE_TOKEN.search(f.mensagem):
                saida.append(("erro", "Token vencido/recusado",
                              f"{f.etapa} ({f.agente}) em {f.ts:%d/%m %Hh%M}: refaça o login OAuth."))
    return saida


def alerta_cota(agora_utc: datetime | None = None, cota_path: Path | None = None,
                upload_path: Path | None = None, pct_alerta: float = 80) -> list[tuple[str, str, str]]:
    cota = ler_json(cota_path or STATE / "cota_youtube.json")
    limite = ler_json(upload_path or UPLOAD_JSON).get("cota_limite_dia") or 10_000
    hoje_pacifico = (agora_utc or datetime.now(ZoneInfo("UTC"))).astimezone(FUSO_COTA).date()
    if cota.get("dia_pacifico") != hoje_pacifico.isoformat():
        return []                                    # cota de outro dia já zerou
    usadas = cota.get("usadas") or 0
    pct = 100 * usadas / limite
    if pct < pct_alerta:
        return []
    return [("erro" if pct >= 100 else "aviso", "Cota do YouTube perto do limite",
             f"{usadas:,} de {limite:,} unidades hoje ({pct:.0f}%). Zera à meia-noite do Pacífico."
             .replace(",", "."))]


def alertas_operacao(est: dict | None, amanha: pd.DataFrame) -> list[tuple[str, str, str]]:
    saida = []
    if est is not None and est["dias"] < est["minimo"]:
        ate = est.get("coberto_ate")
        saida.append(("aviso", "Estoque baixo",
                      (f"canal coberto só até {ate:%d/%m}" if ate else "nada agendado nem pronto")
                      + f" ({est['dias']:.1f} dia(s), mínimo {est['minimo']}): "
                      "o Curador processa um vídeo novo na próxima rodada (17h)."))
    if amanha.empty:
        saida.append(("aviso", "Nada agendado pra amanhã",
                      "nenhum vídeo com data de amanhã no YouTube."))
    return saida


def faixa_alertas(alertas: list[tuple[str, str, str]]) -> None:
    if not alertas:
        return
    itens = "".join(f"<div class='al {nivel}'><b>{html.escape(titulo)}</b> · {html.escape(detalhe)}</div>"
                    for nivel, titulo, detalhe in alertas)
    st.markdown(f"{CSS}<div class='alertas'>{itens}</div>", unsafe_allow_html=True)


# ── custo do mês x orçamento ──────────────────────────────────────────────

def custo_mes(eventos_mes: pd.DataFrame, orcamento: float, agora: pd.Timestamp) -> dict:
    """eventos_mes: colunas agente, custo_usd (eventos do mês corrente com custo)."""
    gasto = float(eventos_mes["custo_usd"].sum()) if not eventos_mes.empty else 0.0
    dias_mes = (agora.replace(day=1) + pd.offsets.MonthBegin(1) - agora.replace(day=1)).days
    projecao = gasto / agora.day * dias_mes
    por_agente = (eventos_mes.groupby("agente")["custo_usd"].sum().sort_values(ascending=False)
                  if not eventos_mes.empty else pd.Series(dtype=float))
    return {"gasto": gasto, "orcamento": orcamento, "pct": 100 * gasto / orcamento if orcamento else 0,
            "projecao": projecao, "por_agente": por_agente[por_agente > 0]}


# ── placar do canal ────────────────────────────────────────────────────────

def placar(path: Path | None = None) -> dict:
    """{chave: (valor|None, meta)} + atualizado. Sem state/placar.json, valores None."""
    dados = ler_json(path or STATE / "placar.json")
    saida = {k: (dados.get(k) if isinstance(dados.get(k), (int, float)) else None, meta)
             for k, meta in YPP.items()}
    saida["atualizado"] = dados.get("atualizado")
    return saida


# ── render ─────────────────────────────────────────────────────────────────

CSS = """<style>
.alertas {margin-bottom:1rem;}
.al {border-radius:8px; padding:.55rem 1rem; margin-bottom:.35rem; font-size:.9rem;}
.al b {font-family:'Anton','Impact',sans-serif; font-weight:400; letter-spacing:.03em;}
.al.erro {background:#3a1414; color:#ffb0b0; border-left:4px solid #ff5c5c;}
.al.aviso {background:#3a3210; color:#F5C518; border-left:4px solid #F5C518;}
.hj-item {display:flex; gap:.8rem; align-items:baseline; padding:.35rem 0;
          border-bottom:1px solid #262626; font-size:.9rem;}
.hj-hora {font-family:'Anton','Impact',sans-serif; color:#F5C518; min-width:3.2rem;}
.hj-dia {color:#9a9a9a; font-size:.75rem; text-transform:uppercase; letter-spacing:.06em;
         margin-top:.6rem;}
.hj-dec {border-left:3px solid #F5C518; padding:.3rem .7rem; margin-bottom:.45rem; font-size:.88rem;}
.hj-dec small {color:#9a9a9a; display:block;}
.hj-vazio {color:#9a9a9a; font-size:.85rem; padding:.3rem 0;}
.placar-n {font-family:'Anton','Impact',sans-serif; font-size:1.6rem; line-height:1.1;}
.placar-n span {color:#9a9a9a; font-size:.95rem;}
.placar-l {color:#9a9a9a; font-size:.78rem;}
</style>"""


def _fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".")


def _lista_no_ar(rotulo: str, df: pd.DataFrame) -> str:
    linhas = [f"<div class='hj-dia'>{rotulo}</div>"]
    if df.empty:
        linhas.append("<div class='hj-vazio'>nada agendado</div>")
    for b in df.itertuples():
        titulo = _nome(b)
        linhas.append(f"<div class='hj-item'><span class='hj-hora'>{b.quando:%Hh%M}</span>"
                      f"<span>{html.escape(str(titulo))}</span></div>")
    return "".join(linhas)


def _placar(dados: dict) -> None:
    st.markdown("<h3>Placar do canal</h3>", unsafe_allow_html=True)
    rotulos = {"inscritos": "inscritos", "horas_12m": "horas assistidas (12 meses)",
               "views_shorts_90d": "views de Shorts (90 dias)"}
    for chave, rotulo in rotulos.items():
        valor, meta = dados[chave]
        txt = _fmt(valor) if valor is not None else "—"
        st.markdown(f"<div class='placar-n'>{txt} <span>/ {_fmt(meta)}</span></div>"
                    f"<div class='placar-l'>{rotulo}</div>", unsafe_allow_html=True)
        st.progress(min(valor / meta, 1.0) if valor is not None else 0.0)
    if dados["atualizado"]:
        st.caption(f"Atualizado em {str(dados['atualizado'])[:16].replace('T', ' ')} pelo Analista. "
                   "YPP: 1.000 inscritos + 4.000 h (ou 10 mi de views em Shorts).")
    else:
        st.caption("Aguardando o Analista (vai preencher `state/placar.json`). "
                   "YPP: 1.000 inscritos + 4.000 h (ou 10 mi de views em Shorts).")


def _custo(c: dict) -> None:
    st.markdown("<h3>Custo do mês x orçamento</h3>", unsafe_allow_html=True)
    st.markdown(f"<div class='placar-n'>US$ {c['gasto']:.2f} <span>/ US$ {c['orcamento']:.2f}</span></div>"
                f"<div class='placar-l'>{c['pct']:.0f}% do orçamento · projeção pro fim do mês "
                f"US$ {c['projecao']:.2f}</div>", unsafe_allow_html=True)
    st.progress(min(c["pct"] / 100, 1.0))
    if c["projecao"] > c["orcamento"]:
        st.warning(f"No ritmo atual o mês fecha em US$ {c['projecao']:.2f}, acima do orçamento.")
    if c["por_agente"].empty:
        st.caption("Nenhum gasto de API este mês.")
    else:
        st.bar_chart(c["por_agente"].rename("US$"), color="#F5C518", horizontal=True,
                     height=40 + 36 * len(c["por_agente"]))


def aba_hoje(blocos: pd.DataFrame, tarefas: pd.DataFrame, est: dict | None, custo: dict,
             agora: pd.Timestamp | None = None) -> None:
    agora = agora or pd.Timestamp.now()
    hoje, amanha = agora.date(), agora.date() + timedelta(days=1)
    df_hoje, df_amanha = no_ar(blocos, hoje), no_ar(blocos, amanha)
    pend = decisoes(tarefas, blocos)
    auditoria = ler_json(UPLOAD_JSON).get("auditoria_aprovada") is True
    st.markdown(CSS, unsafe_allow_html=True)

    m = st.columns(4)
    m[0].metric("Vai ao ar hoje", len(df_hoje))
    m[1].metric("Amanhã", len(df_amanha))
    if est is None:
        m[2].metric("Estoque", "—")
        m[2].caption("não consegui calcular (veja o terminal do painel)")
    else:
        baixo = est["dias"] < est["minimo"]
        ate = est.get("coberto_ate")
        dias = f"{est['dias']:.1f} dia(s)".replace(".", ",")
        m[2].metric("Canal coberto até", f"{ate:%d/%m}" if ate else "—",
                    delta=f"{dias} · abaixo do mínimo ({est['minimo']})" if baixo
                    else f"{dias} · mínimo {est['minimo']}",
                    delta_color="inverse" if baixo else "off", delta_arrow="off",
                    help="O mesmo cálculo do Curador: dias até o último longo agendado no canal "
                         "+ longos prontos pra publicar (1 por dia). Abaixo do mínimo o Curador "
                         "processa um vídeo novo.")
    m[3].metric("Auditoria YouTube", "aprovada" if auditoria else "pendente",
                delta="upload e Shorts liberados" if auditoria else "upload e Shorts travados",
                delta_color="normal" if auditoria else "off", delta_arrow="off")

    n_fila = est.get("agendados_futuros", 0) if est else 0
    ultimo = est.get("ultimo_agendado") if est else None
    fila = (f"<div class='hj-vazio'>Fila no YouTube: {n_fila} agendado(s), até "
            f"{DIAS_SEMANA[ultimo.weekday()]} {ultimo:%d/%m}</div>" if n_fila and ultimo
            else "<div class='hj-vazio'>Fila no YouTube vazia</div>" if est
            else "<div class='hj-vazio'>Fila no YouTube indisponível</div>")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("<h3>No ar</h3>" + fila
                    + _lista_no_ar(f"Hoje · {hoje:%d/%m}", df_hoje)
                    + _lista_no_ar(f"Amanhã · {amanha:%d/%m}", df_amanha), unsafe_allow_html=True)
    with c2:
        st.markdown(f"<h3>Decisões pendentes · {len(pend)}</h3>", unsafe_allow_html=True)
        if not pend:
            st.markdown("<div class='hj-vazio'>nada esperando você</div>", unsafe_allow_html=True)
        st.markdown("".join(f"<div class='hj-dec'>{html.escape(str(p))}"
                            f"<small>{html.escape(o)}</small></div>" for o, p in pend),
                    unsafe_allow_html=True)

    c3, c4 = st.columns([3, 2])
    with c3:
        _custo(custo)
    with c4:
        _placar(placar())
