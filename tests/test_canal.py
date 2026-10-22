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
