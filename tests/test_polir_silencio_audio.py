"""04b_polir: silêncio só onde o áudio também está em silêncio (silencedetect).

Extrai do fonte (ast) só constantes e funções puras; sem ffmpeg, sem API.
"""
import ast
from pathlib import Path

FONTE = Path(__file__).parent.parent / "scripts" / "04b_polir.py"
NOMES_CONST = {"GAP_SILENCIO_S", "MARGEM_SILENCIO_S", "RUIDO_SILENCIO_DB",
               "SILENCIO_AUDIO_S", "PROTECAO_INICIO_S"}
NOMES_FUNC = {"parse_silencedetect", "detectar_silencios"}


def carregar():
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    corpo = []
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in NOMES_FUNC:
            corpo.append(no)
        elif isinstance(no, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in NOMES_CONST for t in no.targets):
            corpo.append(no)
    ns = {}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), str(FONTE), "exec"), ns)
    return ns


NS = carregar()
parse = NS["parse_silencedetect"]
detectar = NS["detectar_silencios"]
M = NS["MARGEM_SILENCIO_S"]


def pal(*pares):
    return [{"start": s, "end": e, "word": "x"} for s, e in pares]


# --- parse_silencedetect ---

def test_parse_pares_start_end():
    err = ("[silencedetect @ 0x1] silence_start: 10.5\n"
           "[silencedetect @ 0x1] silence_end: 14.25 | silence_duration: 3.75\n"
           "[silencedetect @ 0x1] silence_start: 40\n"
           "[silencedetect @ 0x1] silence_end: 42 | silence_duration: 2\n")
    assert parse(err, 100.0) == [(10.5, 14.25), (40.0, 42.0)]


def test_parse_start_sem_end_vai_ate_a_duracao():
    err = ("silence_start: 5\nsilence_end: 7 | silence_duration: 2\n"
           "silence_start: 90.5\n")
    assert parse(err, 120.0) == [(5.0, 7.0), (90.5, 120.0)]


def test_parse_start_negativo_vira_zero():
    err = "silence_start: -0.02\nsilence_end: 3.1 | silence_duration: 3.1\n"
    assert parse(err, 50.0) == [(0.0, 3.1)]


def test_parse_sem_silencio():
    assert parse("size=N/A time=00:01:00 speed=500x\n", 60.0) == []


# --- detectar_silencios ---

def test_gap_sem_silencio_de_audio_nao_corta():
    assert detectar(pal((0, 40), (50, 60)), []) == []


def test_gap_curto_ignorado_mesmo_com_audio_mudo():
    # gap de 3.0s (nao > GAP_SILENCIO_S)
    assert detectar(pal((0, 40), (43, 60)), [(40, 43)]) == []


def test_silencio_parcial_so_interseccao_com_margens():
    # gap 40..50; audio mudo 43..49 -> interseção 43..49 -> 43.3..48.7
    r = detectar(pal((0, 40), (50, 60)), [(43, 49)])
    assert len(r) == 1
    assert r[0]["t_inicio"] == round(43 + M, 3)
    assert r[0]["t_fim"] == round(49 - M, 3)


def test_silencio_de_audio_estendendo_alem_do_gap_e_recortado():
    r = detectar(pal((0, 40), (50, 60)), [(30, 70)])
    assert (r[0]["t_inicio"], r[0]["t_fim"]) == (round(40 + M, 3), round(50 - M, 3))


def test_silencio_curto_ignorado():
    # interseção de 1.0s < SILENCIO_AUDIO_S (1.5)
    assert detectar(pal((0, 40), (50, 60)), [(44, 45)]) == []


def test_dois_trechos_no_mesmo_gap():
    r = detectar(pal((0, 40), (60, 70)), [(41, 45), (50, 56)])
    assert [(i["t_inicio"], i["t_fim"]) for i in r] == [
        (round(41 + M, 3), round(45 - M, 3)),
        (round(50 + M, 3), round(56 - M, 3))]


def test_protecao_dos_30s_iniciais():
    # gap 10..20 totalmente mudo, dentro dos 30s iniciais
    assert detectar(pal((0, 10), (20, 30)), [(10, 20)]) == []
    # gap logo depois dos 30s: corta
    assert len(detectar(pal((0, 31), (41, 50)), [(31, 41)])) == 1
