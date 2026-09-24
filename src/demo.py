# -*- coding: utf-8 -*-
"""Dados FICTICIOS de demonstracao.

Gera, em memoria, os 3 arquivos nos mesmos formatos reais:
    rmatr029 (SpreadsheetML), rmatr052 (SpreadsheetML) e distribuicao (.xlsx).

Serve para abrir a ferramenta sem os arquivos do Protheus (mostrar para a
equipe, testar mudancas de layout). Nenhum dado real da Lactosul aqui.
"""
from __future__ import annotations

import io
import random
from datetime import date, timedelta
from xml.sax.saxutils import escape

COMPRADORES = ["Erisson", "Eloisa", "Alessandro", "Marcos", "Nagella"]
NOME_PROTHEUS = {
    "Erisson": "ERISSON PABLO SOUSA", "Eloisa": "ELOISA BATISTA",
    "Alessandro": "ALESSANDRO CLAUDINO FILHO", "Marcos": "MARCOS VINICIO",
    "Nagella": "NAGELLA MAIARA JESUS PIRES",
}
GRAFIAS = {  # grafias "sujas" como na planilha real
    "Erisson": ["Erisson", "ERISSON", "erisson", "erison"],
    "Eloisa": ["Eloisa", "ELOISA", "eloisa"],
    "Alessandro": ["Alessandro", "ALESSANDRO", "alessadro"],
    "Marcos": ["Marcos", "MARCOS", "marcos"],
    "Nagella": ["Nagella", "NAGELLA", "nagela"],
}
DEPARTAMENTOS = [
    "MANUTENCAO INDUSTRIAL", "PRODUCAO QUEIJOS", "PRODUCAO LEITE UHT",
    "LABORATORIO", "ALMOXARIFADO", "CALDEIRA", "LOGISTICA", "ADMINISTRATIVO",
    "SEGURANCA DO TRABALHO", "TI",
]
PRODUTOS = [
    ("ROLAMENTO 6205 2RS", 45.0), ("CORREIA EM V A-42", 38.0),
    ("SELO MECANICO BOMBA 1.1/4", 620.0), ("VALVULA BORBOLETA INOX 2\"", 480.0),
    ("LUVA NITRILICA CX 100", 32.0), ("DETERGENTE ALCALINO CIP 50L", 890.0),
    ("ACIDO NITRICO 53% BB 50L", 540.0), ("OLEO LUBRIFICANTE ISO 68 20L", 410.0),
    ("SENSOR TEMPERATURA PT100", 350.0), ("CONTATOR TRIPOLAR 25A", 210.0),
    ("FILTRO AR COMPRIMIDO", 260.0), ("PAPEL A4 CX 10 RESMAS", 280.0),
    ("TONER IMPRESSORA", 390.0), ("MANGUEIRA SANITARIA 1\" M", 95.0),
    ("REAGENTE ANALISE GORDURA", 720.0), ("PALLET PBR", 85.0),
    ("SERVICO CALIBRACAO BALANCA", 1800.0), ("SERVICO MANUTENCAO CALDEIRA", 9500.0),
    ("MOTOR ELETRICO 5CV", 3200.0), ("TROCADOR CALOR PLACA (JUNTA)", 2400.0),
]
FORNECEDORES = [
    "ROLAMENTOS GOIAS LTDA", "INOX CENTRO OESTE", "QUIMICA INDUSTRIAL BR",
    "ELETRO TECNICA RIO VERDE", "LUBRIFICANTES PLANALTO", "PAPELARIA CENTRAL",
    "LAB SUPPLY", "EMBALAGENS GO", "METROLOGIA CERRADO", "CALDEIRAS & CIA",
]
TIPOS = ["01/APLICACAO DIRETA", "02/NORMAL", "02/NORMAL", "02/NORMAL",
         "03/SERVICOS", "07/INVESTIMENTO", "04/REGULARIZACAO"]


def _d(x: date | None) -> str:
    return x.strftime("%d/%m/%Y") if x else ""


def _spreadsheetml(sheet: str, titulo: str, header: list, rows: list) -> bytes:
    def cell(v):
        if isinstance(v, (int, float)):
            return f'<Cell><Data ss:Type="Number">{v}</Data></Cell>'
        return f'<Cell><Data ss:Type="String">{escape(str(v))}</Data></Cell>'

    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        f'<Worksheet ss:Name="{sheet}"><Table>',
        f"<Row>{cell(titulo)}</Row>",
        "<Row>" + "".join(cell(h) for h in header) + "</Row>",
    ]
    for r in rows:
        out.append("<Row>" + "".join(cell(v) for v in r) + "</Row>")
    out.append("</Table></Worksheet></Workbook>")
    return "\n".join(out).encode("utf-8")


def gerar(hoje: date | None = None, n_scs: int = 260, seed: int = 7) -> dict:
    """Devolve {'sc': bytes, 'pc': bytes, 'dist': bytes}."""
    import openpyxl

    rnd = random.Random(seed)
    hoje = hoje or date.today()
    inicio = date(hoje.year, 1, 5)
    span = max((hoje - inicio).days, 30)

    sc_rows, pc_rows, dist_rows = [], [], []
    num_sc, num_pc = 52400, 31800
    for _ in range(n_scs):
        num_sc += rnd.randint(1, 3)
        # mais SCs recentes do que antigas
        emissao = inicio + timedelta(days=int(span * (rnd.random() ** 0.7)))
        tipo = rnd.choice(TIPOS)
        urg = rnd.choices(["ALTA", "MEDIA", "BAIXA"], [2, 5, 3])[0]
        dep = rnd.choice(DEPARTAMENTOS)
        solicitante = rnd.choice(["JOAO", "MARIA", "PEDRO", "ANA", "CARLOS", "LUCIA"])
        aprov = rnd.choices(["Aprovada", "Bloqueada", "Rejeitada"], [92, 5, 3])[0]
        idade = (hoje - emissao).days
        dono = rnd.choice(COMPRADORES)
        distribuida = rnd.random() > (0.05 if idade > 20 else 0.18)
        # chance de ja ter pedido cresce com a idade
        p_ped = min(0.95, 0.15 + idade / 70)
        tem_pedido = aprov == "Aprovada" and rnd.random() < p_ped
        necessidade = emissao + timedelta(days=rnd.choice([7, 10, 15, 20, 30, 45]))
        liberacao = emissao + timedelta(days=rnd.randint(0, 3))
        n_itens = rnd.choices([1, 2, 3, 4], [5, 3, 1, 1])[0]
        pedido = ""
        emis_pc = None
        if tem_pedido:
            num_pc += 1
            pedido = f"{num_pc:06d}"
            lead = max(1, int(rnd.gammavariate(2.2, 4 if urg == "ALTA" else 7)))
            emis_pc = min(hoje, liberacao + timedelta(days=lead))
            fornecedor = rnd.choice(FORNECEDORES)
        for it in range(1, n_itens + 1):
            prod, preco = rnd.choice(PRODUTOS)
            qtd = rnd.choice([1, 1, 2, 4, 5, 10, 20])
            preco = round(preco * rnd.uniform(0.8, 1.3), 2)
            rateios = 2 if rnd.random() < 0.08 else 1
            for _r in range(rateios):
                q = qtd / rateios
                sc_rows.append([
                    "03", tipo, f"{num_sc:06d}", f"{it:04d}", f"P{rnd.randint(1000, 9999)}",
                    prod, q, preco, round(q * preco, 2), _d(emissao), _d(liberacao),
                    _d(necessidade), _d(emis_pc), solicitante, dep, urg, aprov,
                    "Pedido Colocado" if pedido else "Pendente", pedido,
                ])
            if distribuida:
                dist_rows.append([
                    num_sc, it, rnd.choice(GRAFIAS[dono]),
                    emissao + timedelta(days=rnd.randint(0, 2)),
                    dep, prod, urg, "", "",
                ])
            if tem_pedido:
                dias_pc = (hoje - emis_pc).days
                if dias_pc > 45 or rnd.random() < 0.45:
                    entregue, enc, leg = qtd, "E", "Pedido Atendido"
                else:
                    r = rnd.random()
                    if r < 0.18:
                        entregue, enc, leg = 0, "", "Pre Nota"
                    elif r < 0.33:
                        entregue, enc, leg = max(0, qtd // 2), "", "Recebido Parcial"
                    elif r < 0.40:
                        entregue, enc, leg = 0, "", "Eliminado por Residuo"
                    elif r < 0.47:
                        entregue, enc, leg = 0, "", "Em Aprovacao"
                    else:
                        entregue, enc, leg = 0, "", "Liberado"
                pc_rows.append([
                    pedido, f"{it:04d}", _d(emis_pc), _d(emissao),
                    NOME_PROTHEUS[dono], fornecedor, f"P{rnd.randint(1000, 9999)}",
                    prod, qtd, entregue, preco, round(qtd * preco, 2), enc, leg,
                ])

    sc = _spreadsheetml(
        "SOLICITACOES", f"rmatr029 - Solicitacoes de Compra - Emissao: {_d(hoje)}",
        ["FILIAL", "TIPO", "NUM.SC", "ITEM", "PRODUTO", "DESCRICAO",
         "QTD.SOLICITADA", "PRC.UNIT.", "TOTAL ITEM", "DT.EMISSAO", "DT.LIBERACAO",
         "DT.NECESSIDADE", "DT.EMIS.PC", "SOLICITANTE", "DESC.DEPARTAMENTO",
         "URGENCIA", "APROVADO?", "Legenda", "PEDIDO"],
        sc_rows,
    )
    pc = _spreadsheetml(
        "Pedidos", f"rmatr052 - Relacao de Pedidos de Compra - Emissao: {_d(hoje)}",
        ["PEDIDO COMPRA", "ITEM", "EMISSAO", "DATA SOLICIT", "COMPRADOR",
         "FORNECEDOR", "PRODUTO", "DESCRICAO.", "QUANTIDADE", "QUANT ENTREG",
         "PRECO.", "VLR.TOTAL", "ENCERRADO", "Legenda"],
        pc_rows,
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "base"
    ws.append(["NUM.SC", "ITEM", "RESPONSAVEL", "DATA DISTRIBUIÇÃO",
               "DEPARTAMENTO", "DESCRICAO", "URGENCIA", "OBS", "STATUS"])
    for r in dist_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return {"sc": sc, "pc": pc, "dist": buf.getvalue()}
