"""
Demonstração interativa da conciliação bancária automática.

Rode localmente com:  streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from src.conciliacao import Conciliador, ParametrosConciliacao
from src.gerador_dados import ConfigGerador, gerar_dataset
from src.relatorio import gerar_excel

st.set_page_config(page_title="Conciliação Bancária Automática", page_icon="📊", layout="wide")

ROTULOS = {
    "nao_contabilizado": "Não contabilizado",
    "nao_compensado": "Não compensado",
    "divergencia_valor": "Divergência de valor",
    "divergencia_data": "Divergência de data",
}


def brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@st.cache_data
def _dataset_demo(seed: int):
    return gerar_dataset(ConfigGerador(seed=seed))


def _ler_arquivo(arquivo) -> pd.DataFrame:
    if arquivo.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(arquivo)
    return pd.read_csv(arquivo)


# --------------------------------------------------------------------------- #
# Cabeçalho
# --------------------------------------------------------------------------- #

st.title("Conciliação Bancária Automática")
st.caption(
    "Cruza extrato bancário e razão contábil, concilia o que casa e classifica o que sobra. "
    "Dados desta demonstração são 100% sintéticos."
)

with st.sidebar:
    st.header("Parâmetros")
    janela = st.slider("Janela de data (dias)", 0, 10, 3)
    tol_abs = st.number_input("Tolerância de valor (R$)", 0.0, 500.0, 50.0, step=5.0)
    tol_pct = st.slider("Tolerância de valor (%)", 0.0, 10.0, 2.0, step=0.5) / 100
    similaridade = st.slider("Similaridade mínima de histórico", 0.3, 1.0, 0.62, step=0.02)

    st.divider()
    st.header("Fonte dos dados")
    modo = st.radio("", ["Dados de demonstração", "Meus arquivos"], label_visibility="collapsed")

    extrato = razao = None
    if modo == "Dados de demonstração":
        seed = st.number_input("Cenário (seed)", 1, 999, 42)
        extrato, razao, gabarito = _dataset_demo(int(seed))
        st.success(f"{len(extrato)} linhas de extrato · {len(razao)} de razão")
    else:
        up_ext = st.file_uploader("Extrato bancário (CSV/XLSX)", type=["csv", "xlsx", "xls"])
        up_raz = st.file_uploader("Razão contábil (CSV/XLSX)", type=["csv", "xlsx", "xls"])
        st.caption("Colunas exigidas: data, valor, historico. Opcional: documento.")
        if up_ext and up_raz:
            extrato, razao = _ler_arquivo(up_ext), _ler_arquivo(up_raz)
            if "id_extrato" not in extrato.columns:
                extrato.insert(0, "id_extrato", [f"E{i:05d}" for i in range(len(extrato))])
            if "id_razao" not in razao.columns:
                razao.insert(0, "id_razao", [f"R{i:05d}" for i in range(len(razao))])
        gabarito = None

if extrato is None or razao is None:
    st.info("Carregue os dois arquivos na barra lateral para começar.")
    st.stop()

# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #

parametros = ParametrosConciliacao(
    janela_dias=janela,
    tolerancia_valor_abs=tol_abs,
    tolerancia_valor_pct=tol_pct,
    similaridade_minima=similaridade,
)

inicio = datetime.now()
resultado = Conciliador(parametros).conciliar(extrato, razao)
duracao = (datetime.now() - inicio).total_seconds()

resumo = resultado["resumo"]
divergencias = resultado["divergencias"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Taxa de conciliação", f"{resumo['taxa_conciliacao']:.1%}")
c2.metric("Divergências críticas", resumo["divergencias_criticas"])
c3.metric("Valor em aberto", brl(resumo["valor_em_aberto"]))
c4.metric("Tempo de processamento", f"{duracao:.2f}s")

st.progress(resumo["taxa_conciliacao"])
st.caption(
    f"{resumo['conciliados']} de {resumo['linhas_extrato']} movimentos bancários conciliados "
    f"automaticamente. Restam {resumo['pendentes_extrato']} no extrato e "
    f"{resumo['pendentes_razao']} no razão para análise humana."
)

aba1, aba2, aba3, aba4 = st.tabs(["Divergências", "Conciliados", "Como o motor decidiu", "Dados de entrada"])

with aba1:
    if divergencias.empty:
        st.success("Nenhuma divergência encontrada.")
    else:
        tipos = st.multiselect(
            "Filtrar por tipo",
            options=list(divergencias["tipo"].unique()),
            default=list(divergencias["tipo"].unique()),
            format_func=lambda t: ROTULOS.get(t, t),
        )
        filtrado = divergencias[divergencias["tipo"].isin(tipos)]

        painel = (
            filtrado.groupby("tipo")
            .agg(ocorrencias=("valor", "size"), valor=("valor", lambda s: s.abs().sum()))
            .reset_index()
        )
        painel["tipo"] = painel["tipo"].map(lambda t: ROTULOS.get(t, t))
        cols = st.columns(max(len(painel), 1))
        for col, (_, linha) in zip(cols, painel.iterrows()):
            col.metric(linha["tipo"], int(linha["ocorrencias"]), brl(linha["valor"]))

        st.dataframe(filtrado, width="stretch", hide_index=True)

with aba2:
    st.dataframe(resultado["conciliados"], width="stretch", hide_index=True)

with aba3:
    st.write(
        "O motor roda uma cascata determinística: cada estágio só recebe o que o anterior "
        "não conseguiu casar, e nenhum registro é usado duas vezes."
    )
    metodos = pd.DataFrame(sorted(resumo["por_metodo"].items(), key=lambda kv: -kv[1]), columns=["Método", "Pares"])
    st.bar_chart(metodos.set_index("Método"))
    st.dataframe(metodos, width="stretch", hide_index=True)

with aba4:
    e, r = st.columns(2)
    e.subheader("Extrato bancário")
    e.dataframe(extrato.head(50), width="stretch", hide_index=True)
    r.subheader("Razão contábil")
    r.dataframe(razao.head(50), width="stretch", hide_index=True)

st.divider()
buffer = io.BytesIO()
caminho = gerar_excel(resultado, "dados/exemplo/relatorio_conciliacao.xlsx")
with open(caminho, "rb") as fh:
    buffer.write(fh.read())

st.download_button(
    "Baixar relatório em Excel",
    data=buffer.getvalue(),
    file_name=f"conciliacao_{datetime.now():%Y%m%d}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
