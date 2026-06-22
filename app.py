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
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from src import loaders, crossref, normalize as nz, datasource as ds

st.set_page_config(
    page_title="Gestao de Solicitacoes de Compra",
    page_icon="🛒",
    layout="wide",
)

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
    ["Upload de arquivos", "Pasta local", "SharePoint"],
    help="Os 3 arquivos: rmatr029 (SCs), rmatr052 (Pedidos) e a planilha de distribuicao.",
)

sc_bytes = pc_bytes = dist_bytes = None
candidatos: list = []

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

else:  # SharePoint
    st.sidebar.info("Le os arquivos direto da pasta configurada do SharePoint.")
    if st.sidebar.button("🔄 Conectar e ler do SharePoint"):
        try:
            from src import sharepoint as sp
            st.session_state["_sp_cands"] = sp.listar_candidatos()
        except Exception as e:  # noqa: BLE001
            st.sidebar.error(f"Falha no SharePoint: {e}")
    candidatos = st.session_state.get("_sp_cands", [])

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
    st.title("Gestao de Solicitacoes de Compra")
    st.info(
        "Forneca os **3 arquivos** na barra lateral para comecar (em qualquer ordem, "
        "com qualquer nome):\n\n"
        "1. **rmatr029** - Solicitacoes de Compra (Protheus)\n"
        "2. **rmatr052** - Pedidos de Compra (Protheus)\n"
        "3. **Distribuicao** - a planilha de distribuicao (.xlsx)\n\n"
        "A ferramenta **identifica cada arquivo pelo conteudo** e, se houver mais de "
        "uma extracao do mesmo tipo, usa sempre a **mais recente** - nada e contado "
        "em dobro."
    )
    st.stop()

# --------------------------------------------------------------------------- #
# Carrega e cruza
# --------------------------------------------------------------------------- #
scs = _load_scs(sc_bytes)
pcs = _load_pcs(pc_bytes)
dist = _load_dist(dist_bytes)

model = crossref.build_sc_model(scs, dist)
pend = crossref.pendencias_entrega(pcs)
ped_agg = crossref.agrega_pedidos(pcs)

hoje = pd.Timestamp.today().normalize()
model["idade_dias"] = (hoje - model["DT_EMISSAO"]).dt.days

# --------------------------------------------------------------------------- #
# Filtros globais
# --------------------------------------------------------------------------- #
st.sidebar.divider()
st.sidebar.subheader("Filtros")

anos = sorted({d.year for d in model["DT_EMISSAO"].dropna()} | {hoje.year}, reverse=True)
ano_sel = st.sidebar.multiselect("Ano (emissao da SC)", anos, default=[2026] if 2026 in anos else anos[:1])
tipos_sel = st.sidebar.multiselect(
    "Tipo de SC", ["01", "02", "03", "07"],
    default=["01", "02", "03", "07"], format_func=lambda t: TIPO_NOME[t],
)
so_aprovadas = st.sidebar.checkbox("Somente SCs aprovadas", value=True,
                                   help="Exclui SCs eliminadas/bloqueadas/reprovadas.")

mf = model.copy()
if ano_sel:
    mf = mf[mf["DT_EMISSAO"].dt.year.isin(ano_sel)]
if tipos_sel:
    mf = mf[mf["tipo_cod"].isin(tipos_sel)]
if so_aprovadas:
    mf = mf[mf["APROVADO"].str.upper().eq("APROVADA")]

# --------------------------------------------------------------------------- #
# Cabecalho + KPIs
# --------------------------------------------------------------------------- #
st.title("Gestao de Solicitacoes de Compra")
st.caption(
    f"Filial 03 - Tipos 01/02/03/07 - {len(mf)} SC-itens no filtro - "
    f"atualizado em {hoje.strftime('%d/%m/%Y')}"
)

backlog = mf[~mf["com_pedido"]]
sem_dist = mf[~mf["distribuida"]]
perdidas = mf[(~mf["com_pedido"]) & (~mf["distribuida"])]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("SC-itens", len(mf))
c2.metric("Backlog (sem pedido)", len(backlog))
c3.metric("Sem distribuicao", len(sem_dist))
c4.metric("⚠️ Sem dono e sem pedido", len(perdidas))
c5.metric("Entregas pendentes", len(pend))

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📋 Backlog a atender",
    "⚠️ Sem distribuicao",
    "👥 Carga por comprador",
    "🚚 Entregas pendentes",
    "🔎 Visao 360 por SC",
    "🧪 Qualidade de dados",
])

COLS_SC = [
    "NUM.SC", "ITEM", "tipo_cod", "DESCRICAO", "QTD", "VALOR",
    "DT_EMISSAO", "idade_dias", "URGENCIA", "responsavel",
    "SOLICITANTE", "DESC_DEPARTAMENTO", "APROVADO", "LEGENDA",
]


def tabela_sc(df: pd.DataFrame):
    show = df[COLS_SC].copy()
    show["DT_EMISSAO"] = br_data(show["DT_EMISSAO"])
    show = show.rename(columns={
        "tipo_cod": "TIPO", "QTD": "QTD", "VALOR": "VALOR R$",
        "DT_EMISSAO": "EMISSAO", "idade_dias": "IDADE (dias)",
        "responsavel": "RESPONSAVEL", "DESC_DEPARTAMENTO": "DEPARTAMENTO",
    })
    st.dataframe(show, width="stretch", hide_index=True)


# --------------------------------------------------------------------------- #
# Tab 1 - Backlog
# --------------------------------------------------------------------------- #
with tab1:
    st.subheader("SCs aprovadas ainda sem pedido")
    st.caption("O que a equipe precisa atender. Ordenado pelas mais antigas.")
    colf1, colf2 = st.columns(2)
    resp_opts = sorted([r for r in backlog["responsavel"].dropna().unique()])
    f_resp = colf1.multiselect("Responsavel", resp_opts, key="bl_resp")
    f_urg = colf2.checkbox("Somente urgencia ALTA", key="bl_urg")
    b = backlog.copy()
    if f_resp:
        b = b[b["responsavel"].isin(f_resp)]
    if f_urg:
        b = b[b["URGENCIA"].str.upper().eq("ALTA")]
    b = b.sort_values("idade_dias", ascending=False)
    st.write(f"**{len(b)}** SC-itens - valor total R$ {b['VALOR'].sum():,.2f}")
    tabela_sc(b)
    baixar_csv(b[COLS_SC], "backlog_a_atender.csv", "⬇️ Baixar backlog (CSV)")

# --------------------------------------------------------------------------- #
# Tab 2 - Sem distribuicao
# --------------------------------------------------------------------------- #
with tab2:
    st.subheader("SCs sem registro de distribuicao")
    st.caption(
        "Estao na demanda do Protheus mas nao aparecem na planilha de distribuicao - "
        "risco classico de 'SC perdida'. As sem pedido sao as mais criticas."
    )
    criticas = sem_dist[~sem_dist["com_pedido"]]
    com_ped = sem_dist[sem_dist["com_pedido"]]
    st.error(f"🔴 {len(criticas)} sem distribuicao E sem pedido (atue primeiro nestas)")
    tabela_sc(criticas.sort_values("idade_dias", ascending=False))
    baixar_csv(criticas[COLS_SC], "sc_perdidas.csv", "⬇️ Baixar criticas (CSV)")
    if len(com_ped):
        st.warning(
            f"🟡 {len(com_ped)} viraram pedido sem passar pela distribuicao "
            "(atendidas direto - vale registrar para manter o historico)."
        )
        tabela_sc(com_ped)

# --------------------------------------------------------------------------- #
# Tab 3 - Carga por comprador
# --------------------------------------------------------------------------- #
with tab3:
    st.subheader("Carga de distribuicao por comprador")
    dist_ok = mf[mf["distribuida"] & mf["responsavel"].notna()]
    carga = (
        dist_ok.groupby("responsavel")
        .agg(SC_itens=("chave", "size"),
             valor=("VALOR", "sum"),
             sem_pedido=("com_pedido", lambda s: (~s).sum()))
        .reset_index()
        .sort_values("SC_itens", ascending=False)
    )
    carga["%_pendente"] = (carga["sem_pedido"] / carga["SC_itens"] * 100).round(0)
    ca, cb = st.columns([2, 3])
    with ca:
        st.dataframe(
            carga.rename(columns={"responsavel": "COMPRADOR", "valor": "VALOR R$",
                                  "sem_pedido": "AINDA SEM PEDIDO"}),
            width="stretch", hide_index=True,
        )
    with cb:
        st.bar_chart(carga.set_index("responsavel")["SC_itens"])
    st.caption("Equipe atual: " + ", ".join(sorted(nz.EQUIPE_ATUAL)) +
               " | Eduardo = aprendiz (implanta pedidos).")

# --------------------------------------------------------------------------- #
# Tab 4 - Entregas pendentes
# --------------------------------------------------------------------------- #
with tab4:
    st.subheader("Pedidos com entrega pendente")
    st.caption("Itens de pedido nao encerrados com saldo a receber (QTD > entregue).")
    pcols = st.columns(3)
    comp_opts = sorted([c for c in pend["comprador"].dropna().unique()])
    f_comp = pcols[0].multiselect("Comprador", comp_opts, key="ent_comp")
    min_idade = pcols[1].slider("Idade minima (dias)", 0, int(pend["dias_em_aberto"].max() or 0), 0)
    forn_busca = pcols[2].text_input("Fornecedor contem", key="ent_forn")
    p = pend.copy()
    if f_comp:
        p = p[p["comprador"].isin(f_comp)]
    p = p[p["dias_em_aberto"] >= min_idade]
    if forn_busca:
        p = p[p["FORNECEDOR"].str.contains(forn_busca, case=False, na=False)]
    p = p.sort_values("dias_em_aberto", ascending=False)
    st.write(f"**{len(p)}** itens em **{p['PEDIDO COMPRA'].nunique()}** pedidos")
    show = p[["PEDIDO COMPRA", "EMISSAO", "comprador", "FORNECEDOR", "PRODUTO",
              "DESCRICAO.", "QUANTIDADE", "QUANT ENTREG", "saldo", "dias_em_aberto",
              "Legenda"]].copy()
    show["EMISSAO"] = br_data(show["EMISSAO"])
    show = show.rename(columns={"comprador": "COMPRADOR", "dias_em_aberto": "DIAS",
                                "DESCRICAO.": "DESCRICAO"})
    st.dataframe(show, width="stretch", hide_index=True)
    baixar_csv(show, "entregas_pendentes.csv", "⬇️ Baixar entregas (CSV)")
    st.bar_chart(p.groupby("comprador").size())

# --------------------------------------------------------------------------- #
# Tab 5 - Visao 360 por SC
# --------------------------------------------------------------------------- #
with tab5:
    st.subheader("Rastreio completo de uma SC")
    num = st.text_input("Numero da SC (ex.: 052507)").strip()
    if num:
        alvo = model[model["NUM.SC"].astype(str).str.contains(num, na=False)]
        if alvo.empty:
            st.warning("SC nao encontrada na demanda atual (rmatr029).")
        else:
            for _, r in alvo.iterrows():
                with st.container(border=True):
                    st.markdown(f"**SC {r['NUM.SC']} - item {r['ITEM']}** · {r['DESCRICAO']}")
                    a, b, c = st.columns(3)
                    a.markdown(f"Tipo: **{r['tipo_cod']}**  \nQtd: **{r['QTD']:g}**  \n"
                               f"Valor: **R$ {r['VALOR']:,.2f}**  \nAprovado: **{r['APROVADO']}**")
                    if r["distribuida"]:
                        dt = r["dt_distribuicao"]
                        dtxt = pd.Timestamp(dt).strftime("%d/%m/%Y") if pd.notna(dt) else "-"
                        b.success(f"Distribuida\nResponsavel: **{r['responsavel'] or 'nao identificado'}**\nEm: {dtxt}")
                    else:
                        b.error("Sem registro de distribuicao")
                    if r["com_pedido"]:
                        ped = ped_agg[ped_agg["PEDIDO COMPRA"].astype(str) == str(r["PEDIDO"])]
                        if not ped.empty:
                            pr = ped.iloc[0]
                            status = "Entregue" if pr["entregue_total"] else f"Saldo {pr['saldo']:g}"
                            c.info(f"Pedido **{r['PEDIDO']}**\n{pr['fornecedor']}\n"
                                   f"Entrega: **{status}**")
                        else:
                            c.info(f"Pedido **{r['PEDIDO']}** (fora do rmatr052 atual)")
                    else:
                        c.warning("Ainda sem pedido")

# --------------------------------------------------------------------------- #
# Tab 6 - Qualidade de dados
# --------------------------------------------------------------------------- #
with tab6:
    st.subheader("Qualidade dos dados")
    brutos = dist["RESPONSAVEL"].astype(str).str.strip()
    nao_rec = sorted({b for b in brutos
                      if nz.norm_comprador(b) is None and b and b.lower() != "none"})
    cqa, cqb = st.columns(2)
    cqa.metric("Grafias distintas em RESPONSAVEL", brutos.nunique())
    cqb.metric("Valores nao reconhecidos (lixo)", len(nao_rec))
    st.write("Valores ignorados como lixo na planilha de distribuicao:")
    st.write(", ".join(f"`{v}`" for v in nao_rec) or "nenhum")
    st.divider()
    rateio = scs.copy()
    rateio["chave"] = [nz.chave_sc(n, i) for n, i in zip(rateio["NUM.SC"], rateio["ITEM"])]
    st.caption(
        f"rmatr029: {len(scs)} linhas -> {rateio['chave'].nunique()} SC-itens unicos "
        f"(diferenca = rateio por centro de custo, tratado automaticamente)."
    )
