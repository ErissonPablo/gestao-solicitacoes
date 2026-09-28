# -*- coding: utf-8 -*-
"""Historico: a vida de cada SC-item ao longo das extracoes.

O rmatr029 sai com "Apenas Pendentes": quando a SC e atendida ela some do
relatorio e o historico se perdia. A cada subida das planilhas comparamos a
foto atual com o que esta no banco e gravamos o que mudou:

    emitida -> distribuida (quem) -> redistribuida -> virou pedido ->
    entregue -> saiu do relatorio (e, se for o caso, voltou)

Regras de seguranca:
  - so grava se a extracao for igual ou mais nova que a ultima gravada
    (subir um arquivo velho nao "volta no tempo");
  - a mesma combinacao de arquivos (assinatura) so e gravada uma vez.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

import pandas as pd

EVENTO_LABEL = {
    "emitida": "SC emitida",
    "distribuida": "Distribuida",
    "redistribuida": "Redistribuida",
    "pedido": "Virou pedido",
    "entregue": "Pedido entregue",
    "status": "Mudou status de aprovacao",
    "saiu": "Saiu do rmatr029 (encerrada)",
    "voltou": "Voltou ao rmatr029",
}
EVENTO_ICONE = {
    "emitida": "🧾", "distribuida": "👤", "redistribuida": "🔁", "pedido": "🛒",
    "entregue": "📦", "status": "🔒", "saiu": "✅", "voltou": "↩️",
}


def assinatura(*partes: bytes) -> str:
    h = hashlib.sha1()
    for p in partes:
        h.update(hashlib.sha1(p or b"").digest())
    return h.hexdigest()


def _d(v) -> str | None:
    """Data -> 'YYYY-MM-DD' (ou None)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _s(v) -> str | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


def _n(v) -> float | None:
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _agora() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def ultima_carga(banco) -> dict | None:
    linhas = banco.select("carga", ordem="ref_sc.desc")
    return linhas[0] if linhas else None


def _indice_pedidos(pcs_itens: pd.DataFrame | None) -> dict:
    """(produto, data da solicitacao) -> linhas de pedido. O rmatr052 nao traz o
    numero da SC; produto + data da SC (+ quantidade) identificam o pedido."""
    if pcs_itens is None or not len(pcs_itens):
        return {}
    p = pcs_itens.copy()
    p["_k"] = list(zip(p["PRODUTO"].astype(str).str.strip(),
                       pd.to_datetime(p["DATA SOLICIT"], errors="coerce").dt.strftime("%Y-%m-%d")))
    return {k: g for k, g in p.groupby("_k")}


def _achar_pedido(indice: dict, produto, dt_emissao, qtd):
    """Devolve a linha do pedido que atendeu o SC-item, se for inequivoca."""
    if not produto or not dt_emissao:
        return None
    g = indice.get((str(produto).strip(), dt_emissao))
    if g is None or not len(g):
        return None
    if g["PEDIDO COMPRA"].nunique() > 1 and qtd is not None:
        g = g[(g["QUANTIDADE"] - qtd).abs() < 1e-6]
    if g["PEDIDO COMPRA"].nunique() != 1:
        return None
    return g.iloc[0]


def _item_entregue(linha) -> bool:
    leg = str(linha.get("Legenda", "")).upper()
    if "ELIMINAD" in leg:
        return False
    return (float(linha.get("QUANT ENTREG") or 0) >= float(linha.get("QUANTIDADE") or 0) > 0
            or "RECEBIDO " in leg and "PARCIAL" not in leg)


def sincronizar(banco, model: pd.DataFrame, ped_agg: pd.DataFrame, refs: dict,
                assin: str, usuario: str | None = None, arquivos: dict | None = None,
                pcs_itens: pd.DataFrame | None = None) -> dict:
    """Compara a foto atual com o banco e grava itens + eventos.

    refs: {'sc': 'YYYY-MM-DD', 'pc': ..., 'dist': ...} (data interna de cada arquivo)
    Devolve um resumo {'status', 'mensagem', 'novos', 'eventos', ...}.
    """
    ref_sc = refs.get("sc")
    if not ref_sc:
        return {"status": "ignorado", "mensagem": "Extracao sem data (DT.REF) no rmatr029."}

    cargas = banco.select("carga", colunas=["id", "assinatura", "ref_sc"])
    if any(c.get("assinatura") == assin for c in cargas):
        return {"status": "ja_gravado", "mensagem": "Estes arquivos ja estao no historico."}
    mais_nova = max((c["ref_sc"] for c in cargas if c.get("ref_sc")), default=None)
    if mais_nova and ref_sc < mais_nova:
        return {"status": "antigo",
                "mensagem": f"Extracao de {ref_sc} e mais antiga que a ultima gravada "
                            f"({mais_nova}); o historico nao foi alterado."}

    antes = {r["chave"]: r for r in banco.select("sc_item")}
    pedidos = {}
    if ped_agg is not None and len(ped_agg):
        for _, p in ped_agg.iterrows():
            pedidos[str(p["PEDIDO COMPRA"]).strip()] = p

    indice = _indice_pedidos(pcs_itens)
    agora = _agora()
    itens, eventos = [], []

    def ev(chave, tipo, data, detalhe=None):
        eventos.append({"chave": chave, "evento": tipo, "data": data or ref_sc,
                        "detalhe": detalhe, "criado_em": agora})

    vistos = set()
    for _, r in model.iterrows():
        chave = r["chave"]
        vistos.add(chave)
        velho = antes.get(chave)
        resp = _s(r.get("responsavel"))
        pedido = _s(r.get("PEDIDO")) if r.get("com_pedido") else None
        if pedido in ("nan",):
            pedido = None
        dt_ped = _d(r.get("DT_EMIS_PC"))
        info_pc = pedidos.get(pedido) if pedido else None
        entregue = bool(info_pc["entregue_total"]) if info_pc is not None else False
        aprovado = _s(r.get("APROVADO"))

        novo = {
            "chave": chave, "num_sc": _s(r.get("NUM.SC")), "item": _s(r.get("ITEM")),
            "tipo_cod": _s(r.get("tipo_cod")), "produto": _s(r.get("PRODUTO")),
            "descricao": _s(r.get("DESCRICAO")), "qtd": _n(r.get("QTD")),
            "valor": _n(r.get("VALOR")), "solicitante": _s(r.get("SOLICITANTE")),
            "departamento": _s(r.get("DESC_DEPARTAMENTO")),
            "urgencia": _s(r.get("URGENCIA")), "aprovado": aprovado,
            "dt_emissao": _d(r.get("DT_EMISSAO")),
            "dt_necessidade": _d(r.get("DT_NECESSIDADE")),
            "responsavel": resp or (velho or {}).get("responsavel"),
            "dt_distribuicao": _d(r.get("dt_distribuicao")) or (velho or {}).get("dt_distribuicao"),
            "pedido": pedido or (velho or {}).get("pedido"),
            "dt_pedido": dt_ped or (velho or {}).get("dt_pedido"),
            "entregue": entregue or bool((velho or {}).get("entregue")),
            "dt_entrega": (velho or {}).get("dt_entrega"),
            "primeira_vez": (velho or {}).get("primeira_vez") or ref_sc,
            "ultima_vez": ref_sc, "dt_saiu": None, "atualizado_em": agora,
        }

        if velho is None:
            ev(chave, "emitida", novo["dt_emissao"], aprovado)
            if resp:
                ev(chave, "distribuida", novo["dt_distribuicao"], resp)
            if pedido:
                ev(chave, "pedido", dt_ped, pedido)
        else:
            if velho.get("situacao") == "saiu":
                ev(chave, "voltou", ref_sc)
            if resp and not velho.get("responsavel"):
                ev(chave, "distribuida", novo["dt_distribuicao"], resp)
            elif resp and velho.get("responsavel") and resp != velho.get("responsavel"):
                ev(chave, "redistribuida", novo["dt_distribuicao"],
                   f"{velho.get('responsavel')} → {resp}")
            if pedido and not velho.get("pedido"):
                ev(chave, "pedido", dt_ped, pedido)
            if aprovado and velho.get("aprovado") and aprovado != velho.get("aprovado"):
                ev(chave, "status", ref_sc, f"{velho.get('aprovado')} → {aprovado}")

        if novo["entregue"] and not (velho or {}).get("entregue"):
            novo["dt_entrega"] = refs.get("pc") or ref_sc
            ev(chave, "entregue", novo["dt_entrega"], novo["pedido"])

        novo["situacao"] = ("entregue" if novo["entregue"] else
                            "com_pedido" if novo["pedido"] else "aberta")
        itens.append(novo)

    # Sumiram do rmatr029 (Apenas Pendentes) desde a ultima foto -> encerradas
    for chave, velho in antes.items():
        if chave in vistos:
            continue
        if velho.get("situacao") == "saiu":
            # ja encerrada: so acompanha a entrega do pedido
            ped = velho.get("pedido")
            if ped and not velho.get("entregue"):
                info = pedidos.get(ped)
                if info is not None and bool(info["entregue_total"]):
                    itens.append({**velho, "entregue": True,
                                  "dt_entrega": refs.get("pc") or ref_sc,
                                  "atualizado_em": agora})
                    ev(chave, "entregue", refs.get("pc") or ref_sc, ped)
            continue
        # atualiza entrega pelo rmatr052 mesmo fora do rmatr029
        pedido = velho.get("pedido")
        info_pc = pedidos.get(pedido) if pedido else None
        entregue = bool(velho.get("entregue")) or (
            bool(info_pc["entregue_total"]) if info_pc is not None else False)
        linha = {**velho, "situacao": "saiu", "dt_saiu": ref_sc, "entregue": entregue,
                 "atualizado_em": agora}
        if not pedido:  # saiu sem pedido conhecido: procura no rmatr052
            achado = _achar_pedido(indice, velho.get("produto"), velho.get("dt_emissao"),
                                   _n(velho.get("qtd")))
            if achado is not None:
                pedido = str(achado["PEDIDO COMPRA"]).strip()
                linha["pedido"] = pedido
                linha["dt_pedido"] = _d(achado.get("EMISSAO"))
                ev(chave, "pedido", linha["dt_pedido"],
                   f"{pedido} · {_s(achado.get('FORNECEDOR')) or ''}".strip(" ·"))
                entregue = entregue or _item_entregue(achado)
                linha["entregue"] = entregue
        if entregue and not velho.get("entregue"):
            linha["dt_entrega"] = refs.get("pc") or ref_sc
            ev(chave, "entregue", linha["dt_entrega"], pedido)
        ev(chave, "saiu", ref_sc, pedido)
        itens.append(linha)

    carga = banco.insert("carga", [{
        "criado_em": agora, "usuario": usuario, "assinatura": assin,
        "ref_sc": ref_sc, "ref_pc": refs.get("pc"), "ref_dist": refs.get("dist"),
        "n_itens": len(model), "n_eventos": len(eventos),
        "arquivos": arquivos or {},
    }])[0]
    cols = [c for c in itens[0].keys()] if itens else []
    itens = [{k: it.get(k) for k in cols} for it in itens]  # mesmas chaves (PostgREST)
    banco.upsert("sc_item", itens)
    for e in eventos:
        e["carga_id"] = carga.get("id")
    banco.insert("sc_evento", eventos)

    novos = sum(1 for e in eventos if e["evento"] == "emitida")
    return {"status": "gravado", "novos": novos, "eventos": len(eventos),
            "saidas": sum(1 for e in eventos if e["evento"] == "saiu"),
            "pedidos": sum(1 for e in eventos if e["evento"] == "pedido"),
            "mensagem": f"Historico atualizado: {novos} SC-itens novos, "
                        f"{len(eventos)} eventos registrados."}


def eventos_da_sc(banco, chave: str) -> list[dict]:
    return banco.select("sc_evento", {"chave": chave}, ordem="data.asc")


def log_da_sc(banco, chave: str) -> list[dict]:
    return banco.select("sc_acompanhamento_log", {"chave": chave}, ordem="em.asc")


def registrar_marcacao(banco, chave, campo, antigo, novo, usuario):
    banco.insert("sc_acompanhamento_log", [{
        "chave": chave, "campo": campo,
        "valor_antigo": None if antigo is None else str(antigo),
        "valor_novo": None if novo is None else str(novo),
        "usuario": usuario, "em": _agora()}])


def importar_inicial(banco, caminho) -> dict | None:
    """Importa um historico montado a partir de extracoes antigas
    (data/historico_inicial.json). So roda com o banco vazio; depois renomeia
    o arquivo para .importado, para nunca repetir."""
    import json
    from pathlib import Path

    caminho = Path(caminho)
    if not caminho.exists():
        return None
    if banco.select("carga", colunas=["id"]):
        return None
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    mapa = {}
    for c in sorted(dados["cargas"], key=lambda x: x["ref_sc"] or ""):
        id_local = c.pop("id")
        mapa[id_local] = banco.insert("carga", [c])[0]["id"]
    banco.upsert("sc_item", dados["itens"])
    evs = [{**e, "carga_id": mapa.get(e.get("carga_id"))} for e in dados["eventos"]]
    banco.insert("sc_evento", evs)
    caminho.rename(caminho.with_suffix(".json.importado"))
    return {"status": "gravado",
            "mensagem": f"Historico inicial importado: {len(dados['itens'])} SC-itens, "
                        f"{len(evs)} eventos ({len(mapa)} extracoes antigas)."}
