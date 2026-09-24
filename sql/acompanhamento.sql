-- Tabela de acompanhamento manual das SCs (Atendida / Onde encontrar).
-- Rode uma vez no SQL Editor do Supabase.
create table if not exists public.sc_acompanhamento (
  chave           text primary key,          -- 'NUM.SC-ITEM', ex.: 052507-0008
  atendida        boolean not null default false,
  atendida_por    text,
  atendida_em     timestamp,
  onde_encontrar  text,
  atualizado_por  text,
  atualizado_em   timestamp
);

create index if not exists sc_acompanhamento_onde_idx
  on public.sc_acompanhamento (onde_encontrar);

-- Sem policies: so a chave service_role (usada pelo app, no secrets.toml)
-- consegue ler/gravar. Ninguem acessa pela chave publica.
alter table public.sc_acompanhamento enable row level security;
