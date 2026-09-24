# -*- coding: utf-8 -*-
"""Camada visual: CSS, cards de KPI, estilo dos graficos e formatacao BR."""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Paleta (validada para daltonismo) - ver README "Visual"
AZUL = "#2a78d6"
LARANJA = "#eb6834"
AQUA = "#1baf7a"
AMARELO = "#eda100"
AZUL_ESCURO = "#1c5cab"
RAMPA_AZUL = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]  # ordinal
BOM, ALERTA, SERIO, CRITICO = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
TINTA, TINTA_2, MUDO, GRADE, EIXO = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
FONTE = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'


def brl(v, casas: int = 2) -> str:
    """1234.5 -> 'R$ 1.234,50'."""
    if v is None or pd.isna(v):
        return "-"
    s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def brl_curto(v) -> str:
    """Valores grandes compactos: R$ 1,2 mi / R$ 350 mil."""
    if v is None or pd.isna(v):
        return "-"
    if abs(v) >= 1e6:
        return f"R$ {v / 1e6:,.1f} mi".replace(".", ",")
    if abs(v) >= 1e4:
        return f"R$ {v / 1e3:,.0f} mil".replace(",", ".")
    return brl(v, 0)


def num(v) -> str:
    return f"{int(v):,}".replace(",", ".")


CSS = f"""
<style>
:root {{
  --tinta: {TINTA}; --tinta-2: {TINTA_2}; --mudo: {MUDO};
  --borda: rgba(11,11,11,.09); --card: #ffffff;
  --azul: {AZUL_ESCURO};
}}
html, body, [class*="css"] {{ font-family: {FONTE}; }}
.block-container {{ padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1500px; }}

/* Cabecalho */
.hero {{
  background: linear-gradient(120deg, #104281 0%, #1c5cab 55%, #2a78d6 100%);
  color: #fff; border-radius: 16px; padding: 22px 28px; margin-bottom: 18px;
  display: flex; justify-content: space-between; align-items: flex-end; gap: 16px;
  flex-wrap: wrap;
}}
.hero h1 {{ color: #fff; font-size: 1.65rem; margin: 0 0 4px 0; padding: 0;
  font-weight: 700; letter-spacing: -.01em; }}
.hero p {{ margin: 0; opacity: .85; font-size: .92rem; }}
.hero .chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.hero .chip {{ background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22);
  padding: 5px 11px; border-radius: 999px; font-size: .78rem; white-space: nowrap; }}

/* Cards de KPI */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 8px; }}
.kpi {{ background: var(--card); border: 1px solid var(--borda); border-radius: 14px;
  padding: 14px 16px 13px; position: relative; overflow: hidden; }}
.kpi::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  background: var(--acento, {AZUL}); }}
.kpi .rot {{ color: var(--tinta-2); font-size: .78rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; display: flex; gap: 6px;
  align-items: center; }}
.kpi .val {{ color: var(--tinta); font-size: 1.85rem; font-weight: 700; line-height: 1.15;
  margin-top: 4px; }}
.kpi .sub {{ color: var(--mudo); font-size: .8rem; margin-top: 2px; }}
.kpi .sub b {{ color: var(--tinta-2); font-weight: 600; }}

/* Titulos de secao dentro de cards */
.sec {{ font-weight: 700; color: var(--tinta); font-size: 1rem; margin: 0; }}
.sec-sub {{ color: var(--mudo); font-size: .82rem; margin: 2px 0 6px 0; }}

/* Alertas */
.alerta {{ border-radius: 12px; padding: 12px 16px; margin: 4px 0 10px 0;
  border: 1px solid var(--borda); background: #fff; display: flex; gap: 12px;
  align-items: center; }}
.alerta .ico {{ font-size: 1.3rem; }}
.alerta .tx b {{ color: var(--tinta); }}
.alerta .tx span {{ color: var(--tinta-2); font-size: .88rem; }}
.alerta.critico {{ border-left: 5px solid {CRITICO}; }}
.alerta.serio {{ border-left: 5px solid {SERIO}; }}
.alerta.aviso {{ border-left: 5px solid {ALERTA}; }}
.alerta.ok {{ border-left: 5px solid {BOM}; }}

/* Abas */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid var(--borda); }}
.stTabs [data-baseweb="tab"] {{ padding: 8px 14px; border-radius: 10px 10px 0 0;
  font-weight: 600; }}
.stTabs [aria-selected="true"] {{ background: #eaf2fc; }}

/* Containers com borda = cards */
[data-testid="stVerticalBlockBorderWrapper"] {{ background: #fff; border-radius: 14px; }}
section[data-testid="stSidebar"] {{ background: #f3f5f8; }}

/* Cartoes de SC (lista estilo sistema) */
.sc-card {{ padding: 2px 0; }}
.sc-top {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 4px; }}
.sc-num {{ font-weight: 700; color: var(--tinta); font-size: .98rem; margin-right: 4px; }}
.sc-item {{ font-weight: 500; color: var(--mudo); }}
.sc-desc {{ font-size: 1.02rem; font-weight: 600; color: #1f2a37; margin: 2px 0 6px; }}
.sc-meta {{ display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--tinta-2);
  font-size: .83rem; }}
.sc-meta b {{ color: var(--tinta); font-weight: 600; }}
.bdg {{ font-size: .72rem; font-weight: 600; padding: 2px 9px; border-radius: 999px;
  border: 1px solid transparent; white-space: nowrap; }}
.bdg.tipo {{ background: #eef2f7; color: #52514e; }}
.bdg.ok {{ background: #e3f6e3; color: #006300; border-color: #b9e5b9; }}
.bdg.venc {{ background: #fdecec; color: #a32121; border-color: #f4c4c4; }}
.bdg.urg {{ background: #fff1e8; color: #9a3d12; border-color: #f7cdb5; }}
.bdg.local {{ background: #eaf2fc; color: #1c5cab; border-color: #c7dcf5; }}
div[class*="st-key-sc-"] {{ border-left: 5px solid #c3c2b7 !important;
  transition: background .15s; }}
div[class*="st-key-sc-normal-"] {{ border-left-color: {AZUL} !important; }}
div[class*="st-key-sc-urg-"] {{ border-left-color: {SERIO} !important; }}
div[class*="st-key-sc-venc-"] {{ border-left-color: {CRITICO} !important; }}
div[class*="st-key-sc-ok-"] {{ border-left-color: {BOM} !important;
  background: #f3fbf3 !important; }}
div[class*="st-key-sc-ok-"] .sc-desc {{ color: #4b6b4b; }}
div[class*="st-key-sc-"]:hover {{ background: #fafcff; }}
</style>
"""


def aplicar_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(titulo: str, subtitulo: str, chips: list[str]):
    chips_html = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips)
    st.markdown(
        f'<div class="hero"><div><h1>{html.escape(titulo)}</h1>'
        f"<p>{html.escape(subtitulo)}</p></div>"
        f'<div class="chips">{chips_html}</div></div>',
        unsafe_allow_html=True,
    )


def kpis(cards: list[dict]):
    """cards: [{'rot','val','sub','cor','ico'}]. 'sub' aceita <b>."""
    partes = []
    for c in cards:
        ico = f"<span>{c['ico']}</span>" if c.get("ico") else ""
        partes.append(
            f'<div class="kpi" style="--acento:{c.get("cor", AZUL)}">'
            f'<div class="rot">{ico}{html.escape(c["rot"])}</div>'
            f'<div class="val">{html.escape(str(c["val"]))}</div>'
            f'<div class="sub">{c.get("sub", "")}</div></div>'
        )
    st.markdown(f'<div class="kpis">{"".join(partes)}</div>', unsafe_allow_html=True)


def secao(titulo: str, sub: str = ""):
    st.markdown(f'<p class="sec">{html.escape(titulo)}</p>'
                + (f'<p class="sec-sub">{html.escape(sub)}</p>' if sub else ""),
                unsafe_allow_html=True)


def alerta(nivel: str, ico: str, titulo: str, texto: str = ""):
    st.markdown(
        f'<div class="alerta {nivel}"><div class="ico">{ico}</div>'
        f'<div class="tx"><b>{html.escape(titulo)}</b><br>'
        f"<span>{html.escape(texto)}</span></div></div>",
        unsafe_allow_html=True,
    )


def estilo(fig: go.Figure, altura: int = 320, legenda: bool = True,
           horizontal: bool = False) -> go.Figure:
    """Aplica o visual padrao. Chame ANTES dos ajustes especificos do grafico.
    horizontal=True: barras deitadas (grade vertical, sem grade horizontal)."""
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=8, t=8 if not legenda else 36, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONTE, color=TINTA_2, size=12),
        showlegend=legenda,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    title=None, font=dict(color=TINTA_2)),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=EIXO,
                        font=dict(family=FONTE, color=TINTA, size=12)),
        barcornerradius=4,
        bargap=0.35,
        separators=",.",
    )
    eixo_valor = dict(showgrid=True, gridcolor=GRADE, gridwidth=1,
                      linecolor="rgba(0,0,0,0)", tickfont=dict(color=MUDO),
                      title_font=dict(color=MUDO), zeroline=False)
    eixo_cat = dict(showgrid=False, linecolor=EIXO, tickfont=dict(color=TINTA_2),
                    title_font=dict(color=MUDO), zeroline=False)
    fig.update_xaxes(**(eixo_valor if horizontal else eixo_cat))
    fig.update_yaxes(**(eixo_cat if horizontal else eixo_valor))
    if horizontal:
        fig.update_yaxes(linecolor="rgba(0,0,0,0)", ticksuffix="  ")
    return fig


CONFIG_PLOTLY = {"displayModeBar": False, "locale": "pt-BR"}


def grafico(fig: go.Figure):
    st.plotly_chart(fig, config=CONFIG_PLOTLY, width="stretch")
