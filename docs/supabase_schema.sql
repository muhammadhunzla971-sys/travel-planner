-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.
-- Creates the table for saved trips. Row Level Security makes sure each user only sees their own trips,
-- so the public "anon" key in the website is safe.

create table if not exists public.trips (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  created_at  timestamptz not null default now(),
  destination text not null,
  start_date  date not null,
  end_date    date not null,
  total_cost  numeric not null,
  currency    text not null,
  data        jsonb not null
);

create index if not exists trips_user_created_idx on public.trips (user_id, created_at desc);

alter table public.trips enable row level security;

drop policy if exists "trips_select_own" on public.trips;
drop policy if exists "trips_insert_own" on public.trips;
drop policy if exists "trips_delete_own" on public.trips;

create policy "trips_select_own" on public.trips for select using (auth.uid() = user_id);
create policy "trips_insert_own" on public.trips for insert with check (auth.uid() = user_id);
create policy "trips_delete_own" on public.trips for delete using (auth.uid() = user_id);
