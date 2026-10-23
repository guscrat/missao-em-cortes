"""dia_d.py: checagem do dia D da auditoria, verificação e checklist do Studio (tudo mockado)."""
import json

import pytest

import _paths
import dia_d

UPLOAD = "https://www.googleapis.com/auth/youtube.upload"


# ── credenciais ────────────────────────────────────────────────────────────

def _secrets(tmp_path, projeto="missao-em-cortes-publisher", token_client="C1", escopos=(UPLOAD,),
             leitura=True):
    s = tmp_path / "secrets"
    s.mkdir()
    (s / "youtube_client_secret.json").write_text(
        json.dumps({"installed": {"client_id": "C1", "project_id": projeto}}), encoding="utf-8")
    if token_client:
        (s / "youtube_token.json").write_text(
            json.dumps({"client_id": token_client, "scopes": list(escopos)}), encoding="utf-8")
    if leitura:
        (s / "analytics_token.json").write_text("{}", encoding="utf-8")
    return s


def test_credenciais_ok(tmp_path):
    assert all(ok for ok, _ in dia_d.checar_credenciais(_secrets(tmp_path)))


@pytest.mark.parametrize("kw, trecho", [
    ({"projeto": "missao-em-cortes-analytics"}, "não do missao-em-cortes-publisher"),
    ({"token_client": "OUTRO"}, "outro client"),
    ({"escopos": ("https://www.googleapis.com/auth/youtube.readonly",)}, "sem o escopo"),
    ({"token_client": None}, "falta youtube_token.json"),
    ({"leitura": False}, "falta analytics_token.json"),
])
def test_credenciais_com_problema(tmp_path, kw, trecho):
    res = dia_d.checar_credenciais(_secrets(tmp_path, **kw))
    assert any(not ok and trecho in msg for ok, msg in res)


def test_credenciais_sem_client(tmp_path):
    (tmp_path / "s").mkdir()
    res = dia_d.checar_credenciais(tmp_path / "s")
    assert not res[0][0] and "falta youtube_client_secret.json" in res[0][1]


# ── veredito / verificar ───────────────────────────────────────────────────

@pytest.mark.parametrize("status, nivel", [
    ({"privacyStatus": "private", "publishAt": "2026-10-29T21:00:00Z", "uploadStatus": "processed"}, "OK"),
    ({"privacyStatus": "public", "uploadStatus": "processed"}, "OK"),
    ({"privacyStatus": "private", "uploadStatus": "processed"}, "ALERTA"),   # trava da auditoria
    ({"privacyStatus": "unlisted"}, "ALERTA"),
    ({"privacyStatus": "private", "uploadStatus": "rejected", "rejectionReason": "duplicate"}, "FALHA"),
])
def test_veredito(status, nivel):
    assert dia_d.veredito({"status": status})[0] == nivel


def test_veredito_privado_sem_data_manda_voltar_a_flag():
    assert "volte a flag pra false" in dia_d.veredito({"status": {"privacyStatus": "private"}})[1]


class _YT:
    def __init__(self, itens):
        self.itens, self.pedidos = itens, []

    def videos(self):
        fake = self

        class _V:
            def list(self, part, id):
                fake.pedidos.append((part, id))

                class _R:
                    def execute(self):
                        return {"items": fake.itens}
                return _R()
        return _V()


def test_verificar(banco, capsys):
    ok = {"id": "A", "snippet": {"title": "Longo"},
          "status": {"privacyStatus": "private", "publishAt": "2026-10-29T21:00:00Z"}}
    assert dia_d.verificar(["A"], _YT([ok])) == 0
    assert dia_d.verificar(["A", "B"], _YT([ok])) == 1          # B não existe no canal
    out = capsys.readouterr().out
    assert "[OK] A" in out and "[FALHA] B" in out and "studio.youtube.com/video/A/edit" in out
    assert banco("SELECT count(*) n FROM eventos WHERE etapa='dia_d'")[0]["n"] == 3


# ── relacionados ───────────────────────────────────────────────────────────

def test_relacionados_lista_e_marca(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(_paths, "OUTPUTS", tmp_path)
    pasta = tmp_path / "2026-10-22_v"
    pasta.mkdir()
    reg = {"01": {"youtube_id": "S1", "longo_id": "L1", "titulo": "T1",
                  "publish_at": "2026-10-22T20:00:00-03:00", "relacionado_ok": False},
           "02": {"youtube_id": "S2", "longo_id": "L2", "titulo": "T2",
                  "publish_at": "2026-10-23T12:00:00-03:00", "relacionado_ok": False}}
    (pasta / "youtube_shorts.json").write_text(json.dumps(reg), encoding="utf-8")
    dia_d.relacionados()
    out = capsys.readouterr().out
    assert "2 Short(s) sem vídeo relacionado" in out and "youtu.be/L1" in out
    dia_d.relacionados({"S1"})
    salvo = json.loads((pasta / "youtube_shorts.json").read_text(encoding="utf-8"))
    assert salvo["01"]["relacionado_ok"] is True and salvo["02"]["relacionado_ok"] is False
    assert "1 Short(s) sem vídeo relacionado" in capsys.readouterr().out


# ── candidato ao teste ─────────────────────────────────────────────────────

def _aprovado(projeto, stem, url="https://youtu.be/fonte"):
    pasta = projeto.video(stem, blocos=[1, 2], finalizados=[1, 2], data="2026-10-22")
    (pasta / "revisao.json").write_text(json.dumps(
        {"01": {"status": "aprovado"}, "02": {"status": "aprovado"}}), encoding="utf-8")
    partes = []
    for i in (1, 2):
        partes += ["=" * 70, f"VÍDEO {i:02d} — tema", "=" * 70, "", "TÍTULO (5 chars):", f"T {i}", "",
                   "-" * 70, "DESCRIÇÃO:", "-" * 70, "", "Resumo.", "",
                   f"📺 Conteúdo original: {url}", "", "-" * 70, "TAGS (x):", "-" * 70, "a", ""]
    (pasta / "descricoes.txt").write_text("\n".join(partes), encoding="utf-8")
    return pasta


def test_candidato_pula_o_que_ja_esta_no_youtube(projeto, monkeypatch):
    from _eventos import upsert_bloco
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    _aprovado(projeto, "v")
    upsert_bloco("v", 1, status="agendado", forcar_status=True, youtube_id="X")
    assert dia_d.candidato_teste() == {"stem": "v", "id": 2, "titulo": "T 2"}
    upsert_bloco("v", 2, status="agendado", forcar_status=True)
    assert dia_d.candidato_teste() is None


def test_candidato_sem_credito_nao_serve(projeto, monkeypatch):
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    _aprovado(projeto, "v", url="[COLAR URL DA LIVE AQUI]")
    assert dia_d.candidato_teste() is None


def test_main_comando_invalido():
    with pytest.raises(SystemExit):
        dia_d.main(["publicar"])


# ── checar ponta a ponta (subprocess mockado) ──────────────────────────────

@pytest.fixture
def checar_cenario(projeto, monkeypatch, tmp_path):
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    monkeypatch.setattr(dia_d, "SECRETS", _secrets(tmp_path))
    monkeypatch.setattr(dia_d.up, "COTA_PATH", tmp_path / "state" / "cota.json")
    chamadas = []

    def rodar(*args):
        chamadas.append(args)
        return 0
    monkeypatch.setattr(dia_d, "_rodar_09", rodar)
    return projeto, chamadas


def test_checar_com_candidato_roda_os_dois_dry_runs(checar_cenario, capsys, banco):
    projeto, chamadas = checar_cenario
    _aprovado(projeto, "v")
    assert dia_d.checar() == 0
    assert chamadas == [("v", "--bloco=1", "--max=1", "--dry-run", "--como-aprovada"),
                        ("todos", "--shorts", "--dry-run", "--como-aprovada")]
    assert "PRONTO pro dia D" in capsys.readouterr().out
    assert banco("SELECT status FROM eventos WHERE etapa='dia_d'")[0]["status"] == "ok"


def test_checar_sem_candidato_testa_com_o_primeiro_short(checar_cenario, capsys):
    _, chamadas = checar_cenario
    assert dia_d.checar() == 0
    assert chamadas[0] == ("todos", "--shorts", "--max=1", "--dry-run", "--como-aprovada")
    assert "o teste é o 1º Short da fila" in capsys.readouterr().out


def test_checar_bloqueia_se_dry_run_falha(checar_cenario, monkeypatch, capsys, banco):
    projeto, _ = checar_cenario
    _aprovado(projeto, "v")
    monkeypatch.setattr(dia_d, "_rodar_09", lambda *a: 1 if "--shorts" in a else 0)
    assert dia_d.checar() == 1
    assert "NÃO PRONTO: dry-run dos Shorts falhou" in capsys.readouterr().out
    assert banco("SELECT status FROM eventos WHERE etapa='dia_d'")[0]["status"] == "aviso"


def test_checar_bloqueia_sem_client_secret(checar_cenario, monkeypatch, tmp_path, capsys):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.setattr(dia_d, "SECRETS", vazio)
    assert dia_d.checar() == 1
    assert "falta youtube_client_secret.json" in capsys.readouterr().out


def test_rodar_09_usa_subprocess_mockado(monkeypatch):
    visto = {}

    class _R:
        returncode = 3
    monkeypatch.setattr(dia_d.subprocess, "run", lambda cmd, cwd: visto.update(cmd=cmd) or _R())
    assert dia_d._rodar_09("todos", "--shorts") == 3
    assert visto["cmd"][1].endswith("09_upload.py") and visto["cmd"][-2:] == ["todos", "--shorts"]


def test_main_despacha_checar_verificar_e_relacionados(monkeypatch):
    monkeypatch.setattr(dia_d, "checar", lambda: 7)
    monkeypatch.setattr(dia_d, "verificar", lambda ids: ids)
    monkeypatch.setattr(dia_d, "relacionados", lambda feitos=None: feitos)
    assert dia_d.main([]) == 7 and dia_d.main(["checar"]) == 7
    assert dia_d.main(["verificar", "A", "B"]) == ["A", "B"]
    assert dia_d.main(["relacionados", "--feito=S1,S2"]) == {"S1", "S2"}


def test_verificar_sem_ids_sai():
    with pytest.raises(SystemExit):
        dia_d.verificar([])
