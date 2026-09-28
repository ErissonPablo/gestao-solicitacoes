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
from src import banco as bc, historico as hi  # noqa: E402
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
@st.cache_data(show_spinner="Gerando dados de demonstracao...")
def _demo() -> dict:
    import os

    from src import demo
    return demo.gerar(n_scs=int(os.environ.get("GSC_DEMO_N", "260")))


# Mudou a regra de leitura/cruzamento? Troque a versao: invalida o cache antigo
# (o cache do Streamlit so enxerga o codigo da propria funcao, nao o de src/).
VERSAO_MOTOR = "2026-09-28"


@st.cache_data(show_spinner="Identificando os arquivos...", max_entries=5)
def _resolver(itens: tuple, versao: str = VERSAO_MOTOR) -> dict:
    """Cacheado: so reclassifica quando os arquivos mudam."""
    cands = [{"nome": n, "bytes": b, "head": h, "path": p, "mtime": m}
             for n, b, h, p, m in itens]
    return ds.resolver(cands)


def _chaves_candidatos(cands: list) -> tuple:
    return tuple((c.get("nome"), c.get("bytes"), c.get("head"), c.get("path"),
                  c.get("mtime")) for c in cands)


@st.cache_data(show_spinner="Lendo a pasta...", max_entries=5)
def _candidatos_pasta(pasta: str, assinatura: tuple) -> list:
    """Cacheado pela assinatura (nome, tamanho, data) dos arquivos da pasta."""
    return ds.candidatos_da_pasta(pasta)


def _assinatura_pasta(pasta: str) -> tuple:
    itens = []
    for p in Path(pasta).iterdir():
        if p.suffix.lower() in (".xls", ".xlsx", ".xml") and not p.name.startswith("~$"):
            try:
                s = p.stat()
                itens.append((p.name, s.st_size, s.st_mtime))
            except OSError:
                continue
    return tuple(sorted(itens))


@st.cache_data(show_spinner="Cruzando SCs, distribuicao e pedidos...", max_entries=3)
def _processar(sc_b: bytes, pc_b: bytes, dist_b: bytes, hoje_iso: str,
               versao: str = VERSAO_MOTOR) -> dict:
    """Todo o processamento pesado, feito 1 vez por conjunto de arquivos/dia."""
    scs_ = loaders.load_scs(io.BytesIO(sc_b))
    pcs_ = loaders.load_pcs(io.BytesIO(pc_b))
    dist_ = loaders.load_distribuicao(io.BytesIO(dist_b))
    hoje_ = pd.Timestamp(hoje_iso)
    resp_col = dist_["RESPONSAVEL"]
    if isinstance(resp_col, pd.DataFrame):  # cabecalho duplicado: usa a 1a coluna
        resp_col = resp_col.iloc[:, 0]
    return {
        "model": mt.enriquecer(crossref.build_sc_model(scs_, dist_), hoje_),
        "pend": crossref.pendencias_entrega(pcs_, hoje_),
        "ped_agg": crossref.agrega_pedidos(pcs_),
        # itens de pedido (so o necessario) p/ achar o pedido das SCs que sairam
        "pcs_itens": pcs_[[c for c in ("PEDIDO COMPRA", "EMISSAO", "PRODUTO", "DATA SOLICIT",
                                       "QUANTIDADE", "QUANT ENTREG", "FORNECEDOR",
                                       "ENCERRADO", "Legenda", "COMPRADOR")
                           if c in pcs_.columns]].copy(),
        "resp_brutos": resp_col.astype(str).str.strip(),
        "n_linhas_sc": len(scs_),
        "n_chaves_sc": len({nz.chave_sc(n, i) for n, i in zip(scs_["NUM.SC"], scs_["ITEM"])}),
    }


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
        candidatos = _candidatos_pasta(pasta, _assinatura_pasta(pasta))
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
    resolvido = _resolver(_chaves_candidatos(candidatos), VERSAO_MOTOR)
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
    # Datas internas (ISO) para o historico
    refs_iso = {}
    for _t, _v in resolvido["detalhes"].items():
        _dt = pd.to_datetime(_v.get("ref"), dayfirst=True, errors="coerce")
        if pd.notna(_dt):
            refs_iso[_t] = _dt.strftime("%Y-%m-%d")
    st.session_state["_refs_iso"] = refs_iso
    # Aviso: distribuicao muito mais antiga que as SCs -> SCs novas sem dono
    _det = resolvido["detalhes"]
    try:
        _d_sc = pd.to_datetime(_det["sc"]["ref"], dayfirst=True)
        _d_dist = pd.to_datetime(_det["dist"]["ref"], dayfirst=True)
        if (_d_sc - _d_dist).days > 3:
            st.sidebar.warning(
                f"⚠️ A distribuicao vai so ate **{_d_dist:%d/%m}** e as SCs sao de "
                f"**{_d_sc:%d/%m}**. SCs mais novas vao aparecer sem responsavel. "
                "Confira se subiu a planilha de distribuicao atualizada.")
    except (KeyError, ValueError, TypeError):
        pass

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
hoje = pd.Timestamp.today().normalize()
_proc = _processar(sc_bytes, pc_bytes, dist_bytes, hoje.isoformat(), VERSAO_MOTOR)
model = _proc["model"]
pend_all = _proc["pend"]
ped_agg = _proc["ped_agg"]

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

COLS_ACOMP = ["chave", "atendida", "atendida_por", "atendida_em", "onde_encontrar"]
model = model.merge(acomp[COLS_ACOMP], on="chave", how="left")
model["atendida"] = model["atendida"].fillna(False).astype(bool)

EQUIPE_USUARIOS = sorted(nz.EQUIPE_ATUAL | nz.IMPLANTADORES)
st.sidebar.divider()
usuario = st.sidebar.selectbox(
    "👤 Voce e", EQUIPE_USUARIOS, index=None, placeholder="Escolha seu nome",
    key="usuario", help="Fica registrado quem marcou cada SC como atendida.")
st.sidebar.caption(f"Marcacoes salvas em: {store.nome}")


# --------------------------------------------------------------------------- #
# Historico (vida de cada SC) - grava 1x por conjunto de arquivos
# --------------------------------------------------------------------------- #
@st.cache_resource
def _banco_persistente():
    try:
        segredos = dict(st.secrets)
    except Exception:  # noqa: BLE001 - sem secrets.toml
        segredos = {}
    return bc.criar(segredos, raiz=Path(__file__).parent)


banco = None if modo_demo else _banco_persistente()
# historico inicial: so vai para o banco compartilhado (Supabase), uma unica vez
if banco is not None and banco.compartilhado and not st.session_state.get("_hist_inicial_ok"):
    try:
        _imp = hi.importar_inicial(banco, Path(__file__).parent / "data" / "historico_inicial.json")
        if _imp:
            st.session_state["_hist_res"] = _imp
            st.toast(_imp["mensagem"], icon="📜")
    except Exception as e:  # noqa: BLE001
        st.session_state["_hist_res"] = {"status": "erro",
                                         "mensagem": f"Falha ao importar historico inicial: {e}"}
    st.session_state["_hist_inicial_ok"] = True
if banco is not None and candidatos:
    _assin = hi.assinatura(sc_bytes, pc_bytes, dist_bytes)
    if st.session_state.get("_hist_assin") != _assin:
        try:
            with st.spinner("Atualizando o historico..."):
                _res = hi.sincronizar(
                    banco, _proc["model"], ped_agg, st.session_state.get("_refs_iso", {}),
                    _assin, usuario,
                    {t: d.get("nome") for t, d in resolvido["detalhes"].items()},
                    _proc["pcs_itens"])
        except Exception as e:  # noqa: BLE001
            _res = {"status": "erro", "mensagem": f"Nao consegui gravar o historico: {e}"}
        st.session_state["_hist_assin"] = _assin
        st.session_state["_hist_res"] = _res
        if _res.get("status") == "gravado":
            st.toast(_res["mensagem"], icon="📜")
            st.session_state["_hist_versao"] = st.session_state.get("_hist_versao", 0) + 1
_hres = st.session_state.get("_hist_res")
if banco is not None:
    _icone = {"gravado": "📜", "ja_gravado": "📜", "antigo": "⚠️", "erro": "❌"}
    st.sidebar.caption(
        f"Historico em: {banco.nome}"
        + (f"  \n{_icone.get(_hres.get('status'), 'ℹ️')} {_hres.get('mensagem')}" if _hres else ""))

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

mf_base = mf.drop(columns=COLS_ACOMP[1:])  # sem as marcacoes (o fragmento reaplica)
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

tabs = st.tabs(on_change="rerun", key="aba", tabs=[
    "📊 Visao geral",
    "🚨 Alertas",
    "📋 Backlog a atender",
    "⚠️ Sem distribuicao",
    "👥 Compradores",
    "🚚 Entregas pendentes",
    "🔎 Visao 360 por SC",
    "📜 Historico",
    "🧪 Qualidade de dados",
])
(tab_geral, tab_alertas, tab1, tab2, tab3, tab4, tab5, tab_hist, tab6) = tabs

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
@st.fragment
def _aba_geral():
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


if tab_geral.open:
    with tab_geral:
        _aba_geral()

# --------------------------------------------------------------------------- #
# Alertas
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_alertas():
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


if tab_alertas.open:
    with tab_alertas:
        _aba_alertas()

# --------------------------------------------------------------------------- #
# Tab 1 - Backlog
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_backlog():
    ui.secao("SCs aprovadas ainda sem pedido",
             "Marque o que ja foi atendido e anote onde encontrar cada produto. "
             "As marcacoes ficam salvas por SC-item e continuam valendo nas proximas "
             "subidas das planilhas.")
    # Recarrega as marcacoes: dentro do fragmento so esta aba roda de novo
    try:
        acomp_f = store.carregar()
    except Exception:  # noqa: BLE001
        acomp_f = acomp
    backlog = mf_base[~mf_base["com_pedido"]].merge(
        acomp_f[COLS_ACOMP], on="chave", how="left")
    backlog["atendida"] = backlog["atendida"].fillna(False).astype(bool)
    locais = sorted(acomp_f["onde_encontrar"].dropna().unique().tolist())

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
    ORDENS = {
        "Mais recentes": (["DT_EMISSAO", "NUM.SC", "ITEM"], [False, False, True]),
        "Mais antigas": (["DT_EMISSAO", "NUM.SC", "ITEM"], [True, True, True]),
        "Necessidade": (["DT_NECESSIDADE", "NUM.SC", "ITEM"], [True, True, True]),
        "Maior valor": (["VALOR"], [False]),
    }
    o1, o2 = st.columns([6, 4], vertical_alignment="bottom")
    ordem_sel = o1.segmented_control("Ordenar por", list(ORDENS), default="Mais recentes",
                                     key="bl_ordem") or "Mais recentes"
    ver_tabela = o2.toggle("Ver como tabela (planilha)", key="bl_tabela")
    cols_o, asc_o = ORDENS[ordem_sel]
    b = b.sort_values(cols_o, ascending=asc_o, na_position="last")

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
        col = "atendida" if campo == "at" else "onde_encontrar"
        lin = acomp_f[acomp_f["chave"] == chave]
        antigo = lin.iloc[0][col] if len(lin) else None
        try:
            if campo == "at":
                novo = bool(valor)
                store.salvar(chave, usuario or "?", atendida=novo)
                antigo = bool(antigo) if antigo is not None and pd.notna(antigo) else False
            else:
                novo = " ".join(str(valor).split()).upper() if valor else None
                store.salvar(chave, usuario or "?", onde=valor or "")
                if valor:  # mostra ja padronizado (mesma grafia para todos)
                    st.session_state[chave_w] = novo
                antigo = antigo if antigo is not None and pd.notna(antigo) else None
            if banco is not None and antigo != novo:
                try:
                    hi.registrar_marcacao(banco, chave, col, antigo, novo, usuario or "?")
                except Exception:  # noqa: BLE001 - log nao pode travar a marcacao
                    pass
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
            # volta para a pagina 1 quando filtro/ordem mudam
            assinatura = (tuple(f_resp), tuple(f_onde), f_busca, f_sit, f_urg, f_venc,
                          ordem_sel, len(b))
            if st.session_state.get("_bl_assin") != assinatura:
                st.session_state["_bl_assin"] = assinatura
                st.session_state["bl_pagina"] = 1
            pag = min(max(1, st.session_state.get("bl_pagina", 1)), n_pag)

            def _ir_para(nova: int):
                st.session_state["bl_pagina"] = min(max(1, int(nova)), n_pag)
                st.session_state["_bl_rolar"] = True  # volta ao topo da lista

            def paginacao(pos: str):
                if n_pag <= 1:
                    st.caption(f"{len(b)} SC-itens · {ordem_sel.lower()} primeiro")
                    return
                c1, c2, c3, c4 = st.columns([2, 4, 2, 2], vertical_alignment="center")
                if c1.button("◀ Anterior", key=f"pg_ant_{pos}", disabled=pag <= 1,
                             width="stretch"):
                    _ir_para(pag - 1)
                    st.rerun(scope="fragment")
                c2.markdown(
                    f"<div style='text-align:center;color:#52514e'>Pagina <b>{pag}</b> de "
                    f"<b>{n_pag}</b> · SC-itens {(pag - 1) * POR_PAGINA + 1}-"
                    f"{min(len(b), pag * POR_PAGINA)} de {len(b)}</div>",
                    unsafe_allow_html=True)
                escolha = c3.selectbox(
                    "Ir para a pagina", list(range(1, n_pag + 1)), index=pag - 1,
                    key=f"pg_sel_{pos}_{pag}_{n_pag}", label_visibility="collapsed",
                    format_func=lambda x: f"Pagina {x}")
                if escolha != pag:
                    _ir_para(escolha)
                    st.rerun(scope="fragment")
                if c4.button("Proxima ▶", key=f"pg_prox_{pos}", disabled=pag >= n_pag,
                             width="stretch", type="primary"):
                    _ir_para(pag + 1)
                    st.rerun(scope="fragment")

            st.markdown('<div id="topo-lista"></div>', unsafe_allow_html=True)
            if st.session_state.pop("_bl_rolar", False):
                import streamlit.components.v1 as _comp
                st.session_state["_bl_rolar_n"] = st.session_state.get("_bl_rolar_n", 0) + 1
                _comp.html(
                    f"<!-- {st.session_state['_bl_rolar_n']} -->"
                    "<script>const d=window.parent.document;"
                    "setTimeout(()=>{const e=d.getElementById('topo-lista');"
                    "if(e){e.scrollIntoView({behavior:'smooth',block:'start'});}},150);</script>",
                    height=0)
            paginacao("topo")
            for _, r in b.iloc[(pag - 1) * POR_PAGINA: pag * POR_PAGINA].iterrows():
                cartao(r)
            paginacao("rodape")

    baixar_csv(b[COLS_SC + ["atendida", "atendida_por", "onde_encontrar"]],
               "backlog_a_atender.csv", "⬇️ Baixar lista (CSV)")


if tab1.open:
    with tab1:
        _aba_backlog()

# --------------------------------------------------------------------------- #
# Tab 2 - Sem distribuicao
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_sem_dist():
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


if tab2.open:
    with tab2:
        _aba_sem_dist()

# --------------------------------------------------------------------------- #
# Tab 3 - Compradores
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_compradores():
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


if tab3.open:
    with tab3:
        _aba_compradores()

# --------------------------------------------------------------------------- #
# Tab 4 - Entregas pendentes
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_entregas():
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


if tab4.open:
    with tab4:
        _aba_entregas()

# --------------------------------------------------------------------------- #
# Tab 5 - Visao 360 por SC
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=300, show_spinner="Lendo o historico...")
def _hist_itens(_b, versao: int) -> pd.DataFrame:
    df = pd.DataFrame(_b.select("sc_item"), columns=bc.ESQUEMA["sc_item"]["cols"])
    for c in ("dt_emissao", "dt_necessidade", "dt_distribuicao", "dt_pedido", "dt_entrega",
              "primeira_vez", "ultima_vez", "dt_saiu"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("qtd", "valor"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["entregue"] = df["entregue"].fillna(False).astype(bool)
    return df


@st.cache_data(ttl=300, show_spinner="Lendo o historico...")
def _hist_eventos(_b, versao: int) -> pd.DataFrame:
    df = pd.DataFrame(_b.select("sc_evento"), columns=bc.ESQUEMA["sc_evento"]["cols"])
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def _hist_cargas(_b, versao: int) -> pd.DataFrame:
    return pd.DataFrame(_b.select("carga", ordem="ref_sc.desc"),
                        columns=bc.ESQUEMA["carga"]["cols"])


def _fdata(d):
    return pd.Timestamp(d).strftime("%d/%m/%Y") if d is not None and pd.notna(d) else "-"


def linha_do_tempo(chave: str):
    """Eventos do historico + alteracoes nas marcacoes, em ordem."""
    if banco is None:
        st.caption("Historico desligado no modo demonstracao.")
        return
    try:
        evs = hi.eventos_da_sc(banco, chave)
        logs = hi.log_da_sc(banco, chave)
    except Exception as e:  # noqa: BLE001
        st.caption(f"Nao consegui ler o historico: {e}")
        return
    itens = [(e.get("data") or "", 0, hi.EVENTO_ICONE.get(e["evento"], "•"),
              hi.EVENTO_LABEL.get(e["evento"], e["evento"]), e.get("detalhe") or "")
             for e in evs]
    for lg in logs:
        if lg["campo"] == "atendida":
            txt = "Marcada como atendida" if lg["valor_novo"] in ("True", "true", "1") \
                else "Desmarcada como atendida"
            ico = "✅"
        else:
            txt = f"Onde encontrar: {lg['valor_antigo'] or '-'} → {lg['valor_novo'] or '-'}"
            ico = "📍"
        itens.append(((lg.get("em") or "")[:10], 1, ico, txt, f"por {lg.get('usuario') or '?'}"))
    if not itens:
        st.caption("Sem historico ainda: ele comeca a ser gravado a partir da primeira "
                   "subida das planilhas com o banco ligado.")
        return
    html_itens = "".join(
        f'<div class="tl-it"><div class="tl-ico">{ico}</div><div><b>{ui.html.escape(t)}</b>'
        f'<span class="tl-dt">{_fdata(d) if d else ""}</span><br>'
        f'<span class="tl-det">{ui.html.escape(det)}</span></div></div>'
        for d, _, ico, t, det in sorted(itens, key=lambda x: (x[0], x[1])))
    st.markdown(f'<div class="tl">{html_itens}</div>', unsafe_allow_html=True)


@st.fragment
def _aba_360():
    ui.secao("Rastreio completo de uma SC",
             "Distribuicao → pedido → entrega, com a linha do tempo gravada no historico "
             "(inclusive SCs que ja sairam do rmatr029).")
    num = st.text_input("Numero da SC (ex.: 052507)").strip()
    if not num:
        return
    alvo = model[model["NUM.SC"].astype(str).str.contains(num, na=False, regex=False)]
    hist = pd.DataFrame()
    if banco is not None:
        try:
            hist = _hist_itens(banco, st.session_state.get("_hist_versao", 0))
            hist = hist[hist["num_sc"].astype(str).str.contains(num, na=False, regex=False)]
        except Exception:  # noqa: BLE001
            hist = pd.DataFrame()
    chaves = list(dict.fromkeys(list(alvo["chave"]) + list(hist.get("chave", []))))
    if not chaves:
        st.warning("SC nao encontrada no rmatr029 atual nem no historico.")
        return
    for chave in chaves[:30]:
        atual = alvo[alvo["chave"] == chave]
        with st.container(border=True):
            if len(atual):
                r = atual.iloc[0]
                st.markdown(f"**SC {r['NUM.SC']} - item {r['ITEM']}** · {r['DESCRICAO']}")
                a, b_, c = st.columns(3)
                a.markdown(f"Tipo: **{r['tipo_cod']}**  \nQtd: **{r['QTD']:g}**  \n"
                           f"Valor: **{ui.brl(r['VALOR'])}**  \n"
                           f"Aprovado: **{r['APROVADO']}**  \n"
                           f"Necessidade: **{_fdata(r['DT_NECESSIDADE'])}**")
                if r["distribuida"]:
                    b_.success(f"Distribuida\n\nResponsavel: **{r['responsavel'] or 'nao identificado'}**"
                               f"\n\nEm: {_fdata(r['dt_distribuicao'])}")
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
            else:
                h = hist[hist["chave"] == chave].iloc[0]
                st.markdown(f"**SC {h['num_sc']} - item {h['item']}** · {h['descricao']}  "
                            f"<span class='bdg ok'>Saiu do rmatr029 em {_fdata(h['dt_saiu'])}</span>",
                            unsafe_allow_html=True)
                a, b_, c = st.columns(3)
                a.markdown(f"Tipo: **{h['tipo_cod']}**  \nQtd: **{(h['qtd'] or 0):g}**  \n"
                           f"Valor: **{ui.brl(h['valor'])}**  \n"
                           f"Emissao: **{_fdata(h['dt_emissao'])}**")
                b_.success(f"Responsavel: **{h['responsavel'] or '-'}**\n\n"
                           f"Distribuida em: {_fdata(h['dt_distribuicao'])}")
                if h["pedido"]:
                    dias = ((h["dt_pedido"] - h["dt_emissao"]).days
                            if pd.notna(h["dt_pedido"]) and pd.notna(h["dt_emissao"]) else None)
                    c.info(f"Pedido **{h['pedido']}** em {_fdata(h['dt_pedido'])}"
                           + (f"\n\nTempo SC → pedido: **{dias} dias**" if dias is not None else "")
                           + f"\n\nEntrega: **{'Entregue' if h['entregue'] else 'pendente'}**")
                else:
                    c.warning("Pedido nao identificado no rmatr052")
            with st.expander("📜 Linha do tempo", expanded=len(chaves) <= 3):
                linha_do_tempo(chave)
    if len(chaves) > 30:
        st.caption(f"Mostrando 30 de {len(chaves)}. Digite o numero completo da SC.")


if tab5.open:
    with tab5:
        _aba_360()

# --------------------------------------------------------------------------- #
# Historico
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_historico():
    ui.secao("Historico das SCs",
             "Tudo o que ja passou pelas planilhas, gravado a cada subida: inclusive as SCs "
             "que ja viraram pedido e sairam do rmatr029.")
    if banco is None:
        ui.alerta("aviso", "📜", "Historico desligado no modo demonstracao",
                  "Suba as planilhas reais para gravar e consultar o historico.")
        return
    versao = st.session_state.get("_hist_versao", 0)
    try:
        hi_it = _hist_itens(banco, versao)
        hi_ev = _hist_eventos(banco, versao)
        cargas = _hist_cargas(banco, versao)
    except Exception as e:  # noqa: BLE001
        ui.alerta("critico", "❌", "Nao consegui ler o historico", str(e))
        return
    if hi_it.empty:
        ui.alerta("aviso", "📜", "Historico vazio",
                  "Ele comeca a ser gravado na proxima subida das planilhas.")
        return

    h1, h2, h3 = st.columns([3, 3, 3])
    periodo = h1.date_input(
        "Periodo (data do acontecimento)",
        value=(max(hi_ev["data"].min(), pd.Timestamp.today() - pd.Timedelta(days=90)).date(),
               pd.Timestamp.today().date()), format="DD/MM/YYYY", key="hist_periodo")
    comp_h = h2.multiselect("Comprador", sorted(hi_it["responsavel"].dropna().unique()),
                            placeholder="Todos", key="hist_comp")
    busca_h = h3.text_input("Buscar (SC, descricao, pedido)", key="hist_busca")

    it = hi_it.copy()
    if comp_h:
        it = it[it["responsavel"].isin(comp_h)]
    if busca_h:
        txt = (it["num_sc"].astype(str) + " " + it["descricao"].astype(str) + " "
               + it["pedido"].astype(str))
        it = it[txt.str.contains(busca_h, case=False, na=False, regex=False)]
    ini, fim = (periodo if isinstance(periodo, (list, tuple)) and len(periodo) == 2
                else (hi_ev["data"].min(), pd.Timestamp.today()))
    ini, fim = pd.Timestamp(ini), pd.Timestamp(fim)
    ev = hi_ev[hi_ev["chave"].isin(it["chave"]) & hi_ev["data"].between(ini, fim)]

    it["dias_ate_pedido"] = (it["dt_pedido"] - it["dt_emissao"]).dt.days
    com_ped = it[it["dt_pedido"].between(ini, fim) & it["dias_ate_pedido"].notna()]
    encerr = it[it["dt_saiu"].between(ini, fim)]
    ui.kpis([
        {"rot": "SC-itens no historico", "val": ui.num(len(it)), "cor": ui.AZUL,
         "sub": f"desde <b>{_fdata(hi_it['primeira_vez'].min())}</b>"},
        {"rot": "Viraram pedido", "val": ui.num(len(com_ped)), "cor": ui.AQUA,
         "sub": "no periodo"},
        {"rot": "Tempo SC → pedido", "cor": ui.AZUL_ESCURO,
         "val": f"{com_ped['dias_ate_pedido'].median():.0f} dias" if len(com_ped) else "-",
         "sub": (f"mediana · 90% em ate <b>{com_ped['dias_ate_pedido'].quantile(.9):.0f} dias</b>"
                 if len(com_ped) else "da emissao ao pedido")},
        {"rot": "Sairam do rmatr029", "val": ui.num(len(encerr)), "cor": ui.BOM,
         "sub": f"<b>{int(encerr['pedido'].notna().sum())}</b> com pedido identificado"},
        {"rot": "Subidas gravadas", "val": ui.num(len(cargas)), "cor": ui.LARANJA,
         "sub": f"ultima: <b>{_fdata(cargas['ref_sc'].iloc[0]) if len(cargas) else '-'}</b>"},
    ])

    g1, g2 = st.columns([3, 2], gap="medium")
    with g1, st.container(border=True):
        ui.secao("Entrada x pedidos por semana",
                 "SC-itens emitidos x SC-itens que viraram pedido, pela data de cada um.")
        sem = pd.DataFrame({
            "Emitidas": it[it["dt_emissao"].between(ini, fim)]
            .groupby(pd.Grouper(key="dt_emissao", freq="W-MON", label="left", closed="left")).size(),
            "Viraram pedido": com_ped
            .groupby(pd.Grouper(key="dt_pedido", freq="W-MON", label="left", closed="left")).size(),
        }).fillna(0)
        if len(sem):
            rot = [f"{d:%d/%m}" for d in sem.index]
            fig = go.Figure()
            fig.add_bar(x=rot, y=sem["Emitidas"], name="Emitidas", marker_color=ui.AZUL,
                        hovertemplate="Semana de %{x}: %{y} emitidas<extra></extra>")
            fig.add_scatter(x=rot, y=sem["Viraram pedido"], name="Viraram pedido",
                            mode="lines+markers", line=dict(color=ui.LARANJA, width=2.5),
                            marker=dict(size=8, line=dict(color="#fff", width=2)),
                            hovertemplate="Semana de %{x}: %{y} com pedido<extra></extra>")
            ui.estilo(fig, 300)
            fig.update_layout(hovermode="x unified")
            ui.grafico(fig)
        else:
            st.caption("Sem dados no periodo.")
    with g2, st.container(border=True):
        ui.secao("Tempo ate o pedido por comprador", "Mediana em dias, no periodo.")
        tc = (com_ped.dropna(subset=["responsavel"]).groupby("responsavel")["dias_ate_pedido"]
              .agg(["median", "size"]).sort_values("median"))
        if len(tc):
            fig = go.Figure(go.Bar(
                y=tc.index, x=tc["median"], orientation="h", marker_color=ui.AZUL_ESCURO,
                text=[f"{m:.0f} d · {n} SC" for m, n in zip(tc["median"], tc["size"])],
                textposition="outside", cliponaxis=False, textfont=dict(color=ui.TINTA_2),
                hovertemplate="%{y}: %{x:.0f} dias (mediana)<extra></extra>"))
            ui.estilo(fig, 300, legenda=False, horizontal=True)
            fig.update_xaxes(visible=False, range=[0, tc["median"].max() * 1.45 + 1])
            ui.grafico(fig)
        else:
            st.caption("Sem pedidos no periodo.")

    with st.container(border=True):
        ui.secao("Acontecimentos no periodo", "Mais recentes primeiro.")
        tipos_ev = st.pills("Tipo", list(hi.EVENTO_LABEL), selection_mode="multi",
                            format_func=lambda k: f"{hi.EVENTO_ICONE[k]} {hi.EVENTO_LABEL[k]}",
                            key="hist_tipos")
        evs = ev if not tipos_ev else ev[ev["evento"].isin(tipos_ev)]
        tab_ev = evs.merge(it[["chave", "num_sc", "item", "descricao", "responsavel"]],
                           on="chave", how="left").sort_values(["data", "id"], ascending=False)
        tab_ev = pd.DataFrame({
            "DATA": tab_ev["data"].dt.strftime("%d/%m/%Y"),
            "EVENTO": tab_ev["evento"].map(lambda k: f"{hi.EVENTO_ICONE.get(k, '')} "
                                                     f"{hi.EVENTO_LABEL.get(k, k)}"),
            "SC": tab_ev["num_sc"], "ITEM": tab_ev["item"], "DESCRICAO": tab_ev["descricao"],
            "DETALHE": tab_ev["detalhe"], "RESPONSAVEL": tab_ev["responsavel"],
        })
        st.dataframe(tab_ev, width="stretch", hide_index=True, height=380)
        st.caption(f"{len(tab_ev)} acontecimentos. Para ver a linha do tempo completa de uma "
                   "SC, use a aba 🔎 Visao 360.")
        baixar_csv(tab_ev, "historico_acontecimentos.csv", "⬇️ Baixar acontecimentos (CSV)")

    with st.expander(f"📦 Subidas gravadas ({len(cargas)})"):
        st.dataframe(pd.DataFrame({
            "GRAVADO EM": pd.to_datetime(cargas["criado_em"]).dt.strftime("%d/%m/%Y %H:%M"),
            "POR": cargas["usuario"], "EXTRACAO SC": pd.to_datetime(cargas["ref_sc"]).dt.strftime("%d/%m/%Y"),
            "EXTRACAO PC": pd.to_datetime(cargas["ref_pc"]).dt.strftime("%d/%m/%Y"),
            "DISTRIBUICAO ATE": pd.to_datetime(cargas["ref_dist"]).dt.strftime("%d/%m/%Y"),
            "SC-ITENS": cargas["n_itens"], "ACONTECIMENTOS": cargas["n_eventos"],
        }), width="stretch", hide_index=True)


if tab_hist.open:
    with tab_hist:
        _aba_historico()

# --------------------------------------------------------------------------- #
# Tab 6 - Qualidade de dados
# --------------------------------------------------------------------------- #
@st.fragment
def _aba_qualidade():
    ui.secao("Qualidade dos dados")
    brutos = _proc["resp_brutos"]
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
    st.caption(
        f"rmatr029: {_proc['n_linhas_sc']} linhas -> {_proc['n_chaves_sc']} SC-itens unicos "
        f"(diferenca = rateio por centro de custo, tratado automaticamente)."
    )


if tab6.open:
    with tab6:
        _aba_qualidade()

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


def _montar_excel() -> bytes:
    carga_x = mt.carga_comprador(mf)
    ent = pend.sort_values("dias_em_aberto", ascending=False)[
        ["PEDIDO COMPRA", "EMISSAO", "comprador", "FORNECEDOR", "PRODUTO", "DESCRICAO.",
         "QUANTIDADE", "QUANT ENTREG", "saldo", "dias_em_aberto", "situacao_label"]
    ].rename(columns={"comprador": "COMPRADOR", "dias_em_aberto": "DIAS",
                      "DESCRICAO.": "DESCRICAO", "situacao_label": "SITUACAO",
                      "saldo": "SALDO"})
    abas_xlsx = {
        "Resumo": pd.DataFrame({
            "Indicador": ["SC-itens no filtro", "Backlog sem pedido", "Backlog R$",
                          "Necessidade vencida", "Sem dono e sem pedido",
                          "Tempo mediano SC-pedido (dias)", "Entregas pendentes"],
            "Valor": [len(mf), len(backlog), round(backlog["VALOR"].sum(), 2),
                      len(vencidas), len(perdidas), lt["mediana"], len(pend)],
        }),
        "Backlog": _sc_excel(backlog.sort_values("idade_dias", ascending=False)),
        "Vencidas": _sc_excel(vencidas.sort_values("dias_atraso", ascending=False)),
        "Sem distribuicao": _sc_excel(sem_dist),
        "Compradores": carga_x.rename(columns={"responsavel": "COMPRADOR"}),
        "Entregas pendentes": ent,
    }
    return export.relatorio_excel(abas_xlsx)


# O Excel so e montado quando alguem pede (montar a cada clique deixava o app lento)
_chave_xlsx = (tuple(ano_sel), tuple(tipos_sel), so_aprovadas, tuple(comp_sel),
               len(sc_bytes), len(pc_bytes), len(dist_bytes), hoje.isoformat())
_xlsx = st.session_state.get("_xlsx")
if _xlsx and _xlsx[0] == _chave_xlsx:
    st.sidebar.download_button(
        "📥 Baixar relatorio Excel", _xlsx[1],
        file_name=f"gestao_sc_{hoje.strftime('%Y-%m-%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch", type="primary", on_click="ignore",
    )
elif st.sidebar.button("📊 Gerar relatorio Excel", width="stretch",
                       help="Todas as visoes (com os filtros atuais) em um unico arquivo."):
    with st.spinner("Montando o Excel..."):
        st.session_state["_xlsx"] = (_chave_xlsx, _montar_excel())
    st.rerun()
