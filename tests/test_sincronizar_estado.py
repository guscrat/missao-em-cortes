import pytest

from _eventos import upsert_bloco
from sincronizar_estado import main, sincronizar_pasta


def _blocos(banco):
    return {r["bloco_id"]: r for r in banco("SELECT * FROM blocos ORDER BY bloco_id")}


def test_status_derivado_dos_arquivos(projeto):
    pasta = projeto.video("v", blocos=[1, 2, 3], cortes=[2, 3], finalizados=[3])
    assert sincronizar_pasta(pasta) == ("v", 3)
    b = _blocos(projeto.banco)
    assert [b[i]["status"] for i in (1, 2, 3)] == ["segmentado", "cortado", "montado"]
    assert b[3]["video_path"] == "outputs/2026-06-25_v/finalizados/video_03_slug.mp4"
    assert b[1]["video_path"] is None


def test_status_do_video_e_url_da_fonte(projeto):
    pasta = projeto.video("v", url="https://youtu.be/abc")
    sincronizar_pasta(pasta)
    r = projeto.banco("SELECT status, pasta, fonte_url FROM videos")[0]
    assert r == {"status": "segmentado", "pasta": "2026-06-25_v", "fonte_url": "https://youtu.be/abc"}


def test_video_so_transcrito(projeto):
    pasta = projeto.outputs / "2026-06-25_t"
    pasta.mkdir()
    (pasta / "transcricao.txt").write_text("oi", encoding="utf-8")
    assert sincronizar_pasta(pasta) == ("t", 0)
    assert projeto.banco("SELECT status FROM videos")[0]["status"] == "transcrito"


def test_prefere_finalizado_polido(projeto):
    pasta = projeto.video("v", finalizados=[1], polidos=[1])
    sincronizar_pasta(pasta)
    assert _blocos(projeto.banco)[1]["video_path"].endswith("video_01_slug_polido.mp4")


def test_thumb_acha_variante_escolhida_b_ou_c(projeto):
    pasta = projeto.video("v", blocos=[1, 2], thumbs=["01_c", "02_b"])
    sincronizar_pasta(pasta)
    b = _blocos(projeto.banco)
    assert b[1]["thumb_path"] == "outputs/2026-06-25_v/thumbs/thumb_01_c.png"
    assert b[2]["thumb_path"] == "outputs/2026-06-25_v/thumbs/thumb_02_b.png"


def test_thumb_manual_ganha_das_variantes(projeto):
    pasta = projeto.video("v", thumbs=["01_a", "01_b", "01_manual"])
    sincronizar_pasta(pasta)
    assert _blocos(projeto.banco)[1]["thumb_path"].endswith("thumb_01_manual.png")


def test_caminhos_gravados_em_posix(projeto):
    pasta = projeto.video("v", finalizados=[1], thumbs=["01_a"])
    sincronizar_pasta(pasta)
    b = _blocos(projeto.banco)[1]
    assert "\\" not in b["video_path"] and "\\" not in b["thumb_path"]


def test_idempotente(projeto):
    projeto.video("v", blocos=[1, 2], cortes=[1], thumbs=["01_a"])
    main()
    antes = _blocos(projeto.banco)
    main()
    depois = _blocos(projeto.banco)
    assert len(projeto.banco("SELECT * FROM videos")) == 1
    tirar_ts = lambda d: {k: {c: v for c, v in r.items() if c != "atualizado_em"}  # noqa: E731
                          for k, r in d.items()}
    assert tirar_ts(antes) == tirar_ts(depois)


def test_sincronizar_nao_rebaixa_decisao(projeto):
    pasta = projeto.video("v", finalizados=[1])
    sincronizar_pasta(pasta)
    upsert_bloco("v", 1, status="agendado", forcar_status=True, youtube_id="abc")
    sincronizar_pasta(pasta)
    r = _blocos(projeto.banco)[1]
    assert (r["status"], r["youtube_id"]) == ("agendado", "abc")


def test_main_ignora_pastas_sem_data(projeto, capsys):
    projeto.video("v")
    for lixo in ("_old", "_debug", "_calibracao"):
        (projeto.outputs / lixo).mkdir()
    main()
    assert [r["stem"] for r in projeto.banco("SELECT stem FROM videos")] == ["v"]
    assert "1 vídeos" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["quarentena", "descartado"])
def test_sincronizar_nao_rebaixa_quarentena_nem_descartado(projeto, status):
    pasta = projeto.video("v", finalizados=[1])
    sincronizar_pasta(pasta)
    upsert_bloco("v", 1, status=status, forcar_status=True)
    sincronizar_pasta(pasta)
    assert _blocos(projeto.banco)[1]["status"] == status
