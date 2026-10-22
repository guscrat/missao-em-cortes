"""Fixtures compartilhadas: banco e outputs/ falsos em tmp_path.

Regra: teste nunca toca o state/ nem o outputs/ reais, nunca baixa vídeo, nunca
roda whisper/ffmpeg e nunca chama API paga (use mock).
"""
import json
import sqlite3

import pytest

import _eventos
import sincronizar_estado


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Aponta o _eventos pra um SQLite descartável. Retorna uma função de consulta."""
    db = tmp_path / "state" / "pipeline.db"
    monkeypatch.setattr(_eventos, "DB_PATH", db)

    def consultar(sql: str, *params):
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, params)]
        finally:
            con.close()

    return consultar


@pytest.fixture
def projeto(tmp_path, monkeypatch, banco):
    """Projeto falso (inputs/ + outputs/) com um criador de vídeos processados.

    projeto.video("kim_decisao", blocos=[1, 2], cortes=[1], finalizados=[1],
                  thumbs=["01_c"], url="https://...")
    cria outputs/2026-06-25_<stem>/ com blocos.json mínimo e mp4/png vazios.
    """
    root = tmp_path   # mesmo root do banco falso (tmp_path/state/), como no repo real
    outputs, inputs = root / "outputs", root / "inputs"
    outputs.mkdir(parents=True)
    inputs.mkdir()
    monkeypatch.setattr(sincronizar_estado, "ROOT", root)
    monkeypatch.setattr(sincronizar_estado, "DB_PATH", _eventos.DB_PATH)
    monkeypatch.setattr(sincronizar_estado, "OUTPUTS", outputs)
    monkeypatch.setattr(sincronizar_estado, "INPUTS", inputs)
    # as pastas falsas são de 2026-06-25: sem isso a regra de conteúdo antigo arquivaria
    # tudo. Os testes do arquivamento religam com monkeypatch.
    monkeypatch.setattr(sincronizar_estado, "DIAS_ARQUIVAR", 10**6)

    class Projeto:
        pass

    p = Projeto()
    p.root, p.outputs, p.inputs, p.banco = root, outputs, inputs, banco

    def video(stem, blocos=(1,), cortes=(), finalizados=(), polidos=(), thumbs=(),
              url=None, data="2026-06-25"):
        pasta = outputs / f"{data}_{stem}"
        for sub in ("cortes", "finalizados", "thumbs"):
            (pasta / sub).mkdir(parents=True, exist_ok=True)
        (pasta / "blocos.json").write_text(json.dumps({"blocos": [
            {"id": i, "tema": f"tema {i}", "titulo_sugerido": f"Título {i}",
             "texto_thumb": f"THUMB {i}", "score_potencial": 8, "duracao_minutos": 6.0}
            for i in blocos]}), encoding="utf-8")
        for i in cortes:
            (pasta / "cortes" / f"corte_{i:02d}_slug.mp4").touch()
        for i in finalizados:
            (pasta / "finalizados" / f"video_{i:02d}_slug.mp4").touch()
        for i in polidos:
            (pasta / "finalizados" / f"video_{i:02d}_slug_polido.mp4").touch()
        for t in thumbs:
            (pasta / "thumbs" / f"thumb_{t}.png").touch()
        if url:
            (inputs / f"{stem}.url").write_text(url + "\n", encoding="utf-8")
        return pasta

    p.video = video
    return p
