"""Aba "Hoje" do painel (tela inicial do PO) + faixa de alertas.

Responde em 10 segundos: o que vai ao ar hoje/amanhã, quantos dias de estoque tem, o que
espera decisão, se a auditoria do YouTube saiu, quanto do orçamento do mês já foi e o
placar do canal rumo ao YPP. Só LÊ: banco, config/ e state/. A única ação é o botão
"Processar" das Sugestões do Curador: dispara o 13 (--processar=ID) num processo à parte,
e é ele quem grava no banco.

Alertas (faixa acima das abas, aparece em qualquer aba):
  - Curador rodando agora (desde HH:MM — etapa X) ou parado no meio (processo sumiu)
  - falha do Curador (evento de falha, Traceback no state/curador.log ou não rodou às 17h); some
    quando a mesma etapa, ou o script citado na mensagem ("11_revisor.py falhou"), dá ok depois
    na mesma live, mesmo rodado fora do Curador
  - erro de download (01_baixar falhou dentro do Curador)
  - token do YouTube/Analytics ausente, sem refresh_token ou recusado (invalid_grant)
  - cota diária do YouTube perto do limite (state/cota_youtube.json, gravado pelo 09)
  - estoque abaixo de dias_minimos (modo sugerir: "escolha uma sugestão") e nada agendado pra amanhã
  - Curador processou sozinho pela rede de segurança (evento curador_rede, últimas 24h)
  - live travada por custo: acima de trava_live_usd (US$ 2) os scripts pagos param
    (scripts/_custo.py) até o Gu liberar

Histórico de alertas (expander abaixo da faixa): falhas dos últimos 30 dias, resolvidas ou não,
e lives que passaram de alerta_live_usd (US$ 1). Informativo: não pede ação, por isso não fica
na faixa.

Placar do canal: o Analista grava state/placar.json; até lá a seção fica com o espaço vazio.
  {"atualizado": "2026-11-01T10:00:00-03:00", "inscritos": 312,
   "horas_12m": 845.5, "views_shorts_90d": 120000}
"""
import html
import importlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import visual

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
JANELA_CUSTO_LIVE = timedelta(days=7)        # live sem gasto há mais que isso sai do alerta
JANELA_REDE = timedelta(hours=24)            # aviso "processei X porque o canal ficaria sem vídeo"
JANELA_HISTORICO = timedelta(days=30)
RE_SCRIPT = re.compile(r"\b(\d{2}[a-z]?_[a-z]+)")   # "11_revisor.py falhou" → 11_revisor
LOG_PEDIDOS = STATE / "curador_pedidos.log"  # saída do botão Processar (o curador.log é das 17h)
TOKENS = [("YouTube (publicar)", "youtube_token.json"), ("YouTube Analytics", "analytics_token.json")]
RE_TOKEN = re.compile(r"invalid_grant|RefreshError|token.*(expir|venc|revog|inv[aá]lid)|"
                      r"unauthorized", re.I)
YPP = {"inscritos": 1000, "horas_12m": 4000, "views_shorts_90d": 10_000_000}
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MODULOS_SCRIPTS = ["_cobertura", "_publicacao", "13_curador"]
_MTIMES: dict[str, float] = {}
PADRAO = {"orcamento_mensal_usd": 10.0, "cota_alerta_pct": 80,
          "alerta_live_usd": 1.0, "trava_live_usd": 2.0}


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
    e o painel (módulo antigo na memória) passam a contar diferente. Ordem = dependência.
    Antes, os helpers de scripts/ já carregados que mudaram (ex.: _eventos ganhou função
    nova e o 13_curador recarregado importa ela). Na 1ª chamada recarrega todos uma vez, de
    propósito: o painel pode já estar no ar com módulo velho. Sem ordem de dependência entre
    helpers: quem dá ImportError (importa nome novo de helper ainda velho) tenta de novo
    na passada seguinte; sem progresso numa passada, o erro sobe."""
    pasta = (ROOT / "scripts").resolve()
    pendentes = {}
    for nome in sorted(n for n in list(sys.modules) if n not in MODULOS_SCRIPTS):
        arquivo = getattr(sys.modules[nome], "__file__", None)
        if not arquivo or Path(arquivo).resolve().parent != pasta or not Path(arquivo).exists():
            continue
        mtime = Path(arquivo).stat().st_mtime
        if _MTIMES.get(nome) != mtime:
            pendentes[nome] = mtime
    mudou = bool(pendentes)
    while pendentes:
        antes, erro = len(pendentes), None
        for nome in list(pendentes):
            try:
                importlib.reload(sys.modules[nome])
            except ImportError as e:
                erro = e
                continue
            _MTIMES[nome] = pendentes.pop(nome)
        if len(pendentes) == antes:
            raise erro
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
        return {**est, "minimo": cfg["estoque"]["dias_minimos"], "modo": curador.curador_modo(cfg)}
    except Exception as e:  # noqa: BLE001 — painel nunca cai por causa do estoque
        print(f"[aviso] não calculei o estoque ({e})", file=sys.stderr)
        return None


def _nome(b) -> str:
    """titulo_youtube (o que está no canal) > titulo > tema > 'bloco N'
    (NaN do pandas é truthy: checa o tipo)."""
    for campo in ("titulo_youtube", "titulo", "tema"):
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

def falhas_com_resolucao(eventos: pd.DataFrame, desde: pd.Timestamp) -> pd.DataFrame:
    """Falhas desde `desde` + coluna `resolvida` (ts do 1º ok posterior na mesma live, na mesma
    etapa ou no script citado na mensagem; NaT = em aberto). Ex.: o Curador grava
    curador_pipeline "11_revisor.py falhou"; o 11 rodado à mão depois resolve."""
    if eventos.empty:
        return eventos.assign(resolvida=pd.Series(dtype="datetime64[ns]"))
    falhas = eventos[(eventos["status"] == "falha") & (eventos["ts"] >= desde)].sort_values("ts")
    oks = eventos[eventos["status"] == "ok"]
    stem_ok = oks["stem"].fillna("")
    resolvida = []
    for f in falhas.itertuples():
        msg = f.mensagem if isinstance(f.mensagem, str) else ""
        stem = f.stem if isinstance(f.stem, str) else ""
        ok = oks[(oks["ts"] > f.ts) & (stem_ok == stem)
                 & oks["etapa"].isin({f.etapa, *RE_SCRIPT.findall(msg)})]
        resolvida.append(ok["ts"].min() if not ok.empty else pd.NaT)
    return falhas.assign(resolvida=pd.to_datetime(pd.Series(resolvida, index=falhas.index,
                                                            dtype="object")))


def _falhas_sem_ok(eventos: pd.DataFrame, desde: pd.Timestamp, agente: str | None = None) -> pd.DataFrame:
    """Falhas recentes ainda em aberto (a última de cada etapa+stem)."""
    falhas = falhas_com_resolucao(eventos, desde)
    if agente is not None and not falhas.empty:
        falhas = falhas[falhas["agente"] == agente]
    if falhas.empty:
        return falhas
    abertas = falhas[falhas["resolvida"].isna()]
    return abertas.groupby([abertas["etapa"], abertas["stem"].fillna("")]).tail(1)


def _alerta_pulado(eventos: pd.DataFrame, agora: pd.Timestamp) -> list[tuple[str, str, str]]:
    """Curador pulou o processamento (outro já rodava) e nenhum processamento dele veio depois."""
    if eventos.empty:
        return []
    ev = eventos[(eventos["agente"] == "curador") & (eventos["ts"] >= agora - JANELA_FALHA)]
    pulos = ev[(ev["etapa"] == "curador_pulado") & (ev["status"] == "aviso")]
    if pulos.empty:
        return []
    ultimo = pulos.sort_values("ts").iloc[-1]
    if (ev[ev["etapa"] == "curador_pipeline"]["ts"] > ultimo["ts"]).any():
        return []
    msg = ultimo["mensagem"] if isinstance(ultimo["mensagem"], str) else ""
    return [("aviso", "Curador pulou o processamento", f"{msg} ({ultimo['ts']:%d/%m %Hh%M})")]


def _alerta_rede(eventos: pd.DataFrame, agora: pd.Timestamp) -> list[tuple[str, str, str]]:
    """Modo sugerir: o Curador processou sozinho porque o canal ficaria sem longo amanhã."""
    if eventos.empty:
        return []
    ev = eventos[(eventos["agente"] == "curador") & (eventos["etapa"] == "curador_rede")
                 & (eventos["ts"] >= agora - JANELA_REDE)]
    if ev.empty:
        return []
    ultimo = ev.sort_values("ts").iloc[-1]
    msg = ultimo["mensagem"] if isinstance(ultimo["mensagem"], str) else ""
    return [("aviso", "Curador processou sozinho", f"{msg} ({ultimo['ts']:%d/%m %Hh%M})")]


def alertas_curador(eventos: pd.DataFrame, agora: pd.Timestamp,
                    log: Path | None = None) -> list[tuple[str, str, str]]:
    log = log or STATE / "curador.log"
    saida = []
    falhas = _falhas_sem_ok(eventos, agora - JANELA_FALHA, agente="curador")
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
    saida += _alerta_pulado(eventos, agora)
    saida += _alerta_rede(eventos, agora)
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


def _pid_vivo(pid) -> bool:
    """O processo do Curador ainda existe? Sem como saber, assume que sim (não alarma à toa)."""
    if not isinstance(pid, int) or pid <= 0:
        return True
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p      # handle 64 bits não trunca
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5        # acesso negado = existe
        try:
            codigo = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(codigo))) and codigo.value == 259
        finally:                                       # 259 = STILL_ACTIVE
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def curador_rodando(eventos: pd.DataFrame, agora: pd.Timestamp, path: Path | None = None,
                    vivo=_pid_vivo) -> list[tuple[str, str, str]]:
    """"Curador rodando desde 17:00 — etapa X" (state/curador_progresso.json, gravado pelo 13).
    Marcado como rodando mas o processo sumiu (PC desligou no meio) = erro."""
    prog = ler_json(path or STATE / "curador_progresso.json")
    desde = _local(prog.get("desde"))
    if not prog.get("rodando") or desde is None:
        return []
    etapa, stem = prog.get("etapa") or "?", prog.get("stem")
    if not vivo(prog.get("pid")):
        return [("erro", "Curador parou no meio",
                 f"etapa \"{etapa}\", rodando desde {desde:%d/%m %Hh%M}, e o processo sumiu "
                 f"(PC desligou?). Veja o fim do state/curador.log; a próxima rodada retoma.")]
    if etapa == "pipeline" and stem and not eventos.empty:   # o pipeline grava o step dele
        ev = eventos[(eventos["agente"] == "pipeline") & (eventos["stem"] == stem)
                     & (eventos["status"] == "inicio") & (eventos["ts"] >= pd.Timestamp(desde))]
        if not ev.empty:
            etapa = f"pipeline · {ev.sort_values('ts')['etapa'].iloc[-1]}"
    quando = f"{desde:%H:%M}" if desde.date() == agora.date() else f"{desde:%d/%m %H:%M}"
    atualizado = _local(prog.get("atualizado"))
    detalhe = " · ".join(x for x in (stem, atualizado and f"atualizado {atualizado:%H:%M}") if x)
    return [("info", f"Curador rodando desde {quando} — etapa {etapa}", detalhe or "sem janela")]


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
                      + ("o Curador processa um vídeo novo na próxima rodada (17h)."
                         if est.get("modo") == "automatico" else
                         "estoque baixo, escolha uma sugestão (aba Hoje → Sugestões do Curador).")))
    if amanha.empty:
        saida.append(("aviso", "Nada agendado pra amanhã",
                      "nenhum vídeo com data de amanhã no YouTube."))
    return saida


def _tetos(custos: pd.DataFrame, trava: float, liberadas_path: Path | None) -> pd.Series:
    """Teto de cada live: a trava padrão ou o que o Gu liberou (state/orcamento_lives.json)."""
    liberadas = ler_json(liberadas_path or STATE / "orcamento_lives.json")
    return custos["stem"].map(lambda s: max(trava, float(liberadas.get(s) or 0)))


def alertas_custo_live(custos: pd.DataFrame, agora: pd.Timestamp, alerta: float, trava: float,
                       liberadas_path: Path | None = None) -> list[tuple[str, str, str]]:
    """custos: colunas stem, custo_usd (soma da live), ultimo (ts do último gasto).
    Só >= teto vai pra faixa (erro: os scripts pagos dessa live estão parados). Live cara
    (>= alerta, abaixo do teto) é informativa: fica no historico_custo_live."""
    if custos.empty:
        return []
    recentes = custos[pd.to_datetime(custos["ultimo"]) >= agora - JANELA_CUSTO_LIVE]
    recentes = recentes.assign(teto=_tetos(recentes, trava, liberadas_path))
    return [("erro", f"Live travada por custo: {c.stem}",
             f"já gastou US$ {c.custo_usd:.2f} de API (teto US$ {c.teto:.2f}); as etapas pagas "
             f"param até você liberar: uv run py scripts/_custo.py liberar {c.stem}")
            for c in recentes.sort_values("custo_usd", ascending=False).itertuples()
            if c.custo_usd >= c.teto]


def historico_custo_live(custos: pd.DataFrame, agora: pd.Timestamp, alerta: float, trava: float,
                         liberadas_path: Path | None = None) -> pd.DataFrame:
    """Lives que passaram de `alerta` com gasto nos últimos 30 dias, a mais recente primeiro."""
    colunas = ["stem", "custo_usd", "teto", "ultimo", "situacao"]
    if custos.empty:
        return pd.DataFrame(columns=colunas)
    c = custos.assign(ultimo=pd.to_datetime(custos["ultimo"]))
    c = c[(c["ultimo"] >= agora - JANELA_HISTORICO) & (c["custo_usd"] >= alerta)]
    c = c.assign(teto=_tetos(c, trava, liberadas_path))
    c = c.assign(situacao=[("travada" if v >= t else f"liberada até US$ {t:.2f}" if t > trava
                            else "cara") for v, t in zip(c["custo_usd"], c["teto"])])
    return c.sort_values("ultimo", ascending=False)[colunas]


def faixa_alertas(alertas: list[tuple[str, str, str]]) -> None:
    if not alertas:
        return
    itens = "".join(f"<div class='al {nivel}'><b>{html.escape(titulo)}</b> · {html.escape(detalhe)}</div>"
                    for nivel, titulo, detalhe in alertas)
    st.markdown(f"{CSS}<div class='alertas'>{itens}</div>", unsafe_allow_html=True)


def historico_alertas(falhas: pd.DataFrame, custos: pd.DataFrame) -> None:
    """Expander abaixo da faixa: falhas (resolvidas ou não) e lives caras dos últimos 30 dias."""
    if falhas.empty and custos.empty:
        return
    abertas = int(falhas["resolvida"].isna().sum()) if not falhas.empty else 0
    partes = [f"{len(falhas)} falha(s)" + (f", {abertas} em aberto" if abertas else ""),
              f"{len(custos)} live(s) cara(s)"]
    with st.expander(f"Histórico de alertas · {' · '.join(partes)} (30 dias)"):
        if not falhas.empty:
            st.markdown("**Falhas**")
            st.dataframe(
                falhas.sort_values("ts", ascending=False)
                .assign(situacao=falhas["resolvida"].map(lambda r: "em aberto" if pd.isna(r)
                                                         else f"resolvida {r:%d/%m %Hh%M}"))
                [["ts", "agente", "etapa", "stem", "mensagem", "situacao"]],
                width="stretch", hide_index=True,
                column_config={"ts": st.column_config.DatetimeColumn("quando", format="DD/MM HH:mm"),
                               "stem": "live", "situacao": "situação"})
        if not custos.empty:
            st.markdown("**Lives caras**")
            st.dataframe(custos, width="stretch", hide_index=True,
                         column_config={"stem": "live",
                                        "custo_usd": st.column_config.NumberColumn("gasto", format="$%.2f"),
                                        "teto": st.column_config.NumberColumn("teto", format="$%.2f"),
                                        "ultimo": st.column_config.DatetimeColumn(
                                            "último gasto", format="DD/MM HH:mm"),
                                        "situacao": "situação"})


# ── sugestões do Curador (modo sugerir) ──────────────────────────────────

def disparar_processamento(video_id: str) -> str | None:
    """Botão Processar: roda o 13 --processar=ID pelo curador_oculto (sem janela, saída no
    state/curador_pedidos.log, falha vira alerta), solto do painel: fechar o painel não
    mata o processamento. None = disparou; senão, o erro. Trava de um processamento por
    vez e orçamento por live ficam com o 13."""
    pasta = Path(sys.executable).parent
    exe = pasta / "pythonw.exe" if (pasta / "pythonw.exe").exists() else Path(sys.executable)
    cmd = [str(exe), str(ROOT / "scripts" / "curador_oculto.py"), f"--processar={video_id}"]
    env = {**os.environ, "MISSAO_CURADOR_LOG": str(LOG_PEDIDOS)}
    kw = dict(cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL)
    if sys.platform != "win32":
        kw["start_new_session"] = True
        tentativas = [0]
    else:   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (+ sair do job do uv/terminal, se der)
        tentativas = [0x00000008 | 0x00000200 | 0x01000000, 0x00000008 | 0x00000200]
    erro = None
    for flags in tentativas:
        try:
            subprocess.Popen(cmd, creationflags=flags, **kw)
            return None
        except OSError as e:   # job sem permissão de breakaway: tenta sem
            erro = e
    return str(erro)


ROTULO_SUGESTAO = {"sugerida": "", "pedida": "na fila", "processando": "processando",
                   "falhou": "falhou"}


def secao_sugestoes(sug: pd.DataFrame, curador_ocupado: bool) -> list[str]:
    """Sugestões em aberto, maior prioridade primeiro, com o botão Processar. Devolve os
    video_id clicados nesta passada (quem chama dispara)."""
    clicados = []
    with st.container(border=True):
        st.markdown(f"<h3>Sugestões do Curador · {len(sug)}</h3>", unsafe_allow_html=True)
        if sug.empty:
            st.caption("Nenhuma sugestão em aberto. O Curador lê os canais todo dia às 17h.")
            return clicados
        st.caption("Você escolhe o que vira corte: Processar baixa e roda o pipeline (~US$ 0,65), "
                   "um vídeo por vez.")
        for s in sug.itertuples():
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            dur = f"{s.duracao_min:.0f} min" if pd.notna(s.duracao_min) else "duração ?"
            data = f" · {s.data[8:10]}/{s.data[5:7]}" if isinstance(s.data, str) and len(s.data) >= 10 else ""
            rotulo = ROTULO_SUGESTAO.get(s.status, s.status)
            extra = (f"<span class='pill {html.escape(s.status)}'>{html.escape(rotulo)}</span>"
                     if rotulo else "")
            erro = (f"<small>{html.escape(s.mensagem)}</small>"
                    if s.status == "falhou" and isinstance(s.mensagem, str) else "")
            with c1:
                st.markdown(
                    f"<div class='hj-dec'><b>[{int(s.prioridade or 0)}]</b> "
                    f"<a href='{html.escape(str(s.url))}' target='_blank'>{html.escape(str(s.titulo))}</a> "
                    f"{extra}<small>{html.escape(str(s.canal))} · {dur}{data} — "
                    f"{html.escape(str(s.motivo or ''))}</small>{erro}</div>", unsafe_allow_html=True)
            with c2:
                if s.status in ("sugerida", "falhou"):
                    rotulo_botao = "Processar" if s.status == "sugerida" else "Tentar de novo"
                    if st.button(rotulo_botao, key=f"sug_{s.video_id}", width="stretch"):
                        clicados.append(s.video_id)
                elif s.status == "pedida" and not curador_ocupado:
                    # pedido parado (o processo não pegou a trava e ninguém está rodando)
                    if st.button("Disparar", key=f"sug_{s.video_id}", width="stretch",
                                 help="O pedido não andou: dispara o processamento de novo."):
                        clicados.append(s.video_id)
    return clicados


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


def custo_cache(eventos: pd.DataFrame) -> dict:
    """Prompt cache nos eventos llm: tokens_in já é o input total (sem cache + escrita +
    leitura). taxa = parte do input lida do cache (0-1). Banco anterior às colunas → zeros."""
    llm = eventos[eventos["tokens_in"] > 0] if not eventos.empty else eventos
    soma = lambda c: int(llm[c].sum()) if c in llm and not llm.empty else 0   # noqa: E731
    total, leitura, escrita = soma("tokens_in"), soma("cache_leitura"), soma("cache_escrita")
    return {"tokens_in": total, "leitura": leitura, "escrita": escrita,
            "taxa": leitura / total if total else 0.0}


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
.al {border-radius:10px; padding:.6rem 1rem; margin-bottom:.4rem; font-size:.9rem;}
.al b {font-family:'Anton','Impact',sans-serif; font-weight:400; letter-spacing:.03em;}
.al.erro {background:var(--erro-bg); color:var(--erro-tx); border-left:4px solid var(--erro-borda);}
.al.aviso {background:var(--acento-bg); color:var(--acento-tx); border-left:4px solid var(--acento);}
.al.info {background:var(--card); color:var(--tx); border-left:4px solid var(--mudo);}
.hj-sec {background:var(--card); border:1px solid var(--borda); border-radius:14px;
         padding:.4rem 1.2rem 1rem; margin-bottom:1rem;}
.hj-item {display:flex; gap:.8rem; align-items:baseline; padding:.4rem 0;
          border-bottom:1px solid var(--borda); font-size:.92rem;}
.hj-item:last-child {border-bottom:none;}
.hj-hora {font-family:'Anton','Impact',sans-serif; color:var(--acento-tx); min-width:3.2rem;}
.hj-dia {color:var(--tx2); font-size:.75rem; font-weight:600; text-transform:uppercase;
         letter-spacing:.06em; margin-top:.7rem;}
.hj-dec {border-left:3px solid var(--acento); padding:.3rem .7rem; margin:.45rem 0; font-size:.9rem;}
.hj-dec small {color:var(--tx2); display:block;}
.hj-vazio {color:var(--mudo); font-size:.88rem; padding:.3rem 0;}
.placar-l {display:flex; justify-content:space-between; gap:.5rem; color:var(--tx2);
           font-size:.85rem; margin-top:.8rem;}
.placar-l b {color:var(--tx); font-size:1.05rem; white-space:nowrap;}
.placar-l b small {color:var(--mudo); font-weight:400; font-size:.8rem;}
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


def _horarios(df: pd.DataFrame) -> str:
    return " · ".join(f"{q:%Hh%M}" for q in df["quando"]) if not df.empty else ""


def _placar(dados: dict) -> str:
    rotulos = {"inscritos": "inscritos", "horas_12m": "horas assistidas (12 meses)",
               "views_shorts_90d": "views de Shorts (90 dias)"}
    linhas = ["<div class='hj-sec'><h3>Placar do canal</h3>"]
    for chave, rotulo in rotulos.items():
        valor, meta = dados[chave]
        txt = _fmt(valor) if valor is not None else "—"
        pct = min(valor / meta, 1.0) if valor is not None else 0.0
        linhas.append(f"<div class='placar-l'><span>{rotulo}</span>"
                      f"<b>{txt} <small>/ {_fmt(meta)}</small></b></div>"
                      f"<div class='medidor'><span style='width:{100 * pct:.1f}%'></span></div>")
    quem = (f"Atualizado em {html.escape(str(dados['atualizado'])[:16].replace('T', ' '))} pelo Analista."
            if dados["atualizado"] else "Aguardando o Analista (vai preencher state/placar.json).")
    linhas.append(f"<div class='hj-vazio'>{quem} YPP: 1.000 inscritos + 4.000 h "
                  "(ou 10 mi de views em Shorts).</div></div>")
    return "".join(linhas)


def _custo(c: dict) -> None:
    st.markdown("<h3>Custo do mês por agente</h3>", unsafe_allow_html=True)
    if c["projecao"] > c["orcamento"]:
        st.warning(f"No ritmo atual o mês fecha em US$ {c['projecao']:.2f}, acima do orçamento.")
    if c["por_agente"].empty:
        st.caption("Nenhum gasto de API este mês.")
    else:
        visual.barras(c["por_agente"], nome="custo")


def aba_hoje(blocos: pd.DataFrame, tarefas: pd.DataFrame, est: dict | None, custo: dict,
             agora: pd.Timestamp | None = None, sugestoes: pd.DataFrame | None = None) -> list[str]:
    """Desenha a aba e devolve os video_id que o Gu mandou processar nesta passada."""
    agora = agora or pd.Timestamp.now()
    hoje, amanha = agora.date(), agora.date() + timedelta(days=1)
    df_hoje, df_amanha = no_ar(blocos, hoje), no_ar(blocos, amanha)
    pend = decisoes(tarefas, blocos)
    auditoria = ler_json(UPLOAD_JSON).get("auditoria_aprovada") is True
    st.markdown(CSS, unsafe_allow_html=True)
    cartao = visual.cartao

    # O que importa: grande e no topo.
    if est is None:
        c_estoque = cartao("Canal coberto até", "—", "não consegui calcular (veja o terminal do painel)",
                           tom="erro")
    else:
        baixo = est["dias"] < est["minimo"]
        ate = est.get("coberto_ate")
        dias = f"{est['dias']:.1f} dia(s)".replace(".", ",")
        c_estoque = cartao(
            "Canal coberto até", f"{ate:%d/%m}" if ate else "—",
            f"{dias} · abaixo do mínimo ({est['minimo']})" if baixo else f"{dias} · mínimo {est['minimo']}",
            tom="alerta" if baixo else "",
            ajuda="O mesmo cálculo do Curador: dias até o último longo agendado no canal + longos "
                  "prontos pra publicar (1 por dia). Abaixo do mínimo "
                  + ("o Curador processa um vídeo novo." if est.get("modo") == "automatico" else
                     "escolha uma sugestão do Curador (ele só processa sozinho se o canal ficaria "
                     "sem vídeo amanhã)."))
    n_dev = sum(o.startswith("Tarefa") for o, _ in pend)
    origem = [f"{n_dev} do time de dev" if n_dev else "",
              f"{len(pend) - n_dev} em quarentena" if len(pend) > n_dev else ""]
    visual.grade([
        c_estoque,
        cartao("Vai ao ar hoje", len(df_hoje), _horarios(df_hoje) or "nada hoje"),
        cartao("Decisões pendentes", len(pend), " · ".join(o for o in origem if o) or "nada esperando você",
               tom="alerta" if pend else ""),
    ], grande=True)

    # O resto: menor.
    n_fila = est.get("agendados_futuros", 0) if est else 0
    ultimo = est.get("ultimo_agendado") if est else None
    prontos = int((blocos["status"] == "aprovado").sum()) if not blocos.empty else 0
    visual.grade([
        cartao("Amanhã", len(df_amanha), _horarios(df_amanha) or "nada agendado",
               tom="" if len(df_amanha) else "alerta"),
        cartao("Fila no YouTube", n_fila if est else "—",
               f"até {DIAS_SEMANA[ultimo.weekday()]} {ultimo:%d/%m}" if n_fila and ultimo
               else "vazia" if est else "indisponível"),
        cartao("Prontos p/ publicar", prontos, "aprovados, fora do YouTube"),
        cartao("Auditoria YouTube", "aprovada" if auditoria else "pendente",
               "upload e Shorts liberados" if auditoria else "upload e Shorts travados",
               tom="ok" if auditoria else ""),
        cartao("Custo do mês", f"${custo['gasto']:.2f}",
               f"{custo['pct']:.0f}% de US$ {custo['orcamento']:.0f} · proj. US$ {custo['projecao']:.2f}",
               tom="alerta" if custo["projecao"] > custo["orcamento"] else "",
               medidor=custo["pct"] / 100),
    ])

    if pend:   # zerado, o cartão grande já diz tudo
        itens = "".join(f"<div class='hj-dec'>{html.escape(str(p))}<small>{html.escape(o)}</small></div>"
                        for o, p in pend)
        st.markdown(f"<div class='hj-sec'><h3>Decisões pendentes · {len(pend)}</h3>{itens}</div>",
                    unsafe_allow_html=True)

    clicados = []
    if sugestoes is not None:
        prog = ler_json(STATE / "curador_progresso.json")
        ocupado = bool(prog.get("rodando")) and _pid_vivo(prog.get("pid"))   # morto = libera "Disparar"
        clicados = secao_sugestoes(sugestoes, ocupado)

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("<div class='hj-sec'><h3>No ar</h3>"
                    + _lista_no_ar(f"Hoje · {hoje:%d/%m}", df_hoje)
                    + _lista_no_ar(f"Amanhã · {amanha:%d/%m}", df_amanha) + "</div>",
                    unsafe_allow_html=True)
        with st.container(border=True):
            _custo(custo)
    with c2:
        st.markdown(_placar(placar()), unsafe_allow_html=True)
    return clicados
