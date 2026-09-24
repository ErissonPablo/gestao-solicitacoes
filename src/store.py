# -*- coding: utf-8 -*-
"""Acompanhamento manual por SC-item: 'Atendida' e 'Onde encontrar'.

As marcacoes ficam salvas pela chave SC-ITEM ('052507-0008'), entao
sobrevivem a cada nova subida das planilhas do Protheus.

Onde salvar (escolhido automaticamente):
  - Supabase, se .streamlit/secrets.toml tiver supabase_url e supabase_key
    -> toda a equipe ve as mesmas marcacoes (recomendado p/ Streamlit Cloud).
  - Senao, SQLite local em data/acompanhamento.db
    -> funciona quando o app roda sempre no mesmo PC (run.bat / run-rede.bat).
  - Modo demonstracao: memoria (nao grava nada).

Tabela no Supabase: ver sql/acompanhamento.sql
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

COLS = ["chave", "atendida", "atendida_por", "atendida_em", "onde_encontrar",
        "atualizado_por", "atualizado_em"]
TABELA = "sc_acompanhamento"


def _agora() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _vazio() -> pd.DataFrame:
    return pd.DataFrame(columns=COLS)


def _campos_salvar(atendida, onde, usuario, anterior: dict | None) -> dict:
    """Monta o registro completo, preservando o que nao mudou."""
    reg = dict(anterior or {})
    if atendida is not None:
        reg["atendida"] = bool(atendida)
        reg["atendida_por"] = usuario if atendida else None
        reg["atendida_em"] = _agora() if atendida else None
    if onde is not None:
        onde = " ".join(str(onde).split()).strip()
        reg["onde_encontrar"] = onde.upper() or None
    reg["atualizado_por"] = usuario
    reg["atualizado_em"] = _agora()
    reg.setdefault("atendida", False)
    return reg


class MemoriaStore:
    nome = "Memoria (demonstracao - nada e gravado)"
    compartilhado = False

    def __init__(self):
        self._d: dict[str, dict] = {}

    def carregar(self) -> pd.DataFrame:
        if not self._d:
            return _vazio()
        return pd.DataFrame([{"chave": k, **v} for k, v in self._d.items()])[COLS]

    def salvar(self, chave: str, usuario: str, atendida=None, onde=None):
        self._d[chave] = _campos_salvar(atendida, onde, usuario, self._d.get(chave))


class SQLiteStore:
    compartilhado = False

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.nome = f"Arquivo local ({self.caminho.name})"
        with self._con() as c:
            c.execute(f"""CREATE TABLE IF NOT EXISTS {TABELA} (
                chave TEXT PRIMARY KEY, atendida INTEGER DEFAULT 0,
                atendida_por TEXT, atendida_em TEXT, onde_encontrar TEXT,
                atualizado_por TEXT, atualizado_em TEXT)""")

    def _con(self):
        return sqlite3.connect(self.caminho, timeout=10)

    def carregar(self) -> pd.DataFrame:
        with self._con() as c:
            df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM {TABELA}", c)
        df["atendida"] = df["atendida"].fillna(0).astype(bool)
        return df

    def salvar(self, chave: str, usuario: str, atendida=None, onde=None):
        with self._con() as c:
            row = c.execute(f"SELECT {', '.join(COLS)} FROM {TABELA} WHERE chave=?",
                            (chave,)).fetchone()
            anterior = dict(zip(COLS, row)) if row else None
            reg = _campos_salvar(atendida, onde, usuario, anterior)
            reg["chave"] = chave
            c.execute(
                f"INSERT OR REPLACE INTO {TABELA} ({', '.join(COLS)}) "
                f"VALUES ({', '.join('?' * len(COLS))})",
                [int(reg[k]) if k == "atendida" else reg.get(k) for k in COLS],
            )


class SupabaseStore:
    compartilhado = True
    nome = "Supabase (compartilhado com a equipe)"

    def __init__(self, url: str, key: str):
        import requests

        self._s = requests.Session()
        self._s.headers.update({"apikey": key, "Authorization": f"Bearer {key}",
                                "Content-Type": "application/json"})
        self._url = url.rstrip("/") + f"/rest/v1/{TABELA}"

    def carregar(self) -> pd.DataFrame:
        r = self._s.get(self._url, params={"select": ",".join(COLS)}, timeout=15)
        r.raise_for_status()
        df = pd.DataFrame(r.json(), columns=COLS)
        df["atendida"] = df["atendida"].fillna(False).astype(bool)
        return df

    def salvar(self, chave: str, usuario: str, atendida=None, onde=None):
        r = self._s.get(self._url, params={"select": ",".join(COLS),
                                           "chave": f"eq.{chave}"}, timeout=15)
        r.raise_for_status()
        anterior = r.json()[0] if r.json() else None
        reg = _campos_salvar(atendida, onde, usuario, anterior)
        reg["chave"] = chave
        r = self._s.post(self._url, json=reg, timeout=15,
                         headers={"Prefer": "resolution=merge-duplicates"})
        r.raise_for_status()


def criar(secrets: dict | None, demo: bool, raiz: Path):
    if demo:
        return MemoriaStore()
    s = secrets or {}
    if s.get("supabase_url") and s.get("supabase_key"):
        return SupabaseStore(s["supabase_url"], s["supabase_key"])
    return SQLiteStore(raiz / "data" / "acompanhamento.db")
