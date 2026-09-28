# -*- coding: utf-8 -*-
"""Acesso ao banco (Supabase via REST ou SQLite local) com uma API minima:
select / upsert / insert. Usado pelo historico (src/historico.py) e pelas
marcacoes (src/store.py).

Escolha automatica (mesma regra das marcacoes):
  - secrets com supabase_url + supabase_key -> Supabase (equipe toda ve igual)
  - senao -> SQLite em data/historico.db (so no PC que roda o app)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Tabelas e colunas (a mesma estrutura do sql/historico.sql)
ESQUEMA = {
    "carga": {
        "pk": "id",
        "cols": ["id", "criado_em", "usuario", "assinatura", "ref_sc", "ref_pc",
                 "ref_dist", "n_itens", "n_eventos", "arquivos"],
    },
    "sc_item": {
        "pk": "chave",
        "cols": ["chave", "num_sc", "item", "tipo_cod", "produto", "descricao", "qtd",
                 "valor", "solicitante", "departamento", "urgencia", "aprovado",
                 "dt_emissao", "dt_necessidade", "responsavel", "dt_distribuicao",
                 "pedido", "dt_pedido", "entregue", "dt_entrega", "situacao",
                 "primeira_vez", "ultima_vez", "dt_saiu", "atualizado_em"],
    },
    "sc_evento": {
        "pk": "id",
        "cols": ["id", "chave", "evento", "data", "detalhe", "carga_id", "criado_em"],
    },
    "sc_acompanhamento_log": {
        "pk": "id",
        "cols": ["id", "chave", "campo", "valor_antigo", "valor_novo", "usuario",
                 "em"],
    },
}


class SQLiteBanco:
    compartilhado = False

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.nome = f"Arquivo local ({self.caminho.name})"
        with self._con() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS carga (
              id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT, usuario TEXT,
              assinatura TEXT UNIQUE, ref_sc TEXT, ref_pc TEXT, ref_dist TEXT,
              n_itens INTEGER, n_eventos INTEGER, arquivos TEXT);
            CREATE TABLE IF NOT EXISTS sc_item (
              chave TEXT PRIMARY KEY, num_sc TEXT, item TEXT, tipo_cod TEXT,
              produto TEXT, descricao TEXT, qtd REAL, valor REAL, solicitante TEXT,
              departamento TEXT, urgencia TEXT, aprovado TEXT, dt_emissao TEXT,
              dt_necessidade TEXT, responsavel TEXT, dt_distribuicao TEXT,
              pedido TEXT, dt_pedido TEXT, entregue INTEGER, dt_entrega TEXT,
              situacao TEXT, primeira_vez TEXT, ultima_vez TEXT, dt_saiu TEXT,
              atualizado_em TEXT);
            CREATE TABLE IF NOT EXISTS sc_evento (
              id INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT, evento TEXT,
              data TEXT, detalhe TEXT, carga_id INTEGER, criado_em TEXT);
            CREATE INDEX IF NOT EXISTS sc_evento_chave ON sc_evento(chave);
            CREATE TABLE IF NOT EXISTS sc_acompanhamento_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT, campo TEXT,
              valor_antigo TEXT, valor_novo TEXT, usuario TEXT, em TEXT);
            CREATE INDEX IF NOT EXISTS sc_log_chave ON sc_acompanhamento_log(chave);
            """)

    def _con(self):
        c = sqlite3.connect(self.caminho, timeout=15)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _enc(v):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v

    def select(self, tabela: str, filtros: dict | None = None, ordem: str | None = None,
               colunas: list | None = None) -> list[dict]:
        cols = ", ".join(colunas or ESQUEMA[tabela]["cols"])
        sql, args = f"SELECT {cols} FROM {tabela}", []
        if filtros:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k in filtros)
            args = list(filtros.values())
        if ordem:
            campo, _, sentido = ordem.partition(".")
            sql += f" ORDER BY {campo} {'DESC' if sentido == 'desc' else 'ASC'}"
        with self._con() as c:
            rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        if tabela == "sc_item":
            for r in rows:
                r["entregue"] = bool(r.get("entregue"))
        return rows

    def insert(self, tabela: str, linhas: list[dict]) -> list[dict]:
        if not linhas:
            return []
        out = []
        with self._con() as c:
            for ln in linhas:
                cols = [k for k in ln if k in ESQUEMA[tabela]["cols"] and k != "id"]
                cur = c.execute(
                    f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES "
                    f"({', '.join('?' * len(cols))})", [self._enc(ln[k]) for k in cols])
                out.append({**ln, "id": cur.lastrowid})
        return out

    def upsert(self, tabela: str, linhas: list[dict]):
        if not linhas:
            return
        pk = ESQUEMA[tabela]["pk"]
        cols = ESQUEMA[tabela]["cols"]
        with self._con() as c:
            for ln in linhas:
                usados = [k for k in cols if k in ln]
                atualiza = ", ".join(f"{k}=excluded.{k}" for k in usados if k != pk)
                c.execute(
                    f"INSERT INTO {tabela} ({', '.join(usados)}) VALUES "
                    f"({', '.join('?' * len(usados))}) ON CONFLICT({pk}) DO UPDATE SET "
                    f"{atualiza}", [self._enc(ln[k]) for k in usados])


class SupabaseBanco:
    compartilhado = True
    nome = "Supabase (compartilhado com a equipe)"
    LOTE = 500

    def __init__(self, url: str, key: str):
        import requests

        self._s = requests.Session()
        self._s.headers.update({"apikey": key, "Content-Type": "application/json"})
        if key.startswith("eyJ"):  # chaves antigas (JWT) tambem vao no Authorization
            self._s.headers["Authorization"] = f"Bearer {key}"
        self._base = url.rstrip("/") + "/rest/v1/"

    def select(self, tabela: str, filtros: dict | None = None, ordem: str | None = None,
               colunas: list | None = None) -> list[dict]:
        params = {"select": ",".join(colunas or ESQUEMA[tabela]["cols"])}
        for k, v in (filtros or {}).items():
            params[k] = f"eq.{v}"
        if ordem:
            params["order"] = ordem
        out, ini = [], 0
        while True:  # paginacao (o PostgREST devolve no maximo 1000 por vez)
            r = self._s.get(self._base + tabela, timeout=30,
                            params={**params, "limit": 1000, "offset": ini})
            r.raise_for_status()
            lote = r.json()
            out += lote
            if len(lote) < 1000:
                return out
            ini += 1000

    def insert(self, tabela: str, linhas: list[dict]) -> list[dict]:
        out = []
        for i in range(0, len(linhas), self.LOTE):
            r = self._s.post(self._base + tabela, json=linhas[i:i + self.LOTE],
                             timeout=60, headers={"Prefer": "return=representation"})
            r.raise_for_status()
            out += r.json()
        return out

    def upsert(self, tabela: str, linhas: list[dict]):
        pk = ESQUEMA[tabela]["pk"]
        for i in range(0, len(linhas), self.LOTE):
            r = self._s.post(
                self._base + tabela, json=linhas[i:i + self.LOTE], timeout=60,
                params={"on_conflict": pk},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
            r.raise_for_status()


def criar(secrets: dict | None, raiz: Path):
    s = secrets or {}
    if s.get("supabase_url") and s.get("supabase_key"):
        return SupabaseBanco(s["supabase_url"], s["supabase_key"])
    return SQLiteBanco(raiz / "data" / "historico.db")
