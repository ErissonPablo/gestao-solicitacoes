# -*- coding: utf-8 -*-
"""Gestao de Solicitacoes de Compra - Lactosul.

Cruza 3 fontes do Protheus/Excel para acompanhar SCs sem que nenhuma se perca:
  1. rmatr029  -> Solicitacoes de Compra (demanda)
  2. distribuicao.xlsx (base) -> responsavel por cada SC-item
  3. rmatr052  -> Pedidos de Compra e entregas

Foco: nada de SC pendente sem dono e sem virar pedido; e acompanhar entregas.
"""
import io
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from src import loaders, crossref, normalize as nz, datasource as ds  # noqa: E402
from src import metrics as mt, ui, export, store as st_store  # noqa: E402
import html as _html  # noqa: E402

st.set_page_config(
    page_title="Gestao de Solicitacoes de Compra",
    page_icon="🛒",
    layout="wide",
)
ui.aplicar_css()


# --------------------------------------------------------------------------- #
# Loaders cacheados (chave = bytes do arquivo)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Lendo Solicitacoes (rmatr029)...")
def _load_scs(b: bytes) -> pd.DataFrame:
    return loaders.load_scs(io.BytesIO(b))


@st.cache_data(show_spinner="Lendo Pedidos (rmatr052)...")
def _load_pcs(b: bytes) -> pd.DataFrame:
    return loaders.load_pcs(io.BytesIO(b))


@st.cache_data(show_spinner="Lendo planilha de distribuicao...")
def _load_dist(b: bytes) -> pd.DataFrame:
    return loaders.load_distribuicao(io.BytesIO(b))


@st.cache_data(show_spinner="Gerando dados de demonstracao...")
def _demo() -> dict:
    from src import demo
    return demo.gerar()


# --------------------------------------------------------------------------- #
# Helpers de exibicao
# --------------------------------------------------------------------------- #
def br_data(serie):
    return pd.to_datetime(serie, errors="coerce").dt.strftime("%d/%m/%Y")


def baixar_csv(df: pd.DataFrame, nome: str, label: str):
    st.download_button(
        label, df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=nome, mime="text/csv",
    )


TIPO_NOME = {
    "01": "01 Aplicacao Direta", "02": "02 Normal",
    "03": "03 Servicos", "07": "07 Investimento",
}

# --------------------------------------------------------------------------- #
# Sidebar - fonte de dados
# --------------------------------------------------------------------------- #
st.sidebar.title("🛒 Gestao de SC")
st.sidebar.caption("Cruzamento Protheus x Distribuicao x Pedidos")

fonte = st.sidebar.radio(
    "Fonte dos dados",
    ["Upload de arquivos", "Pasta local", "SharePoint", "Demonstracao (dados ficticios)"],
    help="Os 3 arquivos: rmatr029 (SCs), rmatr052 (Pedidos) e a planilha de distribuicao.",
)

sc_bytes = pc_bytes = dist_bytes = None
candidatos: list = []
modo_demo = fonte.startswith("Demonstracao")

if fonte == "Upload de arquivos":
    st.sidebar.caption(
        "Solte os arquivos - a ferramenta identifica cada um pelo conteudo, "
        "nao importa o nome."
    )
    ups = st.sidebar.file_uploader(
        "rmatr029, rmatr052 e a distribuicao",
        type=["xls", "xlsx", "xml"], accept_multiple_files=True,
    )
    candidatos = [{"nome": u.name, "bytes": u.getvalue(), "mtime": None} for u in (ups or [])]

elif fonte == "Pasta local":
    pasta = st.sidebar.text_input(
        "Pasta com os arquivos (ex.: pasta sincronizada do SharePoint)",
        value=str(Path.home() / "Downloads"),
    )
    if pasta and Path(pasta).is_dir():
        candidatos = ds.candidatos_da_pasta(pasta)
    else:
        st.sidebar.warning("Informe uma pasta valida.")

elif fonte == "SharePoint":
    st.sidebar.info("Le os arquivos direto da pasta configurada do SharePoint.")
    if st.sidebar.button("🔄 Conectar e ler do SharePoint"):
        try:
            from src import sharepoint as sp
            st.session_state["_sp_cands"] = sp.listar_candidatos()
        except Exception as e:  # noqa: BLE001
            st.sidebar.error(f"Falha no SharePoint: {e}")
    candidatos = st.session_state.get("_sp_cands", [])

else:  # Demonstracao
    st.sidebar.warning("Dados **ficticios**, so para conhecer a ferramenta.")
    d = _demo()
    sc_bytes, pc_bytes, dist_bytes = d["sc"], d["pc"], d["dist"]

# Identificacao por conteudo + escolha da extracao mais recente (sem duplicar)
if candidatos:
    resolvido = ds.resolver(candidatos)
    sc_bytes, pc_bytes, dist_bytes = resolvido["sc"], resolvido["pc"], resolvido["dist"]
    rotulos = {"sc": "Solicitacoes (rmatr029)", "pc": "Pedidos (rmatr052)",
               "dist": "Distribuicao"}
    for tipo, rot in rotulos.items():
        det = resolvido["detalhes"].get(tipo)
        if det:
            extra = (f" · {len(det['descartados'])} duplicado(s) ignorado(s)"
                     if det["descartados"] else "")
            st.sidebar.success(f"✅ {rot}\n\n{det['nome']} · extracao {det['ref']}{extra}")
        else:
            st.sidebar.error(f"❌ {rot}: nao encontrado nos arquivos")

if not (sc_bytes and pc_bytes and dist_bytes):
    ui.hero("Gestao de Solicitacoes de Compra",
            "Nenhuma SC sem dono, nenhuma SC esquecida, nenhuma entrega sem acompanhamento.",
            ["Protheus rmatr029", "Distribuicao", "Protheus rmatr052"])
    st.info(
        "Forneca os **3 arquivos** na barra lateral para comecar (em qualquer ordem, "
        "com qualquer nome):\n\n"
        "1. **rmatr029** - Solicitacoes de Compra (Protheus)\n"
        "2. **rmatr052** - Pedidos de Compra (Protheus)\n"
        "3. **Distribuicao** - a planilha de distribuicao (.xlsx)\n\n"
        "A ferramenta **identifica cada arquivo pelo conteudo** e, se houver mais de "
        "uma extracao do mesmo tipo, usa sempre a **mais recente** - nada e contado "
        "em dobro.\n\n"
        "Quer so conhecer as telas? Escolha **Demonstracao** na barra lateral."
    )
    st.stop()

# --------------------------------------------------------------------------- #
# Carrega e cruza
# --------------------------------------------------------------------------- #
scs = _load_scs(sc_bytes)
pcs = _load_pcs(pc_bytes)
dist = _load_dist(dist_bytes)

hoje = pd.Timestamp.today().normalize()
model = mt.enriquecer(crossref.build_sc_model(scs, dist), hoje)
pend_all = crossref.pendencias_entrega(pcs)
ped_agg = crossref.agrega_pedidos(pcs)

# --------------------------------------------------------------------------- #
# Acompanhamento manual (Atendida / Onde encontrar) - salvo por SC-item
# --------------------------------------------------------------------------- #
@st.cache_resource
def _store_persistente():
    try:
        segredos = dict(st.secrets)
    except Exception:  # noqa: BLE001 - sem secrets.toml
        segredos = {}
    return st_store.criar(segredos, demo=False, raiz=Path(__file__).parent)


if modo_demo:
    if "_store_demo" not in st.session_state:
        st.session_state["_store_demo"] = st_store.criar(None, demo=True, raiz=Path("."))
    store = st.session_state["_store_demo"]
else:
    store = _store_persistente()

try:
    acomp = store.carregar()
except Exception as e:  # noqa: BLE001
    st.sidebar.error(f"Nao consegui ler as marcacoes ({store.nome}): {e}")
    acomp = st_store._vazio()

model = model.merge(acomp[["chave", "atendida", "atendida_por", "atendida_em",
                           "onde_encontrar"]], on="chave", how="left")
model["atendida"] = model["atendida"].fillna(False).astype(bool)

EQUIPE_USUARIOS = sorted(nz.EQUIPE_ATUAL | nz.IMPLANTADORES)
st.sidebar.divider()
usuario = st.sidebar.selectbox(
    "👤 Voce e", EQUIPE_USUARIOS, index=None, placeholder="Escolha seu nome",
    key="usuario", help="Fica registrado quem marcou cada SC como atendida.")
st.sidebar.caption(f"Marcacoes salvas em: {store.nome}")

# --------------------------------------------------------------------------- #
# Filtros globais
# --------------------------------------------------------------------------- #
st.sidebar.divider()
st.sidebar.subheader("Filtros")

anos = sorted({d.year for d in model["DT_EMISSAO"].dropna()} | {hoje.year}, reverse=True)
ano_sel = st.sidebar.multiselect("Ano (emissao da SC)", anos,
                                 default=[2026] if 2026 in anos else anos[:1])
tipos_sel = st.sidebar.multiselect(
    "Tipo de SC", ["01", "02", "03", "07"],
    default=["01", "02", "03", "07"], format_func=lambda t: TIPO_NOME[t],
)
so_aprovadas = st.sidebar.checkbox("Somente SCs aprovadas", value=True,
                                   help="Exclui SCs eliminadas/bloqueadas/reprovadas.")
compradores_opts = sorted(
    set(model["responsavel"].dropna()) | set(pend_all["comprador"].dropna()))
comp_sel = st.sidebar.multiselect(
    "Comprador", compradores_opts, placeholder="Todos",
    help="Filtra todas as telas pelo responsavel (SCs) e pelo comprador (pedidos).")

mf = model.copy()
if ano_sel:
    mf = mf[mf["DT_EMISSAO"].dt.year.isin(ano_sel)]
if tipos_sel:
    mf = mf[mf["tipo_cod"].isin(tipos_sel)]
if so_aprovadas:
    mf = mf[mf["APROVADO"].fillna("").str.upper().eq("APROVADA")]
pend = pend_all
if comp_sel:
    mf = mf[mf["responsavel"].isin(comp_sel)]
    pend = pend_all[pend_all["comprador"].isin(comp_sel)]

backlog = mf[~mf["com_pedido"]]
sem_dist = mf[~mf["distribuida"]]
perdidas = mf[(~mf["com_pedido"]) & (~mf["distribuida"])]
vencidas = backlog[backlog["vencida"]]
urgentes = backlog[backlog["urgente"]]
lt = mt.resumo_lead_time(mf)

# --------------------------------------------------------------------------- #
# Cabecalho + KPIs
# --------------------------------------------------------------------------- #
chips = [f"Atualizado em {hoje.strftime('%d/%m/%Y')}",
         f"{ui.num(len(mf))} SC-itens no filtro",
         "Tipos " + "/".join(tipos_sel or ["-"])]
if comp_sel:
    chips.append("Comprador: " + ", ".join(comp_sel))
if modo_demo:
    chips.append("DADOS FICTICIOS")
ui.hero("Gestao de Solicitacoes de Compra",
        "Lactosul · Filial 03 · SC → distribuicao → pedido → entrega", chips)

pct_atend = (mf["com_pedido"].mean() * 100) if len(mf) else 0
ui.kpis([
    {"rot": "SC-itens", "val": ui.num(len(mf)), "ico": "🧾", "cor": ui.AZUL,
     "sub": f"<b>{pct_atend:.0f}%</b> ja viraram pedido"},
    {"rot": "Backlog sem pedido", "val": ui.num(len(backlog)), "ico": "📋",
     "cor": ui.AZUL_ESCURO, "sub": f"<b>{ui.brl_curto(backlog['VALOR'].sum())}</b> em aberto"},
    {"rot": "Necessidade vencida", "val": ui.num(len(vencidas)), "ico": "⏰",
     "cor": ui.CRITICO if len(vencidas) else ui.BOM,
     "sub": "sem pedido e ja passou da data"},
    {"rot": "Sem dono e sem pedido", "val": ui.num(len(perdidas)), "ico": "⚠️",
     "cor": ui.CRITICO if len(perdidas) else ui.BOM,
     "sub": f"{ui.num(len(sem_dist))} sem distribuicao no total"},
    {"rot": "Tempo SC → pedido", "ico": "⏱️", "cor": ui.AQUA,
     "val": f"{lt['mediana']:.0f} dias" if lt["mediana"] is not None else "-",
     "sub": (f"mediana · 90% em ate <b>{lt['p90']:.0f} dias</b>"
             if lt["p90"] is not None else "sem DT.EMIS.PC no rmatr029")},
    {"rot": "Entregas pendentes", "val": ui.num(len(pend)), "ico": "🚚", "cor": ui.LARANJA,
     "sub": f"<b>{ui.num(pend['chegou_fabrica'].sum())}</b> ja chegaram (pre nota)"},
])

tabs = st.tabs([
    "📊 Visao geral",
    "🚨 Alertas",
    "📋 Backlog a atender",
    "⚠️ Sem distribuicao",
    "👥 Compradores",
    "🚚 Entregas pendentes",
    "🔎 Visao 360 por SC",
    "🧪 Qualidade de dados",
])
(tab_geral, tab_alertas, tab1, tab2, tab3, tab4, tab5, tab6) = tabs

COLS_SC = [
    "NUM.SC", "ITEM", "tipo_cod", "DESCRICAO", "QTD", "VALOR",
    "DT_EMISSAO", "idade_dias", "DT_NECESSIDADE", "URGENCIA", "responsavel",
    "SOLICITANTE", "DESC_DEPARTAMENTO", "APROVADO", "LEGENDA",
]
CFG_SC = {
    "VALOR R$": st.column_config.NumberColumn(format="R$ %.2f"),
    "IDADE (dias)": st.column_config.NumberColumn(format="%d d"),
    "QTD": st.column_config.NumberColumn(format="%g"),
}


def _preparar(df: pd.DataFrame, extra: list | None = None) -> pd.DataFrame:
    cols = COLS_SC + [c for c in (extra or []) if c not in COLS_SC]
    show = df[cols].copy()
    for c in ("DT_EMISSAO", "DT_NECESSIDADE"):
        show[c] = br_data(show[c])
    show["responsavel"] = show["responsavel"].fillna("(sem dono)")
    return show.rename(columns={
        "tipo_cod": "TIPO", "VALOR": "VALOR R$",
        "DT_EMISSAO": "EMISSAO", "idade_dias": "IDADE (dias)",
        "DT_NECESSIDADE": "NECESSIDADE", "dias_atraso": "ATRASO (dias)",
        "responsavel": "RESPONSAVEL", "DESC_DEPARTAMENTO": "DEPARTAMENTO",
        "atendida": "ATENDIDA", "onde_encontrar": "ONDE ENCONTRAR",
    })


def tabela_sc(df: pd.DataFrame, extra: list | None = None, altura: int | None = None):
    kw = {"height": altura} if altura else {}
    st.dataframe(_preparar(df, extra), width="stretch", hide_index=True,
                 column_config={**CFG_SC,
                                "ATRASO (dias)": st.column_config.NumberColumn(format="%d d")},
                 **kw)


# --------------------------------------------------------------------------- #
# Visao geral
# --------------------------------------------------------------------------- #
with tab_geral:
    g1, g2 = st.columns([5, 4], gap="medium")
    with g1, st.container(border=True):
        ui.secao("Funil da solicitacao",
                 "Quantos SC-itens avancaram em cada etapa do processo.")
        fn = mt.funil(mf, pend, ped_agg)
        base = max(int(fn["qtd"].iloc[0]), 1)
        fig = go.Figure(go.Bar(
            x=fn["qtd"], y=fn["etapa"], orientation="h",
            marker_color=[ui.RAMPA_AZUL[4], ui.RAMPA_AZUL[3], ui.RAMPA_AZUL[2],
                          ui.RAMPA_AZUL[1]],
            text=[f"{ui.num(q)} · {q / base * 100:.0f}%" for q in fn["qtd"]],
            textposition="outside", cliponaxis=False,
            textfont=dict(color=ui.TINTA_2),
            hovertemplate="%{y}: %{x} SC-itens<extra></extra>",
        ))
        ui.estilo(fig, 280, legenda=False, horizontal=True)
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(visible=False, range=[0, base * 1.22])
        ui.grafico(fig)

    with g2, st.container(border=True):
        ui.secao("Envelhecimento do backlog",
                 "SCs sem pedido por tempo desde a emissao.")
        fx = mt.backlog_por_faixa(backlog)
        fig = go.Figure(go.Bar(
            x=fx["faixa_idade"], y=fx["qtd"], marker_color=ui.RAMPA_AZUL,
            customdata=fx["valor"].map(ui.brl),
            text=fx["qtd"].astype(int), textposition="outside", cliponaxis=False,
            textfont=dict(color=ui.TINTA_2),
            hovertemplate="%{x}: %{y} SC-itens<br>%{customdata}<extra></extra>",
        ))
        ui.estilo(fig, 280, legenda=False)
        fig.update_yaxes(rangemode="tozero", range=[0, max(fx["qtd"].max(), 1) * 1.2])
        ui.grafico(fig)

    with st.container(border=True):
        ui.secao("Entrada x atendimento por mes",
                 "SC-itens emitidos no mes x SC-itens que viraram pedido no mes. "
                 "Barras acima da linha = backlog crescendo.")
        tm = mt.tendencia_mensal(mf)
        fig = go.Figure()
        fig.add_bar(x=tm["mes"], y=tm["Emitidas"], name="Emitidas", marker_color=ui.AZUL,
                    hovertemplate="%{x}: %{y} emitidas<extra></extra>")
        fig.add_scatter(x=tm["mes"], y=tm["Atendidas"], name="Viraram pedido",
                        mode="lines+markers", line=dict(color=ui.LARANJA, width=2.5),
                        marker=dict(size=8, line=dict(color="#fff", width=2)),
                        hovertemplate="%{x}: %{y} atendidas<extra></extra>")
        fig.update_layout(hovermode="x unified")
        ui.grafico(ui.estilo(fig, 300))

    g3, g4 = st.columns([5, 4], gap="medium")
    with g3, st.container(border=True):
        ui.secao("Carteira por comprador",
                 "SC-itens distribuidos: ja com pedido x ainda sem pedido.")
        cg = mt.carga_comprador(mf).sort_values("total")
        fig = go.Figure()
        fig.add_bar(y=cg["responsavel"], x=cg["Com pedido"], name="Com pedido",
                    orientation="h", marker_color=ui.AZUL,
                    hovertemplate="%{y}: %{x} com pedido<extra></extra>")
        fig.add_bar(y=cg["responsavel"], x=cg["Sem pedido"], name="Sem pedido",
                    orientation="h", marker_color=ui.LARANJA,
                    hovertemplate="%{y}: %{x} sem pedido<extra></extra>")
        fig.update_layout(barmode="stack", bargap=0.4, legend_traceorder="normal")
        fig.update_traces(marker_line_color="#fff", marker_line_width=2)
        ui.grafico(ui.estilo(fig, 300, horizontal=True))

    with g4, st.container(border=True):
        ui.secao("Departamentos com mais SCs paradas",
                 "Top 8 do backlog (sem pedido).")
        dp = mt.departamentos_backlog(backlog).sort_values("qtd")
        fig = go.Figure(go.Bar(
            y=[" ".join(w.capitalize() if len(w) > 2 else w for w in s.split())
               for s in dp["DEP"]], x=dp["qtd"], orientation="h",
            marker_color=ui.AZUL_ESCURO, customdata=dp["valor"].map(ui.brl),
            text=dp["qtd"], textposition="outside", cliponaxis=False,
            textfont=dict(color=ui.TINTA_2),
            hovertemplate="%{y}: %{x} SC-itens<br>%{customdata}<extra></extra>",
        ))
        ui.estilo(fig, 300, legenda=False, horizontal=True)
        fig.update_xaxes(visible=False, range=[0, max(dp["qtd"].max() if len(dp) else 1, 1) * 1.18])
        ui.grafico(fig)

# --------------------------------------------------------------------------- #
# Alertas
# --------------------------------------------------------------------------- #
with tab_alertas:
    ui.secao("O que precisa de atencao hoje",
             "Lista de acao: comece de cima para baixo.")
    dias_urg = st.slider("Considerar urgencia ALTA parada a partir de (dias)", 1, 30, 5)
    urg_paradas = urgentes[urgentes["idade_dias"] >= dias_urg]
    ent_antigas = pend[(~pend["chegou_fabrica"]) & (pend["dias_em_aberto"] > 30)]

    if len(perdidas):
        ui.alerta("critico", "🔴", f"{len(perdidas)} SC-itens sem dono e sem pedido",
                  "Nao estao na planilha de distribuicao - ninguem esta cuidando delas.")
    if len(vencidas):
        ui.alerta("critico", "⏰", f"{len(vencidas)} SC-itens com necessidade vencida",
                  f"Somam {ui.brl(vencidas['VALOR'].sum())}. O solicitante ja esperava "
                  "o material e ainda nao ha pedido.")
    if len(urg_paradas):
        ui.alerta("serio", "🔥", f"{len(urg_paradas)} urgencias ALTA paradas ha "
                  f"{dias_urg}+ dias", "Urgentes ainda sem pedido.")
    if len(ent_antigas):
        ui.alerta("aviso", "🚚", f"{len(ent_antigas)} itens de pedido com mais de 30 dias "
                  "sem chegar", "Vale cobrar o fornecedor.")
    if not (len(perdidas) or len(vencidas) or len(urg_paradas) or len(ent_antigas)):
        ui.alerta("ok", "✅", "Nenhum alerta no filtro atual", "Tudo sob controle.")

    if len(perdidas):
        with st.expander(f"🔴 Sem dono e sem pedido ({len(perdidas)})", expanded=True):
            tabela_sc(perdidas.sort_values("idade_dias", ascending=False))
    if len(vencidas):
        with st.expander(f"⏰ Necessidade vencida ({len(vencidas)})", expanded=True):
            tabela_sc(vencidas.sort_values("dias_atraso", ascending=False),
                      extra=["dias_atraso"])
            baixar_csv(vencidas[COLS_SC + ["dias_atraso"]], "sc_vencidas.csv",
                       "⬇️ Baixar vencidas (CSV)")
    if len(urg_paradas):
        with st.expander(f"🔥 Urgencia ALTA parada ({len(urg_paradas)})"):
            tabela_sc(urg_paradas.sort_values("idade_dias", ascending=False))
    if len(ent_antigas):
        with st.expander(f"🚚 Entregas com mais de 30 dias ({len(ent_antigas)})"):
            ea = ent_antigas.sort_values("dias_em_aberto", ascending=False)[
                ["PEDIDO COMPRA", "EMISSAO", "comprador", "FORNECEDOR", "DESCRICAO.",
                 "saldo", "dias_em_aberto", "situacao_label"]].copy()
            ea["EMISSAO"] = br_data(ea["EMISSAO"])
            st.dataframe(ea.rename(columns={
                "comprador": "COMPRADOR", "DESCRICAO.": "DESCRICAO", "saldo": "SALDO",
                "dias_em_aberto": "DIAS", "situacao_label": "SITUACAO"}),
                width="stretch", hide_index=True)

# --------------------------------------------------------------------------- #
# Tab 1 - Backlog
# --------------------------------------------------------------------------- #
with tab1:
    ui.secao("SCs aprovadas ainda sem pedido",
             "Marque o que ja foi atendido e anote onde encontrar cada produto. "
             "As marcacoes ficam salvas por SC-item e continuam valendo nas proximas "
             "subidas das planilhas.")
    locais = sorted(acomp["onde_encontrar"].dropna().unique().tolist())

    f1, f2, f3 = st.columns([3, 3, 3])
    resp_opts = sorted([r for r in backlog["responsavel"].dropna().unique()])
    f_resp = f1.multiselect("Responsavel", resp_opts, key="bl_resp", placeholder="Todos")
    f_onde = f2.multiselect("Onde encontrar", ["(nao definido)"] + locais,
                            key="bl_onde", placeholder="Todos os locais")
    f_busca = f3.text_input("Buscar (descricao, SC, solicitante)", key="bl_busca")
    f4, f5, f6, f7 = st.columns([4, 2, 2, 2])
    f_sit = f4.segmented_control(
        "Situacao", ["Pendentes", "Atendidas", "Todas"], default="Todas", key="bl_sit")
    f_urg = f5.checkbox("Somente urgencia ALTA", key="bl_urg")
    f_venc = f6.checkbox("Somente vencidas", key="bl_venc")
    agrupar = f7.toggle("Agrupar por local", key="bl_agrupar",
                        help="Separa a lista pelos nomes de 'Onde encontrar'.")

    b = backlog.copy()
    if f_resp:
        b = b[b["responsavel"].isin(f_resp)]
    if f_onde:
        sem_local = "(nao definido)" in f_onde
        b = b[b["onde_encontrar"].isin(f_onde) | (sem_local & b["onde_encontrar"].isna())]
    if f_sit == "Pendentes":
        b = b[~b["atendida"]]
    elif f_sit == "Atendidas":
        b = b[b["atendida"]]
    if f_urg:
        b = b[b["urgente"]]
    if f_venc:
        b = b[b["vencida"]]
    if f_busca:
        alvo_txt = (b["DESCRICAO"].astype(str) + " " + b["NUM.SC"].astype(str) + " "
                    + b["SOLICITANTE"].astype(str))
        b = b[alvo_txt.str.contains(f_busca, case=False, na=False, regex=False)]
    b = b.sort_values("idade_dias", ascending=False)

    n_at = int(b["atendida"].sum())
    ui.kpis([
        {"rot": "Na lista", "val": ui.num(len(b)), "cor": ui.AZUL,
         "sub": f"<b>{ui.brl_curto(b['VALOR'].sum())}</b> em valor"},
        {"rot": "Pendentes", "val": ui.num(len(b) - n_at), "cor": ui.LARANJA,
         "sub": "ainda nao marcadas"},
        {"rot": "Atendidas", "val": ui.num(n_at), "cor": ui.BOM,
         "sub": "marcadas pela equipe"},
        {"rot": "Sem local definido", "val": ui.num(b["onde_encontrar"].isna().sum()),
         "cor": ui.AZUL_ESCURO, "sub": "campo 'Onde encontrar' vazio"},
    ])

    if usuario is None:
        ui.alerta("aviso", "👤", "Escolha seu nome na barra lateral",
                  "Assim fica registrado quem marcou cada SC como atendida.")

    def _salvar(chave: str, campo: str):
        chave_w = f"{campo}_{chave}"
        valor = st.session_state.get(chave_w)
        try:
            if campo == "at":
                store.salvar(chave, usuario or "?", atendida=bool(valor))
            else:
                store.salvar(chave, usuario or "?", onde=valor or "")
                if valor:  # mostra ja padronizado (mesma grafia para todos)
                    st.session_state[chave_w] = " ".join(str(valor).split()).upper()
            st.toast("Salvo ✓", icon="💾")
        except Exception as e:  # noqa: BLE001
            st.toast(f"Erro ao salvar: {e}", icon="⚠️")

    def _fmt(d):
        return pd.Timestamp(d).strftime("%d/%m/%Y") if pd.notna(d) else "-"

    def cartao(r):
        chave = r["chave"]
        estado = "ok" if r["atendida"] else ("venc" if r["vencida"] else
                                             ("urg" if r["urgente"] else "normal"))
        with st.container(border=True, key=f"sc-{estado}-{chave}"):
            c_info, c_acao = st.columns([7, 3], gap="medium", vertical_alignment="center")
            badges = [f'<span class="bdg tipo">{_html.escape(TIPO_NOME.get(r["tipo_cod"], r["tipo_cod"] or "-"))}</span>']
            if r["atendida"]:
                quem = r["atendida_por"] or "-"
                quando = (pd.Timestamp(r["atendida_em"]).strftime("%d/%m %H:%M")
                          if pd.notna(r["atendida_em"]) and r["atendida_em"] else "")
                badges.insert(0, f'<span class="bdg ok">✓ Atendida · {_html.escape(str(quem))} {quando}</span>')
            if r["vencida"]:
                badges.append(f'<span class="bdg venc">⏰ Vencida ha {int(r["dias_atraso"])} d</span>')
            if r["urgente"]:
                badges.append('<span class="bdg urg">🔥 Urgencia ALTA</span>')
            if pd.notna(r["onde_encontrar"]) and r["onde_encontrar"]:
                badges.append(f'<span class="bdg local">📍 {_html.escape(r["onde_encontrar"])}</span>')
            resp = r["responsavel"] if pd.notna(r["responsavel"]) and r["responsavel"] else "sem dono"
            c_info.markdown(
                f'<div class="sc-card">'
                f'<div class="sc-top"><span class="sc-num">SC {_html.escape(str(r["NUM.SC"]))}'
                f'<span class="sc-item"> · item {_html.escape(str(r["ITEM"]))}</span></span>'
                f'{"".join(badges)}</div>'
                f'<div class="sc-desc">{_html.escape(str(r["DESCRICAO"]))}</div>'
                f'<div class="sc-meta">'
                f'<span><b>{r["QTD"]:g}</b> un</span>'
                f'<span><b>{ui.brl(r["VALOR"])}</b></span>'
                f'<span>Emissao <b>{_fmt(r["DT_EMISSAO"])}</b> · {int(r["idade_dias"])} dias</span>'
                f'<span>Necessidade <b>{_fmt(r["DT_NECESSIDADE"])}</b></span>'
                f'<span>👤 <b>{_html.escape(str(resp))}</b></span>'
                f'<span>Solicitante {_html.escape(str(r["SOLICITANTE"]))}</span>'
                f'<span>{_html.escape(str(r["DESC_DEPARTAMENTO"]).title())}</span>'
                f"</div></div>",
                unsafe_allow_html=True,
            )
            k_at, k_onde = f"at_{chave}", f"onde_{chave}"
            if k_at not in st.session_state:
                st.session_state[k_at] = bool(r["atendida"])
            if k_onde not in st.session_state:
                st.session_state[k_onde] = (r["onde_encontrar"]
                                            if pd.notna(r["onde_encontrar"]) else None)
            opcoes = locais + ([st.session_state[k_onde]]
                               if st.session_state[k_onde] and st.session_state[k_onde] not in locais
                               else [])
            c_acao.checkbox("✅ Atendida", key=k_at, on_change=_salvar, args=(chave, "at"))
            c_acao.selectbox(
                "📍 Onde encontrar", opcoes, key=k_onde, accept_new_options=True,
                placeholder="Digite ou escolha...", on_change=_salvar, args=(chave, "onde"),
                label_visibility="collapsed")

    ver_tabela = st.toggle("Ver como tabela (planilha)", key="bl_tabela")
    if ver_tabela:
        tabela_sc(b, extra=["atendida", "onde_encontrar"], altura=520)
    elif b.empty:
        ui.alerta("ok", "✅", "Nenhuma SC neste filtro")
    else:
        POR_PAGINA = 20
        if agrupar:
            grupos = b.assign(_g=b["onde_encontrar"].fillna("(nao definido)"))
            ordem = [g for g in grupos.groupby("_g").size().sort_values(ascending=False).index
                     if g != "(nao definido)"] + (["(nao definido)"]
                                                  if b["onde_encontrar"].isna().any() else [])
            for g in ordem:
                sub = grupos[grupos["_g"] == g]
                with st.expander(f"📍 {g} · {len(sub)} SC-itens · "
                                 f"{ui.brl(sub['VALOR'].sum())}",
                                 expanded=g != "(nao definido)"):
                    for _, r in sub.head(100).iterrows():
                        cartao(r)
                    if len(sub) > 100:
                        st.caption(f"Mostrando 100 de {len(sub)}. Use os filtros.")
        else:
            n_pag = max(1, -(-len(b) // POR_PAGINA))
            pg_col1, pg_col2 = st.columns([8, 2])
            pag = pg_col2.number_input("Pagina", 1, n_pag, 1, key="bl_pag") if n_pag > 1 else 1
            pg_col1.caption(f"Mostrando {min(len(b), (pag - 1) * POR_PAGINA + 1)}-"
                            f"{min(len(b), pag * POR_PAGINA)} de {len(b)} · "
                            "mais antigas primeiro")
            for _, r in b.iloc[(pag - 1) * POR_PAGINA: pag * POR_PAGINA].iterrows():
                cartao(r)

    baixar_csv(b[COLS_SC + ["atendida", "atendida_por", "onde_encontrar"]],
               "backlog_a_atender.csv", "⬇️ Baixar lista (CSV)")

# --------------------------------------------------------------------------- #
# Tab 2 - Sem distribuicao
# --------------------------------------------------------------------------- #
with tab2:
    ui.secao("SCs sem registro de distribuicao",
             "Estao na demanda do Protheus mas nao aparecem na planilha de distribuicao - "
             "risco classico de 'SC perdida'. As sem pedido sao as mais criticas.")
    criticas = sem_dist[~sem_dist["com_pedido"]]
    com_ped = sem_dist[sem_dist["com_pedido"]]
    ui.alerta("critico" if len(criticas) else "ok", "🔴" if len(criticas) else "✅",
              f"{len(criticas)} sem distribuicao E sem pedido",
              "Atue primeiro nestas." if len(criticas) else "Nenhuma SC perdida.")
    tabela_sc(criticas.sort_values("idade_dias", ascending=False))
    baixar_csv(criticas[COLS_SC], "sc_perdidas.csv", "⬇️ Baixar criticas (CSV)")
    if len(com_ped):
        ui.alerta("aviso", "🟡", f"{len(com_ped)} viraram pedido sem passar pela distribuicao",
                  "Atendidas direto - vale registrar para manter o historico.")
        tabela_sc(com_ped)

# --------------------------------------------------------------------------- #
# Tab 3 - Compradores
# --------------------------------------------------------------------------- #
with tab3:
    ui.secao("Desempenho e carga por comprador",
             "SC-itens distribuidos no filtro. Tempo SC → pedido em dias corridos "
             "(da liberacao ate a emissao do pedido).")
    carga = mt.carga_comprador(mf)
    st.dataframe(
        carga[["responsavel", "total", "Com pedido", "Sem pedido", "pct_pendente",
               "vencidas", "valor_backlog", "lead_mediano"]].rename(columns={
            "responsavel": "COMPRADOR", "total": "SC-ITENS", "Com pedido": "COM PEDIDO",
            "Sem pedido": "SEM PEDIDO", "pct_pendente": "% PENDENTE",
            "vencidas": "VENCIDAS", "valor_backlog": "BACKLOG R$",
            "lead_mediano": "TEMPO MEDIANO (dias)"}),
        width="stretch", hide_index=True,
        column_config={
            "% PENDENTE": st.column_config.ProgressColumn(
                format="%d%%", min_value=0, max_value=100),
            "BACKLOG R$": st.column_config.NumberColumn(format="R$ %.2f"),
            "TEMPO MEDIANO (dias)": st.column_config.NumberColumn(format="%.0f d"),
        },
    )
    c_a, c_b = st.columns(2, gap="medium")
    with c_a, st.container(border=True):
        ui.secao("Tempo SC → pedido por comprador",
                 "Cada ponto e um SC-item atendido; a caixa mostra onde esta a maioria.")
        lt_df = mf[mf["lead_time_dias"].notna() & mf["responsavel"].notna()]
        fig = go.Figure()
        for resp in sorted(lt_df["responsavel"].unique()):
            v = lt_df[lt_df["responsavel"] == resp]["lead_time_dias"]
            fig.add_box(y=v, name=resp, marker_color=ui.AZUL, line=dict(width=1.5),
                        fillcolor="rgba(42,120,214,.15)", boxpoints="all", jitter=0.4,
                        pointpos=0, marker=dict(size=5, opacity=.45),
                        hovertemplate=f"{resp}: %{{y}} dias<extra></extra>")
        ui.estilo(fig, 340, legenda=False)
        fig.update_yaxes(title="dias", rangemode="tozero")
        ui.grafico(fig)
    with c_b, st.container(border=True):
        ui.secao("Backlog por comprador (R$)", "Valor das SCs distribuidas ainda sem pedido.")
        cv = carga.sort_values("valor_backlog")
        fig = go.Figure(go.Bar(
            y=cv["responsavel"], x=cv["valor_backlog"], orientation="h",
            marker_color=ui.AZUL_ESCURO, text=cv["valor_backlog"].map(ui.brl_curto),
            textposition="outside", cliponaxis=False, textfont=dict(color=ui.TINTA_2),
            hovertemplate="%{y}: R$ %{x:,.2f}<extra></extra>",
        ))
        ui.estilo(fig, 340, legenda=False, horizontal=True)
        fig.update_xaxes(visible=False,
                         range=[0, max(cv["valor_backlog"].max() if len(cv) else 1, 1) * 1.25])
        ui.grafico(fig)
    st.caption("Equipe atual: " + ", ".join(sorted(nz.EQUIPE_ATUAL)) +
               " | Eduardo = aprendiz (implanta pedidos, fora das metricas de carga).")

# --------------------------------------------------------------------------- #
# Tab 4 - Entregas pendentes
# --------------------------------------------------------------------------- #
with tab4:
    ui.secao("Pedidos com entrega pendente",
             "Itens nao encerrados com saldo a receber. Cinza (eliminado por residuo) "
             "nao entra - e saldo cancelado.")
    pcols = st.columns(4)
    comp_opts = sorted([c for c in pend["comprador"].dropna().unique()])
    f_comp = pcols[0].multiselect("Comprador", comp_opts, key="ent_comp", placeholder="Todos")
    max_idade = int(pend["dias_em_aberto"].max()) if len(pend) else 0
    min_idade = pcols[1].slider("Idade minima (dias)", 0, max(max_idade, 1), 0)
    forn_busca = pcols[2].text_input("Fornecedor contem", key="ent_forn")
    ocultar_prenota = pcols[3].checkbox(
        "Ocultar o que ja chegou (pre nota)", key="ent_prenota",
        help="Pre nota (laranja) = ja chegou na fabrica, falta so lancar a nota fiscal.",
    )
    p = pend.copy()
    if f_comp:
        p = p[p["comprador"].isin(f_comp)]
    p = p[p["dias_em_aberto"] >= min_idade]
    if forn_busca:
        p = p[p["FORNECEDOR"].str.contains(forn_busca, case=False, na=False)]
    if ocultar_prenota:
        p = p[~p["chegou_fabrica"]]
    p = p.sort_values("dias_em_aberto", ascending=False)

    ui.kpis([
        {"rot": "Itens pendentes", "val": ui.num(len(p)), "cor": ui.LARANJA,
         "sub": f"em <b>{ui.num(p['PEDIDO COMPRA'].nunique())}</b> pedidos"},
        {"rot": "Ja chegaram (pre nota)", "val": ui.num(p["chegou_fabrica"].sum()),
         "cor": ui.BOM, "sub": "falta lancar a nota"},
        {"rot": "Aguardando chegada", "val": ui.num((~p["chegou_fabrica"]).sum()),
         "cor": ui.AZUL, "sub": "com o fornecedor"},
        {"rot": "Valor a receber", "cor": ui.AZUL_ESCURO,
         "val": ui.brl_curto((p["saldo"] * p.get("PRECO.", 0)).sum()),
         "sub": "saldo x preco unitario"},
    ])

    show = p[["PEDIDO COMPRA", "EMISSAO", "comprador", "FORNECEDOR", "PRODUTO",
              "DESCRICAO.", "QUANTIDADE", "QUANT ENTREG", "saldo", "dias_em_aberto",
              "situacao_label"]].copy()
    show["EMISSAO"] = br_data(show["EMISSAO"])
    show = show.rename(columns={"comprador": "COMPRADOR", "dias_em_aberto": "DIAS",
                                "DESCRICAO.": "DESCRICAO", "situacao_label": "SITUACAO",
                                "saldo": "SALDO"})
    st.dataframe(show, width="stretch", hide_index=True, height=420,
                 column_config={"DIAS": st.column_config.NumberColumn(format="%d d")})
    baixar_csv(show, "entregas_pendentes.csv", "⬇️ Baixar entregas (CSV)")

    e1, e2 = st.columns(2, gap="medium")
    with e1, st.container(border=True):
        ui.secao("Pendencias por comprador")
        pc_c = p.groupby("comprador").size().sort_values()
        fig = go.Figure(go.Bar(y=pc_c.index, x=pc_c.values, orientation="h",
                               marker_color=ui.LARANJA, text=pc_c.values,
                               textposition="outside", cliponaxis=False,
                               textfont=dict(color=ui.TINTA_2),
                               hovertemplate="%{y}: %{x} itens<extra></extra>"))
        ui.estilo(fig, 280, legenda=False, horizontal=True)
        fig.update_xaxes(visible=False, range=[0, max(pc_c.max() if len(pc_c) else 1, 1) * 1.2])
        ui.grafico(fig)
    with e2, st.container(border=True):
        ui.secao("Pendencias por situacao")
        pc_s = p.groupby("situacao_label").size().sort_values()
        fig = go.Figure(go.Bar(y=pc_s.index, x=pc_s.values, orientation="h",
                               marker_color=ui.AZUL, text=pc_s.values,
                               textposition="outside", cliponaxis=False,
                               textfont=dict(color=ui.TINTA_2),
                               hovertemplate="%{y}: %{x} itens<extra></extra>"))
        ui.estilo(fig, 280, legenda=False, horizontal=True)
        fig.update_xaxes(visible=False, range=[0, max(pc_s.max() if len(pc_s) else 1, 1) * 1.2])
        ui.grafico(fig)

# --------------------------------------------------------------------------- #
# Tab 5 - Visao 360 por SC
# --------------------------------------------------------------------------- #
with tab5:
    ui.secao("Rastreio completo de uma SC", "Distribuicao → pedido → entrega.")
    num = st.text_input("Numero da SC (ex.: 052507)").strip()
    if num:
        alvo = model[model["NUM.SC"].astype(str).str.contains(num, na=False, regex=False)]
        if alvo.empty:
            st.warning("SC nao encontrada na demanda atual (rmatr029).")
        else:
            for _, r in alvo.iterrows():
                with st.container(border=True):
                    st.markdown(f"**SC {r['NUM.SC']} - item {r['ITEM']}** · {r['DESCRICAO']}")
                    a, b_, c = st.columns(3)
                    nec = (pd.Timestamp(r["DT_NECESSIDADE"]).strftime("%d/%m/%Y")
                           if pd.notna(r["DT_NECESSIDADE"]) else "-")
                    a.markdown(f"Tipo: **{r['tipo_cod']}**  \nQtd: **{r['QTD']:g}**  \n"
                               f"Valor: **{ui.brl(r['VALOR'])}**  \n"
                               f"Aprovado: **{r['APROVADO']}**  \nNecessidade: **{nec}**")
                    if r["distribuida"]:
                        dt = r["dt_distribuicao"]
                        dtxt = pd.Timestamp(dt).strftime("%d/%m/%Y") if pd.notna(dt) else "-"
                        b_.success(f"Distribuida\n\nResponsavel: **{r['responsavel'] or 'nao identificado'}**\n\nEm: {dtxt}")
                    else:
                        b_.error("Sem registro de distribuicao")
                    if r["com_pedido"]:
                        ped = ped_agg[ped_agg["PEDIDO COMPRA"].astype(str) == str(r["PEDIDO"])]
                        lt_txt = (f"\n\nTempo SC → pedido: **{r['lead_time_dias']:.0f} dias**"
                                  if pd.notna(r["lead_time_dias"]) else "")
                        if not ped.empty:
                            pr = ped.iloc[0]
                            status = "Entregue" if pr["entregue_total"] else f"Saldo {pr['saldo']:g}"
                            c.info(f"Pedido **{r['PEDIDO']}**\n\n{pr['fornecedor']}\n\n"
                                   f"Entrega: **{status}**{lt_txt}")
                        else:
                            c.info(f"Pedido **{r['PEDIDO']}** (fora do rmatr052 atual){lt_txt}")
                    else:
                        c.warning("Ainda sem pedido" + (" · **necessidade vencida**"
                                                        if r["vencida"] else ""))

# --------------------------------------------------------------------------- #
# Tab 6 - Qualidade de dados
# --------------------------------------------------------------------------- #
with tab6:
    ui.secao("Qualidade dos dados")
    resp_col = dist["RESPONSAVEL"]
    if isinstance(resp_col, pd.DataFrame):  # cabecalho duplicado: usa a 1a coluna
        resp_col = resp_col.iloc[:, 0]
    brutos = resp_col.astype(str).str.strip()
    _descartar = {"", "none", "nan", "nat", "<na>"}
    # forca str + key=str.lower: impossivel dar TypeError mesmo com dado misto
    nao_rec = sorted(
        {str(b).strip() for b in brutos
         if nz.norm_comprador(b) is None and str(b).strip().lower() not in _descartar},
        key=str.lower,
    )
    ui.kpis([
        {"rot": "Grafias distintas em RESPONSAVEL", "val": ui.num(brutos.nunique()),
         "cor": ui.AZUL, "sub": "normalizadas para o nome canonico"},
        {"rot": "Valores nao reconhecidos", "val": ui.num(len(nao_rec)),
         "cor": ui.ALERTA if nao_rec else ui.BOM, "sub": "ignorados como lixo"},
        {"rot": "SC-itens sem data de necessidade", "cor": ui.AZUL,
         "val": ui.num(model["DT_NECESSIDADE"].isna().sum()), "sub": "no rmatr029"},
    ])
    st.write("Valores ignorados como lixo na planilha de distribuicao:")
    st.write(", ".join(f"`{v}`" for v in nao_rec) or "nenhum")
    st.divider()
    rateio = scs.copy()
    rateio["chave"] = [nz.chave_sc(n, i) for n, i in zip(rateio["NUM.SC"], rateio["ITEM"])]
    st.caption(
        f"rmatr029: {len(scs)} linhas -> {rateio['chave'].nunique()} SC-itens unicos "
        f"(diferenca = rateio por centro de custo, tratado automaticamente)."
    )

# --------------------------------------------------------------------------- #
# Relatorio Excel (sidebar)
# --------------------------------------------------------------------------- #
st.sidebar.divider()
st.sidebar.subheader("Relatorio")


def _sc_excel(df):
    out = df[COLS_SC + ["vencida", "dias_atraso", "lead_time_dias", "atendida",
                        "atendida_por", "onde_encontrar"]].copy()
    return out.rename(columns={
        "tipo_cod": "TIPO", "VALOR": "VALOR R$", "DT_EMISSAO": "EMISSAO",
        "idade_dias": "IDADE (dias)", "DT_NECESSIDADE": "NECESSIDADE",
        "responsavel": "RESPONSAVEL", "DESC_DEPARTAMENTO": "DEPARTAMENTO",
        "vencida": "VENCIDA", "dias_atraso": "ATRASO (dias)",
        "lead_time_dias": "TEMPO SC-PEDIDO (dias)", "atendida": "ATENDIDA",
        "atendida_por": "ATENDIDA POR", "onde_encontrar": "ONDE ENCONTRAR"})


abas_xlsx = {
    "Resumo": pd.DataFrame({
        "Indicador": ["SC-itens no filtro", "Backlog sem pedido", "Backlog R$",
                      "Necessidade vencida", "Sem dono e sem pedido",
                      "Tempo mediano SC-pedido (dias)", "Entregas pendentes"],
        "Valor": [len(mf), len(backlog), round(backlog["VALOR"].sum(), 2), len(vencidas),
                  len(perdidas), lt["mediana"], len(pend)],
    }),
    "Backlog": _sc_excel(backlog.sort_values("idade_dias", ascending=False)),
    "Vencidas": _sc_excel(vencidas.sort_values("dias_atraso", ascending=False)),
    "Sem distribuicao": _sc_excel(sem_dist),
    "Compradores": carga.rename(columns={"responsavel": "COMPRADOR"}),
    "Entregas pendentes": show,
}
st.sidebar.download_button(
    "📥 Baixar relatorio Excel",
    export.relatorio_excel(abas_xlsx),
    file_name=f"gestao_sc_{hoje.strftime('%Y-%m-%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    help="Todas as visoes (com os filtros atuais) em um unico arquivo.",
    width="stretch",
)
