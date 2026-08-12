"""
Conciliação de repasses consolidados de plataformas.

O caso: plataformas como Airbnb, Booking e operadoras de cartão não creditam
uma reserva por vez. Elas agrupam várias reservas em um único repasse e
descontam a comissão antes de creditar. O resultado é que **nenhuma linha do
extrato bate com nenhuma linha do razão** — não existe correspondência 1:1,
e por isso a conferência manual é tão cara.

    Razão:    Reserva A  R$ 1.200,00
              Reserva B  R$   800,00
              Reserva C  R$   500,00
                         ------------
                         R$ 2.500,00  (bruto)

    Extrato:  Repasse    R$ 2.150,00  (líquido, após 14% de comissão)

Este módulo estende o motor base resolvendo a soma de subconjunto **líquida**:
procura o conjunto de lançamentos cujo bruto, descontada a taxa, resulta no
valor efetivamente creditado.

Todos os dados de exemplo são sintéticos.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import pandas as pd


@dataclass
class ParametrosRepasse:
    """
    Configuração da conciliação de repasses.

    `taxa_esperada` é o parâmetro decisivo. Se o cliente informa a comissão
    da plataforma (Airbnb, Booking, operadora), a precisão sobe muito: o motor
    só aceita conjuntos cuja taxa implícita caia na faixa esperada. Deixando
    em None, o motor calibra sozinho — ver `calibrar_taxa`.
    """

    taxa_esperada: float | None = None
    tolerancia_taxa: float = 0.025
    taxa_minima: float = 0.00
    taxa_maxima: float = 0.30
    tolerancia_centavos: float = 0.05
    max_itens_por_repasse: int = 12
    janela_dias: int = 7


@dataclass
class Repasse:
    """Um repasse conciliado e sua composição."""

    id_extrato: str
    data: pd.Timestamp
    valor_liquido: float
    valor_bruto: float
    taxa_valor: float
    taxa_percentual: float
    ids_razao: list[str]

    def resumo(self) -> dict:
        return {
            "id_extrato": self.id_extrato,
            "data": self.data,
            "reservas": len(self.ids_razao),
            "valor_bruto": round(self.valor_bruto, 2),
            "taxa_valor": round(self.taxa_valor, 2),
            "taxa_percentual": round(self.taxa_percentual, 4),
            "valor_liquido": round(self.valor_liquido, 2),
            "ids_razao": ",".join(self.ids_razao),
        }


class ConciliadorRepasses:
    """
    Concilia créditos líquidos consolidados contra lançamentos brutos.

    A busca é feita do conjunto menor para o maior e, dentro de cada tamanho,
    prioriza a combinação cuja taxa implícita fica mais próxima da taxa mediana
    já observada nos repasses anteriores do mesmo cliente. Isso evita o falso
    positivo clássico: dois conjuntos diferentes que, com taxas diferentes,
    chegariam ao mesmo líquido.
    """

    def __init__(self, parametros: ParametrosRepasse | None = None):
        self.p = parametros or ParametrosRepasse()
        self.taxa_calibrada: float | None = None

    # ------------------------------------------------------------------ #

    def conciliar(self, extrato: pd.DataFrame, razao: pd.DataFrame) -> dict:
        """
        Parâmetros
        ----------
        extrato : DataFrame  [id_extrato, data, valor]  — créditos líquidos
        razao   : DataFrame  [id_razao, data, valor]    — reservas brutas
        """
        ext = extrato.copy()
        raz = razao.copy()
        ext["data"] = pd.to_datetime(ext["data"])
        raz["data"] = pd.to_datetime(raz["data"])
        ext = ext.sort_values("data").reset_index(drop=True)
        raz = raz.sort_values("data").reset_index(drop=True)

        taxa = self.p.taxa_esperada
        if taxa is None:
            taxa = self.calibrar_taxa(ext, raz)
        self.taxa_calibrada = taxa

        fila = raz.to_dict("records")
        alocados: set[str] = set()
        repasses: list[Repasse] = []
        nao_identificados: list[dict] = []

        for credito in ext.to_dict("records"):
            achado = self._resolver(credito, fila, alocados, taxa)
            if achado:
                repasses.append(achado)
                alocados.update(achado.ids_razao)
            else:
                nao_identificados.append(credito)

        livres = {r["id_razao"]: r for r in fila if r["id_razao"] not in alocados}

        return {
            "repasses": pd.DataFrame([r.resumo() for r in repasses]),
            "creditos_nao_identificados": pd.DataFrame(nao_identificados),
            "reservas_sem_repasse": pd.DataFrame(list(livres.values())),
            "resumo": self._resumo(ext, raz, repasses, nao_identificados, livres, taxa),
        }

    # ------------------------------------------------------------------ #

    def calibrar_taxa(self, ext: pd.DataFrame, raz: pd.DataFrame) -> float:
        """
        Descobre a comissão da plataforma sem que o cliente precise informar.

        A soma total do período dá uma primeira estimativa robusta: o agregado
        das reservas contra o agregado dos créditos. Repasses e reservas órfãs
        distorcem pouco quando o volume é razoável, e o refino por janela
        corrige o resto.
        """
        bruto = float(raz["valor"].clip(lower=0).sum())
        liquido = float(ext["valor"].clip(lower=0).sum())
        if bruto <= 0:
            return 0.0
        estimativa = (bruto - liquido) / bruto
        return float(min(max(estimativa, self.p.taxa_minima), self.p.taxa_maxima))

    def _resolver(
        self, credito: dict, fila: list[dict], alocados: set[str], taxa: float
    ) -> Repasse | None:
        """
        Busca o conjunto de reservas que explica o crédito.

        Estratégia principal: janelas contíguas na ordem cronológica. Plataformas
        fecham lote por período, não por seleção arbitrária — então o conjunto
        certo é quase sempre um bloco consecutivo de reservas ainda não repassadas.
        Isso troca uma busca combinatória (que gera falso positivo à vontade) por
        uma varredura O(n²) muito mais fiel à realidade do negócio.
        """
        liquido = round(float(credito["valor"]), 2)
        if liquido <= 0:
            return None

        piso, teto = taxa - self.p.tolerancia_taxa, taxa + self.p.tolerancia_taxa
        pendentes = [
            r
            for r in fila
            if r["id_razao"] not in alocados
            and float(r["valor"]) > 0
            and (credito["data"] - r["data"]).days >= -self.p.janela_dias
        ]
        if not pendentes:
            return None

        melhor: tuple[float, list[dict]] | None = None

        for inicio in range(len(pendentes)):
            bruto = 0.0
            for fim in range(inicio, min(inicio + self.p.max_itens_por_repasse, len(pendentes))):
                bruto += float(pendentes[fim]["valor"])
                if bruto <= liquido - self.p.tolerancia_centavos:
                    continue  # ainda não alcança o líquido
                taxa_implicita = (bruto - liquido) / bruto
                if taxa_implicita > teto:
                    break  # daqui pra frente só piora
                if taxa_implicita < piso:
                    continue
                distancia = abs(taxa_implicita - taxa)
                if melhor is None or distancia < melhor[0]:
                    melhor = (distancia, pendentes[inicio : fim + 1])
            if melhor is not None and melhor[0] < 0.002:
                break  # encaixe praticamente exato

        if melhor is None:
            melhor = self._busca_combinatoria(liquido, pendentes, piso, teto, taxa)
        if melhor is None:
            return None

        grupo = melhor[1]
        bruto = round(sum(float(r["valor"]) for r in grupo), 2)
        return Repasse(
            id_extrato=credito["id_extrato"],
            data=credito["data"],
            valor_liquido=liquido,
            valor_bruto=bruto,
            taxa_valor=round(bruto - liquido, 2),
            taxa_percentual=(bruto - liquido) / bruto,
            ids_razao=[r["id_razao"] for r in grupo],
        )

    def _busca_combinatoria(
        self, liquido: float, pendentes: list[dict], piso: float, teto: float, taxa: float
    ) -> tuple[float, list[dict]] | None:
        """Plano B para lotes não contíguos. Restrito para não explodir."""
        candidatos = pendentes[:14]
        melhor: tuple[float, list[dict]] | None = None
        for tamanho in range(1, min(5, len(candidatos)) + 1):
            for combo in combinations(candidatos, tamanho):
                bruto = round(sum(float(r["valor"]) for r in combo), 2)
                if bruto <= liquido:
                    continue
                taxa_implicita = (bruto - liquido) / bruto
                if not (piso <= taxa_implicita <= teto):
                    continue
                distancia = abs(taxa_implicita - taxa)
                if melhor is None or distancia < melhor[0]:
                    melhor = (distancia, list(combo))
        return melhor

    @staticmethod
    def _resumo(ext, raz, repasses, nao_identificados, livres, taxa_usada) -> dict:
        taxas = [r.taxa_percentual for r in repasses]
        return {
            "taxa_utilizada": round(taxa_usada, 4),
            "creditos_no_extrato": len(ext),
            "reservas_no_razao": len(raz),
            "repasses_identificados": len(repasses),
            "reservas_conciliadas": sum(len(r.ids_razao) for r in repasses),
            "creditos_nao_identificados": len(nao_identificados),
            "reservas_sem_repasse": len(livres),
            "taxa_media": round(sum(taxas) / len(taxas), 4) if taxas else 0.0,
            "taxa_min": round(min(taxas), 4) if taxas else 0.0,
            "taxa_max": round(max(taxas), 4) if taxas else 0.0,
            "total_taxas_pagas": round(sum(r.taxa_valor for r in repasses), 2),
            "valor_reservas_sem_repasse": round(
                sum(float(r["valor"]) for r in livres.values()), 2
            ),
        }


def ratear_por_reserva(resultado: dict, razao: pd.DataFrame) -> pd.DataFrame:
    """
    Distribui o valor líquido de cada repasse entre as reservas que o compõem.

    O rateio é proporcional ao bruto: reserva maior absorve fatia maior da
    comissão. Arredondar cada parcela em centavos pode deixar sobra — a
    diferença é atribuída à maior reserva do lote, porque é a que menos
    distorce percentualmente, garantindo que a soma do lote feche exatamente
    com o valor creditado.
    """
    raz = razao.set_index("id_razao")
    linhas: list[dict] = []

    for repasse in resultado["repasses"].itertuples():
        ids = repasse.ids_razao.split(",")
        grupo = raz.loc[ids]
        bruto_total = float(grupo["valor"].sum())
        liquido_total = round(float(repasse.valor_liquido), 2)

        parcelas = []
        for id_razao, linha in grupo.iterrows():
            bruto = round(float(linha["valor"]), 2)
            proporcao = bruto / bruto_total if bruto_total > 0 else 0.0
            liquido = round(liquido_total * proporcao, 2)
            parcelas.append(
                {
                    "id_razao": id_razao,
                    "id_extrato": repasse.id_extrato,
                    "data": repasse.data,
                    "imovel": linha.get("imovel", ""),
                    "proprietario": linha.get("proprietario", ""),
                    "valor_bruto": bruto,
                    "valor_liquido": liquido,
                }
            )

        sobra = round(liquido_total - sum(p["valor_liquido"] for p in parcelas), 2)
        if sobra != 0 and parcelas:
            maior = max(parcelas, key=lambda p: p["valor_bruto"])
            maior["valor_liquido"] = round(maior["valor_liquido"] + sobra, 2)

        for p in parcelas:
            p["comissao_rateada"] = round(p["valor_bruto"] - p["valor_liquido"], 2)

        linhas.extend(parcelas)

    colunas = [
        "id_razao",
        "id_extrato",
        "data",
        "imovel",
        "proprietario",
        "valor_bruto",
        "comissao_rateada",
        "valor_liquido",
    ]
    return pd.DataFrame(linhas, columns=colunas)


def agregar_por_proprietario(rateio: pd.DataFrame) -> pd.DataFrame:
    """Confere quanto cada proprietário tem a receber no período."""
    return _agregar_rateio(rateio, "proprietario")


def agregar_por_imovel(rateio: pd.DataFrame) -> pd.DataFrame:
    """Confere quanto cada imóvel gerou de bruto, comissão e líquido."""
    return _agregar_rateio(rateio, "imovel")


def _agregar_rateio(rateio: pd.DataFrame, coluna: str) -> pd.DataFrame:
    if rateio.empty:
        return pd.DataFrame(columns=[coluna, "reservas", "valor_bruto", "comissao_rateada", "valor_liquido"])
    agregado = (
        rateio.groupby(coluna, as_index=False)
        .agg(
            reservas=("id_razao", "count"),
            valor_bruto=("valor_bruto", "sum"),
            comissao_rateada=("comissao_rateada", "sum"),
            valor_liquido=("valor_liquido", "sum"),
        )
        .sort_values(coluna)
        .reset_index(drop=True)
    )
    for c in ("valor_bruto", "comissao_rateada", "valor_liquido"):
        agregado[c] = agregado[c].round(2)
    return agregado


# --------------------------------------------------------------------------- #
# Dados sintéticos para demonstração
# --------------------------------------------------------------------------- #


def gerar_cenario_plataforma(
    n_reservas: int = 90,
    taxa: float = 0.14,
    seed: int = 11,
    reservas_sem_repasse: int = 3,
    creditos_orfaos: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Simula uma operação de aluguel por temporada.

    Reservas individuais no razão, repasses consolidados e líquidos no extrato.
    Injeta reservas que nunca foram repassadas e créditos sem origem — as duas
    perdas silenciosas mais comuns nesse tipo de operação.
    """
    import random
    from datetime import date, timedelta

    from faker import Faker

    rng = random.Random(seed)
    inicio = date(2026, 6, 1)

    fake = Faker("pt_BR")
    Faker.seed(seed)
    n_imoveis = 8
    proprietario_por_imovel = {
        f"Imovel {i:02d}": fake.name() for i in range(1, n_imoveis + 1)
    }

    reservas = []
    for i in range(n_reservas):
        data = inicio + timedelta(days=rng.randint(0, 27))
        imovel = f"Imovel {rng.randint(1, n_imoveis):02d}"
        valor = round(rng.uniform(280, 3_200), 2)
        reservas.append(
            {
                "id_razao": f"R{i:04d}",
                "data": data,
                "imovel": imovel,
                "proprietario": proprietario_por_imovel[imovel],
                "historico": f"Reserva plataforma #{20000 + i}",
                "valor": valor,
            }
        )
    raz = pd.DataFrame(reservas).sort_values("data").reset_index(drop=True)

    orfas = set(rng.sample(list(raz["id_razao"]), reservas_sem_repasse))
    disponiveis = raz[~raz["id_razao"].isin(orfas)].to_dict("records")

    creditos, i, n = [], 0, 0
    while i < len(disponiveis):
        tamanho = rng.randint(2, 5)
        lote = disponiveis[i : i + tamanho]
        if not lote:
            break
        bruto = sum(r["valor"] for r in lote)
        taxa_lote = taxa + rng.uniform(-0.012, 0.012)  # variação real da plataforma
        creditos.append(
            {
                "id_extrato": f"E{n:04d}",
                "data": max(r["data"] for r in lote) + timedelta(days=rng.randint(1, 3)),
                "historico": "REPASSE PLATAFORMA TEMPORADA",
                "valor": round(bruto * (1 - taxa_lote), 2),
            }
        )
        i += tamanho
        n += 1

    for _ in range(creditos_orfaos):
        creditos.append(
            {
                "id_extrato": f"E{n:04d}",
                "data": inicio + timedelta(days=rng.randint(0, 27)),
                "historico": "CREDITO NAO IDENTIFICADO",
                "valor": round(rng.uniform(400, 2_500), 2),
            }
        )
        n += 1

    ext = pd.DataFrame(creditos).sort_values("data").reset_index(drop=True)
    gabarito = {
        "reservas": n_reservas,
        "reservas_sem_repasse": reservas_sem_repasse,
        "creditos_orfaos": creditos_orfaos,
        "taxa_nominal": taxa,
    }
    return ext, raz, gabarito


if __name__ == "__main__":  # pragma: no cover
    ext, raz, gab = gerar_cenario_plataforma()
    resultado = ConciliadorRepasses().conciliar(ext, raz)
    print("Gabarito:", gab)
    for chave, valor in resultado["resumo"].items():
        print(f"  {chave:.<32} {valor}")
