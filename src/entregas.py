# -*- coding: utf-8 -*-
"""Acompanhamento das entregas pendentes, por PEDIDO.

- Nova previsao de entrega (manual ou vinda de e-mail), com historico.
- E-mails vinculados ao pedido (tabela pedido_email). Quem preenche essa tabela
  e a leitura automatica da caixa de e-mail (feita fora do app); o app so le.

Vinculo de e-mail -> pedido:
  1. pedido informado no proprio e-mail (assunto "LCO/Pedido de Compra - 169688",
     ou "pedido 169688" no texto)
     Tipo "pedido": o e-mail do pedido enviado ao fornecedor, so para registrar a
     data de entrega combinada (nao conta como retorno do fornecedor).
  2. e-mail de rastreio da transportadora (so tem NF + remetente): vai para o
     pedido cuja NF ja apareceu num e-mail do fornecedor; senao, para os pedidos
     pendentes daquele fornecedor (pelo nome).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

import pandas as pd

COLS_PREV = ["pedido", "nova_previsao", "obs", "fonte", "atualizado_por", "atualizado_em"]
COLS_EMAIL = ["id", "message_id", "pedido", "tipo", "recebido_em", "remetente",
              "remetente_nome", "fornecedor", "assunto", "resumo", "nf", "previsao",
              "situacao", "link", "corpo"]

_PALAVRAS_VAZIAS = {"LTDA", "ME", "EPP", "EIRELI", "SA", "S/A", "S.A", "IND", "INDUSTRIA",
                    "COM", "COMERCIO", "E", "DE", "DO", "DA", "DOS", "DAS", "EM", "LTD",
                    "INDL", "COML", "CIA", "IMP", "EXP", "IND.", "COM.", "COMERCIAL",
                    "INDUSTRIAL", "MAQUINAS", "PRODUTOS", "SERVICOS"}


def _agora() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def norm_pedido(v) -> str | None:
    """'169688', '169.688', 169688.0 -> '169688' (sem zeros a esquerda ate 6 digitos)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    d = re.sub(r"\D", "", str(v).split(".")[0] if isinstance(v, float) else str(v))
    return d.zfill(6) if d else None


def norm_nf(v) -> str | None:
    """'1 017400', '17.400', '017400' -> '17400' (so os digitos do numero)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    partes = s.split()
    if len(partes) > 1:  # "1 017400" -> serie + numero
        s = partes[-1]
    d = re.sub(r"\D", "", s).lstrip("0")
    return d or None


def _tokens(nome) -> list[str]:
    s = "".join(c for c in unicodedata.normalize("NFD", str(nome or ""))
                if unicodedata.category(c) != "Mn").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return [t for t in s.split() if t not in _PALAVRAS_VAZIAS and len(t) > 1]


def mesmo_fornecedor(a, b) -> bool:
    """Compara nomes truncados/abreviados: 'IMPERIAL COM DE PARAFUSO FERR' x
    'IMPERIAL COMERCIO DE PARAFUSOS E FERRAMENTAS LTDA'."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if ta[0] != tb[0] and not (ta[0].startswith(tb[0]) or tb[0].startswith(ta[0])):
        return False
    if len(ta) == 1 or len(tb) == 1:
        return True
    # segunda palavra significativa compativel (prefixo, por causa do truncamento)
    return ta[1][:4] == tb[1][:4] or ta[1].startswith(tb[1]) or tb[1].startswith(ta[1])


# --------------------------------------------------------------------------- #
# Leitura / gravacao
# --------------------------------------------------------------------------- #
def carregar_previsoes(banco) -> pd.DataFrame:
    rows = banco.select("pedido_entrega", colunas=COLS_PREV) if banco is not None else []
    df = pd.DataFrame(rows, columns=COLS_PREV)
    df["pedido"] = df["pedido"].map(norm_pedido)
    df["nova_previsao"] = pd.to_datetime(df["nova_previsao"], errors="coerce")
    return df


def carregar_emails(banco) -> pd.DataFrame:
    rows = banco.select("pedido_email", colunas=COLS_EMAIL) if banco is not None else []
    df = pd.DataFrame(rows, columns=COLS_EMAIL)
    # data combinada no pedido nao conta: a previsao vem do fornecedor/transportadora
    df = df[df["tipo"].fillna("") != "pedido"].reset_index(drop=True)
    df["pedido"] = df["pedido"].map(norm_pedido)
    df["nf_n"] = df["nf"].map(norm_nf)
    df["recebido_em"] = pd.to_datetime(df["recebido_em"], errors="coerce", utc=True) \
        .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
    df["previsao"] = pd.to_datetime(df["previsao"], errors="coerce")
    return df


def historico_previsao(banco, pedido: str) -> list[dict]:
    if banco is None:
        return []
    rows = banco.select("pedido_entrega_log", {"pedido": pedido}, ordem="em.desc")
    return rows


def salvar_previsao(banco, pedido: str, nova: date | None, obs: str | None,
                    usuario: str, anterior=None, fonte: str = "manual"):
    pedido = norm_pedido(pedido)
    nova_s = nova.isoformat() if nova else None
    banco.upsert("pedido_entrega", [{
        "pedido": pedido, "nova_previsao": nova_s, "obs": (obs or "").strip() or None,
        "fonte": fonte, "atualizado_por": usuario, "atualizado_em": _agora()}])
    ant = None
    if anterior is not None and pd.notna(anterior):
        ant = pd.Timestamp(anterior).date().isoformat()
    banco.insert("pedido_entrega_log", [{
        "pedido": pedido, "previsao_antiga": ant, "previsao_nova": nova_s,
        "obs": (obs or "").strip() or None, "fonte": fonte, "usuario": usuario,
        "em": _agora()}])


# --------------------------------------------------------------------------- #
# Vinculo e-mail -> pedido
# --------------------------------------------------------------------------- #
def vincular(pedidos: pd.DataFrame, emails: pd.DataFrame) -> pd.DataFrame:
    """pedidos: 1 linha por pedido com PEDIDO, FORNECEDOR, EMISSAO.
    Devolve os e-mails com a coluna 'pedido_vinc' (um e-mail pode ir para
    mais de um pedido do mesmo fornecedor) e 'como' (pedido | nf | fornecedor)."""
    if emails.empty or pedidos.empty:
        return emails.assign(pedido_vinc=pd.Series(dtype=str), como=pd.Series(dtype=str))
    ped_set = set(pedidos["PEDIDO"])
    saida = []
    diretos = emails[emails["pedido"].isin(ped_set)]
    for _, e in diretos.iterrows():
        saida.append({**e.to_dict(), "pedido_vinc": e["pedido"], "como": "pedido"})
    # NF citada em e-mail de pedido conhecido
    nf_ped = {}
    for _, e in diretos.dropna(subset=["nf_n"]).iterrows():
        nf_ped.setdefault(e["nf_n"], set()).add(e["pedido"])
    soltos = emails[~emails["pedido"].isin(ped_set)]
    for _, e in soltos.iterrows():
        alvo, como = set(), ""
        if pd.notna(e["nf_n"]) and e["nf_n"] in nf_ped:
            alvo, como = nf_ped[e["nf_n"]], "nf"
        elif e.get("fornecedor"):
            cand = pedidos[pedidos["FORNECEDOR"].map(
                lambda f, x=e["fornecedor"]: mesmo_fornecedor(x, f))]
            if pd.notna(e["recebido_em"]):
                cand = cand[cand["EMISSAO"] <= e["recebido_em"] + pd.Timedelta(days=1)]
            alvo, como = set(cand["PEDIDO"]), "fornecedor"
        for ped in alvo:
            saida.append({**e.to_dict(), "pedido_vinc": ped, "como": como})
    return pd.DataFrame(saida)


def resumo_por_pedido(pedidos: pd.DataFrame, previsoes: pd.DataFrame,
                      emails_v: pd.DataFrame, hoje=None) -> pd.DataFrame:
    """Uma linha por pedido com a previsao em vigor e os indicadores."""
    hoje = pd.Timestamp(hoje) if hoje is not None else pd.Timestamp.today().normalize()
    r = pedidos.merge(previsoes.rename(columns={"pedido": "PEDIDO"}), on="PEDIDO",
                      how="left")
    if not emails_v.empty:
        ev = emails_v.sort_values("recebido_em")
        # tipo "pedido" = o proprio e-mail do pedido (data combinada); nao e retorno
        retorno = ev[ev["tipo"].fillna("") != "pedido"]
        ult = retorno.groupby("pedido_vinc").agg(
            n_emails=("message_id", "nunique"),
            ult_email=("recebido_em", "max"))
        # previsao mais recente informada por e-mail (transportadora ou fornecedor)
        com_prev = ev.dropna(subset=["previsao"])
        prev_mail = com_prev.groupby("pedido_vinc").agg(
            previsao_email=("previsao", "last"),
            previsao_email_em=("recebido_em", "last"),
            previsao_email_de=("remetente_nome", "last"))
        sit = ev.dropna(subset=["situacao"]).groupby("pedido_vinc").agg(
            ult_situacao=("situacao", "last"))
        r = r.merge(ult, left_on="PEDIDO", right_index=True, how="left") \
             .merge(prev_mail, left_on="PEDIDO", right_index=True, how="left") \
             .merge(sit, left_on="PEDIDO", right_index=True, how="left")
    for c in ("n_emails", "ult_email", "previsao_email", "previsao_email_em",
              "previsao_email_de", "ult_situacao"):
        if c not in r.columns:
            r[c] = pd.NA
    r["n_emails"] = r["n_emails"].fillna(0).astype(int)
    # previsao em vigor: a informada por ultimo (manual x e-mail)
    usar_mail = r["previsao_email"].notna() & (
        r["nova_previsao"].isna()
        | (pd.to_datetime(r["previsao_email_em"]) >
           pd.to_datetime(r["atualizado_em"], errors="coerce", utc=True)
           .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)))
    r["previsao"] = r["nova_previsao"].where(~usar_mail, r["previsao_email"])
    r["previsao_fonte"] = "manual"
    r.loc[usar_mail, "previsao_fonte"] = "e-mail"
    r.loc[r["previsao"].isna(), "previsao_fonte"] = None
    r["dias_para_previsao"] = (r["previsao"] - hoje).dt.days
    r["atrasado"] = r["previsao"].notna() & (r["dias_para_previsao"] < 0) & ~r["chegou"]
    r["vence_logo"] = r["previsao"].notna() & r["dias_para_previsao"].between(0, 3) \
        & ~r["chegou"]
    # previsao pendente: ninguem informou data (nem e-mail, nem manual)
    r["sem_retorno"] = r["previsao"].isna() & ~r["chegou"]
    return r
