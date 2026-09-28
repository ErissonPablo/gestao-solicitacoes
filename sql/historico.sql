-- Historico da Gestao de SC (rode uma vez no SQL Editor do Supabase).
-- Acesso so pela chave secreta (service_role) usada no servidor do app:
-- RLS ligado e sem policies = ninguem acessa pela chave publica.

-- Marcacoes da equipe (Atendida / Onde encontrar) - valor atual
create table if not exists public.sc_acompanhamento (
  chave           text primary key,          -- 'NUM.SC-ITEM', ex.: 052507-0008
  atendida        boolean not null default false,
  atendida_por    text,
  atendida_em     timestamp,
  onde_encontrar  text,
  atualizado_por  text,
  atualizado_em   timestamp
);
create index if not exists sc_acompanhamento_onde_idx on public.sc_acompanhamento (onde_encontrar);

-- Toda alteracao nas marcacoes (quem, o que, quando)
create table if not exists public.sc_acompanhamento_log (
  id            bigint generated always as identity primary key,
  chave         text not null,
  campo         text not null,               -- 'atendida' | 'onde_encontrar'
  valor_antigo  text,
  valor_novo    text,
  usuario       text,
  em            timestamp not null default now()
);
create index if not exists sc_acompanhamento_log_chave_idx on public.sc_acompanhamento_log (chave);

-- Cada subida de planilhas gravada no historico
create table if not exists public.carga (
  id          bigint generated always as identity primary key,
  criado_em   timestamp not null default now(),
  usuario     text,
  assinatura  text unique not null,          -- hash dos 3 arquivos (nao grava 2x)
  ref_sc      date,                          -- DT.REF do rmatr029
  ref_pc      date,                          -- DT.REF do rmatr052
  ref_dist    date,                          -- ultima data de distribuicao
  n_itens     integer,
  n_eventos   integer,
  arquivos    jsonb
);

-- Ultima situacao conhecida de cada SC-item (inclusive as que ja sairam do rmatr029)
create table if not exists public.sc_item (
  chave            text primary key,
  num_sc           text,
  item             text,
  tipo_cod         text,
  produto          text,
  descricao        text,
  qtd              numeric,
  valor            numeric,
  solicitante      text,
  departamento     text,
  urgencia         text,
  aprovado         text,
  dt_emissao       date,
  dt_necessidade   date,
  responsavel      text,
  dt_distribuicao  date,
  pedido           text,
  dt_pedido        date,
  entregue         boolean default false,
  dt_entrega       date,
  situacao         text,                     -- aberta | com_pedido | entregue | saiu
  primeira_vez     date,                     -- 1a extracao em que apareceu
  ultima_vez       date,                     -- ultima extracao em que apareceu
  dt_saiu          date,                     -- quando sumiu do rmatr029
  atualizado_em    timestamp
);
create index if not exists sc_item_num_sc_idx on public.sc_item (num_sc);
create index if not exists sc_item_situacao_idx on public.sc_item (situacao);
create index if not exists sc_item_responsavel_idx on public.sc_item (responsavel);

-- Linha do tempo: um registro por acontecimento
create table if not exists public.sc_evento (
  id         bigint generated always as identity primary key,
  chave      text not null,
  evento     text not null,   -- emitida | distribuida | redistribuida | pedido | entregue | status | saiu | voltou
  data       date,
  detalhe    text,
  carga_id   bigint references public.carga (id) on delete cascade,
  criado_em  timestamp not null default now()
);
create index if not exists sc_evento_chave_idx on public.sc_evento (chave);
create index if not exists sc_evento_data_idx on public.sc_evento (data);

alter table public.sc_acompanhamento     enable row level security;
alter table public.sc_acompanhamento_log enable row level security;
alter table public.carga                 enable row level security;
alter table public.sc_item               enable row level security;
alter table public.sc_evento             enable row level security;
