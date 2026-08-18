-- Cairn 0001_init
-- Schema for the Wasatch Front trail dataset, per ARCHITECTURE.md.
-- Tables: regions, trails, trailheads, tracks, saved_trails.
-- Public data (regions, trails, trailheads) is world readable.
-- User data (tracks, saved_trails) is readable and writable only by its owner.

create extension if not exists postgis;

create table regions (
  id text primary key,
  name text not null,
  bbox geometry(Polygon, 4326) not null,
  pmtiles_url text not null,
  pmtiles_bytes bigint,
  trail_count int,
  updated_at timestamptz default now()
);

create table trails (
  id uuid primary key default gen_random_uuid(),
  region_id text references regions(id),
  osm_id bigint,
  osm_type text check (osm_type in ('way','relation')),
  name text,
  geom geometry(LineString, 4326) not null,
  length_m double precision not null,
  elev_gain_m double precision,
  elev_loss_m double precision,
  elev_min_m double precision,
  elev_max_m double precision,
  elevation_profile jsonb,
  surface text,
  is_named boolean generated always as (name is not null) stored,
  tags jsonb default '{}'::jsonb,
  updated_at timestamptz default now(),
  unique (osm_type, osm_id)
);

create index trails_geom_idx on trails using gist (geom);
create index trails_name_idx on trails using gin (to_tsvector('english', coalesce(name,'')));
create index trails_region_idx on trails (region_id);

create table trailheads (
  id uuid primary key default gen_random_uuid(),
  region_id text references regions(id),
  osm_id bigint unique,
  name text,
  geom geometry(Point, 4326) not null,
  has_parking boolean default false,
  has_toilets boolean default false,
  tags jsonb default '{}'::jsonb
);

create index trailheads_geom_idx on trailheads using gist (geom);

create table tracks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  name text,
  geom geometry(LineStringZ, 4326),
  points jsonb not null,          -- [{lat,lon,ele,t,acc}]
  distance_m double precision,
  duration_s int,
  elev_gain_m double precision,
  started_at timestamptz,
  created_at timestamptz default now()
);

create table saved_trails (
  user_id uuid references auth.users(id) on delete cascade,
  trail_id uuid references trails(id) on delete cascade,
  created_at timestamptz default now(),
  primary key (user_id, trail_id)
);

-- Row level security

alter table trails enable row level security;
alter table trailheads enable row level security;
alter table regions enable row level security;
create policy "public read" on trails for select using (true);
create policy "public read" on trailheads for select using (true);
create policy "public read" on regions for select using (true);

alter table tracks enable row level security;
create policy "own tracks" on tracks for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table saved_trails enable row level security;
create policy "own saves" on saved_trails for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
