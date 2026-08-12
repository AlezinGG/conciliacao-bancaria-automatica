"""
Demonstração: conciliação de repasses consolidados de plataformas.

Caso de uso: aluguel por temporada (Airbnb, Booking) e operadoras de cartão,
onde um único crédito líquido cobre várias reservas e a comissão já vem
descontada.

Rode com:  streamlit run app_repasses.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.repasses import (
    ConciliadorRepasses,
    ParametrosRepasse,
    agregar_por_proprietario,
    gerar_cenario_plataforma,
    ratear_por_reserva,
)

st.set_page_config(page_title="Conciliação de Repasses", page_icon="🏠", layout="wide")


def brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@st.cache_data
def _demo(seed: int, taxa: float, n: int):
    return gerar_cenario_plataforma(n_reservas=n, taxa=taxa, seed=seed)


def _ler(arquivo) -> pd.DataFrame:
    if arquivo.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(arquivo)
    return pd.read_csv(arquivo)


st.title("Conciliação de Repasses Consolidados")
st.caption(
    "Plataformas de temporada e operadoras de cartão agrupam várias reservas em um único "
    "crédito e descontam a comissão antes do repasse — não existe correspondência 1:1 "
    "entre extrato e lançamentos. Esta ferramenta reconstrói a composição de cada repasse."
)

with st.sidebar:
    st.header("Comissão da plataforma")
    auto = st.checkbox("Descobrir automaticamente", value=True)
    taxa_informada = None
    if not auto:
        taxa_informada = st.slider("Comissão (%)", 0.0, 30.0, 14.0, step=0.5) / 100
    tolerancia = st.slider("Tolerância da comissão (p.p.)", 0.5, 6.0, 2.5, step=0.5) / 100
    janela = st.slider("Janela de data (dias)", 1, 15, 7)

    st.divider()
    st.header("Dados")
    modo = st.radio("", ["Demonstração", "Meus arquivos"], label_visibility="collapsed")

    extrato = razao = None
    if modo == "Demonstração":
        seed = st.number_input("Cenário", 1, 999, 11)
        taxa_demo = st.slider("Comissão real do cenário (%)", 3.0, 25.0, 14.0, step=1.0) / 100
        n_reservas = st.slider("Reservas no período", 30, 200, 90, step=10)
        extrato, razao, gabarito = _demo(int(seed), taxa_demo, int(n_reservas))
        st.success(f"{len(extrato)} repasses · {len(razao)} reservas")
    else:
        up_e = st.file_uploader("Extrato — créditos recebidos", type=["csv", "xlsx", "xls"])
        up_r = st.file_uploader("Reservas / razão", type=["csv", "xlsx", "xls"])
        st.caption("Colunas exigidas: data, valor. Ids são gerados se ausentes.")
        gabarito = None
        if up_e and up_r:
            extrato, razao = _ler(up_e), _ler(up_r)
            if "id_extrato" not in extrato.columns:
                extrato.insert(0, "id_extrato", [f"E{i:04d}" for i in range(len(extrato))])
            if "id_razao" not in razao.columns:
                razao.insert(0, "id_razao", [f"R{i:04d}" for i in range(len(razao))])

if extrato is None or razao is None:
    st.info("Carregue os dois arquivos na barra lateral para começar.")
    st.stop()

parametros = ParametrosRepasse(
    taxa_esperada=taxa_informada, tolerancia_taxa=tolerancia, janela_dias=janela
)
resultado = ConciliadorRepasses(parametros).conciliar(extrato, razao)
resumo = resultado["resumo"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Comissão identificada", f"{resumo['taxa_utilizada']:.2%}")
c2.metric("Repasses reconstruídos", resumo["repasses_identificados"])
c3.metric("Reservas conciliadas", f"{resumo['reservas_conciliadas']} de {resumo['reservas_no_razao']}")
c4.metric("Comissões pagas no período", brl(resumo["total_taxas_pagas"]))

if gabarito:
    erro = abs(resumo["taxa_utilizada"] - gabarito["taxa_nominal"])
    st.caption(
        f"Comissão real do cenário: {gabarito['taxa_nominal']:.2%} · "
        f"identificada pelo motor: {resumo['taxa_utilizada']:.2%} · erro de {erro:.2%}"
    )

alerta1 = resumo["creditos_nao_identificados"]
alerta2 = resumo["reservas_sem_repasse"]
if alerta1 or alerta2:
    st.warning(
        f"**{alerta1} crédito(s) sem origem identificada** e "
        f"**{alerta2} reserva(s) sem repasse correspondente** "
        f"({brl(resumo['valor_reservas_sem_repasse'])} em aberto). "
        "São os dois pontos onde dinheiro costuma se perder silenciosamente."
    )
else:
    st.success("Todos os repasses e reservas foram conciliados.")

aba1, aba2, aba3, aba4, aba5 = st.tabs(
    [
        "Repasses reconstruídos",
        "Reservas sem repasse",
        "Créditos sem origem",
        "Comissão por repasse",
        "Rateio por proprietário",
    ]
)

with aba1:
    st.dataframe(resultado["repasses"], width="stretch", hide_index=True)
    st.caption("Cada linha mostra a composição do crédito: quais reservas o formaram e qual comissão foi aplicada.")

with aba2:
    pendentes = resultado["reservas_sem_repasse"]
    if pendentes.empty:
        st.success("Nenhuma reserva pendente de repasse.")
    else:
        st.error(f"{len(pendentes)} reserva(s) faturada(s) sem crédito correspondente.")
        st.dataframe(pendentes, width="stretch", hide_index=True)

with aba3:
    orfaos = resultado["creditos_nao_identificados"]
    if orfaos.empty:
        st.success("Todos os créditos foram atribuídos.")
    else:
        st.dataframe(orfaos, width="stretch", hide_index=True)

with aba4:
    r = resultado["repasses"]
    if not r.empty:
        st.line_chart(r.set_index("data")["taxa_percentual"])
        st.caption(
            f"Comissão média {resumo['taxa_media']:.2%} · mínima {resumo['taxa_min']:.2%} · "
            f"máxima {resumo['taxa_max']:.2%}. Variação alta pode indicar mudança de política "
            "da plataforma ou cobrança indevida."
        )

with aba5:
    if "proprietario" not in razao.columns:
        st.info(
            "A planilha de reservas não tem coluna **proprietario** — envie um arquivo "
            "com essa coluna para ver o rateio."
        )
    elif resultado["repasses"].empty:
        st.info("Nenhum repasse reconstruído para ratear.")
    else:
        rateio = ratear_por_reserva(resultado, razao)
        por_dono = agregar_por_proprietario(rateio)
        st.caption(
            "Quanto cada proprietário tem a receber no período, já descontada a "
            "comissão da plataforma proporcionalmente ao bruto de cada reserva."
        )
        st.dataframe(por_dono, width="stretch", hide_index=True)
        with st.expander("Ver rateio reserva a reserva"):
            st.dataframe(rateio, width="stretch", hide_index=True)
