"""A conta da vinheta: propriedades, sem ffmpeg nem Qt (a comparação com o ffmpeg está em ``test_vinheta_contra_o_ffmpeg``)."""


from videomanager.domain.vignette import mask_size, vignette_factors


def _fator(mascara: bytes, largura: int, x: int, y: int) -> int:
    return mascara[y * largura + x]


def test_a_mascara_tem_um_byte_por_pixel_e_o_centro_nao_escurece():
    mascara = vignette_factors(40, 20)
    assert len(mascara) == 40 * 20
    assert _fator(mascara, 40, 20, 10) == 255


def test_escurece_mais_quanto_mais_longe_do_centro():
    mascara = vignette_factors(100, 60)
    ao_longo = [_fator(mascara, 100, x, 30) for x in range(50, 100, 7)]
    assert ao_longo == sorted(ao_longo, reverse=True) and ao_longo[-1] < ao_longo[0]
    assert _fator(mascara, 100, 0, 0) < _fator(mascara, 100, 99, 30)         # o canto escurece mais que o meio da borda


def test_o_canto_chega_a_um_quarto_e_nunca_a_zero():
    mascara = vignette_factors(200, 100)
    assert 255 * 0.25 - 2 <= _fator(mascara, 200, 0, 0) <= 255 * 0.25 + 12   # cos(π/4)⁴ = 0,25 no pixel mais distante


def test_a_forma_depende_da_proporcao_do_quadro():
    larga, quadrada = vignette_factors(200, 100), vignette_factors(100, 100)
    assert _fator(larga, 200, 100, 0) != _fator(quadrada, 100, 50, 0)         # o meio da borda de cima: 2:1 contra 1:1


def test_quadro_minimo_nao_quebra():
    assert vignette_factors(2, 2) and len(vignette_factors(2, 2)) == 4


def test_a_grade_menor_e_a_mesma_curva_amostrada_no_centro_de_cada_bloco():
    """Com ``step`` a grade tem um valor por bloco; cada um é o fator do pixel do meio do bloco no quadro inteiro."""
    cheia, grade = vignette_factors(80, 40), vignette_factors(80, 40, 4)
    gw, gh = mask_size(80, 40, 4)
    assert (gw, gh) == (20, 10) and len(grade) == gw * gh
    # O centro do bloco (j, i) cai entre os pixels 4j+1 e 4j+2: o fator é o dos dois, dentro de um nível.
    for i in range(gh):
        for j in range(gw):
            vizinhos = [cheia[y * 80 + x] for y in (4 * i + 1, 4 * i + 2) for x in (4 * j + 1, 4 * j + 2)]
            assert min(vizinhos) - 2 <= grade[i * gw + j] <= max(vizinhos) + 2


def test_o_tamanho_da_grade_arredonda_para_cima():
    assert mask_size(81, 41, 4) == (21, 11) and mask_size(80, 40, 1) == (80, 40)
