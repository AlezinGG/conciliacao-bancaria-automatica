"""
Gerador de dados sintéticos para demonstração.

IMPORTANTE: nenhum dado real de cliente, empregador ou instituição
financeira é utilizado neste projeto. Todos os registros são gerados
artificialmente pela biblioteca Faker.

O gerador injeta propositalmente as divergências que o motor de
conciliação precisa detectar, de forma que os testes e a demonstração
tenham um gabarito conhecido.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from faker import Faker

# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #

HISTORICOS_ENTRADA = [
    "RECEBIMENTO CLIENTE",
    "PIX RECEBIDO",
    "TED RECEBIDA",
    "LIQUIDACAO BOLETO",
    "CREDITO CARTAO",
]

HISTORICOS_SAIDA = [
    "PAGAMENTO FORNECEDOR",
    "PIX ENVIADO",
    "TARIFA BANCARIA",
    "FOLHA DE PAGAMENTO",
    "DARF",
    "ALUGUEL",
]

CONTAS_CONTABEIS = {
    "RECEBIMENTO CLIENTE": "1.1.2.01 - Clientes",
    "PIX RECEBIDO": "1.1.2.01 - Clientes",
    "TED RECEBIDA": "1.1.2.01 - Clientes",
    "LIQUIDACAO BOLETO": "1.1.2.01 - Clientes",
    "CREDITO CARTAO": "1.1.2.05 - Operadoras de Cartao",
    "PAGAMENTO FORNECEDOR": "2.1.1.01 - Fornecedores",
    "PIX ENVIADO": "2.1.1.01 - Fornecedores",
    "TARIFA BANCARIA": "4.1.3.02 - Despesas Bancarias",
    "FOLHA DE PAGAMENTO": "2.1.2.01 - Salarios a Pagar",
    "DARF": "2.1.3.01 - Tributos a Recolher",
    "ALUGUEL": "4.1.2.03 - Despesas com Ocupacao",
}


@dataclass
class ConfigGerador:
    """Parâmetros do cenário sintético."""

    n_lancamentos: int = 320
    data_inicio: date = date(2026, 6, 1)
    data_fim: date = date(2026, 6, 30)
    seed: int = 42

    # Divergências injetadas (quantidade absoluta de casos)
    n_nao_contabilizados: int = 6   # existe no banco, não existe no razão
    n_nao_compensados: int = 5      # existe no razão, não existe no banco
    n_divergencia_valor: int = 4    # mesmo doc, valor diferente
    n_divergencia_data: int = 7     # mesmo doc, defasagem de dias
    n_agrupados: int = 3            # N lançamentos no razão = 1 crédito no banco

    gabarito: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Geração
# --------------------------------------------------------------------------- #


def _valor_aleatorio(rng: random.Random, entrada: bool) -> float:
    if entrada:
        base = rng.choice([rng.uniform(150, 3_000), rng.uniform(3_000, 25_000)])
    else:
        base = rng.choice([rng.uniform(50, 1_500), rng.uniform(1_500, 18_000)])
    valor = round(base, 2)
    return valor if entrada else -valor


def gerar_dataset(config: ConfigGerador | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Gera o par (extrato bancário, razão contábil) com divergências conhecidas.

    Retorna
    -------
    extrato : DataFrame  [id_extrato, data, historico, documento, valor]
    razao   : DataFrame  [id_razao, data, conta, historico, documento, valor]
    gabarito: dict       contagem esperada por tipo de divergência
    """
    config = config or ConfigGerador()
    rng = random.Random(config.seed)
    fake = Faker("pt_BR")
    Faker.seed(config.seed)

    dias = (config.data_fim - config.data_inicio).days

    registros = []
    for i in range(config.n_lancamentos):
        entrada = rng.random() < 0.45
        historico = rng.choice(HISTORICOS_ENTRADA if entrada else HISTORICOS_SAIDA)
        data_mov = config.data_inicio + timedelta(days=rng.randint(0, dias))
        registros.append(
            {
                "documento": f"DOC{100000 + i}",
                "data": data_mov,
                "historico": historico,
                "contraparte": fake.company()[:40],
                "valor": _valor_aleatorio(rng, entrada),
                "conta": CONTAS_CONTABEIS[historico],
            }
        )

    base = pd.DataFrame(registros)

    # Índices reservados para cada tipo de divergência (sem sobreposição)
    total_divergentes = (
        config.n_nao_contabilizados
        + config.n_nao_compensados
        + config.n_divergencia_valor
        + config.n_divergencia_data
    )
    idx_sorteados = rng.sample(range(len(base)), total_divergentes)
    corte = 0

    def _fatiar(n: int) -> list[int]:
        nonlocal corte
        fatia = idx_sorteados[corte : corte + n]
        corte += n
        return fatia

    idx_sem_razao = _fatiar(config.n_nao_contabilizados)
    idx_sem_extrato = _fatiar(config.n_nao_compensados)
    idx_valor = _fatiar(config.n_divergencia_valor)
    idx_data = _fatiar(config.n_divergencia_data)

    linhas_extrato, linhas_razao = [], []

    for i, linha in base.iterrows():
        no_extrato = i not in idx_sem_extrato
        no_razao = i not in idx_sem_razao

        if no_extrato:
            linhas_extrato.append(
                {
                    "data": linha["data"],
                    "historico": f"{linha['historico']} {linha['contraparte'].upper()}",
                    "documento": linha["documento"],
                    "valor": linha["valor"],
                }
            )

        if no_razao:
            valor_razao = linha["valor"]
            data_razao = linha["data"]

            if i in idx_valor:
                # Erro de digitação: diferença pequena e plausível
                delta = round(rng.uniform(0.9, 45.0), 2)
                valor_razao = round(valor_razao + (delta if valor_razao > 0 else -delta), 2)

            if i in idx_data:
                # Competência contabilizada em dia diferente da compensação
                data_razao = linha["data"] + timedelta(days=rng.choice([1, 2, 3, -1, -2]))

            linhas_razao.append(
                {
                    "data": data_razao,
                    "conta": linha["conta"],
                    "historico": f"{linha['historico']} - {linha['contraparte']}",
                    "documento": linha["documento"],
                    "valor": valor_razao,
                }
            )

    # Casos agrupados: 1 crédito consolidado no banco = N títulos no razão
    for g in range(config.n_agrupados):
        data_mov = config.data_inicio + timedelta(days=rng.randint(0, dias))
        n_titulos = rng.randint(2, 4)
        titulos = [round(rng.uniform(200, 4_000), 2) for _ in range(n_titulos)]
        lote = f"LOTE{900 + g}"

        linhas_extrato.append(
            {
                "data": data_mov,
                "historico": f"CREDITO CARTAO REPASSE {lote}",
                "documento": lote,
                "valor": round(sum(titulos), 2),
            }
        )
        for j, v in enumerate(titulos):
            linhas_razao.append(
                {
                    "data": data_mov,
                    "conta": CONTAS_CONTABEIS["CREDITO CARTAO"],
                    "historico": f"Repasse cartao {lote} - parcela {j + 1}",
                    "documento": f"{lote}-{j + 1}",
                    "valor": v,
                }
            )

    extrato = pd.DataFrame(linhas_extrato).sample(frac=1, random_state=config.seed)
    razao = pd.DataFrame(linhas_razao).sample(frac=1, random_state=config.seed + 1)

    extrato = extrato.reset_index(drop=True)
    razao = razao.reset_index(drop=True)
    extrato.insert(0, "id_extrato", [f"E{i:05d}" for i in range(len(extrato))])
    razao.insert(0, "id_razao", [f"R{i:05d}" for i in range(len(razao))])

    extrato["data"] = pd.to_datetime(extrato["data"])
    razao["data"] = pd.to_datetime(razao["data"])

    gabarito = {
        "nao_contabilizado": config.n_nao_contabilizados,
        "nao_compensado": config.n_nao_compensados,
        "divergencia_valor": config.n_divergencia_valor,
        "divergencia_data": config.n_divergencia_data,
        "agrupamentos": config.n_agrupados,
        "linhas_extrato": len(extrato),
        "linhas_razao": len(razao),
    }
    return extrato, razao, gabarito


if __name__ == "__main__":  # pragma: no cover
    ext, raz, gab = gerar_dataset()
    ext.to_csv("dados/exemplo/extrato.csv", index=False)
    raz.to_csv("dados/exemplo/razao.csv", index=False)
    print("Gabarito:", gab)
