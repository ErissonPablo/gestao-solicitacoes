# -*- coding: utf-8 -*-
"""Guarda os arquivos de cada carga para quem abre o app sem subir nada.

Quem sobe as planilhas "publica" a carga: os 3 arquivos vao comprimidos
(gzip, o rmatr052 de ~28 MB vira ~2 MB) para o Storage do Supabase (bucket
privado 'cargas'); sem Supabase, para data/cargas/ no proprio PC.
Qualquer pessoa que abrir o app depois ja recebe a ultima carga.
"""
from __future__ import annotations

import gzip
from pathlib import Path

BUCKET = "cargas"


def _zip(b: bytes) -> bytes:
    return gzip.compress(b, compresslevel=6)


def _unzip(b: bytes) -> bytes:
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


class LocalArmazem:
    nome = "PC local (data/cargas)"

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz) / "data" / "cargas"

    def enviar(self, caminho: str, dados: bytes):
        p = self.raiz / caminho
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_zip(dados))

    def baixar(self, caminho: str) -> bytes:
        return _unzip((self.raiz / caminho).read_bytes())


class SupabaseArmazem:
    nome = "Supabase Storage"

    def __init__(self, url: str, key: str):
        import requests

        self._s = requests.Session()
        self._s.headers.update({"apikey": key})
        if key.startswith("eyJ"):
            self._s.headers["Authorization"] = f"Bearer {key}"
        self._base = url.rstrip("/") + f"/storage/v1/object/{BUCKET}/"

    def enviar(self, caminho: str, dados: bytes):
        r = self._s.post(self._base + caminho, data=_zip(dados), timeout=120,
                         headers={"Content-Type": "application/gzip", "x-upsert": "true"})
        r.raise_for_status()

    def baixar(self, caminho: str) -> bytes:
        r = self._s.get(self._base + caminho, timeout=120)
        r.raise_for_status()
        return _unzip(r.content)


def criar(secrets: dict | None, raiz: Path):
    s = secrets or {}
    if s.get("supabase_url") and s.get("supabase_key"):
        return SupabaseArmazem(s["supabase_url"], s["supabase_key"])
    return LocalArmazem(raiz)


def publicar(armazem, banco, assin: str, arquivos: dict) -> dict:
    """arquivos: {'sc': (nome, bytes), 'pc': ..., 'dist': ...}. Envia e anota na carga."""
    info = {}
    for tipo, (nome, dados) in arquivos.items():
        caminho = f"{assin}/{tipo}.gz"
        armazem.enviar(caminho, dados)
        info[tipo] = {"nome": nome, "caminho": caminho, "bytes": len(dados)}
    banco.atualizar("carga", {"assinatura": assin}, {"storage": info})
    return info


def ultima_publicada(banco) -> dict | None:
    """Carga mais nova (extracao do rmatr029, depois horario) que tem arquivos guardados."""
    cargas = [c for c in banco.select("carga", ordem="criado_em.desc") if c.get("storage")]
    if not cargas:
        return None
    cargas.sort(key=lambda c: (str(c.get("ref_sc") or ""), str(c.get("criado_em") or "")),
                reverse=True)
    return cargas[0]


def baixar_carga(armazem, carga: dict) -> dict:
    """Devolve {'sc': bytes, 'pc': bytes, 'dist': bytes}."""
    return {t: armazem.baixar(i["caminho"]) for t, i in carga["storage"].items()}
