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
    gerar_cenario_plataforma,
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
