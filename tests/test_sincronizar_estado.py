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


# ── conteúdo antigo → arquivado ────────────────────────────────────────────

from datetime import date  # noqa: E402

import sincronizar_estado  # noqa: E402


@pytest.fixture
def arquivamento(monkeypatch):
    monkeypatch.setattr(sincronizar_estado, "DIAS_ARQUIVAR", 15)


@pytest.mark.parametrize("hoje, arquiva", [(date(2026, 7, 10), False),    # 15 dias: ainda não
                                           (date(2026, 7, 11), True)])    # 16 dias: arquiva
def test_arquiva_live_com_mais_de_15_dias(projeto, arquivamento, hoje, arquiva):
    pasta = projeto.video("v", blocos=[1, 2], finalizados=[1, 2])   # pasta de 2026-06-25
    sincronizar_pasta(pasta, hoje=hoje)
    esperado = "arquivado" if arquiva else "montado"
    assert {r["status"] for r in _blocos(projeto.banco).values()} == {esperado}


def test_arquivar_preserva_agendado_e_registra_evento(projeto, arquivamento):
    pasta = projeto.video("v", blocos=[1, 2], finalizados=[1, 2])
    sincronizar_pasta(pasta, hoje=date(2026, 6, 26))
    upsert_bloco("v", 2, status="agendado", forcar_status=True, publish_at="2026-07-01T18:00")
    assert sincronizar_estado.arquivar_se_antigo(pasta, "v", hoje=date(2026, 10, 22)) == [1]
    b = _blocos(projeto.banco)
    assert (b[1]["status"], b[1]["motivo"]) == ("arquivado", "conteúdo antigo")
    assert b[2]["status"] == "agendado"
    ev = projeto.banco("SELECT etapa, mensagem FROM eventos WHERE etapa='arquivar'")
    assert len(ev) == 1 and "blocos [1]" in ev[0]["mensagem"]


def test_main_arquiva_antigo_e_poupa_recente(projeto, arquivamento, capsys):
    projeto.video("velho", blocos=[1], finalizados=[1], data="2026-06-25")
    projeto.video("novo", blocos=[1], finalizados=[1], data=date.today().isoformat())
    main()
    st = {r["stem"]: r["status"] for r in projeto.banco("SELECT stem, status FROM blocos")}
    assert st == {"velho": "arquivado", "novo": "montado"}
    assert "arquivados por conteúdo antigo" in capsys.readouterr().out
    main()   # re-sincronizar não desarquiva
    assert projeto.banco("SELECT status FROM blocos WHERE stem='velho'")[0]["status"] == "arquivado"
