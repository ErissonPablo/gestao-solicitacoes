# -*- coding: utf-8 -*-
"""Leitura dos arquivos direto da pasta do SharePoint da Lactosul.

Le TODOS os arquivos da pasta configurada e devolve candidatos
(nome, bytes, mtime) para o datasource.resolver identificar cada um.

Requer:  pip install Office365-REST-Python-Client
Config:  config/paths.yaml -> sharepoint: {site_url, pasta}
Credenciais em .streamlit/secrets.toml, em ordem de preferencia:
  1) App (recomendado p/ sempre-online):  sp_client_id / sp_client_secret
  2) Usuario (so funciona sem MFA):        sp_username / sp_password
  3) Interativo (login no navegador):      sp_tenant / sp_client_id (sem secret)
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path


def _config() -> dict:
    import yaml  # type: ignore

    cfg_path = Path(__file__).parent.parent / "config" / "paths.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            "config/paths.yaml nao encontrado. Copie de paths.example.yaml e ajuste."
        )
    with open(cfg_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("sharepoint", {})


def _context(site_url: str):
    """Monta o ClientContext escolhendo a autenticacao disponivel nos secrets."""
    import streamlit as st
    from office365.sharepoint.client_context import ClientContext

    sec = st.secrets
    if sec.get("sp_client_id") and sec.get("sp_client_secret"):
        from office365.runtime.auth.client_credential import ClientCredential

        return ClientContext(site_url).with_credentials(
            ClientCredential(sec["sp_client_id"], sec["sp_client_secret"])
        )
    if sec.get("sp_username") and sec.get("sp_password"):
        from office365.runtime.auth.user_credential import UserCredential

        return ClientContext(site_url).with_credentials(
            UserCredential(sec["sp_username"], sec["sp_password"])
        )
    if sec.get("sp_tenant") and sec.get("sp_client_id"):
        return ClientContext(site_url).with_interactive(
            sec["sp_tenant"], sec["sp_client_id"]
        )
    raise RuntimeError(
        "Credenciais do SharePoint nao configuradas em .streamlit/secrets.toml."
    )


def listar_candidatos() -> list[dict]:
    """Baixa todos os arquivos da pasta configurada. Devolve lista de
    {'nome', 'bytes', 'mtime'} pronta para o datasource.resolver."""
    cfg = _config()
    site = cfg["site_url"]
    pasta = cfg["pasta"]  # server-relative, ex.: /sites/grp.compras/Documentos.../...
    ctx = _context(site)

    folder = ctx.web.get_folder_by_server_relative_url(pasta)
    arquivos = folder.files
    ctx.load(arquivos)
    ctx.execute_query()

    out = []
    for f in arquivos:
        nome = f.properties.get("Name", "")
        if not nome.lower().endswith((".xls", ".xlsx", ".xml")) or nome.startswith("~$"):
            continue
        buf = io.BytesIO()
        f.download(buf).execute_query()
        tlm = f.properties.get("TimeLastModified")
        mtime = None
        if tlm:
            try:
                mtime = datetime.fromisoformat(str(tlm).replace("Z", "+00:00")).timestamp()
            except ValueError:
                mtime = None
        out.append({"nome": nome, "bytes": buf.getvalue(), "mtime": mtime})
    return out
