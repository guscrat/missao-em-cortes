"""Modo --demo do 09 (screencast da auditoria): tudo mockado, nada de rede/OAuth/ffmpeg."""
import importlib
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import _demo_auditoria as d
import _eventos
import _paths

up = importlib.import_module("09_upload")
SLOT = datetime(2026, 11, 10, 18, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
ESC_UPLOAD = ["https://www.googleapis.com/auth/youtube.upload"]
ESC_SSL = ["https://www.googleapis.com/auth/youtube.force-ssl"]
RESP = {"id": "VID123", "status": {"uploadStatus": "uploaded", "privacyStatus": "private"}}


@pytest.fixture
def amb(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    (tmp_path / "secrets").mkdir()
    pasta = tmp_path / "state" / "demo_auditoria"
    monkeypatch.setattr(d, "ROOT", tmp_path)
    monkeypatch.setattr(d, "PASTA", pasta)
    monkeypatch.setattr(d, "REGISTRO", pasta / "demo.json")
    monkeypatch.setattr(up, "TOKEN", tmp_path / "secrets" / "tok.json")
    monkeypatch.setattr(up, "COTA_PATH", tmp_path / "state" / "cota.json")
    monkeypatch.setattr(up, "CONFIG", tmp_path / "upload.json")
    monkeypatch.setattr(d, "proximo_slot", lambda cfg: SLOT)
    monkeypatch.setattr(_eventos, "evento", MagicMock())
    yt = MagicMock(name="youtube")
    monkeypatch.setattr(up, "autenticar", lambda: yt)
    return SimpleNamespace(root=tmp_path, pasta=pasta, yt=yt)


def _prepara_registro(amb, **extra):
    amb.pasta.mkdir(parents=True, exist_ok=True)
    (amb.pasta / "clip_demo.mp4").write_bytes(b"")
    (amb.pasta / "thumb_demo.jpg").write_bytes(b"")
    reg = {"stem": "live", "bloco": 1, "origem": "v.mp4", "segundos": 15, "clip": "clip_demo.mp4",
           "thumb": "thumb_demo.jpg", "fonte": "https://youtu.be/fonte"} | extra
    d.REGISTRO.write_text(json.dumps(reg), encoding="utf-8")
    return reg


def _token(escopos):
    up.TOKEN.write_text(json.dumps({"refresh_token": "rt", "scopes": escopos}), encoding="utf-8")


def _reg():
    return json.loads(d.REGISTRO.read_text(encoding="utf-8"))


# ── despacho ───────────────────────────────────────────────────────────────

def test_etapa_invalida_retorna_2(amb, capsys):
    assert d.main(["--demo=xyz"]) == 2
    assert "--demo precisa" in capsys.readouterr().out
    assert d.main(["--demo"]) == 2   # flag sem valor


@pytest.mark.parametrize("etapa", ["plano", "upload"])
def test_sem_preparar_retorna_1(amb, etapa, capsys):
    assert d.main([f"--demo={etapa}"]) == 1
    assert "--demo=preparar" in capsys.readouterr().out


def test_thumb_sem_upload_retorna_1(amb, capsys):
    _prepara_registro(amb)
    assert d.main(["--demo=thumb"]) == 1
    assert "--demo=upload" in capsys.readouterr().out


def test_09_despacha_demo(monkeypatch):
    visto = []
    monkeypatch.setattr(d, "main", lambda argv: visto.append(argv) or 7)
    assert up.main(["--demo=plano", "--lang=en"]) == 7
    assert visto == [["--demo=plano", "--lang=en"]]


# ── preparar ───────────────────────────────────────────────────────────────

@pytest.fixture
def live(amb, monkeypatch):
    out = amb.root / "outputs"
    pasta = out / "2026-11-01_live"
    (pasta / "finalizados").mkdir(parents=True)
    (pasta / "thumbs").mkdir()
    (pasta / "finalizados" / "video_01_x.mp4").write_bytes(b"")
    (pasta / "thumbs" / "thumb_01.jpg").write_bytes(b"jpg")
    (amb.root / "inputs").mkdir()
    monkeypatch.setattr(_paths, "OUTPUTS", out)
    monkeypatch.setattr(_paths, "escolher_thumb", lambda p, nn: p / "thumb_01.jpg")
    run = MagicMock()
    monkeypatch.setattr(d.subprocess, "run", run)
    amb.run = run
    return amb


def test_preparar_sem_url_recusa(live, capsys):
    assert d.main(["--demo=preparar", "live"]) == 1
    assert "Sem URL da fonte" in capsys.readouterr().out
    live.run.assert_not_called()


def test_preparar_url_do_nosso_canal_recusa(live, capsys):
    (live.root / "inputs" / "live.url").write_text(
        "https://www.youtube.com/channel/UCRJDgbBEndOdbNaiwzFju2g", encoding="utf-8")
    assert d.main(["--demo=preparar", "live"]) == 1
    assert "nosso canal" in capsys.readouterr().out
    live.run.assert_not_called()


@pytest.mark.parametrize("seg", ["9", "21"])
def test_preparar_segundos_fora_da_faixa(live, seg, capsys):
    assert d.main(["--demo=preparar", "live", f"--segundos={seg}"]) == 1
    assert "entre 10 e 20" in capsys.readouterr().out
    live.run.assert_not_called()


def test_preparar_ok_grava_registro(live):
    (live.root / "inputs" / "live.url").write_text("https://youtu.be/abc", encoding="utf-8")
    assert d.main(["--demo=preparar", "live", "--segundos=12"]) == 0
    cmd = live.run.call_args.args[0]
    assert cmd[0] == "ffmpeg" and cmd[cmd.index("-t") + 1] == "12"
    reg = _reg()
    assert reg["fonte"] == "https://youtu.be/abc" and reg["segundos"] == 12 and reg["bloco"] == 1
    assert (d.PASTA / "thumb_demo.jpg").exists()


# ── plano ──────────────────────────────────────────────────────────────────

def test_plano_imprime_corpo_com_publish_at(amb, capsys):
    _prepara_registro(amb)
    assert d.main(["--demo=plano", "--agendar"]) == 0
    out = capsys.readouterr().out
    assert '"publishAt": "2026-11-10T21:00:00Z"' in out
    assert "[TEST]" in out and "Original content: https://youtu.be/fonte" in out
    assert "PLANO DO UPLOAD" in out and "PRIVADO + publishAt" in out


# ── upload ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("agendar", [False, True])
def test_upload_publish_at_so_com_agendar(amb, monkeypatch, agendar):
    _prepara_registro(amb)
    ins = MagicMock(return_value=RESP)
    monkeypatch.setattr(up, "inserir_video", ins)
    assert d.main(["--demo=upload"] + (["--agendar"] if agendar else [])) == 0
    status = ins.call_args.args[2]["status"]
    assert status["privacyStatus"] == "private"
    assert ("publishAt" in status) is agendar
    if agendar:
        assert status["publishAt"] == "2026-11-10T21:00:00Z"


def test_upload_grava_youtube_id_e_gasta_cota(amb, monkeypatch):
    _prepara_registro(amb)
    monkeypatch.setattr(up, "inserir_video", MagicMock(return_value=RESP))
    assert d.main(["--demo=upload"]) == 0
    reg = _reg()
    assert reg["youtube_id"] == "VID123" and reg["privacy_status"] == "private"
    assert reg["thumb_ok"] is False
    assert up.Cota(10_000).usadas == 1_600


def test_upload_cota_insuficiente(amb, monkeypatch):
    _prepara_registro(amb)
    up.Cota(10_000).gastar(9_000)
    ins = MagicMock()
    monkeypatch.setattr(up, "inserir_video", ins)
    assert d.main(["--demo=upload"]) == 1
    ins.assert_not_called()


# ── thumb ──────────────────────────────────────────────────────────────────

def test_thumb_marca_thumb_ok(amb, monkeypatch):
    _prepara_registro(amb, youtube_id="VID123", thumb_ok=False)
    st = MagicMock(return_value={"items": [{"default": {"url": "http://x/t.jpg"}}]})
    monkeypatch.setattr(up, "subir_thumb", st)
    assert d.main(["--demo=thumb"]) == 0
    assert st.call_args.args[2] == "VID123"
    assert _reg()["thumb_ok"] is True
    assert up.Cota(10_000).usadas == 50


# ── update ─────────────────────────────────────────────────────────────────

def test_update_so_upload_pula(amb, capsys):
    _prepara_registro(amb, youtube_id="VID123")
    _token(ESC_UPLOAD)
    assert d.main(["--demo=update"]) == 0
    assert "PULADO" in capsys.readouterr().out
    amb.yt.videos.assert_not_called()


def test_update_com_force_ssl_chama_api(amb):
    _prepara_registro(amb, youtube_id="VID123")
    _token(ESC_SSL)
    assert d.main(["--demo=update"]) == 0
    amb.yt.videos().update.assert_called_once()
    assert amb.yt.videos().update.call_args.kwargs["body"]["id"] == "VID123"
    assert _reg()["update_ok"] is True


# ── login ──────────────────────────────────────────────────────────────────

def test_login_revoga_e_apaga_antes_de_autenticar(amb, monkeypatch):
    _token(ESC_UPLOAD)
    chamadas = []
    monkeypatch.setattr(d.urllib.request, "urlopen",
                        lambda req, timeout=None: chamadas.append(req) or MagicMock())

    def aut():
        assert not up.TOKEN.exists()   # já apagado quando abre o consentimento
        return amb.yt
    monkeypatch.setattr(up, "autenticar", aut)
    assert d.main(["--demo=login"]) == 0
    assert len(chamadas) == 1
    assert chamadas[0].full_url == d.REVOKE_URL and chamadas[0].get_method() == "POST"
    assert b"token=rt" in chamadas[0].data


def test_login_segue_se_revoke_falhar(amb, monkeypatch, capsys):
    _token(ESC_UPLOAD)

    def boom(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(d.urllib.request, "urlopen", boom)
    aut = MagicMock(return_value=amb.yt)
    monkeypatch.setattr(up, "autenticar", aut)
    assert d.main(["--demo=login"]) == 0
    assert not up.TOKEN.exists()
    aut.assert_called_once()
    assert "não confirmou" in capsys.readouterr().out


def test_login_sem_token_nao_chama_revoke(amb, monkeypatch):
    uo = MagicMock()
    monkeypatch.setattr(d.urllib.request, "urlopen", uo)
    assert d.main(["--demo=login"]) == 0
    uo.assert_not_called()


# ── idioma ─────────────────────────────────────────────────────────────────

def test_lang_en_e_padrao_pt(amb, capsys):
    d.main(["--demo=plano"])
    assert "Rode antes" in capsys.readouterr().out
    d.main(["--demo=plano", "--lang=en"])
    assert "Run first" in capsys.readouterr().out


# ── refatorações do 09 ─────────────────────────────────────────────────────

def test_inserir_video_devolve_resposta_inteira(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(up, "MediaFileUpload", MagicMock())
    req = MagicMock()
    req.next_chunk.return_value = (None, RESP)
    yt = MagicMock()
    yt.videos().insert.return_value = req
    assert up.inserir_video(yt, video, {"a": 1}) == RESP


def test_subir_thumb_devolve_resposta(tmp_path, monkeypatch):
    t = tmp_path / "t.jpg"
    t.write_bytes(b"x")
    monkeypatch.setattr(up, "MediaFileUpload", MagicMock())
    yt = MagicMock()
    yt.thumbnails().set().execute.return_value = {"items": [1]}
    assert up.subir_thumb(yt, t, "VID") == {"items": [1]}


def test_subir_video_continua_devolvendo_id(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "inserir_video", lambda y, v, b: RESP)
    meta = {"titulo": "t", "descricao": "d", "tags": []}
    assert up.subir_video(None, tmp_path / "v", meta, None, up.carregar_config(tmp_path / "n")) == "VID123"
