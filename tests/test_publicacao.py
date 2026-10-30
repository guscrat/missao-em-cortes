"""_publicacao: lista de publicação manual (só aprovados, por score, com agenda)."""
import json
from datetime import date, datetime

import pytest

import _cobertura
import _publicacao as pub


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch, banco):
    """Nunca lê o state/ real: canal.json e banco falsos (vazios)."""
    monkeypatch.setattr(_cobertura, "CANAL_JSON", tmp_path / "canal.json")


def _pasta(tmp_path, revisao, blocos, finais):
    pasta = tmp_path / "2026-10-22_renan_x"
    (pasta / "finalizados").mkdir(parents=True)
    (pasta / "thumbs").mkdir()
    (pasta / "revisao.json").write_text(json.dumps(revisao), encoding="utf-8")
    (pasta / "blocos.json").write_text(json.dumps({"blocos": blocos}), encoding="utf-8")
    for nome in finais:
        (pasta / "finalizados" / nome).touch()
    partes = []
    for b in blocos:
        partes += ["=" * 70, f"VÍDEO {b['id']:02d} — x", "=" * 70,
                   f"TÍTULO (5 chars):", f"Título {b['id']}", "", "-" * 70, "DESCRIÇÃO:", "-" * 70,
                   f"Desc {b['id']}", "-" * 70, "TAGS (x):", "-" * 70, "a, b", ""]
    (pasta / "descricoes.txt").write_text("\n".join(partes), encoding="utf-8")
    return pasta


def _bloco(bid, score):
    return {"id": bid, "score_potencial": score, "duracao_minutos": 7.0,
            "titulo_sugerido": f"sug {bid}"}


def test_aprovados_ordem_de_score_e_so_aprovados(tmp_path):
    pasta = _pasta(tmp_path,
                   {"01": {"status": "aprovado", "thumb": "thumb_01_a.png"},
                    "02": {"status": "descartado"},
                    "03": {"status": "aprovado", "thumb": "thumb_03_b.png"},
                    "04": {"status": "aprovado"}},                 # sem vídeo final: fica fora
                   [_bloco(1, 7), _bloco(2, 9), _bloco(3, 9), _bloco(4, 10)],
                   ["video_01_a_polido.mp4", "video_01_a_polido_legendado.mp4",
                    "video_02_b.mp4", "video_03_c.mp4"])
    lista = pub.aprovados(pasta)
    assert [x["id"] for x in lista] == [3, 1]
    assert lista[1]["video"].name == "video_01_a_polido_legendado.mp4"
    assert lista[0]["titulo"] == "Título 3" and lista[0]["tags"] == ["a", "b"]


def test_agenda_1_por_dia_e_2_so_quando_pedido():
    manha = datetime(2026, 10, 22, 9)
    noite = datetime(2026, 10, 22, 20)
    assert pub.agenda(2, manha) == [date(2026, 10, 22), date(2026, 10, 23)]
    assert pub.agenda(3, noite) == [date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 25)]
    assert pub.agenda(3, noite, por_dia=2) == [date(2026, 10, 23), date(2026, 10, 23), date(2026, 10, 24)]


def test_gerar_sem_aprovados_nao_grava(tmp_path):
    pasta = _pasta(tmp_path, {"01": {"status": "descartado"}}, [_bloco(1, 5)], ["video_01_a.mp4"])
    assert pub.gerar(pasta) == (None, [])
    assert not (pasta / "publicacao.txt").exists()


def test_gerar_escreve_lista(tmp_path):
    pasta = _pasta(tmp_path, {"01": {"status": "aprovado", "thumb": "thumb_01_a.png"}},
                   [_bloco(1, 8)], ["video_01_a_polido_legendado.mp4"])
    caminho, lista = pub.gerar(pasta, datetime(2026, 10, 22, 9))
    texto = caminho.read_text(encoding="utf-8")
    assert "qui 22/10 18h · VÍDEO 01 · score 8" in texto
    assert "finalizados/video_01_a_polido_legendado.mp4" in texto
    assert "thumbs/thumb_01_a.png" in texto and "Título 1" in texto and "a, b" in texto


def test_sem_revisao_lista_vazia(tmp_path):
    pasta = tmp_path / "p"
    pasta.mkdir()
    assert pub.aprovados(pasta) == []


def test_final_preferencias(tmp_path):
    f = tmp_path / "finalizados"
    f.mkdir()

    def com(*nomes):
        for p in f.iterdir():
            p.unlink()
        for n in nomes:
            (f / n).touch()
        return pub._final(tmp_path, 1)

    assert com("video_01_a.mp4", "video_01_a_polido.mp4").name == "video_01_a_polido.mp4"
    assert com("video_01_a.mp4", "video_01_a_polido.mp4",
               "video_01_a_legendado.mp4").name == "video_01_a_legendado.mp4"
    assert com("video_01_a_legendado.mp4",
               "video_01_a_polido_legendado.mp4").name == "video_01_a_polido_legendado.mp4"
    assert com("video_01_a.mp4").name == "video_01_a.mp4"
    assert com("video_02_b.mp4") is None                  # outro bloco não conta
    assert com() is None


def test_gerar_sem_thumb_e_titulo_cai_pro_sugerido(tmp_path):
    pasta = _pasta(tmp_path, {"01": {"status": "aprovado"}}, [_bloco(1, 8)], ["video_01_a.mp4"])
    (pasta / "descricoes.txt").unlink()
    caminho, lista = pub.gerar(pasta, datetime(2026, 10, 22, 20))
    texto = caminho.read_text(encoding="utf-8")
    assert "(sem thumb)" in texto and "sug 1" in texto
    assert "sex 23/10 18h" in texto                       # depois das 16h: começa amanhã


def test_gerar_lista_short_quando_existe(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "auditoria_aprovada", lambda: True)
    pasta = _pasta(tmp_path, {"01": {"status": "aprovado", "thumb": "thumb_01_a.png"},
                              "02": {"status": "aprovado"}},
                   [_bloco(1, 8), _bloco(2, 7)], ["video_01_a.mp4", "video_02_b.mp4"])
    (pasta / "shorts").mkdir()
    (pasta / "shorts" / "shorts.json").write_text(
        json.dumps({"01": {"arquivo": "short_01_x.mp4"}}), encoding="utf-8")
    caminho, _ = pub.gerar(pasta, datetime(2026, 10, 22, 9))
    texto = caminho.read_text(encoding="utf-8")
    assert "SHORT:   shorts/short_01_x.mp4 (sobe pela API)" in texto and "SHORT:   (sem Short)" in texto


def test_agenda_continua_depois_do_ultimo_agendado():
    manha = datetime(2026, 10, 22, 9)
    assert pub.agenda(2, manha, date(2026, 10, 25)) == [date(2026, 10, 26), date(2026, 10, 27)]
    assert pub.agenda(1, manha, date(2026, 10, 1)) == [date(2026, 10, 22)]   # já passou


def test_ultimo_agendado_pega_o_maior_entre_canal_e_banco(tmp_path, monkeypatch, banco):
    from _eventos import upsert_bloco
    canal = tmp_path / "canal.json"
    monkeypatch.setattr(_cobertura, "CANAL_JSON", canal)
    assert pub.ultimo_agendado() is None
    canal.write_text('{"ultimo_longo": "2026-10-25T18:00:00-03:00"}', encoding="utf-8")
    assert pub.ultimo_agendado() == date(2026, 10, 25)
    upsert_bloco("v", 1, status="agendado", publish_at="2026-10-27T18:00:00-03:00",
                 forcar_status=True)
    assert pub.ultimo_agendado() == date(2026, 10, 27)
    canal.write_text("lixo", encoding="utf-8")
    assert pub.ultimo_agendado() == date(2026, 10, 27)


def test_gerar_sem_auditoria_omite_short_e_avisa(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "auditoria_aprovada", lambda: False)
    pasta = _pasta(tmp_path, {"01": {"status": "aprovado"}}, [_bloco(1, 8)], ["video_01_a.mp4"])
    (pasta / "shorts").mkdir()
    (pasta / "shorts" / "shorts.json").write_text(
        json.dumps({"01": {"arquivo": "short_01_x.mp4"}}), encoding="utf-8")
    caminho, _ = pub.gerar(pasta, datetime(2026, 10, 22, 9))
    texto = caminho.read_text(encoding="utf-8")
    assert "SHORT:" not in texto and "short_01_x.mp4" not in texto
    assert "Só os vídeos LONGOS" in texto and "sobem pela API (09" not in texto
    assert "ARQUIVO: finalizados/video_01_a.mp4" in texto


def test_gerar_com_auditoria_mantem_cabecalho_do_short(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "auditoria_aprovada", lambda: True)
    pasta = _pasta(tmp_path, {"01": {"status": "aprovado"}}, [_bloco(1, 8)], ["video_01_a.mp4"])
    texto = pub.gerar(pasta, datetime(2026, 10, 22, 9))[0].read_text(encoding="utf-8")
    assert "NÃO suba à mão" in texto and "SHORT:   (sem Short)" in texto
    assert "Só os vídeos LONGOS" not in texto


def _tres_aprovados(tmp_path):
    rev = {f"0{i}": {"status": "aprovado"} for i in (1, 2, 3)}
    return _pasta(tmp_path, rev, [_bloco(i, 9 - i) for i in (1, 2, 3)],
                  [f"video_0{i}_a.mp4" for i in (1, 2, 3)])


def _datas(caminho):
    import re
    return re.findall(r"^\w{3} (\d\d/\d\d) \d+h · VÍDEO", caminho.read_text(encoding="utf-8"), re.M)


def test_gerar_sem_modo_evento_3_aprovados_1_por_dia(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "modo_evento", lambda *_a, **_k: None)
    caminho, _ = pub.gerar(_tres_aprovados(tmp_path), datetime(2026, 10, 22, 9))
    assert _datas(caminho) == ["22/10", "23/10", "24/10"]


def test_gerar_com_modo_evento_3_aprovados_2_por_dia(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "modo_evento", lambda *_a, **_k: {"ate": date(2026, 10, 30)})
    caminho, _ = pub.gerar(_tres_aprovados(tmp_path), datetime(2026, 10, 22, 9))
    assert _datas(caminho) == ["22/10", "22/10", "23/10"]
