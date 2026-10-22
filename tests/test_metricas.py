"""Step 12: retenção com x sem legenda. APIs do Google falsas (nunca rede, nunca login)."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "metricas", Path(__file__).parent.parent / "scripts" / "12_metricas.py")
mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mt)


def _desc(titulos: dict[int, str]) -> str:
    partes = []
    for bid, t in titulos.items():
        partes += ["=" * 70, f"VÍDEO {bid:02d} — x", "=" * 70, f"TÍTULO ({len(t)} chars):", t, "",
                   "-" * 70, "DESCRIÇÃO:", "-" * 70, "desc", "-" * 70, "TAGS (x):", "-" * 70, "a, b", ""]
    return "\n".join(partes)


def test_normalizar_ignora_acento_caixa_e_pontuacao():
    assert mt.normalizar("Kim: 'R$ 1,1 TRI' — Superministério!") == mt.normalizar("kim r 1 1 tri superministerio")


def test_duracao_iso():
    assert mt.duracao_iso("PT6M30S") == 390
    assert mt.duracao_iso("PT1H2M3S") == 3723
    assert mt.duracao_iso("PT45S") == 45
    assert mt.duracao_iso("lixo") == 0


def test_titulos_locais_marca_legendado(tmp_path):
    pasta = tmp_path / "2026-10-22_kim"
    (pasta / "finalizados").mkdir(parents=True)
    (pasta / "descricoes.txt").write_text(_desc({1: "Com Legenda", 2: "Sem Legenda"}), encoding="utf-8")
    (pasta / "finalizados" / "video_01_x_polido_legendado.mp4").touch()
    (pasta / "finalizados" / "video_02_x_polido.mp4").touch()
    (tmp_path / "_debug").mkdir()   # pasta sem descricoes é ignorada
    assert mt.titulos_locais(tmp_path) == {"com legenda": True, "sem legenda": False}


def _v(titulo, publicado="2026-10-25T18:00:00Z", dur=400, **kw):
    return {"titulo": titulo, "publicado": publicado, "duracao_s": dur, **kw}


def test_classificar():
    mapa = {"com legenda": True, "sem legenda": False}
    assert mt.classificar(_v("Com legenda!"), mapa) == "com_legenda"
    assert mt.classificar(_v("Sem legenda"), mapa) == "sem_legenda"
    assert mt.classificar(_v("antigo", "2026-06-01T00:00:00Z"), mapa) == "sem_legenda"
    assert mt.classificar(_v("novo sem match"), mapa) == "sem_info"
    assert mt.classificar(_v("Com legenda", dur=60), mapa) == "short"


def test_resumo_grupo_pondera_por_views_e_ignora_poucas_views():
    g = mt.resumo_grupo([{"views": 100, "retencao_pct": 40.0, "assistido_s": 120},
                         {"views": 300, "retencao_pct": 60.0, "assistido_s": 200},
                         {"views": 5, "retencao_pct": 99.0, "assistido_s": 999}])
    assert g == {"n": 2, "views": 400, "retencao_pct": 55.0, "assistido_s": 180}
    assert mt.resumo_grupo([{"views": 1, "retencao_pct": 50.0, "assistido_s": 1}]) is None
    assert mt.resumo_grupo([]) is None


# ── main() com Google falso ────────────────────────────────────────────────

class _Req:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


class FakeYT:
    def __init__(self, videos):
        self.videos_ = videos

    def channels(self):
        return types.SimpleNamespace(list=lambda **k: _Req(
            {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}))

    def playlistItems(self):
        itens = [{"contentDetails": {"videoId": v["id"]}} for v in self.videos_]
        return types.SimpleNamespace(list=lambda **k: _Req({"items": itens}))

    def videos(self):
        def lista(id, **k):
            ids = id.split(",")
            return _Req({"items": [
                {"id": v["id"], "snippet": {"title": v["titulo"], "publishedAt": v["publicado"]},
                 "contentDetails": {"duration": v["dur"]}, "status": {"privacyStatus": v.get("priv", "public")}}
                for v in self.videos_ if v["id"] in ids]})
        return types.SimpleNamespace(list=lista)


class FakeAnalytics:
    def __init__(self, linhas):
        self.linhas, self.consultas = linhas, []

    def reports(self):
        def query(**k):
            self.consultas.append(k)
            return _Req({"rows": self.linhas})
        return types.SimpleNamespace(query=query)


@pytest.fixture
def canal(tmp_path, monkeypatch, banco):
    out = tmp_path / "outputs" / "2026-10-22_kim"
    (out / "finalizados").mkdir(parents=True)
    (out / "descricoes.txt").write_text(_desc({1: "Kim legendado"}), encoding="utf-8")
    (out / "finalizados" / "video_01_x_legendado.mp4").touch()
    videos = [
        {"id": "a", "titulo": "Kim legendado", "publicado": "2026-10-25T18:00:00Z", "dur": "PT6M"},
        {"id": "b", "titulo": "Antigo 1", "publicado": "2026-06-01T18:00:00Z", "dur": "PT8M"},
        {"id": "c", "titulo": "Antigo 2", "publicado": "2026-06-05T18:00:00Z", "dur": "PT7M"},
        {"id": "d", "titulo": "Um short", "publicado": "2026-10-26T18:00:00Z", "dur": "PT40S"},
        {"id": "e", "titulo": "Teste privado", "publicado": "2026-10-26T18:00:00Z", "dur": "PT6M",
         "priv": "private"},
    ]
    analytics = FakeAnalytics([["a", 1000, 216.0, 60.0], ["b", 500, 192.0, 40.0],
                               ["c", 500, 210.0, 50.0], ["d", 9000, 30.0, 90.0]])
    builds = {"youtube": FakeYT(videos), "youtubeAnalytics": analytics}
    fake_discovery = types.SimpleNamespace(build=lambda api, v, **k: builds[api])
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", fake_discovery)
    monkeypatch.setattr(mt, "credenciais", lambda escopos, token: "creds")
    monkeypatch.setattr(mt, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(mt, "SAIDA", tmp_path / "state" / "metricas_retencao.json")
    return analytics


def test_main_compara_com_e_sem_legenda(canal, capsys, banco):
    assert mt.main([]) == 0
    out = capsys.readouterr().out
    assert "COM legenda: 60.0%" in out and "SEM legenda: 45.0%" in out
    assert "+15.0 pontos" in out and "Um short" not in out and "Teste privado" not in out
    salvo = json.loads(mt.SAIDA.read_text(encoding="utf-8"))
    assert salvo["com_legenda"]["n"] == 1 and salvo["sem_legenda"]["n"] == 2
    ev = banco("SELECT agente FROM eventos WHERE etapa='12_metricas'")
    assert ev == [{"agente": "analista"}]


def test_main_consulta_analytics_so_dos_publicos(canal):
    mt.main(["--desde=2026-06-01"])
    q = canal.consultas[0]
    assert q["ids"] == "channel==MINE" and q["startDate"] == "2026-06-01"
    assert set(q["filters"].removeprefix("video==").split(",")) == {"a", "b", "c", "d"}


def test_escopos_sao_so_leitura_e_token_separado():
    assert all(e.endswith(".readonly") for e in mt.ESCOPOS)
    assert mt.TOKEN.name == "youtube_leitura_token.json"
