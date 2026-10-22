"""_paths.auditoria_aprovada: só true literal libera; o resto trava."""
import pytest

import _paths


@pytest.mark.parametrize("conteudo, esperado", [
    ('{"auditoria_aprovada": true}', True),
    ('{"auditoria_aprovada": false}', False),
    ('{}', False),
    ('{"auditoria_aprovada": "true"}', False),
    ('{"auditoria_aprovada": 1}', False),
    ('{"auditoria_aprovada": null}', False),
    ('nao e json', False),
    ('[1, 2]', False),
])
def test_auditoria_aprovada(tmp_path, monkeypatch, conteudo, esperado):
    f = tmp_path / "upload.json"
    f.write_text(conteudo, encoding="utf-8")
    monkeypatch.setattr(_paths, "UPLOAD_JSON", f)
    assert _paths.auditoria_aprovada() is esperado


def test_auditoria_arquivo_ausente(tmp_path, monkeypatch):
    monkeypatch.setattr(_paths, "UPLOAD_JSON", tmp_path / "nao_existe.json")
    assert _paths.auditoria_aprovada() is False
