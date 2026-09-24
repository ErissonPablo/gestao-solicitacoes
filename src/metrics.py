# -*- coding: utf-8 -*-
"""Indicadores do painel (derivados do modelo de SC e das pendencias).

Tudo aqui e calculo puro sobre DataFrames: nada de Streamlit, para poder
testar/validar isoladamente (ex.: no reconcile.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAIXAS_IDADE = [
    (0, 7, "0-7 dias"),
    (8, 15, "8-15 dias"),
    (16, 30, "16-30 dias"),
    (31, 60, "31-60 dias"),
    (61, 10**6, "60+ dias"),
]
ORDEM_FAIXAS = [f[2] for f in FAIXAS_IDADE]
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"]


def faixa_idade(dias) -> str | None:
    if pd.isna(dias):
        return None
    for ini, fim, rot in FAIXAS_IDADE:
        if ini <= dias <= fim:
            return rot
    return ORDEM_FAIXAS[0] if dias < 0 else ORDEM_FAIXAS[-1]


def enriquecer(model: pd.DataFrame, hoje: pd.Timestamp) -> pd.DataFrame:
    """Colunas derivadas usadas em varias telas."""
    m = model.copy()
    m["idade_dias"] = (hoje - m["DT_EMISSAO"]).dt.days
    m["faixa_idade"] = m["idade_dias"].map(faixa_idade)
    inicio = m["DT_LIBERACAO"].fillna(m["DT_EMISSAO"])
    m["lead_time_dias"] = np.where(
        m["com_pedido"] & m["DT_EMIS_PC"].notna(),
        (m["DT_EMIS_PC"] - inicio).dt.days.clip(lower=0),
        np.nan,
    )
    nec = m["DT_NECESSIDADE"]
    m["vencida"] = (~m["com_pedido"]) & nec.notna() & (nec < hoje)
    m["dias_atraso"] = np.where(m["vencida"], (hoje - nec).dt.days, np.nan)
    m["urgente"] = m["URGENCIA"].fillna("").astype(str).str.upper().eq("ALTA")
    m["status"] = np.select(
        [m["com_pedido"], m["distribuida"]],
        ["Com pedido", "Distribuida, sem pedido"],
        default="Sem dono e sem pedido",
    )
    return m


def funil(mf: pd.DataFrame, pend: pd.DataFrame, ped_agg: pd.DataFrame) -> pd.DataFrame:
    """SC-itens -> distribuidas -> com pedido -> pedido entregue."""
    com_ped = mf[mf["com_pedido"]]
    entregues = 0
    if len(com_ped) and len(ped_agg):
        ok = ped_agg.set_index(ped_agg["PEDIDO COMPRA"].astype(str))["entregue_total"]
        entregues = int(com_ped["PEDIDO"].astype(str).map(ok).fillna(False).astype(bool).sum())
    return pd.DataFrame({
        "etapa": ["SC-itens aprovados", "Distribuidos", "Viraram pedido", "Pedido entregue"],
        "qtd": [len(mf), int(mf["distribuida"].sum()), len(com_ped), entregues],
    })


def backlog_por_faixa(backlog: pd.DataFrame) -> pd.DataFrame:
    g = (backlog.groupby("faixa_idade")
         .agg(qtd=("chave", "size"), valor=("VALOR", "sum"))
         .reindex(ORDEM_FAIXAS).fillna(0).reset_index())
    return g


def tendencia_mensal(mf: pd.DataFrame) -> pd.DataFrame:
    """SC-itens emitidos x atendidos (viraram pedido) por mes."""
    em = mf.dropna(subset=["DT_EMISSAO"]).groupby(
        mf["DT_EMISSAO"].dt.to_period("M")).size().rename("Emitidas")
    at = mf[mf["com_pedido"]].dropna(subset=["DT_EMIS_PC"])
    at = at.groupby(at["DT_EMIS_PC"].dt.to_period("M")).size().rename("Atendidas")
    t = pd.concat([em, at], axis=1).fillna(0).sort_index()
    if t.empty:
        return pd.DataFrame(columns=["mes", "Emitidas", "Atendidas"])
    t = t.reindex(pd.period_range(t.index.min(), t.index.max(), freq="M"), fill_value=0)
    t["mes"] = [f"{MESES_PT[p.month - 1]}/{str(p.year)[2:]}" for p in t.index]
    return t.reset_index(drop=True)[["mes", "Emitidas", "Atendidas"]].astype(
        {"Emitidas": int, "Atendidas": int})


def carga_comprador(mf: pd.DataFrame) -> pd.DataFrame:
    d = mf[mf["distribuida"] & mf["responsavel"].notna()]
    if d.empty:
        return pd.DataFrame(columns=["responsavel", "Com pedido", "Sem pedido",
                                     "total", "valor_backlog", "lead_mediano", "vencidas"])
    g = d.groupby("responsavel").agg(
        **{"Com pedido": ("com_pedido", "sum"),
           "Sem pedido": ("com_pedido", lambda s: int((~s).sum())),
           "total": ("chave", "size"),
           "vencidas": ("vencida", "sum"),
           "lead_mediano": ("lead_time_dias", "median")},
    )
    g["valor_backlog"] = d[~d["com_pedido"]].groupby("responsavel")["VALOR"].sum()
    g = g.fillna({"valor_backlog": 0}).reset_index()
    g["pct_pendente"] = (g["Sem pedido"] / g["total"] * 100).round(0)
    return g.sort_values("total", ascending=False)


def departamentos_backlog(backlog: pd.DataFrame, top: int = 8) -> pd.DataFrame:
    return (backlog.assign(DEP=backlog["DESC_DEPARTAMENTO"].fillna("(sem depto)"))
            .groupby("DEP").agg(qtd=("chave", "size"), valor=("VALOR", "sum"))
            .sort_values("qtd", ascending=False).head(top).reset_index())


def resumo_lead_time(mf: pd.DataFrame) -> dict:
    lt = mf["lead_time_dias"].dropna()
    if lt.empty:
        return {"mediana": None, "media": None, "p90": None, "n": 0}
    return {"mediana": float(lt.median()), "media": float(lt.mean()),
            "p90": float(lt.quantile(0.9)), "n": int(len(lt))}
