# -*- coding: utf-8 -*-
"""Cruzamento das 3 fontes em um modelo unico de acompanhamento.

Fluxo da operacao:
    SC (demanda) -> distribuicao (responsavel) -> Pedido -> entrega

Saidas principais:
    build_sc_model()      -> 1 linha por SC-item (tipos 01/02/03/07), com flags
                             distribuida / com_pedido e o responsavel canonico.
    pendencias_entrega()  -> itens de pedido com saldo a receber.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import normalize as nz


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def dias_uteis(inicio, fim, feriados=None) -> float:
    """Dias uteis entre duas datas (NaN se faltar alguma)."""
    if pd.isna(inicio) or pd.isna(fim):
        return np.nan
    hol = [np.datetime64(pd.Timestamp(f).date()) for f in (feriados or [])]
    return float(
        np.busday_count(
            np.datetime64(pd.Timestamp(inicio).date()),
            np.datetime64(pd.Timestamp(fim).date()),
            holidays=hol,
        )
    )


# --------------------------------------------------------------------------- #
# Distribuicao -> mapa chave -> responsavel (mais recente)
# --------------------------------------------------------------------------- #
def mapa_distribuicao(dist: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por chave SC-ITEM com o responsavel canonico mais recente."""
    d = dist.copy()
    d["chave"] = [nz.chave_sc(s, i) for s, i in zip(d["NUM.SC"], d["ITEM"])]
    d["responsavel"] = d["RESPONSAVEL"].map(nz.norm_comprador)
    d["dt_distribuicao"] = d["DATA DISTRIBUIÇÃO"]
    d = d.dropna(subset=["chave"])
    # registros invalidos (lixo na coluna responsavel) ficam com responsavel None
    d["_lixo"] = d["responsavel"].isna()
    d = d.sort_values("dt_distribuicao")
    # responsavel valido mais recente (ignora linhas-lixo se houver alternativa)
    def ultimo_valido(serie):
        validos = serie.dropna()
        return validos.iloc[-1] if len(validos) else None

    agg = (
        d.groupby("chave")
        .agg(
            responsavel=("responsavel", ultimo_valido),
            dt_distribuicao=("dt_distribuicao", "last"),
            n_distribuicoes=("chave", "size"),
        )
        .reset_index()
    )
    agg["na_base"] = True  # a chave existe na base = foi distribuida
    return agg


# --------------------------------------------------------------------------- #
# Pedidos -> agregado por numero de pedido
# --------------------------------------------------------------------------- #
def agrega_pedidos(pcs: pd.DataFrame) -> pd.DataFrame:
    """Agrega itens de pedido por PEDIDO COMPRA (1 linha por pedido)."""
    p = pcs.copy()
    p["saldo"] = (p["QUANTIDADE"] - p["QUANT ENTREG"]).clip(lower=0)
    p["comprador"] = p["COMPRADOR"].map(nz.norm_comprador)
    g = (
        p.groupby("PEDIDO COMPRA")
        .agg(
            emissao_pc=("EMISSAO", "min"),
            comprador_pc=("comprador", "first"),
            fornecedor=("FORNECEDOR", "first"),
            qtd_total=("QUANTIDADE", "sum"),
            qtd_entregue=("QUANT ENTREG", "sum"),
            saldo=("saldo", "sum"),
            itens=("ITEM", "size"),
            encerrado=("ENCERRADO", lambda s: (s == "E").all()),
        )
        .reset_index()
    )
    g["entregue_total"] = g["saldo"] <= 1e-9
    return g


# --------------------------------------------------------------------------- #
# Modelo de SC (1 linha por SC-item, tipos de compras)
# --------------------------------------------------------------------------- #
def build_sc_model(
    scs: pd.DataFrame, dist: pd.DataFrame, somente_tipos_compras: bool = True
) -> pd.DataFrame:
    s = scs.copy()
    s["tipo_cod"] = s["TIPO"].map(nz.tipo_codigo)
    s["chave"] = [nz.chave_sc(n, i) for n, i in zip(s["NUM.SC"], s["ITEM"])]
    if somente_tipos_compras:
        s = s[s["tipo_cod"].isin(nz.TIPOS_COMPRAS)]

    # Colapsa rateio: 1 linha por SC-item. Soma qtd/valor; conta rateios.
    s["_pedido_norm"] = s["PEDIDO"].astype(str).str.strip()
    agg = (
        s.sort_values("DT.EMISSAO")
        .groupby("chave")
        .agg(
            FILIAL=("FILIAL", "first"),
            tipo_cod=("tipo_cod", "first"),
            TIPO=("TIPO", "first"),
            **{"NUM.SC": ("NUM.SC", "first"), "ITEM": ("ITEM", "first")},
            PRODUTO=("PRODUTO", "first"),
            DESCRICAO=("DESCRICAO", "first"),
            QTD=("QTD.SOLICITADA", "sum"),
            VALOR=("TOTAL ITEM", "sum"),
            DT_EMISSAO=("DT.EMISSAO", "first"),
            DT_NECESSIDADE=("DT.NECESSIDADE", "first"),
            SOLICITANTE=("SOLICITANTE", "first"),
            DESC_DEPARTAMENTO=("DESC.DEPARTAMENTO", "first"),
            URGENCIA=("URGENCIA", "first"),
            APROVADO=("APROVADO?", "first"),
            LEGENDA=("Legenda", "first"),
            PEDIDO=("_pedido_norm", "first"),
            n_rateios=("chave", "size"),
        )
        .reset_index()
    )

    # Junta distribuicao
    md = mapa_distribuicao(dist)
    agg = agg.merge(md, on="chave", how="left")

    # distribuida = a chave esta na base (independe de o nome ser reconhecido)
    agg["distribuida"] = agg["na_base"].eq(True)
    agg["responsavel"] = agg["responsavel"].where(agg["responsavel"].notna(), None)
    agg["com_pedido"] = agg["PEDIDO"].fillna("").str.strip().ne("") & agg[
        "PEDIDO"
    ].fillna("").str.strip().ne("nan")
    return agg


# --------------------------------------------------------------------------- #
# Pendencias de entrega (nivel item de pedido)
# --------------------------------------------------------------------------- #
def pendencias_entrega(pcs: pd.DataFrame, hoje=None) -> pd.DataFrame:
    p = pcs.copy()
    p["saldo"] = (p["QUANTIDADE"] - p["QUANT ENTREG"]).clip(lower=0)
    p["comprador"] = p["COMPRADOR"].map(nz.norm_comprador)
    pend = p[(p["saldo"] > 1e-9) & (p["ENCERRADO"] != "E")].copy()
    hoje = pd.Timestamp(hoje) if hoje is not None else pd.Timestamp.today().normalize()
    pend["dias_em_aberto"] = (hoje - pend["EMISSAO"]).dt.days
    return pend
