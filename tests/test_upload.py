"""09_upload.py com a API do YouTube 100% mockada (nada sai da máquina)."""
import importlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

up = importlib.import_module("09_upload")
SP = ZoneInfo("America/Sao_Paulo")


def _txt_descricoes(blocos: dict[int, dict]) -> str:
    """Mesmo formato que o 08_descricao.py gera."""
    partes = ["# Descrições — v", "", ""]
    for bid, b in blocos.items():
        partes += ["=" * 70, f"VÍDEO {bid:02d} — tema {bid}", "=" * 70, "",
                   f"TÍTULO ({len(b['titulo'])} chars):", b["titulo"], "",
                   "-" * 70, "DESCRIÇÃO:", "-" * 70, "",
                   b.get("descricao", "Resumo do bloco.\n\nPrincipais momentos:\n• gancho"),
                   "", "─" * 40,
                   f"📺 Conteúdo original: {b.get('url', 'https://youtu.be/fonte')}", "",
                   "#MissãoEmCortes #MBL", "",
                   "-" * 70, "TAGS (separadas por vírgula, copiar pro YouTube Studio):", "-" * 70,
                   ", ".join(b.get("tags", ["Kim Kataguiri", "MBL"])), "", ""]
    return "\n".join(partes)


# ── parsing e limites da API ───────────────────────────────────────────────

def test_ler_descricoes_formato_do_step_8():
    txt = _txt_descricoes({1: {"titulo": "Título um"}, 2: {"titulo": "Título dois",
                                                           "tags": ["a", "b c"]}})
    d = up.ler_descricoes(txt)
    assert set(d) == {1, 2}
    assert d[1]["titulo"] == "Título um"
    assert d[1]["descricao"].startswith("Resumo do bloco.")
    assert "📺 Conteúdo original: https://youtu.be/fonte" in d[1]["descricao"]
    assert "TAGS" not in d[1]["descricao"]
    assert d[2]["tags"] == ["a", "b c"]


def test_ler_descricoes_aceita_crlf():
    txt = _txt_descricoes({1: {"titulo": "T"}}).replace("\n", "\r\n")
    assert up.ler_descricoes(txt)[1]["titulo"] == "T"


def test_preparar_metadados_respeita_limites():
    meta = up.preparar_metadados({"titulo": "<b>" + "x" * 200, "descricao": "a > b " + "é" * 4000,
                                  "tags": [f"tag numero {i}" for i in range(100)]})
    assert len(meta["titulo"]) == 100 and "<" not in meta["titulo"]
    assert len(meta["descricao"].encode("utf-8")) <= 5000 and ">" not in meta["descricao"]
    total = sum(len(t) + 2 for t in meta["tags"]) + len(meta["tags"]) - 1
    assert 0 < len(meta["tags"]) < 100 and total <= 500


# ── agendamento ────────────────────────────────────────────────────────────

CFG = dict(up.DEFAULTS)


def test_slot_hoje_se_da_tempo():
    s = up.proximos_slots(1, None, CFG, datetime(2026, 10, 21, 10, 0, tzinfo=SP))
    assert s == [datetime(2026, 10, 21, 18, 0, tzinfo=SP)]


def test_slot_amanha_se_nao_respeita_antecedencia():
    s = up.proximos_slots(1, None, CFG, datetime(2026, 10, 21, 16, 30, tzinfo=SP))
    assert s == [datetime(2026, 10, 22, 18, 0, tzinfo=SP)]


def test_slots_continuam_depois_do_ultimo_agendado():
    ultimo = datetime(2026, 10, 25, 18, 0, tzinfo=SP)
    s = up.proximos_slots(3, ultimo, CFG, datetime(2026, 10, 21, 10, 0, tzinfo=SP))
    assert [x.day for x in s] == [26, 27, 28] and all(x.hour == 18 for x in s)


def test_ultimo_agendado_varre_todos_os_videos(tmp_path):
    for nome, data in (("2026-06-01_a", "2026-10-22T18:00:00-03:00"),
                       ("2026-06-02_b", "2026-10-30T18:00:00-03:00")):
        (tmp_path / nome).mkdir()
        (tmp_path / nome / "youtube.json").write_text(
            json.dumps({"01": {"youtube_id": "x", "publish_at": data}}), encoding="utf-8")
    assert up.ultimo_agendado(tmp_path).day == 30


# ── cota ───────────────────────────────────────────────────────────────────

def test_cota_persiste_e_zera_no_dia_seguinte(tmp_path):
    p = tmp_path / "cota.json"
    c = up.Cota(10_000, p)
    c.gastar(1_650)
    assert up.Cota(10_000, p).usadas == 1_650
    p.write_text(json.dumps({"dia_pacifico": "2000-01-01", "usadas": 9_999}))
    assert up.Cota(10_000, p).usadas == 0


def test_cota_cabe(tmp_path):
    c = up.Cota(3_300, tmp_path / "cota.json")
    c.usadas = 1_650
    assert c.cabe(1_650) and not c.cabe(1_651)


# ── main() ponta a ponta com YouTube falso ─────────────────────────────────

class _Resp:
    def __init__(self, status):
        self.status, self.reason = status, "x"


class FakeYouTube:
    def __init__(self, thumb_falha=False):
        self.uploads, self.thumbs, self.thumb_falha = [], [], thumb_falha

    def videos(self):
        fake = self

        class _V:
            def insert(self, part, body, media_body):
                fake.uploads.append(body)

                class _Req:
                    def next_chunk(self):
                        return None, {"id": f"yt{len(fake.uploads)}"}
                return _Req()
        return _V()

    def thumbnails(self):
        fake = self

        class _T:
            def set(self, videoId, media_body):
                class _Req:
                    def execute(self):
                        if fake.thumb_falha:
                            raise up.HttpError(_Resp(500), b"erro")
                        fake.thumbs.append(videoId)
                return _Req()
        return _T()


@pytest.fixture
def cenario(projeto, monkeypatch, tmp_path):
    """Vídeo com 3 blocos finalizados + descricoes.txt + YouTube falso."""
    pasta = projeto.video("v", blocos=[1, 2, 3], finalizados=[1, 2, 3], thumbs=["01_a", "02_c"])
    (pasta / "descricoes.txt").write_text(
        _txt_descricoes({i: {"titulo": f"Título {i}"} for i in (1, 2, 3)}), encoding="utf-8")
    yt = FakeYouTube()
    monkeypatch.setattr(up, "autenticar", lambda: yt)
    monkeypatch.setattr(up, "MediaFileUpload", lambda *a, **k: None)
    monkeypatch.setattr(up, "COTA_PATH", tmp_path / "state" / "cota_youtube.json")
    monkeypatch.setattr(up, "CONFIG", tmp_path / "nao_existe.json")   # usa DEFAULTS
    monkeypatch.setitem(up.DEFAULTS, "auditoria_aprovada", True)   # os testes antigos cobrem o agendado
    monkeypatch.setattr(up, "agora", lambda: datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc))
    return pasta, yt, projeto.banco


def test_dry_run_nao_chama_api(cenario, monkeypatch):
    pasta, yt, _ = cenario
    monkeypatch.setattr(up, "autenticar", lambda: pytest.fail("dry-run autenticou"))
    assert up.main([str(pasta), "--dry-run"]) == 0
    assert not (pasta / "youtube.json").exists()


def test_sobe_agenda_e_grava_no_banco(cenario):
    pasta, yt, banco = cenario
    assert up.main([str(pasta)]) == 0
    assert len(yt.uploads) == 3 and yt.thumbs == ["yt1", "yt2"]  # bloco 3 sem thumb
    st = yt.uploads[0]["status"]
    assert st["privacyStatus"] == "private" and st["publishAt"] == "2026-10-21T21:00:00Z"
    assert yt.uploads[1]["status"]["publishAt"] == "2026-10-22T21:00:00Z"

    reg = json.loads((pasta / "youtube.json").read_text(encoding="utf-8"))
    assert reg["01"]["youtube_id"] == "yt1" and reg["01"]["thumb_ok"] is True
    assert reg["03"]["thumb_ok"] is False
    assert reg["01"]["arquivo"].startswith("video_01_") and reg["01"]["arquivo"].endswith(".mp4")

    b = banco("SELECT status, youtube_id, publish_at FROM blocos WHERE bloco_id=1")[0]
    assert b == {"status": "agendado", "youtube_id": "yt1",
                 "publish_at": "2026-10-21T18:00:00-03:00"}
    ev = banco("SELECT agente, status FROM eventos WHERE etapa='09_upload' AND status='ok'")
    assert len(ev) == 3 and {e["agente"] for e in ev} == {"publicador"}
    assert json.loads(up.COTA_PATH.read_text())["usadas"] == 3 * 1600 + 2 * 50


def test_idempotente_nao_sobe_de_novo(cenario):
    pasta, yt, _ = cenario
    up.main([str(pasta)])
    up.main([str(pasta)])
    assert len(yt.uploads) == 3


def test_idempotente_pelo_banco_mesmo_sem_youtube_json(cenario):
    pasta, yt, _ = cenario
    up.upsert_bloco("v", 1, status="agendado", forcar_status=True, youtube_id="antigo")
    up.main([str(pasta)])
    assert [u["snippet"]["title"] for u in yt.uploads] == ["Título 2", "Título 3"]


def test_thumb_que_falhou_e_retentada_sozinha(cenario):
    pasta, yt, _ = cenario
    yt.thumb_falha = True
    up.main([str(pasta), "--bloco=1"])
    assert json.loads((pasta / "youtube.json").read_text())["01"]["thumb_ok"] is False
    yt.thumb_falha = False
    up.main([str(pasta), "--bloco=1"])
    assert len(yt.uploads) == 1 and yt.thumbs == ["yt1"]


def test_para_antes_de_estourar_a_cota(cenario, monkeypatch):
    pasta, yt, banco = cenario
    monkeypatch.setitem(up.DEFAULTS, "cota_limite_dia", 3_400)  # cabe 2 uploads com thumb
    up.main([str(pasta)])
    assert len(yt.uploads) == 2
    assert banco("SELECT count(*) n FROM eventos WHERE status='aviso'")[0]["n"] == 1


def test_bloco_sem_url_da_fonte_nao_sobe(cenario):
    pasta, yt, _ = cenario
    (pasta / "descricoes.txt").write_text(_txt_descricoes(
        {1: {"titulo": "T", "url": up.PLACEHOLDER_URL}}), encoding="utf-8")
    up.main([str(pasta)])
    assert yt.uploads == []


def test_bloco_com_credito_apontando_pro_nosso_canal_nao_sobe(cenario):
    pasta, yt, _ = cenario
    (pasta / "descricoes.txt").write_text(_txt_descricoes({
        1: {"titulo": "T1", "url": "https://www.youtube.com/channel/" + up.eh_nosso_canal.__globals__["CANAL_ID"]},
        2: {"titulo": "T2", "url": "https://www.youtube.com/@missaoemcortes-14"},
        3: {"titulo": "T3"}}), encoding="utf-8")
    up.main([str(pasta)])
    assert [u["snippet"]["title"] for u in yt.uploads] == ["T3"]   # só o com fonte real sobe


# ── lacunas: cota da API, thumb grande, ler_bloco, _paths ──────────────────

def test_quota_exceeded_da_api_para_o_loop(cenario):
    pasta, yt, _ = cenario
    erro = up.HttpError(_Resp(403), b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}')

    class _V:
        def insert(self, part, body, media_body):
            yt.uploads.append(body)

            class _Req:
                def next_chunk(self):
                    raise erro
            return _Req()
    yt.videos = lambda: _V()
    assert up.main([str(pasta)]) == 1
    assert len(yt.uploads) == 1                       # parou no 1º, não tentou 2 e 3
    assert not (pasta / "youtube.json").exists() or json.loads(
        (pasta / "youtube.json").read_text()) == {}
    assert json.loads((up.COTA_PATH).read_text())["usadas"] == up.DEFAULTS["cota_limite_dia"]


def test_thumb_grande_vira_jpeg(tmp_path, monkeypatch):
    from PIL import Image
    import os
    png = tmp_path / "t.png"
    Image.frombytes("RGB", (900, 900), os.urandom(900 * 900 * 3)).save(png)
    assert png.stat().st_size > up.LIMITE_THUMB_BYTES
    enviados = []
    monkeypatch.setattr(up, "MediaFileUpload", lambda caminho, mimetype=None, **k: enviados.append((caminho, mimetype)))

    class _T:
        def set(self, videoId, media_body):
            class _R:
                def execute(self): pass
            return _R()
    class _Y:
        def thumbnails(self): return _T()
    up.subir_thumb(_Y(), png, "abc")
    assert enviados[0][1] == "image/jpeg" and enviados[0][0].endswith(".jpg")


def test_ler_bloco_banco_fora_do_ar_retorna_none(monkeypatch):
    import _eventos
    def boom(*a, **k): raise RuntimeError("banco morto")
    monkeypatch.setattr(_eventos, "conectar", boom)
    assert _eventos.ler_bloco("x", 1) is None


def test_escolher_arquivo_prefere_polido(tmp_path):
    import _paths
    assert _paths.escolher_arquivo(tmp_path / "nao_existe", "v_*.mp4") is None
    (tmp_path / "video_01_a.mp4").touch()
    assert _paths.escolher_arquivo(tmp_path, "video_01_*.mp4").name == "video_01_a.mp4"
    (tmp_path / "video_01_a_polido.mp4").touch()
    assert _paths.escolher_arquivo(tmp_path, "video_01_*.mp4").name == "video_01_a_polido.mp4"
    assert _paths.escolher_arquivo(tmp_path, "video_01_*.mp4", False).name == "video_01_a.mp4"


def test_escolher_thumb_prioridade(tmp_path):
    import _paths
    assert _paths.escolher_thumb(tmp_path, "01") is None
    for n in ("thumb_01_c.png", "thumb_01_b.png"):
        (tmp_path / n).touch()
    assert _paths.escolher_thumb(tmp_path, "01").name == "thumb_01_b.png"
    (tmp_path / "thumb_01_manual.png").touch()
    assert _paths.escolher_thumb(tmp_path, "01").name == "thumb_01_manual.png"


# ── trava da auditoria (projeto não auditado = vídeo bloqueado como privado) ──

@pytest.fixture
def travado(cenario, monkeypatch):
    monkeypatch.setitem(up.DEFAULTS, "auditoria_aprovada", False)
    return cenario


def test_config_do_repo_esta_travada():
    assert up.carregar_config()["auditoria_aprovada"] is False


def test_travado_recusa_upload_real(travado, monkeypatch, capsys):
    pasta, yt, banco = travado
    monkeypatch.setattr(up, "autenticar", lambda: pytest.fail("travado autenticou"))
    assert up.main([str(pasta)]) == 1
    out = capsys.readouterr().out
    assert "TRAVADO" in out and "auditoria_aprovada" in out and "--teste" in out
    assert "Studio" not in out
    assert yt.uploads == [] and not (pasta / "youtube.json").exists()
    ev = banco("SELECT mensagem FROM eventos WHERE etapa='09_upload' AND status='aviso'")
    assert "auditoria" in ev[0]["mensagem"]


def test_travado_dry_run_avisa_e_sai_zero(travado, capsys):
    pasta, yt, _ = travado
    assert up.main([str(pasta), "--dry-run"]) == 0
    assert "TRAVADO" in capsys.readouterr().out and yt.uploads == []


def test_travado_tambem_recusa_retentativa_de_thumb(travado):
    pasta, yt, _ = travado
    (pasta / "youtube.json").write_text(json.dumps(
        {"01": {"youtube_id": "velho", "publish_at": None, "titulo": "T", "thumb_ok": False}}))
    assert up.main([str(pasta), "--bloco=1"]) == 1
    assert yt.thumbs == []


def test_teste_exige_bloco(travado):
    pasta, yt, _ = travado
    with pytest.raises(SystemExit):
        up.main([str(pasta), "--teste"])
    assert yt.uploads == []


def test_teste_sobe_privado_sem_data_e_nao_conta_como_real(travado):
    pasta, yt, banco = travado
    assert up.main([str(pasta), "--bloco=1", "--teste"]) == 0
    u = yt.uploads[0]
    assert u["status"]["privacyStatus"] == "private" and "publishAt" not in u["status"]
    assert u["snippet"]["title"] == "[TESTE] Título 1"
    assert yt.thumbs == ["yt1"]
    reg = json.loads((pasta / up.TESTE_JSON).read_text(encoding="utf-8"))
    assert reg["01"][0]["youtube_id"] == "yt1"
    assert not (pasta / "youtube.json").exists()
    assert banco("SELECT youtube_id FROM blocos WHERE bloco_id=1 AND youtube_id IS NOT NULL") == []
    assert up.ultimo_agendado(pasta.parent) is None
    ev = banco("SELECT mensagem FROM eventos WHERE etapa='09_upload' AND status='ok'")
    assert ev[0]["mensagem"].startswith("TESTE")


def test_teste_pode_repetir_e_acumula_registro(travado):
    pasta, yt, _ = travado
    up.main([str(pasta), "--bloco=1", "--teste"])
    up.main([str(pasta), "--bloco=1", "--teste"])
    assert len(yt.uploads) == 2
    assert len(json.loads((pasta / up.TESTE_JSON).read_text())["01"]) == 2


def test_teste_nao_bloqueia_upload_real_depois_da_auditoria(travado, monkeypatch):
    pasta, yt, banco = travado
    up.main([str(pasta), "--bloco=1", "--teste"])
    monkeypatch.setitem(up.DEFAULTS, "auditoria_aprovada", True)
    assert up.main([str(pasta), "--bloco=1"]) == 0
    assert yt.uploads[1]["snippet"]["title"] == "Título 1"
    assert "publishAt" in yt.uploads[1]["status"]
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "agendado"


def test_auditoria_aprovada_invalida_falha_alto(tmp_path):
    cfg = tmp_path / "upload.json"
    cfg.write_text('{"auditoria_aprovada": "sim"}')
    with pytest.raises(SystemExit):
        up.carregar_config(cfg)
