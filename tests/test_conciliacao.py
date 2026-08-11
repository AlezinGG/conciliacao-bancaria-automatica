"""
Testes do motor de conciliação.

O dataset sintético tem gabarito conhecido — sabemos exatamente quantas
divergências de cada tipo foram injetadas. Os testes verificam se o motor
recupera esse gabarito.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conciliacao import Conciliador, ParametrosConciliacao, conciliar  # noqa: E402
from src.gerador_dados import ConfigGerador, gerar_dataset  # noqa: E402


@pytest.fixture(scope="module")
def cenario():
    extrato, razao, gabarito = gerar_dataset(ConfigGerador(seed=42))
    return extrato, razao, gabarito, conciliar(extrato, razao)


# --------------------------------------------------------------------------- #
# Gabarito
# --------------------------------------------------------------------------- #


def test_recupera_gabarito(cenario):
    _, _, gabarito, resultado = cenario
    contagem = resultado["divergencias"]["tipo"].value_counts().to_dict()
    for tipo in ("nao_contabilizado", "nao_compensado", "divergencia_valor", "divergencia_data"):
        assert contagem.get(tipo, 0) == gabarito[tipo], f"tipo {tipo} divergiu do gabarito"


def test_taxa_conciliacao_alta(cenario):
    _, _, _, resultado = cenario
    assert resultado["resumo"]["taxa_conciliacao"] > 0.95


# --------------------------------------------------------------------------- #
# Invariantes — as regras que impedem output errado chegar ao contador
# --------------------------------------------------------------------------- #


def test_nenhum_registro_conciliado_duas_vezes(cenario):
    _, _, _, resultado = cenario
    pares = resultado["conciliados"]
    assert pares["id_razao"].is_unique, "linha do razao usada em mais de um par"
    agrupados = pares[pares["metodo"] == "agrupamento"]["id_extrato"]
    simples = pares[pares["metodo"] != "agrupamento"]["id_extrato"]
    assert simples.is_unique, "linha do extrato usada em mais de um par simples"
    assert set(agrupados) & set(simples) == set()


def test_conservacao_de_linhas(cenario):
    extrato, razao, _, resultado = cenario
    pares = resultado["conciliados"]
    pendentes_ext = resultado["resumo"]["pendentes_extrato"]
    assert pares["id_extrato"].nunique() + pendentes_ext == len(extrato)
    assert pares["id_razao"].nunique() + resultado["resumo"]["pendentes_razao"] == len(razao)


def test_resultado_reprodutivel():
    extrato, razao, _ = gerar_dataset(ConfigGerador(seed=7))
    a = conciliar(extrato, razao)["resumo"]
    b = conciliar(extrato, razao)["resumo"]
    assert a == b


def test_agrupamento_soma_confere(cenario):
    _, _, _, resultado = cenario
    pares = resultado["conciliados"]
    lotes = pares[pares["metodo"] == "agrupamento"]
    assert not lotes.empty
    for id_ext, grupo in lotes.groupby("id_extrato"):
        assert abs(grupo["valor_razao"].sum() - grupo["valor_extrato"].iloc[0]) < 0.01


# --------------------------------------------------------------------------- #
# Casos de borda
# --------------------------------------------------------------------------- #


def test_colunas_obrigatorias():
    df = pd.DataFrame({"id_extrato": ["E1"], "data": [datetime(2026, 6, 1)]})
    with pytest.raises(ValueError, match="Colunas ausentes"):
        Conciliador().conciliar(df, df)


def test_dataframes_vazios():
    colunas_e = ["id_extrato", "data", "valor", "historico", "documento"]
    colunas_r = ["id_razao", "data", "valor", "historico", "documento"]
    resultado = conciliar(pd.DataFrame(columns=colunas_e), pd.DataFrame(columns=colunas_r))
    assert resultado["resumo"]["conciliados"] == 0
    assert resultado["divergencias"].empty


def test_nao_casa_sinais_opostos():
    """Débito de R$ 100 não pode conciliar com crédito de R$ 100."""
    ext = pd.DataFrame(
        [{"id_extrato": "E1", "data": "2026-06-01", "valor": 100.0, "historico": "PIX", "documento": "D1"}]
    )
    raz = pd.DataFrame(
        [{"id_razao": "R1", "data": "2026-06-01", "valor": -100.0, "historico": "PIX", "documento": "D1"}]
    )
    resultado = conciliar(ext, raz)
    assert resultado["resumo"]["conciliados"] == 0


def test_tolerancia_respeitada():
    """Diferença acima da tolerância não pode ser conciliada como erro de digitação."""
    ext = pd.DataFrame(
        [{"id_extrato": "E1", "data": "2026-06-01", "valor": 1000.0, "historico": "PIX", "documento": "D1"}]
    )
    raz = pd.DataFrame(
        [{"id_razao": "R1", "data": "2026-06-01", "valor": 1500.0, "historico": "PIX", "documento": "D1"}]
    )
    parametros = ParametrosConciliacao(tolerancia_valor_abs=50.0, tolerancia_valor_pct=0.02)
    resultado = conciliar(ext, raz, parametros)
    assert resultado["resumo"]["conciliados"] == 0
    assert set(resultado["divergencias"]["tipo"]) == {"nao_contabilizado", "nao_compensado"}
