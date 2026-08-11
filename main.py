"""
Execução via linha de comando.

Exemplos
--------
    python main.py --demo
    python main.py --extrato extrato.csv --razao razao.csv --saida relatorio.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src.conciliacao import Conciliador, ParametrosConciliacao
from src.gerador_dados import ConfigGerador, gerar_dataset
from src.relatorio import gerar_excel


def _ler(caminho: str) -> pd.DataFrame:
    p = Path(caminho)
    if not p.exists():
        sys.exit(f"Arquivo nao encontrado: {p}")
    return pd.read_excel(p) if p.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(p)


def main() -> None:
    parser = argparse.ArgumentParser(description="Conciliacao bancaria automatica")
    parser.add_argument("--demo", action="store_true", help="usa dados sinteticos de demonstracao")
    parser.add_argument("--extrato", help="caminho do extrato bancario (CSV/XLSX)")
    parser.add_argument("--razao", help="caminho do razao contabil (CSV/XLSX)")
    parser.add_argument("--saida", default="dados/exemplo/relatorio_conciliacao.xlsx")
    parser.add_argument("--janela-dias", type=int, default=3)
    parser.add_argument("--tolerancia", type=float, default=50.0)
    args = parser.parse_args()

    if args.demo:
        extrato, razao, gabarito = gerar_dataset(ConfigGerador())
        Path("dados/exemplo").mkdir(parents=True, exist_ok=True)
        extrato.to_csv("dados/exemplo/extrato.csv", index=False)
        razao.to_csv("dados/exemplo/razao.csv", index=False)
        print(f"Cenario sintetico gerado: {gabarito}")
    elif args.extrato and args.razao:
        extrato, razao = _ler(args.extrato), _ler(args.razao)
        if "id_extrato" not in extrato.columns:
            extrato.insert(0, "id_extrato", [f"E{i:05d}" for i in range(len(extrato))])
        if "id_razao" not in razao.columns:
            razao.insert(0, "id_razao", [f"R{i:05d}" for i in range(len(razao))])
    else:
        parser.error("informe --demo ou o par --extrato/--razao")

    parametros = ParametrosConciliacao(janela_dias=args.janela_dias, tolerancia_valor_abs=args.tolerancia)
    resultado = Conciliador(parametros).conciliar(extrato, razao)
    resumo = resultado["resumo"]

    print("\n" + "=" * 58)
    print("CONCILIACAO BANCARIA - RESUMO")
    print("=" * 58)
    print(f"  Extrato / Razao .......... {resumo['linhas_extrato']} / {resumo['linhas_razao']} linhas")
    print(f"  Conciliados .............. {resumo['conciliados']} ({resumo['taxa_conciliacao']:.1%})")
    print(f"  Divergencias criticas .... {resumo['divergencias_criticas']}")
    print(f"  Valor em aberto .......... R$ {resumo['valor_em_aberto']:,.2f}")
    print("-" * 58)
    for metodo, n in sorted(resumo["por_metodo"].items(), key=lambda kv: -kv[1]):
        print(f"  {metodo:.<28} {n}")
    print("=" * 58)

    caminho = gerar_excel(resultado, args.saida)
    print(f"\nRelatorio salvo em: {caminho}\n")


if __name__ == "__main__":
    main()
