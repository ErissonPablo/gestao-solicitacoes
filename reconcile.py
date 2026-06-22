# -*- coding: utf-8 -*-
"""Confere o motor de dados contra os arquivos reais. Imprime contagens
para o usuario validar a confiabilidade antes de confiar na interface.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from src import loaders, crossref, normalize as nz

DL = Path(r"C:\Users\erisson.sousa\Downloads")
F_SC = DL / "rmatr029.xls"
F_PC = DL / "rmatr052 (3).xls"
F_DIST = DL / "DISTRIBUIÇAO DE COMPRA (1).xlsx"

print("Carregando arquivos...")
scs = loaders.load_scs(str(F_SC))
pcs = loaders.load_pcs(str(F_PC))
dist = loaders.load_distribuicao(str(F_DIST))
print(f"  SCs (linhas/rateios): {len(scs)}")
print(f"  PCs (itens):          {len(pcs)}")
print(f"  Distribuicao (linhas):{len(dist)}")

print("\n" + "=" * 70)
print("MODELO DE SC (tipos 01/02/03/07, 1 linha por SC-item)")
print("=" * 70)
model = crossref.build_sc_model(scs, dist)
print(f"SC-itens unicos (tipos compras): {len(model)}")
print(f"  distribuidos:        {model['distribuida'].sum()}")
print(f"  SEM distribuicao:    {(~model['distribuida']).sum()}  <- risco de SC perdida")
print(f"  com pedido:          {model['com_pedido'].sum()}")
print(f"  SEM pedido (backlog):{(~model['com_pedido']).sum()}")
print(f"  pendente s/ pedido E s/ distribuicao: "
      f"{((~model['com_pedido']) & (~model['distribuida'])).sum()}")

print("\nPor responsavel (distribuidos):")
print(model[model["distribuida"]]["responsavel"].value_counts().to_string())

print("\nPor tipo:")
print(model["tipo_cod"].value_counts().to_string())

print("\n" + "=" * 70)
print("PENDENCIAS DE ENTREGA (rmatr052)")
print("=" * 70)
pend = crossref.pendencias_entrega(pcs, hoje="2026-06-19")
print(f"Itens com saldo a receber (nao encerrados): {len(pend)}")
print(f"Pedidos distintos com pendencia: {pend['PEDIDO COMPRA'].nunique()}")
print("\nPor comprador:")
print(pend["comprador"].value_counts(dropna=False).to_string())
print(f"\nIdade media em aberto (dias corridos): {pend['dias_em_aberto'].mean():.0f}")
print(f"Mais antigo (dias): {pend['dias_em_aberto'].max():.0f}")

print("\n" + "=" * 70)
print("CHECAGEM DE NORMALIZACAO DE NOMES")
print("=" * 70)
md = crossref.mapa_distribuicao(dist)
brutos = dist["RESPONSAVEL"].astype(str).str.strip()
nao_reconhecidos = sorted(
    {b for b in brutos if nz.norm_comprador(b) is None and b and b.lower() != "none"}
)
print(f"Valores brutos distintos em RESPONSAVEL: {brutos.nunique()}")
print(f"Nao reconhecidos (viram None): {len(nao_reconhecidos)}")
for v in nao_reconhecidos[:20]:
    print(f"   ! {v!r}")
