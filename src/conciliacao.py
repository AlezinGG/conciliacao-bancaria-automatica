"""
Motor de conciliação bancária.

Estratégia: cascata determinística de estágios, do mais restritivo ao mais
permissivo. Cada estágio só enxerga o que sobrou do anterior, e todo par
conciliado sai imediatamente do pool. Isso garante que um registro nunca
seja usado duas vezes e que o resultado seja reproduzível — sem isso,
nenhum contador aceita o output.

Estágios
--------
1. documento_e_valor      documento idêntico + valor idêntico
2. valor_e_data           valor idêntico + mesma data
3. valor_data_aproximada  valor idêntico + data dentro da janela
4. divergencia_valor      documento idêntico + valor divergente na tolerância
5. similaridade_historico valor idêntico + histórico similar na janela ampliada
6. agrupamento            soma de N linhas do razão = 1 linha do extrato

Resíduo
-------
nao_contabilizado : consta no banco, não consta no razão
nao_compensado    : consta no razão, não consta no banco
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

import pandas as pd


@dataclass
class ParametrosConciliacao:
    janela_dias: int = 3
    janela_dias_similaridade: int = 7
    tolerancia_valor_abs: float = 50.0
    tolerancia_valor_pct: float = 0.02
    similaridade_minima: float = 0.62
    max_linhas_agrupamento: int = 4
    max_grupo_combinatorio: int = 12


SEVERIDADE = {
    "nao_contabilizado": "alta",
    "nao_compensado": "alta",
    "divergencia_valor": "alta",
    "divergencia_data": "baixa",
}


def _norm(texto: str) -> str:
    return " ".join(str(texto).upper().split())


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


class Conciliador:
    """Concilia extrato bancário contra razão contábil."""

    def __init__(self, parametros: ParametrosConciliacao | None = None):
        self.p = parametros or ParametrosConciliacao()

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def conciliar(self, extrato: pd.DataFrame, razao: pd.DataFrame) -> dict:
        ext = self._preparar(extrato, "id_extrato")
        raz = self._preparar(razao, "id_razao")

        self._ext = {r["id_extrato"]: r for r in ext.to_dict("records")}
        self._raz = {r["id_razao"]: r for r in raz.to_dict("records")}
        self._livres_ext = set(self._ext)
        self._livres_raz = set(self._raz)
        self._pares: list[dict] = []

        self._estagio_documento_e_valor()
        self._estagio_valor_e_data()
        self._estagio_valor_data_aproximada()
        self._estagio_divergencia_valor()
        self._estagio_similaridade()
        self._estagio_agrupamento()

        pares = pd.DataFrame(self._pares)
        divergencias = self._montar_divergencias(pares)
        return {
            "conciliados": pares,
            "divergencias": divergencias,
            "resumo": self._resumo(pares, divergencias),
        }

    # ------------------------------------------------------------------ #
    # Preparação
    # ------------------------------------------------------------------ #

    @staticmethod
    def _preparar(df: pd.DataFrame, chave: str) -> pd.DataFrame:
        obrigatorias = {chave, "data", "valor", "historico"}
        faltantes = obrigatorias - set(df.columns)
        if faltantes:
            raise ValueError(f"Colunas ausentes em {chave}: {sorted(faltantes)}")
        out = df.copy()
        out["data"] = pd.to_datetime(out["data"])
        out["valor"] = out["valor"].astype(float).round(2)
        if "documento" not in out.columns:
            out["documento"] = ""
        out["documento"] = out["documento"].fillna("").map(_norm)
        return out

    def _registrar(self, id_e: str, id_r: str, metodo: str, score: float, obs: str = "") -> None:
        e, r = self._ext[id_e], self._raz[id_r]
        self._pares.append(
            {
                "id_extrato": id_e,
                "id_razao": id_r,
                "data_extrato": e["data"],
                "data_razao": r["data"],
                "valor_extrato": e["valor"],
                "valor_razao": r["valor"],
                "diferenca": round(e["valor"] - r["valor"], 2),
                "dias_defasagem": int((e["data"] - r["data"]).days),
                "historico_extrato": e["historico"],
                "metodo": metodo,
                "score": round(score, 3),
                "observacao": obs,
            }
        )
        self._livres_ext.discard(id_e)
        self._livres_raz.discard(id_r)

    # ------------------------------------------------------------------ #
    # Estágios
    # ------------------------------------------------------------------ #

    def _indexar_razao(self, chave_fn) -> dict:
        indice: dict = {}
        for rid in self._livres_raz:
            indice.setdefault(chave_fn(self._raz[rid]), []).append(rid)
        return indice

    def _estagio_documento_e_valor(self) -> None:
        idx = self._indexar_razao(lambda r: (r["documento"], r["valor"]))
        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            if not e["documento"]:
                continue
            candidatos = [c for c in idx.get((e["documento"], e["valor"]), []) if c in self._livres_raz]
            if candidatos:
                self._registrar(eid, candidatos[0], "documento_e_valor", 1.0)

    def _estagio_valor_e_data(self) -> None:
        idx = self._indexar_razao(lambda r: (r["valor"], r["data"]))
        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            candidatos = [c for c in idx.get((e["valor"], e["data"]), []) if c in self._livres_raz]
            if candidatos:
                self._registrar(eid, candidatos[0], "valor_e_data", 0.95)

    def _estagio_valor_data_aproximada(self) -> None:
        idx = self._indexar_razao(lambda r: r["valor"])
        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            melhor, menor = None, None
            for rid in idx.get(e["valor"], []):
                if rid not in self._livres_raz:
                    continue
                dias = abs((e["data"] - self._raz[rid]["data"]).days)
                if dias <= self.p.janela_dias and (menor is None or dias < menor):
                    melhor, menor = rid, dias
            if melhor:
                self._registrar(
                    eid, melhor, "valor_data_aproximada", 0.85,
                    f"defasagem de {menor} dia(s) entre compensacao e competencia",
                )

    def _estagio_divergencia_valor(self) -> None:
        idx = self._indexar_razao(lambda r: r["documento"])
        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            if not e["documento"]:
                continue
            for rid in idx.get(e["documento"], []):
                if rid not in self._livres_raz:
                    continue
                r = self._raz[rid]
                if r["valor"] * e["valor"] <= 0:  # sinais opostos: nao e o mesmo fato
                    continue
                dif = abs(e["valor"] - r["valor"])
                limite = max(self.p.tolerancia_valor_abs, abs(e["valor"]) * self.p.tolerancia_valor_pct)
                if 0 < dif <= limite:
                    self._registrar(
                        eid, rid, "divergencia_valor", 0.70,
                        f"mesmo documento, diferenca de R$ {dif:,.2f}",
                    )
                    break

    def _estagio_similaridade(self) -> None:
        idx = self._indexar_razao(lambda r: r["valor"])
        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            melhor, melhor_score = None, 0.0
            for rid in idx.get(e["valor"], []):
                if rid not in self._livres_raz:
                    continue
                r = self._raz[rid]
                if abs((e["data"] - r["data"]).days) > self.p.janela_dias_similaridade:
                    continue
                score = _similaridade(e["historico"], r["historico"])
                if score > melhor_score:
                    melhor, melhor_score = rid, score
            if melhor and melhor_score >= self.p.similaridade_minima:
                self._registrar(
                    eid, melhor, "similaridade_historico", melhor_score,
                    f"historico similar ({melhor_score:.0%})",
                )

    def _estagio_agrupamento(self) -> None:
        """1 linha do extrato = soma de N linhas do razão (repasses, lotes)."""
        grupos: dict = {}
        for rid in self._livres_raz:
            r = self._raz[rid]
            grupos.setdefault((r["data"], r["valor"] > 0), []).append(rid)

        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            grupo = [g for g in grupos.get((e["data"], e["valor"] > 0), []) if g in self._livres_raz]
            if len(grupo) < 2 or len(grupo) > self.p.max_grupo_combinatorio:
                continue

            achou = None
            for tamanho in range(2, min(self.p.max_linhas_agrupamento, len(grupo)) + 1):
                for combo in combinations(grupo, tamanho):
                    soma = round(sum(self._raz[c]["valor"] for c in combo), 2)
                    if abs(soma - e["valor"]) < 0.01:
                        achou = combo
                        break
                if achou:
                    break

            if achou:
                for rid in achou:
                    self._registrar(
                        eid, rid, "agrupamento", 0.80,
                        f"lote de {len(achou)} lancamentos consolidados em 1 credito",
                    )
                self._livres_ext.discard(eid)

    # ------------------------------------------------------------------ #
    # Saída
    # ------------------------------------------------------------------ #

    def _montar_divergencias(self, pares: pd.DataFrame) -> pd.DataFrame:
        linhas = []

        for eid in sorted(self._livres_ext):
            e = self._ext[eid]
            linhas.append(
                {
                    "tipo": "nao_contabilizado",
                    "origem": "extrato",
                    "id": eid,
                    "data": e["data"],
                    "documento": e["documento"],
                    "historico": e["historico"],
                    "valor": e["valor"],
                    "detalhe": "Movimento no banco sem lancamento correspondente no razao",
                }
            )

        for rid in sorted(self._livres_raz):
            r = self._raz[rid]
            linhas.append(
                {
                    "tipo": "nao_compensado",
                    "origem": "razao",
                    "id": rid,
                    "data": r["data"],
                    "documento": r["documento"],
                    "historico": r["historico"],
                    "valor": r["valor"],
                    "detalhe": "Lancamento contabil sem compensacao bancaria",
                }
            )

        if not pares.empty:
            for _, p in pares[pares["metodo"] == "divergencia_valor"].iterrows():
                linhas.append(
                    {
                        "tipo": "divergencia_valor",
                        "origem": "ambos",
                        "id": f"{p['id_extrato']} / {p['id_razao']}",
                        "data": p["data_extrato"],
                        "documento": "",
                        "historico": p["historico_extrato"],
                        "valor": p["diferenca"],
                        "detalhe": p["observacao"],
                    }
                )
            for _, p in pares[pares["dias_defasagem"] != 0].iterrows():
                if p["metodo"] == "divergencia_valor":
                    continue
                linhas.append(
                    {
                        "tipo": "divergencia_data",
                        "origem": "ambos",
                        "id": f"{p['id_extrato']} / {p['id_razao']}",
                        "data": p["data_extrato"],
                        "documento": "",
                        "historico": p["historico_extrato"],
                        "valor": p["valor_extrato"],
                        "detalhe": f"defasagem de {int(p['dias_defasagem'])} dia(s)",
                    }
                )

        div = pd.DataFrame(linhas)
        if div.empty:
            return pd.DataFrame(
                columns=["tipo", "origem", "id", "data", "documento", "historico", "valor", "detalhe", "severidade"]
            )
        div["severidade"] = div["tipo"].map(SEVERIDADE)
        ordem = {"alta": 0, "baixa": 1}
        return div.sort_values(
            by=["severidade", "valor"],
            key=lambda s: s.map(ordem) if s.name == "severidade" else s.abs(),
            ascending=[True, False],
        ).reset_index(drop=True)

    def _resumo(self, pares: pd.DataFrame, divergencias: pd.DataFrame) -> dict:
        total_ext = len(self._ext)
        conciliados_ext = total_ext - len(self._livres_ext)
        graves = divergencias[divergencias["severidade"] == "alta"] if not divergencias.empty else divergencias
        return {
            "linhas_extrato": total_ext,
            "linhas_razao": len(self._raz),
            "conciliados": conciliados_ext,
            "taxa_conciliacao": round(conciliados_ext / total_ext, 4) if total_ext else 0.0,
            "pendentes_extrato": len(self._livres_ext),
            "pendentes_razao": len(self._livres_raz),
            "divergencias_totais": len(divergencias),
            "divergencias_criticas": len(graves),
            "valor_em_aberto": round(float(graves["valor"].abs().sum()), 2) if len(graves) else 0.0,
            "por_metodo": pares["metodo"].value_counts().to_dict() if not pares.empty else {},
        }


def conciliar(extrato: pd.DataFrame, razao: pd.DataFrame, parametros=None) -> dict:
    """Atalho funcional."""
    return Conciliador(parametros).conciliar(extrato, razao)
