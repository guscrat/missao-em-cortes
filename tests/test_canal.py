"""14_canal: lê o NOSSO canal e marca publicado/agendado. YouTube sempre falso (sem rede)."""
import importlib.util
import json
import types
from datetime import datetime
from pathlib import Path

import pytest

import _google
import _youtube_leitura as yl

_spec = importlib.util.spec_from_file_location(
    "canal14", Path(__file__).parent.parent / "scripts" / "14_canal.py")
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)

AGORA = datetime(2026, 10, 22, 12, tzinfo=ca.BRT)
TITULO_1 = "LULA LACRA Flávio com o pai preso"
TITULO_2 = "Debate: ninguém teve proposta de segurança"


def _v(vid, titulo, priv="public", publish_at=None, dur=420, publicado="2026-10-20T21:00:00Z"):
    return {"id": vid, "titulo": titulo, "privacidade": priv, "publish_at": publish_at,
            "publicado": publicado, "duracao_s": dur}


@pytest.fixture
def local(projeto, monkeypatch):
    """1 vídeo processado com 2 blocos e Short gerado só do bloco 1."""
    pasta = projeto.video("arthur_debate", blocos=[1, 2])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0].update(titulo_sugerido=TITULO_1, texto_thumb="ATÉ TEU PAI")
    blocos["blocos"][1].update(titulo_sugerido=TITULO_2,
                               titulo_original="A MACACADA: título velho")
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    (pasta / "shorts").mkdir(exist_ok=True)
    (pasta / "shorts" / "shorts.json").write_text(json.dumps(
        {"01": {"arquivo": "short_01_x.mp4"}}), encoding="utf-8")
    monkeypatch.setattr(ca, "ESTADO", projeto.outputs.parent / "state" / "canal.json")
    return pasta, projeto.banco, ca.titulos_locais(projeto.outputs)


def test_chave_ignora_hashtag_acento_e_pontuacao():
    assert ca.chave("LULA LACRA Flávio! #shorts #MBL") == "lula lacra flavio"


def test_casar_exato_e_por_similaridade(local):
    _, _, locais = local
    assert ca.casar(TITULO_1 + " #shorts", locais)["bloco"] == 1
    m = ca.casar("Debate: ninguém teve UMA proposta de segurança", locais)   # editado no Studio
    assert m and m["bloco"] == 2
    assert ca.casar("Outro assunto qualquer", locais) is None
    assert ca.casar("A MACACADA: título velho", locais)["bloco"] == 2      # título original


def test_casar_nao_chuta_titulo_repetido(local):
    _, _, locais = local
    dup = [dict(x, bloco=9) for x in locais if x["bloco"] == 1]
    assert ca.casar(TITULO_1, locais + dup) is None


def test_texto_da_thumb_so_casa_exato(local):
    _, _, locais = local
    assert ca.casar("ATÉ TEU PAI", locais)["bloco"] == 1
    assert ca.casar("ATÉ TEU PAI AGORA", locais) is None


def test_reconhece_short_pela_manchete_do_tema_ou_cortada(projeto):
    """Título do Short subido pelo 09 = _descricoes.manchete: vem do tema sem texto_thumb e é
    cortado acima de 60 chars. O 14 tem que reconhecer os dois (exato)."""
    from _descricoes import manchete
    pasta = projeto.video("live_x", blocos=[1, 2])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0].update(texto_thumb="", tema="Renan explica a virada do segundo turno")
    blocos["blocos"][1].update(texto_thumb="PALAVRA " * 10)                 # 80 chars
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    locais = ca.titulos_locais(projeto.outputs)
    for b in blocos["blocos"]:
        titulo_short = manchete(b)
        assert len(titulo_short) <= 60
        assert ca.casar(titulo_short, locais)["bloco"] == b["id"]


def test_reconhece_short_pelo_titulo_manchete_barra_nome(projeto):
    from _descricoes import titulo_short
    pasta = projeto.video("renan_x", blocos=[1])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0].update(texto_thumb="NICOLAS SERÁ O REI?", speakers_principais=["Renan Santos"])
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    titulo = titulo_short(blocos["blocos"][0], "renan_x")
    assert titulo == "NIKOLAS SERÁ O REI? | Renan Santos"
    assert ca.casar(titulo, ca.titulos_locais(projeto.outputs))["bloco"] == 1


def test_situacao():
    assert ca.situacao(_v("a", "x"))[0] == "publicado"
    st, quando = ca.situacao(_v("a", "x", "private", "2026-10-25T21:00:00Z"))
    assert st == "agendado" and quando.isoformat() == "2026-10-25T18:00:00-03:00"
    assert ca.situacao(_v("a", "x", "private")) is None       # rascunho
    assert ca.situacao(_v("a", "x", "unlisted")) is None


def test_aplicar_marca_longo_agendado_e_short_postado(local):
    pasta, banco, locais = local
    videos = [_v("LONGO000001", TITULO_1, "private", "2026-10-26T21:00:00Z"),
              _v("SHORT000001", TITULO_1 + " #shorts", dur=45, publicado="2026-10-22T13:00:00Z"),
              _v("PUBLIC00002", TITULO_2, publicado="2026-10-21T21:00:00Z")]
    res = ca.aplicar(videos, locais, AGORA)
    b = {r["bloco_id"]: r for r in
         banco("SELECT bloco_id, status, youtube_id, publish_at FROM blocos")}
    assert b[1]["status"] == "agendado" and b[1]["youtube_id"] == "LONGO000001"
    assert b[1]["publish_at"] == "2026-10-26T18:00:00-03:00"
    assert b[2]["status"] == "publicado"
    short = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))["01"]
    assert short["postado"] == "2026-10-22" and short["youtube_id"] == "SHORT000001"
    assert res["ultimo_longo"] == "2026-10-26T18:00:00-03:00"          # Short não conta
    estado = json.loads(ca.ESTADO.read_text(encoding="utf-8"))
    assert estado["ultimo_longo"] == res["ultimo_longo"]
    ev = banco("SELECT agente FROM eventos WHERE etapa='14_canal'")
    assert len(ev) == 3 and {e["agente"] for e in ev} == {"publicador"}


def test_aplicar_e_idempotente(local):
    _, banco, locais = local
    videos = [_v("LONGO000001", TITULO_1, "private", "2026-10-26T21:00:00Z")]
    ca.aplicar(videos, locais, AGORA)
    res = ca.aplicar(videos, locais, AGORA)
    assert res["longos"] == []
    assert len(banco("SELECT 1 FROM eventos WHERE etapa='14_canal'")) == 1


def test_publicado_depois_de_agendado_atualiza(local):
    _, banco, locais = local
    ca.aplicar([_v("L1", TITULO_1, "private", "2026-10-22T21:00:00Z")], locais, AGORA)
    ca.aplicar([_v("L1", TITULO_1, publish_at="2026-10-22T21:00:00Z")], locais, AGORA)
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "publicado"


def test_sem_match_so_recente(local):
    _, _, locais = local
    res = ca.aplicar([_v("N1", "Vídeo novo sem bloco", publicado="2026-10-21T21:00:00Z"),
                      _v("V1", "Vídeo antigo do canal", publicado="2026-06-01T21:00:00Z")],
                     locais, AGORA)
    assert [x["id"] for x in res["sem_match"]] == ["N1"]


def test_dry_run_nao_grava(local):
    pasta, banco, locais = local
    ca.aplicar([_v("L1", TITULO_1, "private", "2026-10-26T21:00:00Z"),
                _v("S1", TITULO_1, dur=40)], locais, AGORA, dry=True)
    assert banco("SELECT 1 FROM blocos WHERE youtube_id IS NOT NULL") == []
    short = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))["01"]
    assert "postado" not in short
    assert not ca.ESTADO.exists()


def test_short_sem_registro_local_e_ignorado(local):
    _, _, locais = local
    res = ca.aplicar([_v("S2", TITULO_2, dur=50)], locais, AGORA)
    assert res["shorts"] == []        # bloco 2 não tem Short gerado


# --- leitura do canal (cliente falso) -------------------------------------------------------

class _Req:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


def test_listar_videos_inclui_privados_e_publish_at():
    ns = types.SimpleNamespace
    yt = ns(
        channels=lambda: ns(list=lambda **k: _Req(
            {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})),
        playlistItems=lambda: ns(list=lambda **k: _Req(
            {"items": [{"contentDetails": {"videoId": "a"}}, {"contentDetails": {"videoId": "b"}}]})),
        videos=lambda: ns(list=lambda **k: _Req({"items": [
            {"id": "a", "snippet": {"title": "A", "publishedAt": "2026-10-20T21:00:00Z"},
             "status": {"privacyStatus": "private", "publishAt": "2026-10-25T21:00:00Z"},
             "contentDetails": {"duration": "PT7M28S"}},
            {"id": "b", "snippet": {"title": "B", "publishedAt": "2026-10-19T21:00:00Z"},
             "status": {"privacyStatus": "public"}, "contentDetails": {"duration": "PT45S"}}]})))
    vs = yl.listar_videos(yt)
    assert vs[0] == {"id": "a", "titulo": "A", "privacidade": "private",
                     "publish_at": "2026-10-25T21:00:00Z", "publicado": "2026-10-20T21:00:00Z",
                     "duracao_s": 448}
    assert vs[1]["publish_at"] is None and vs[1]["duracao_s"] == 45


def test_usa_o_projeto_de_metricas_nunca_o_publisher():
    assert yl.CLIENT_SECRET.name == "analytics_client_secret.json"
    assert yl.CLIENT_SECRET != _google.CLIENT_SECRET
    assert yl.ESCOPOS == ["https://www.googleapis.com/auth/yt-analytics.readonly",
                          "https://www.googleapis.com/auth/youtube.readonly"]


def test_login_nao_interativo_nunca_abre_navegador(tmp_path):
    with pytest.raises(_google.LoginNecessario):
        _google.credenciais(yl.ESCOPOS, tmp_path / "token.json", tmp_path / "cs.json",
                            interativo=False)


# --- cobertura extra ------------------------------------------------------------------------

def test_titulos_locais_usa_descricoes_editado(projeto):
    pasta = projeto.video("kim_x", blocos=[1])
    (pasta / "descricoes.txt").write_text(
        "====\nVÍDEO 1 — x\n====\nTÍTULO (20 chars):\nTítulo editado à mão #mbl\n\n"
        "----\nDESCRIÇÃO:\n----\nresumo\n----\nTAGS:\n----\na, b\n", encoding="utf-8")
    ls = ca.titulos_locais(projeto.outputs)
    assert "titulo editado a mao" in {x["chave"] for x in ls}
    assert "titulo 1" in {x["chave"] for x in ls}      # o do blocos.json continua


def test_titulos_locais_blocos_json_quebrado(projeto):
    pasta = projeto.video("kim_y", blocos=[1])
    (pasta / "blocos.json").write_text("{lixo", encoding="utf-8")
    assert ca.titulos_locais(projeto.outputs) == []


@pytest.mark.parametrize("conteudo", ["{lixo", "[]", '{"01": "x"}', '{"02": {}}'])
def test_marcar_short_malformado_nao_quebra(tmp_path, conteudo):
    (tmp_path / "shorts").mkdir()
    (tmp_path / "shorts" / "shorts.json").write_text(conteudo, encoding="utf-8")
    assert ca.marcar_short(tmp_path, 1, "S1", AGORA, False) is False


def test_marcar_short_sem_arquivo(tmp_path):
    assert ca.marcar_short(tmp_path, 1, "S1", AGORA, False) is False


def test_sincronizar_e_main_com_mocks(local, monkeypatch, capsys):
    _, _, _ = local
    monkeypatch.setattr(ca, "OUTPUTS", local[0].parent)
    chamadas = []
    monkeypatch.setattr(ca, "youtube", lambda interativo=True: chamadas.append(interativo) or "yt")
    monkeypatch.setattr(ca, "listar_videos", lambda yt: [
        _v("L1", TITULO_1, "private", "2026-10-26T21:00:00Z"), _v("S1", TITULO_1, dur=40)])
    res = ca.sincronizar(interativo=False)
    assert chamadas == [False] and len(res["longos"]) == 1 and len(res["shorts"]) == 1
    assert ca.main(["--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert chamadas == [False, True]


def test_main_sem_login_propaga(local, monkeypatch):
    def boom(interativo=True):
        raise _google.LoginNecessario("x")
    monkeypatch.setattr(ca, "youtube", boom)
    with pytest.raises(_google.LoginNecessario):
        ca.sincronizar(interativo=False)


def test_listar_videos_pagina_e_lota_em_50():
    ns = types.SimpleNamespace
    paginas = {None: {"items": [{"contentDetails": {"videoId": f"v{i}"}} for i in range(50)],
                      "nextPageToken": "P2"},
               "P2": {"items": [{"contentDetails": {"videoId": f"v{i}"}} for i in range(50, 60)]}}
    lotes = []

    def vlist(**k):
        ids = k["id"].split(",")
        lotes.append(len(ids))
        return _Req({"items": [{"id": i, "snippet": {"title": i, "publishedAt": "2026-10-20T21:00:00Z"},
                                "status": {"privacyStatus": "public"},
                                "contentDetails": {"duration": "PT1M"}} for i in ids]})
    yt = ns(channels=lambda: ns(list=lambda **k: _Req(
                {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})),
            playlistItems=lambda: ns(list=lambda **k: _Req(paginas[k["pageToken"]])),
            videos=lambda: ns(list=vlist))
    vs = yl.listar_videos(yt)
    assert len(vs) == 60 and lotes == [50, 10]


# --- correções da revisão: casamento conservador, 1 vídeo por bloco, nunca rebaixa ---------

def test_titulo_parecido_com_2_blocos_nao_casa(projeto, monkeypatch):
    """Blocos da mesma live com títulos quase iguais: na dúvida vira sem-match."""
    pasta = projeto.video("renan_y", blocos=[1, 2])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0]["titulo_sugerido"] = "Renan Santos detona o Lula no debate da Band"
    blocos["blocos"][1]["titulo_sugerido"] = "Renan Santos detona o Flávio no debate da Band"
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    locais = [x for x in ca.titulos_locais(projeto.outputs) if x["tipo"] == "titulo"]
    assert ca.casar("Renan Santos detona o Lula no debate da Band", locais)["bloco"] == 1
    assert ca.casar("Renan Santos detona o Lula no debate da Band", locais[:1] + locais)["bloco"] == 1
    assert ca.casar("Renan Santos detona o rival no debate da Band", locais) is None   # ambíguo


def test_reupload_fica_o_publico_e_nao_alterna(local):
    _, banco, locais = local
    videos = [_v("PRIVADO0001", TITULO_1, "private", "2026-10-28T21:00:00Z"),
              _v("PUBLICO0001", TITULO_1, publicado="2026-10-21T21:00:00Z")]
    ca.aplicar(videos, locais, AGORA)
    ca.aplicar(list(reversed(videos)), locais, AGORA)
    b = banco("SELECT status, youtube_id FROM blocos WHERE bloco_id=1")[0]
    assert (b["status"], b["youtube_id"]) == ("publicado", "PUBLICO0001")
    assert len(banco("SELECT 1 FROM eventos WHERE etapa='14_canal'")) == 1


def test_publicado_nunca_volta_pra_agendado(local):
    _, banco, locais = local
    ca.aplicar([_v("L1", TITULO_1, publicado="2026-10-21T21:00:00Z")], locais, AGORA)
    ca.aplicar([_v("L2", TITULO_1, "private", "2026-10-28T21:00:00Z")], locais, AGORA)
    b = banco("SELECT status, youtube_id FROM blocos WHERE bloco_id=1")[0]
    assert (b["status"], b["youtube_id"]) == ("publicado", "L1")


def test_longo_e_short_do_mesmo_bloco_nao_competem(local):
    pasta, banco, locais = local
    ca.aplicar([_v("L1", TITULO_1, "private", "2026-10-26T21:00:00Z"),
                _v("S1", TITULO_1, dur=40)], locais, AGORA)
    assert banco("SELECT youtube_id FROM blocos WHERE bloco_id=1")[0]["youtube_id"] == "L1"
    short = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))["01"]
    assert short["youtube_id"] == "S1"
