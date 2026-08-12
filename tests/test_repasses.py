"""Testes da conciliação de repasses consolidados de plataformas."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.repasses import (  # noqa: E402
    ConciliadorRepasses,
    ParametrosRepasse,
    agregar_por_imovel,
    agregar_por_proprietario,
    gerar_cenario_plataforma,
    ratear_por_reserva,
)


@pytest.fixture(scope="module")
def cenario():
    ext, raz, gabarito = gerar_cenario_plataforma(seed=11)
    resultado = ConciliadorRepasses().conciliar(ext, raz)
    return ext, raz, gabarito, resultado


def test_calibra_taxa_sem_informacao_do_cliente(cenario):
    """Sem informar a comissão, o motor precisa descobri-la sozinho."""
    _, _, gabarito, resultado = cenario
    assert abs(resultado["resumo"]["taxa_utilizada"] - gabarito["taxa_nominal"]) < 0.01


def test_detecta_creditos_sem_origem(cenario):
    """Crédito na conta sem reserva correspondente é dinheiro a investigar."""
    _, _, gabarito, resultado = cenario
    assert len(resultado["creditos_nao_identificados"]) == gabarito["creditos_orfaos"]


def test_concilia_maioria_das_reservas(cenario):
    _, raz, _, resultado = cenario
    taxa = resultado["resumo"]["reservas_conciliadas"] / len(raz)
    assert taxa > 0.95


def test_nenhuma_reserva_em_dois_repasses(cenario):
    _, _, _, resultado = cenario
    ids = [i for linha in resultado["repasses"]["ids_razao"] for i in linha.split(",")]
    assert len(ids) == len(set(ids)), "reserva alocada em mais de um repasse"


def test_soma_liquida_confere(cenario):
    """bruto - taxa = líquido, em todo repasse."""
    _, _, _, resultado = cenario
    r = resultado["repasses"]
    assert ((r["valor_bruto"] - r["taxa_valor"] - r["valor_liquido"]).abs() < 0.02).all()


def test_taxa_informada_restringe_busca():
    """Informar a comissão real deve produzir taxas dentro da faixa esperada."""
    ext, raz, _ = gerar_cenario_plataforma(seed=5, taxa=0.18)
    resultado = ConciliadorRepasses(
        ParametrosRepasse(taxa_esperada=0.18, tolerancia_taxa=0.02)
    ).conciliar(ext, raz)
    taxas = resultado["repasses"]["taxa_percentual"]
    assert not taxas.empty
    assert taxas.between(0.16 - 1e-6, 0.20 + 1e-6).all()


def test_credito_impossivel_nao_e_forcado():
    """Valor que nenhuma combinação explica deve ficar como não identificado."""
    raz = pd.DataFrame(
        [
            {"id_razao": "R1", "data": "2026-06-01", "valor": 100.0},
            {"id_razao": "R2", "data": "2026-06-02", "valor": 200.0},
        ]
    )
    ext = pd.DataFrame([{"id_extrato": "E1", "data": "2026-06-03", "valor": 9_999.0}])
    resultado = ConciliadorRepasses(ParametrosRepasse(taxa_esperada=0.14)).conciliar(ext, raz)
    assert len(resultado["creditos_nao_identificados"]) == 1
    assert resultado["repasses"].empty


def test_reserva_nunca_repassada_aparece_no_relatorio():
    """A perda silenciosa mais cara: reserva faturada que nunca foi creditada."""
    raz = pd.DataFrame(
        [
            {"id_razao": "R1", "data": "2026-06-01", "valor": 1_000.0},
            {"id_razao": "R2", "data": "2026-06-20", "valor": 5_000.0},
        ]
    )
    ext = pd.DataFrame([{"id_extrato": "E1", "data": "2026-06-02", "valor": 860.0}])
    resultado = ConciliadorRepasses(ParametrosRepasse(taxa_esperada=0.14)).conciliar(ext, raz)
    pendentes = resultado["reservas_sem_repasse"]
    assert len(pendentes) == 1
    assert pendentes.iloc[0]["id_razao"] == "R2"


def test_reprodutivel():
    ext, raz, _ = gerar_cenario_plataforma(seed=3)
    a = ConciliadorRepasses().conciliar(ext, raz)["resumo"]
    b = ConciliadorRepasses().conciliar(ext, raz)["resumo"]
    assert a == b


def test_rateio_fecha_a_soma_do_lote(cenario):
    """A soma dos líquidos rateados de um repasse tem que bater com o crédito."""
    _, raz, _, resultado = cenario
    rateio = ratear_por_reserva(resultado, raz)

    por_repasse = rateio.groupby("id_extrato")["valor_liquido"].sum()
    esperado = resultado["repasses"].set_index("id_extrato")["valor_liquido"]
    diferenca = (por_repasse - esperado).abs()
    assert (diferenca < 0.01).all()


def test_rateio_e_proporcional_ao_bruto():
    """Reserva com o dobro do bruto recebe o dobro do líquido, dentro do lote."""
    raz = pd.DataFrame(
        [
            {"id_razao": "R1", "data": "2026-06-01", "imovel": "Imovel 01",
             "proprietario": "Ana", "valor": 1_000.0},
            {"id_razao": "R2", "data": "2026-06-01", "imovel": "Imovel 02",
             "proprietario": "Beto", "valor": 500.0},
        ]
    )
    ext = pd.DataFrame([{"id_extrato": "E1", "data": "2026-06-02", "valor": 1_290.0}])
    resultado = ConciliadorRepasses(ParametrosRepasse(taxa_esperada=0.14)).conciliar(ext, raz)
    rateio = ratear_por_reserva(resultado, raz)

    liquido_r1 = rateio.set_index("id_razao").loc["R1", "valor_liquido"]
    liquido_r2 = rateio.set_index("id_razao").loc["R2", "valor_liquido"]
    assert abs(liquido_r1 - 2 * liquido_r2) < 0.02


def test_rateio_com_reserva_de_valor_zero():
    """
    Reserva de cortesia (bruto zero) não recebe fatia do líquido nem quebra o rateio.

    O motor de conciliação nunca agrupa uma reserva de valor zero num repasse
    (ela não move a soma), então o cenário é montado direto sobre o formato de
    saída de `conciliar()` para exercitar essa borda do rateio isoladamente.
    """
    raz = pd.DataFrame(
        [
            {"id_razao": "R1", "data": "2026-06-01", "imovel": "Imovel 01",
             "proprietario": "Ana", "valor": 1_000.0},
            {"id_razao": "R2", "data": "2026-06-01", "imovel": "Imovel 02",
             "proprietario": "Beto", "valor": 0.0},
        ]
    )
    resultado = {
        "repasses": pd.DataFrame(
            [
                {
                    "id_extrato": "E1",
                    "data": pd.Timestamp("2026-06-02"),
                    "reservas": 2,
                    "valor_bruto": 1_000.0,
                    "taxa_valor": 140.0,
                    "taxa_percentual": 0.14,
                    "valor_liquido": 860.0,
                    "ids_razao": "R1,R2",
                }
            ]
        )
    }
    rateio = ratear_por_reserva(resultado, raz)

    linha_zero = rateio.set_index("id_razao").loc["R2"]
    assert linha_zero["valor_liquido"] == 0.0
    assert linha_zero["comissao_rateada"] == 0.0
    assert rateio["valor_liquido"].sum() == pytest.approx(860.0, abs=0.01)


def test_agregacao_por_proprietario_e_imovel(cenario):
    _, raz, _, resultado = cenario
    rateio = ratear_por_reserva(resultado, raz)

    por_dono = agregar_por_proprietario(rateio)
    por_imovel = agregar_por_imovel(rateio)

    assert set(por_dono["proprietario"]) <= set(raz["proprietario"])
    assert set(por_imovel["imovel"]) == set(
        raz.loc[raz["id_razao"].isin(rateio["id_razao"]), "imovel"]
    )
    assert abs(por_dono["valor_liquido"].sum() - rateio["valor_liquido"].sum()) < 0.01
