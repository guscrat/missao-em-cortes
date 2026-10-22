"""Step 11: agente revisor. Claude, ffmpeg e imagens mockados (nunca chama API paga)."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

import _paths

_spec = importlib.util.spec_from_file_location(
    "revisor", Path(__file__).parent.parent / "scripts" / "11_revisor.py")
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

OK = {"titulo_fiel": True, "titulo_problema": "", "thumb_ok": True, "thumb_problema": "",
      "tela_compartilhada": False, "tela_problema": "", "corte_sem_sentido": False,
      "sentido_problema": ""}
TITULO_RUIM = {**OK, "titulo_fiel": False, "titulo_problema": "não menciona Lula"}


# ── decisão (é do código, não do modelo) ───────────────────────────────────

def test_decidir_tudo_ok_aprova():
    assert rv.decidir(OK) == ("aprovado", None)


def test_decidir_junta_problemas_de_titulo_e_thumb():
    ruim = {**OK, "titulo_fiel": False, "titulo_problema": "inverte o sentido",
            "thumb_ok": False, "thumb_problema": ""}
    assert rv.decidir(ruim) == ("quarentena", "título: inverte o sentido; thumb: reprovada")


def test_decidir_conteudo_ruim_descarta_mesmo_com_titulo_ruim():
    ruim = {**TITULO_RUIM, "tela_compartilhada": True, "corte_sem_sentido": True,
            "sentido_problema": "termina no meio da frase"}
    assert rv.decidir(ruim) == ("descartado", "tela compartilhada: maior parte do corte; "
                                              "corte sem sentido: termina no meio da frase")
    assert not rv.precisa_editor(*rv.decidir(ruim)[:1], ruim)


def test_precisa_editor_so_com_titulo_reprovado():
    assert rv.precisa_editor("quarentena", TITULO_RUIM)
    assert not rv.precisa_editor("quarentena", {**OK, "thumb_ok": False})
    assert not rv.precisa_editor("quarentena", None)   # recusa: revisar à mão


def test_decidir_recusa_vira_quarentena():
    status, motivo = rv.decidir(None)
    assert status == "quarentena" and "à mão" in motivo


def test_montar_conteudo_ordem_e_aviso_sem_thumb():
    c = rv.montar_conteudo("T", "THUMB", "fala", None, ["f1", "f2"])
    assert [x["type"] for x in c] == ["text", "image", "image", "text"]
    assert "SEM THUMB" in c[-1]["text"] and "fala" in c[-1]["text"]
    c = rv.montar_conteudo("T", "THUMB", "fala", "th", ["f1"])
    assert c[1]["source"]["data"] == "th" and "SEM THUMB" not in c[-1]["text"]


def test_custo_opus():
    resp = types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=1_000_000,
                                                             output_tokens=100_000))
    assert rv.custo(resp) == (1_000_000, 100_000, pytest.approx(6.0))


# ── chamada ao Claude (cliente falso) ──────────────────────────────────────

class FakeClient:
    def __init__(self, respostas):
        self.respostas, self.chamadas = list(respostas), []
        fake = self

        class _Msgs:
            def create(self, **kw):
                fake.chamadas.append(kw)
                r = fake.respostas.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r
        self.beta = types.SimpleNamespace(messages=_Msgs())


def _resp(checagens=OK, stop="end_turn"):
    return types.SimpleNamespace(
        stop_reason=stop, model="claude-opus-5-5",
        content=[types.SimpleNamespace(type="text", text=json.dumps(checagens))],
        usage=types.SimpleNamespace(input_tokens=5000, output_tokens=1000))


def test_chamar_claude_pede_json_estruturado_e_fallback():
    cli = FakeClient([_resp()])
    checagens, _ = rv.chamar_claude(cli, [{"type": "text", "text": "x"}])
    assert checagens == OK
    kw = cli.chamadas[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["schema"] is rv.SCHEMA
    assert kw["extra_body"] == {"fallbacks": "default"}
    assert "thinking" not in kw and "temperature" not in kw   # 400 no opus 5.5


def test_chamar_claude_recusa():
    checagens, _ = rv.chamar_claude(FakeClient([_resp(stop="refusal")]), [])
    assert checagens is None


# ── main() ponta a ponta ───────────────────────────────────────────────────

@pytest.fixture
def video(projeto, monkeypatch):
    pasta = projeto.video("v", blocos=[1, 2, 3], thumbs=["01_a"])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    for b in blocos["blocos"]:
        b["timestamp_inicio"], b["timestamp_fim"] = "00:00:10", "00:00:20"
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    (pasta / "words.json").write_text(json.dumps({"words": [
        {"word": "dentro", "start": 12.0, "end": 12.3},
        {"word": "fora", "start": 40.0, "end": 40.3}]}), encoding="utf-8")
    for i in (1, 2):
        (pasta / "cortes" / f"corte_{i:02d}_slug.mp4").touch()
    (pasta / "cortes" / "corte_01_slug_polido.mp4").touch()
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    monkeypatch.setattr(rv, "frames_b64", lambda v: ["f"] * 6)
    monkeypatch.setattr(rv, "ler_imagem_b64", lambda p: "thumb")
    monkeypatch.setattr(rv._editor, "refazer_artes", lambda pasta, bid, thumb: [])
    cli = FakeClient([_resp(), _resp({**OK, "thumb_ok": False, "thumb_problema": "sem rosto"})])
    fake_anthropic = types.SimpleNamespace(Anthropic=lambda: cli, APIError=RuntimeError)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    return pasta, cli, projeto.banco


def test_dry_run_nao_chama_api(video, capsys):
    pasta, cli, _ = video
    assert rv.main([str(pasta), "--dry-run"]) == 0
    assert cli.chamadas == [] and "2 bloco(s)" in capsys.readouterr().out   # bloco 3 sem corte


def test_main_aprova_e_poe_em_quarentena(video):
    pasta, cli, banco = video
    assert rv.main([str(pasta)]) == 0
    blocos = {b["bloco_id"]: b for b in banco("SELECT bloco_id, status, motivo FROM blocos")}
    assert blocos[1]["status"] == "aprovado" and blocos[1]["motivo"] is None
    assert blocos[2]["status"] == "quarentena" and "sem rosto" in blocos[2]["motivo"]
    # bloco 1 com thumb; bloco 2 sem → aviso no prompt
    texto_1 = cli.chamadas[0]["messages"][0]["content"][-1]["text"]
    texto_2 = cli.chamadas[1]["messages"][0]["content"][-1]["text"]
    assert "SEM THUMB" not in texto_1 and "SEM THUMB" in texto_2
    assert "dentro" in texto_1 and "fora" not in texto_1             # só o trecho do bloco
    assert "TÍTULO DO YOUTUBE: Título 1" in texto_1                    # fallback: blocos.json
    rev = json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))
    assert rev["02"]["status"] == "quarentena" and rev["01"]["thumb"] == "thumb_01_a.png"
    ev = banco("SELECT agente, custo_usd FROM eventos WHERE etapa='11_revisor' AND status='llm'")
    assert len(ev) == 2 and {e["agente"] for e in ev} == {"revisor"}
    assert ev[0]["custo_usd"] == pytest.approx(5000 / 1e6 * 4 + 1000 / 1e6 * 20)


def test_main_usa_titulo_editado_no_descricoes(video):
    pasta, cli, _ = video
    (pasta / "descricoes.txt").write_text(
        "=" * 70 + "\nVÍDEO 01 — x\n" + "=" * 70 + "\nTÍTULO (9 chars):\nEditado!\n\n"
        + "-" * 70 + "\nDESCRIÇÃO:\n" + "-" * 70 + "\ndesc\n" + "-" * 70
        + "\nTAGS (x):\n" + "-" * 70 + "\na, b\n", encoding="utf-8")
    rv.main([str(pasta), "--bloco=1"])
    assert "TÍTULO DO YOUTUBE: Editado!" in cli.chamadas[0]["messages"][0]["content"][-1]["text"]


def test_main_nao_mexe_em_agendado(video):
    pasta, cli, banco = video
    rv.upsert_bloco("v", 1, status="agendado", forcar_status=True)
    rv.main([str(pasta)])
    assert len(cli.chamadas) == 1
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "agendado"


def test_main_erro_da_api_conta_falha_e_segue(video):
    pasta, cli, banco = video
    cli.respostas = [RuntimeError("500"), _resp()]
    assert rv.main([str(pasta)]) == 1
    assert banco("SELECT status FROM blocos WHERE bloco_id=2")[0]["status"] == "aprovado"
    assert banco("SELECT count(*) n FROM eventos WHERE etapa='11_revisor' AND status='falha'")[0]["n"] == 1


def test_main_sem_words_json_falha_alto(video):
    pasta, _, _ = video
    (pasta / "words.json").unlink()
    with pytest.raises(SystemExit):
        rv.main([str(pasta)])


def test_escolher_video_ignora_polido(video):
    pasta, _, _ = video
    assert rv.escolher_video(pasta, "01").name == "corte_01_slug.mp4"
    assert rv.escolher_video(pasta, "03") is None


def test_main_recusa_do_modelo_vira_quarentena(video):
    pasta, cli, banco = video
    cli.respostas = [_resp(stop="refusal")]
    assert rv.main([str(pasta), "--bloco=1"]) == 0
    row = banco("SELECT status, motivo FROM blocos WHERE bloco_id=1")[0]
    assert row["status"] == "quarentena" and "recusou" in row["motivo"]


def test_main_bloco_filtra_so_um(video):
    pasta, cli, _ = video
    rv.main([str(pasta), "--bloco=2"])
    assert len(cli.chamadas) == 1
    assert list(json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))) == ["02"]


def test_09_e_11_usam_o_mesmo_parser():
    import _descricoes
    spec = importlib.util.spec_from_file_location(
        "up09", Path(__file__).parent.parent / "scripts" / "09_upload.py")
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    assert up.ler_descricoes is _descricoes.ler_descricoes is rv.ler_descricoes


def test_chamar_claude_sem_texto_vira_erro_tratavel():
    resp = _resp()
    resp.content, resp.stop_reason = [], "max_tokens"
    with pytest.raises(json.JSONDecodeError):
        rv.chamar_claude(FakeClient([resp]), [])


# ── loop editor → revisor (regra de produto da quarentena) ─────────────────

def _edit(titulo="Novo título fiel", thumb="TEXTO NOVO", stop="end_turn"):
    return types.SimpleNamespace(
        stop_reason=stop, model="claude-opus-5-5",
        content=[types.SimpleNamespace(type="text", text=json.dumps(
            {"titulo": titulo, "texto_thumb": thumb, "mudanca": "tirei o Lula"}))],
        usage=types.SimpleNamespace(input_tokens=2000, output_tokens=300))


def _desc_txt(pasta, titulos):
    partes = []
    for bid, t in titulos.items():
        partes += ["=" * 70, f"VÍDEO {bid:02d} — x", "=" * 70, "", f"TÍTULO ({len(t)} chars):", t,
                   "", "-" * 70, "DESCRIÇÃO:", "-" * 70, "desc", "-" * 70, "TAGS (x):", "-" * 70,
                   "a, b", ""]
    (pasta / "descricoes.txt").write_text("\n".join(partes), encoding="utf-8")


def test_titulo_reprovado_editor_reescreve_e_aprova(video):
    pasta, cli, banco = video
    _desc_txt(pasta, {1: "Título exagerado", 2: "Outro"})
    cli.respostas = [_resp(TITULO_RUIM), _edit(), _resp()]
    assert rv.main([str(pasta), "--bloco=1"]) == 0
    row = banco("SELECT status, motivo FROM blocos WHERE bloco_id=1")[0]
    assert row == {"status": "aprovado", "motivo": None}
    # editor recebeu o problema; revisor reavaliou com o título novo
    assert "não menciona Lula" in cli.chamadas[1]["messages"][0]["content"]
    assert "TÍTULO DO YOUTUBE: Novo título fiel" in cli.chamadas[2]["messages"][0]["content"][-1]["text"]
    # gravado no txt (só o bloco 1) e no blocos.json, com o original guardado
    desc = rv.ler_descricoes((pasta / "descricoes.txt").read_text(encoding="utf-8"))
    assert desc[1]["titulo"] == "Novo título fiel" and desc[2]["titulo"] == "Outro"
    b1 = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"][0]
    assert b1["titulo_sugerido"] == "Novo título fiel" and b1["texto_thumb"] == "TEXTO NOVO"
    assert b1["titulo_original"] == "Título 1"
    rev = json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))["01"]
    assert rev["reescritas"][0]["titulo"] == "Título exagerado"
    ev = banco("SELECT agente, custo_usd FROM eventos WHERE status='llm'")
    assert [e["agente"] for e in ev] == ["revisor", "editor", "revisor"]
    assert ev[1]["custo_usd"] == pytest.approx(2000 / 1e6 * 4 + 300 / 1e6 * 20)


def test_titulo_reprova_nas_2_reescritas_chama_o_gu(video, monkeypatch, capsys):
    pasta, cli, banco = video
    import _eventos
    tid = _eventos.nova_tarefa("loop editor")
    monkeypatch.setenv("MISSAO_TAREFA", str(tid))
    cli.respostas = [_resp(TITULO_RUIM), _edit("T2"), _resp(TITULO_RUIM),
                     _edit("T3"), _resp(TITULO_RUIM)]
    assert rv.main([str(pasta), "--bloco=1"]) == 0
    assert cli.respostas == []                             # 3 revisões + 2 reescritas, e para
    row = banco("SELECT status, motivo FROM blocos WHERE bloco_id=1")[0]
    assert row["status"] == "quarentena" and "decisão do Gu" in row["motivo"]
    assert "DECISÃO DO GU" in capsys.readouterr().out
    pend = banco(f"SELECT decisao_pendente FROM tarefas WHERE id={tid}")[0]["decisao_pendente"]
    assert "bloco 01" in pend
    # a 2ª reescrita viu a 1ª tentativa reprovada
    pedido = cli.chamadas[3]["messages"][0]["content"]
    assert "REPROVADO: T2" in pedido and "TENTATIVA 1 (também reprovada): Título 1" in pedido


def test_conteudo_ruim_descarta_sem_editor(video):
    pasta, cli, banco = video
    cli.respostas = [_resp({**TITULO_RUIM, "tela_compartilhada": True})]
    rv.main([str(pasta), "--bloco=1"])
    assert len(cli.chamadas) == 1
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "descartado"


def test_sem_editor_so_poe_em_quarentena(video):
    pasta, cli, banco = video
    cli.respostas = [_resp(TITULO_RUIM)]
    rv.main([str(pasta), "--bloco=1", "--sem-editor"])
    assert len(cli.chamadas) == 1
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "quarentena"


def test_editor_recusa_fica_em_quarentena(video):
    pasta, cli, banco = video
    cli.respostas = [_resp(TITULO_RUIM), _edit(stop="refusal")]
    rv.main([str(pasta), "--bloco=1"])
    row = banco("SELECT status, motivo FROM blocos WHERE bloco_id=1")[0]
    assert row["status"] == "quarentena" and "editor não conseguiu" in row["motivo"]
