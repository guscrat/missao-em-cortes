import pytest

import _eventos
from _eventos import evento, upsert_bloco, upsert_video


def _status(banco, stem="v", bloco_id=1):
    return banco("SELECT status FROM blocos WHERE stem=? AND bloco_id=?", stem, bloco_id)[0]["status"]


# ── status AUTO x DECISÃO ──────────────────────────────────────────────────

def test_status_auto_avanca(banco):
    upsert_bloco("v", 1, status="segmentado")
    upsert_bloco("v", 1, status="montado")
    assert _status(banco) == "montado"


def test_status_auto_nao_rebaixa_decisao(banco):
    upsert_bloco("v", 1, status="agendado", forcar_status=True)
    upsert_bloco("v", 1, status="montado")  # o que o sincronizar faria
    assert _status(banco) == "agendado"


def test_forcar_status_sobrescreve_decisao(banco):
    upsert_bloco("v", 1, status="quarentena", forcar_status=True)
    upsert_bloco("v", 1, status="aprovado", forcar_status=True)
    assert _status(banco) == "aprovado"


def test_bloco_cria_video_pra_fk(banco):
    upsert_bloco("sem_video", 3, tema="x")
    assert banco("SELECT stem FROM videos") == [{"stem": "sem_video"}]


def test_campos_atualizam_sem_mexer_no_status(banco):
    upsert_bloco("v", 1, status="agendado", forcar_status=True)
    upsert_bloco("v", 1, youtube_id="abc123", publish_at="2026-11-01T18:00")
    r = banco("SELECT status, youtube_id, publish_at FROM blocos")[0]
    assert r == {"status": "agendado", "youtube_id": "abc123", "publish_at": "2026-11-01T18:00"}


def test_status_invalido_falha_alto(banco):
    with pytest.raises(ValueError):
        upsert_bloco("v", 1, status="inventado")


def test_campo_invalido_falha_alto(banco):
    with pytest.raises(ValueError):
        upsert_bloco("v", 1, campo_que_nao_existe=1)


def test_upsert_video_nao_apaga_campos_com_none(banco):
    upsert_video("v", pasta="2026-06-25_v", fonte_url="https://x", status="transcrito")
    upsert_video("v", status="segmentado")
    r = banco("SELECT pasta, fonte_url, status FROM videos")[0]
    assert r == {"pasta": "2026-06-25_v", "fonte_url": "https://x", "status": "segmentado"}


def test_evento_grava_tokens_e_custo(banco):
    evento("v", "03_segmentar", "llm", agente="editor",
           tokens_in=40_000, tokens_out=3_000, custo_usd=0.165)
    r = banco("SELECT agente, etapa, status, tokens_in, tokens_out, custo_usd FROM eventos")[0]
    assert r == {"agente": "editor", "etapa": "03_segmentar", "status": "llm",
                 "tokens_in": 40_000, "tokens_out": 3_000, "custo_usd": 0.165}


# ── best-effort: banco falhar nunca derruba o pipeline ─────────────────────

def test_banco_nao_conecta_nao_derruba(banco, monkeypatch, capsys):
    def quebra(*a, **k):
        raise OSError("disco cheio (simulado)")
    monkeypatch.setattr(_eventos, "conectar", quebra)

    evento("v", "04_cortar", "ok")
    upsert_video("v", status="baixado")
    upsert_bloco("v", 1, status="cortado")

    assert capsys.readouterr().err.count("[aviso] painel") == 3


def test_erro_no_meio_da_escrita_nao_derruba(banco, capsys):
    upsert_bloco("v", 1, tema={"dict": "não vira coluna sqlite"})
    assert "[aviso] painel" in capsys.readouterr().err


def test_caminho_do_banco_invalido_nao_derruba(tmp_path, monkeypatch, capsys):
    bloqueio = tmp_path / "arquivo_no_lugar_da_pasta"
    bloqueio.write_text("")
    monkeypatch.setattr(_eventos, "DB_PATH", bloqueio / "pipeline.db")
    evento("v", "05_cards", "ok")
    assert "[aviso] painel" in capsys.readouterr().err
