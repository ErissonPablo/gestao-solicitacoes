# Gestão de Solicitações de Compra — Lactosul

Ferramenta para acompanhar Solicitações de Compra (SC) sem que nenhuma se
perca. Cruza **3 fontes** e mostra, por SC-item, se ela tem dono, se já virou
pedido e se o pedido foi entregue.

## As 3 fontes

| # | Arquivo | O que é | De onde tirar |
|---|---------|---------|---------------|
| 1 | `rmatr029.xls` | Solicitações de Compra (demanda) | Protheus — relatório rmatr029, **Apenas Pendentes = SIM** |
| 2 | `DISTRIBUICAO DE COMPRA.xlsx` | Quem é responsável por cada SC-item (aba `base`) | SharePoint da Lactosul |
| 3 | `rmatr052.xls` | Pedidos de Compra e entregas | Protheus — relatório rmatr052 |

> Os `.xls` do Protheus são, na verdade, XML do Excel (SpreadsheetML). A
> ferramenta lê esse formato direto, não precisa converter.

## Regras de negócio aplicadas

- **Tipos atendidos pela equipe:** 01 (Aplicação Direta), 02 (Normal),
  03 (Serviços), 07 (Investimento). Tipos 04 e 09 (regularizações) ficam de fora.
- **Recorte padrão:** ano 2026 e somente SCs **aprovadas** (exclui
  eliminadas/bloqueadas/reprovadas).
- **Rateio:** uma SC-item rateada em vários centros de custo vira **1 linha só**.
- **Nomes dos compradores:** normalizados para um nome canônico
  (`erisson`, `ERISSON`, `erison`… → **Erisson**). Erros de digitação conhecidos
  e nomes combinados (`A/B`) também são tratados. Veja `src/normalize.py`.
- **Equipe atual:** Alessandro, Erisson, Eloisa, Marcos, Nagella.
  Eduardo = menor aprendiz (implanta pedidos, não recebe distribuição).

## Telas

No topo: **6 cards de KPI** (SC-itens, backlog em R$, necessidade vencida,
sem dono e sem pedido, tempo SC → pedido, entregas pendentes).

0. **Visão geral** — funil (SC → distribuída → pedido → entregue),
   envelhecimento do backlog por faixa de dias, entrada × atendimento por mês,
   carteira por comprador e departamentos com mais SCs paradas.
1. **Alertas** — lista de ação do dia: sem dono e sem pedido, necessidade
   vencida, urgência ALTA parada há N dias, entregas com mais de 30 dias.
2. **Backlog a atender** — SCs aprovadas ainda sem pedido, em **cartões**
   (estilo sistema), mais antigas no topo. Em cada SC:
   - **✅ Atendida** — marca que a SC já foi tratada (fica verde, com quem
     marcou e quando);
   - **📍 Onde encontrar** — fornecedor/local onde comprar; os nomes já usados
     aparecem como sugestão.
   Filtros por situação (pendentes/atendidas), por local, busca, urgentes e
   vencidas; **Agrupar por local** separa a lista pelos nomes de "Onde encontrar".
   "Ver como tabela" volta ao formato planilha.
3. **Sem distribuição** — SCs na demanda que não aparecem na planilha de
   distribuição (risco de "SC perdida"). Críticas = sem dono **e** sem pedido.
4. **Compradores** — carga, % pendente, vencidas, backlog em R$ e tempo
   mediano SC → pedido por comprador (com gráfico de dispersão).
5. **Entregas pendentes** — itens de pedido não encerrados com saldo a receber.
6. **Visão 360 por SC** — busca uma SC e mostra distribuição → pedido → entrega.
7. **Qualidade de dados** — grafias não reconhecidas e checagem de rateio.

**Filtro global de comprador** na barra lateral e **relatório Excel** com
todas as visões (respeitando os filtros) no botão "Baixar relatório Excel".

### Indicadores novos

- **Necessidade vencida:** SC-item sem pedido cujo `DT.NECESSIDADE` já passou.
- **Tempo SC → pedido:** `DT.EMIS.PC` − `DT.LIBERACAO` (ou `DT.EMISSAO` se não
  houver liberação), em dias corridos. Precisa da coluna `DT.EMIS.PC` no rmatr029.

### Onde ficam salvas as marcações (Atendida / Onde encontrar)

Ficam salvas **por SC-item** (ex.: `052507-0008`), então continuam valendo
quando você sobe as planilhas de novo. Escolha seu nome em **👤 Você é** na
barra lateral para registrar quem marcou.

- **Padrão:** arquivo `data/acompanhamento.db` na pasta do projeto. Serve
  quando o app roda sempre no mesmo PC (`run.bat` / `run-rede.bat`).
- **Equipe toda / Streamlit Cloud (recomendado):** Supabase.
  1. Rode `sql/acompanhamento.sql` no SQL Editor do Supabase.
  2. Em `.streamlit/secrets.toml` (ou em *Settings → Secrets* no Streamlit Cloud):
     ```toml
     supabase_url = "https://SEU-PROJETO.supabase.co"
     supabase_key = "chave service_role"
     ```
  Com isso o app passa a gravar no Supabase sozinho. A barra lateral mostra
  onde as marcações estão sendo salvas.

> No Streamlit Cloud **sem** Supabase as marcações se perdem quando o app
> reinicia.

### Modo demonstração

Na barra lateral, **Demonstração (dados fictícios)** abre a ferramenta com
dados inventados (`src/demo.py`), nos mesmos formatos do Protheus. Serve para
mostrar a ferramenta e testar mudanças de layout sem os arquivos reais.

## Como rodar

```bat
run.bat
```

Ou manualmente:

```bat
python -m pip install -r requirements.txt
streamlit run app.py
```

Abre em `http://localhost:8501`. Na barra lateral, escolha a fonte:

- **Upload de arquivos** — sobe os 3 arquivos manualmente.
- **Pasta local** — informa uma pasta; a ferramenta detecta os 3 por nome
  (`rmatr029*`, `rmatr052*`, `*DISTRIB*.xlsx`) e pega os mais recentes.
- **SharePoint** — lê a planilha de distribuição direto do SharePoint
  (rmatr029/rmatr052 continuam por upload). Veja "SharePoint" abaixo.

## Deploy na nuvem (Streamlit Community Cloud)

Roda sempre-online e acessivel por link, de graca, sem mexer no firewall nem
depender de um PC ligado. Os dados entram pelo modo **Upload** (a nuvem nao
enxerga pastas locais nem o SharePoint sem credencial de app).

1. **Crie um repositorio PRIVADO** no GitHub (ex.: `gestao-solicitacoes`), vazio.
2. **Envie o codigo** (na pasta do projeto):
   ```bat
   git remote add origin https://github.com/SEU_USUARIO/gestao-solicitacoes.git
   git push -u origin main
   ```
3. Acesse **https://share.streamlit.io** → *New app* → escolha o repositorio,
   branch `main`, arquivo `app.py` → *Deploy*.
4. Em **Settings → Sharing**, deixe **"Only specific people"** e convide os
   e-mails da equipe (o app fica privado, so quem voce liberar acessa).

O `requirements.txt` ja esta pronto; o Streamlit Cloud instala tudo sozinho.
Nunca suba os arquivos de dados nem `secrets.toml` (o `.gitignore` ja bloqueia).

## SharePoint (opcional)

1. `pip install Office365-REST-Python-Client`
2. Copie `config/paths.example.yaml` para `config/paths.yaml` e ajuste
   `sharepoint.site_url` e `sharepoint.arquivo_distribuicao`.
3. Crie `.streamlit/secrets.toml`:
   ```toml
   sp_username = "voce@lactosul.com.br"
   sp_password = "sua-senha"
   ```

## Validação dos números

`python reconcile.py` imprime as contagens do motor contra os arquivos reais —
use para conferir a confiabilidade após qualquer mudança.

## Estrutura

```
app.py              # interface Streamlit (8 telas)
reconcile.py        # validação das contagens
src/
  loaders.py        # leitura dos 3 formatos
  normalize.py      # nomes canônicos, chave SC-ITEM, tipos
  crossref.py       # cruzamento SC × distribuição × pedido
  datasource.py     # upload / pasta local / detecção por nome
  sharepoint.py     # leitura opcional do SharePoint
  metrics.py        # indicadores do painel (funil, aging, tempo SC->pedido...)
  ui.py             # visual: CSS, cards de KPI, estilo dos graficos
  export.py         # relatorio Excel
  demo.py           # dados ficticios para o modo demonstracao
  store.py          # marcacoes Atendida / Onde encontrar (SQLite ou Supabase)
sql/
  acompanhamento.sql  # tabela para o Supabase
```
