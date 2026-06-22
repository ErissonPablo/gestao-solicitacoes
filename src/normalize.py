# -*- coding: utf-8 -*-
"""Normalizacao de nomes de compradores, chaves SC-ITEM e tipos de SC.

A planilha de distribuicao tem o nome do responsavel digitado a mao, com
dezenas de grafias para a mesma pessoa (erisson / ERISSON / Erisson...).
Os relatorios do Protheus usam o nome completo (ERISSON PABLO SOUSA).
Aqui consolidamos tudo em um nome canonico unico.
"""
from __future__ import annotations

import re
import unicodedata


# Equipe ativa em 2026 + historico. A chave de busca e o PRIMEIRO nome,
# sem acento e em maiusculo. O valor e o nome canonico para exibir.
CANONICO = {
    "ERISSON": "Erisson",
    "ELOISA": "Eloisa",
    "ALESSANDRO": "Alessandro",
    "ALESSADRO": "Alessandro",  # erro de digitacao
    "MARCOS": "Marcos",
    "NAGELLA": "Nagella",
    "NAGELA": "Nagella",  # erro de digitacao
    "NEGELA": "Nagella",  # erro de digitacao
    "EDUARDO": "Eduardo",
    # historico / nao mais no time de distribuicao
    "HERICLYS": "Hericlys",
    "HERCLYS": "Hericlys",  # erro de digitacao
    "BRUNNA": "Brunna",
    "BRUNA": "Brunna",
    "RAFAEL": "Rafael",
    "RAAFEL": "Rafael",  # erro de digitacao
    "HELOISA": "Eloisa",  # erro de digitacao (mesma pessoa)
    "ANA": "Ana Paula",
    "ESTHEFANE": "Esthefane",
    "ESTEFANE": "Esthefane",  # erro de digitacao
    "ESTEHAFENE": "Esthefane",  # erro de digitacao
    "ALEXANDRE": "Alexandre",
    "IASMIN": "Iasmin",
    "JU": "Juliane",
    "JULIANE": "Juliane",
    "JUMARA": "Jumara",
    "FELIX": "Felix",
    "GUSTAVO": "Gustavo",
    "MARCELO": "Marcelo",
    "MONICA": "Monica",
}

# Quem faz parte da equipe de compras hoje (atende/distribui em 2026).
EQUIPE_ATUAL = {"Erisson", "Eloisa", "Alessandro", "Marcos", "Nagella"}
# Eduardo (menor aprendiz): nao recebe distribuicao, apenas implanta pedidos.
IMPLANTADORES = {"Eduardo"}

# Apelidos especificos que nao batem pelo primeiro nome.
ALIAS_DIRETO = {
    "ERISON": "Erisson",
    "NAGELLA MAIARA JESUS PIRES": "Nagella",
    "ALESSANDRO CLAUDINO FILHO": "Alessandro",
    "ERISSON PABLO SOUSA": "Erisson",
    "ELOISA BATISTA": "Eloisa",
    "MARCOS VINICIO": "Marcos",
    "EDUARDO SILVA": "Eduardo",
    "HERICLYS AUGUSTO": "Hericlys",
    "ALEXANDRE BUENO DA SILVA FONSE": "Alexandre",
}


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


# Valores que NAO sao nome de pessoa (erros operacionais na planilha).
LIXO = {"#REF!", "ERRO", "ELIMINAR", "MATERIAL COMPRO", "ERIFLON"}


def norm_comprador(raw) -> str | None:
    """Devolve o nome canonico do comprador, ou None se nao reconhecido/lixo."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "none":
        return None
    # lixo: data colada na coluna (ex.: '2026-06-08 00:00:00')
    if re.match(r"^\d{4}-\d{2}-\d{2}", s) or re.match(r"^\d{2}/\d{2}/\d{4}", s):
        return None
    up = strip_accents(s).upper().strip()
    # remove caracteres estranhos de digitacao (ex.: 'nage]la' -> 'NAGELA')
    up = re.sub(r"[^A-Z/ ]", "", up).strip()
    if not up or up in LIXO:
        return None
    if up in ALIAS_DIRETO:
        return ALIAS_DIRETO[up]
    # nomes combinados 'A/B' ou 'A / B': pega o primeiro reconhecido
    for parte in re.split(r"[/]", up):
        primeiro = parte.split()[0] if parte.split() else ""
        if primeiro in CANONICO:
            return CANONICO[primeiro]
    return None


def tipo_codigo(raw) -> str | None:
    """'02/NORMAL' -> '02'; '03' -> '03'; aceita inteiros."""
    if raw is None:
        return None
    s = str(raw).strip()
    m = re.match(r"^(\d{1,2})", s)
    if not m:
        return None
    return m.group(1).zfill(2)


# Tipos que a equipe de compras atende.
TIPOS_COMPRAS = {"01", "02", "03", "07"}


def chave_sc(num_sc, item) -> str | None:
    """Chave canonica NUM.SC+ITEM: '052507-0008'. Padroniza zero-fill.

    base usa SC inteiro e item inteiro (28199, 1); os relatorios usam
    strings zero-padded ('052824', '0001'). Unificamos em 6+4 digitos.
    """
    if num_sc is None or item is None:
        return None
    sc = re.sub(r"\D", "", str(num_sc))
    it = re.sub(r"\D", "", str(item))
    if not sc or not it:
        return None
    return f"{int(sc):06d}-{int(it):04d}"
