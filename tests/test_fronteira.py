"""_fronteira: pontos de corte naturais pelos tempos das palavras. Puro, sem I/O."""
import _fronteira as fr


def P(*itens):
    """P(("oi", 0, .3), ...) -> palavras."""
    return [{"word": w, "start": s, "end": e} for w, s, e in itens]


# ── fim / início ───────────────────────────────────────────────────────────

def test_termina_frase_pontuacao_forte_sim_reticencias_nao():
    assert fr.termina_frase("fim.") and fr.termina_frase("sério?") and fr.termina_frase('"fim!"')
    assert not fr.termina_frase("então...") and not fr.termina_frase("então…")
    assert not fr.termina_frase("então,") and not fr.termina_frase("então")


def test_sem_pontuacao():
    assert fr.sem_pontuacao("então") and fr.sem_pontuacao("2026")
    assert not fr.sem_pontuacao("então,") and not fr.sem_pontuacao("então...")
    assert not fr.sem_pontuacao("")


def test_virgula_com_pausa_nao_e_fim():
    assert not fr.eh_fim(P(("oi,", 0, .5), ("tudo", 3, 3.5)), 0)


def test_reticencias_com_pausa_nao_sao_fim():
    assert not fr.eh_fim(P(("é...", 0, .5), ("assim", 4, 4.5)), 0)


def test_ponto_com_pausa_curta_nao_e_fim_e_com_pausa_e():
    assert not fr.eh_fim(P(("fim.", 0, .5), ("oi", .7, 1)), 0)
    assert fr.eh_fim(P(("fim.", 0, .5), ("oi", 1.1, 1.4)), 0)


def test_pausa_longa_sem_pontuacao_e_fim():
    assert fr.eh_fim(P(("fim", 0, .5), ("oi", 2.0, 2.3)), 0)
    assert not fr.eh_fim(P(("fim", 0, .5), ("oi", 1.0, 1.3)), 0)   # 0.5s sem ponto: não


def test_ultima_palavra_com_ponto_e_fim():
    assert fr.eh_fim(P(("fim.", 0, .5)), 0)


def test_eh_inicio():
    p = P(("a.", 0, .5), ("b", .6, 1), ("c,", 1.1, 1.5), ("d", 1.6, 2), ("e", 5, 5.5))
    assert fr.eh_inicio(p, 0)           # primeira palavra
    assert fr.eh_inicio(p, 1)           # anterior termina com ponto
    assert not fr.eh_inicio(p, 3)       # anterior termina com vírgula
    assert fr.eh_inicio(p, 4)           # anterior sem pontuação e pausa de 3s


# ── janela ─────────────────────────────────────────────────────────────────

def test_janela_sem_palavras_so_padding():
    assert fr.janela([], 10, 20) == (9.0, 22.0)
    assert fr.janela([], 0.5, 20) == (0.0, 22.0)


def test_janela_nao_vaza_palavra_vizinha():
    p = P(("antes", 9.0, 9.5), ("a", 10.0, 10.5), ("z.", 19.0, 19.5), ("depois", 20.5, 21.0))
    a, b = fr.janela(p, 10.0, 19.5)
    assert a >= 9.5 + fr.FOLGA_S - 1e-9           # não pega "antes"
    assert 19.5 <= b <= 20.5 - fr.FOLGA_S + 1e-9  # não pega "depois"


def test_janela_fim_no_meio_de_palavra_inclui_inteira():
    p = P(("a", 10.0, 10.5), ("longa", 19.0, 20.0), ("prox", 20.3, 20.6))
    a, b = fr.janela(p, 10.0, 19.5)
    assert 20.0 <= b <= 20.3


def test_janela_palavra_de_duracao_zero_no_fim_entra():
    # live do Renan, bloco 07: "Eu acho o seguinte, cara." — o whisper deu start == end
    # pro "cara." e o corte saía em "seguinte,"
    p = P(("seguinte,", 9741.45, 9741.71), ("cara.", 9742.43, 9742.43),
          ("Essa", 9743.05, 9743.25))
    a, b = fr.janela(p, 9741.45, 9742.43)
    assert 9742.43 < b <= 9743.05 - fr.FOLGA_S + 1e-9
    c = fr.checar(p, 9741.45, 9742.43)
    assert c["ultimas"].endswith("cara.") and c["fim_ok"]


def test_janela_varias_palavras_de_duracao_zero_seguidas_no_fim():
    p = P(("seguinte,", 10.0, 10.3), ("cara", 10.5, 10.5), ("mesmo.", 10.5, 10.5),
          ("Essa", 11.2, 11.4))
    a, b = fr.janela(p, 10.0, 10.5)
    assert 10.5 < b <= 11.2 - fr.FOLGA_S + 1e-9
    assert fr.checar(p, 10.0, 10.5)["ultimas"].endswith("mesmo.")


def test_janela_palavra_de_duracao_zero_no_inicio():
    p = P(("Oi.", 4.0, 4.3), ("Então", 5.0, 5.0), ("vamos", 5.0, 5.3), ("lá.", 5.4, 5.8),
          ("Fim", 7.0, 7.2))
    a, b = fr.janela(p, 5.0, 5.8)
    assert a >= 4.3 + fr.FOLGA_S - 1e-9 and a <= 5.0
    assert fr.checar(p, 5.0, 5.8)["primeiras"].startswith("Então")


def test_janela_palavra_zero_no_fim_sem_proxima_palavra():
    p = P(("fim", 1.0, 1.2), ("tchau.", 2.0, 2.0))
    a, b = fr.janela(p, 1.0, 2.0)
    assert b >= 2.0


# ── checar ─────────────────────────────────────────────────────────────────

def test_checar_ok():
    p = P(("Oi.", 0, .4), ("Começa", 1.0, 1.4), ("aqui", 1.5, 1.9), ("fim.", 2.0, 2.4),
          ("Outra", 5.0, 5.4))
    c = fr.checar(p, 1.0, 2.4)
    assert c["inicio_ok"] and c["fim_ok"] and c["ultimas"].endswith("fim.")


def test_checar_meio_de_frase():
    p = P(("Oi.", 0, .4), ("Começa", 1.0, 1.4), ("aqui", 1.5, 1.9), ("fim", 2.0, 2.4),
          ("e", 2.5, 2.7), ("segue.", 2.8, 3.2))
    c = fr.checar(p, 1.5, 2.4)
    assert not c["inicio_ok"] and not c["fim_ok"]


def test_checar_sem_palavras_ok():
    c = fr.checar([], 1, 5)
    assert c["inicio_ok"] and c["fim_ok"] and c["pausa_depois_s"] is None


# ── encaixar ───────────────────────────────────────────────────────────────

def _longa():
    # fins de frase em 100, 110 e 130
    return P(("x.", 98, 100), ("a", 101, 102), ("b.", 108, 110), ("c", 112, 113),
             ("d.", 128, 130), ("e", 132, 133))


def test_encaixar_leva_pro_ponto_natural():
    e = fr.encaixar(_longa(), 101.2, 109.0, 5)
    assert e["inicio"] == 101 and e["fim"] == 110 and e["inicio_ok"] and e["fim_ok"]


def test_encaixar_prefere_depois_em_empate():
    assert fr.ajustar_fim(_longa(), 105, 6) == 110      # 100 e 110 equidistantes


def test_encaixar_respeita_dur_min_e_dur_max():
    p = _longa()
    assert fr.encaixar(p, 101, 110, 30, dur_min=20)["fim"] == 130      # fim >= 121
    assert fr.encaixar(p, 101, 125, 30, dur_max=10)["fim"] == 110      # fim <= 111


def test_encaixar_sem_ponto_mantem_tempo_e_marca_falso():
    e = fr.encaixar(P(("a,", 0, 1), ("b,", 1.1, 2)), 0.5, 1.5, 3)
    assert e["fim"] == 1.5 and e["fim_ok"] is False


def test_encaixar_duracao_inalcancavel_nao_ok():
    e = fr.encaixar(_longa(), 101, 110, 30, dur_min=500)
    assert e["fim_ok"] is False and e["fim"] == 110


# ── faixa / ts ─────────────────────────────────────────────────────────────

def test_faixa_bordas():
    assert fr.faixa(None) is None
    assert fr.faixa(7.99) == "fora" and fr.faixa(5) == "fora"
    assert fr.faixa(8) == "curto" and fr.faixa(11.99) == "curto"
    assert fr.faixa(12) == "medio" and fr.faixa(19.99) == "medio"
    assert fr.faixa(20) == "longo" and fr.faixa(30) == "longo"
    assert fr.faixa(30.01) == "fora"


def test_segundos_para_ts():
    assert fr.segundos_para_ts(3725.5) == "01:02:05.50"
    assert fr.segundos_para_ts(-3) == "00:00:00.00"
