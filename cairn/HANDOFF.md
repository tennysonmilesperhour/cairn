# Claude Code Handoff Prompt

Paste everything below the line into a fresh Claude Code session at the repo root.

---

We are building **Cairn**, a free offline-capable trail app for the Wasatch Front. Web-first PWA on Next.js 15 / TypeScript / Supabase (PostGIS) / MapLibre GL / Protomaps / Vercel.

**Read these five files before doing anything else, in this order:** `CONTEXT.md`, `INTENT.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `IDENTITY.md`. They contain the scope, the schema, the phasing, and the reasoning behind every technical choice. `DECISIONS.md` in particular explains what would reverse each decision. Do not relitigate a decision without reading its entry first.

## Your first task is Phase 0 only

Do not scaffold the Next.js app yet. Do not write UI. Phase 0 is a data proof, and it exists because the entire project depends on OpenStreetMap having usable named-trail coverage in the Wasatch. If that coverage is bad, this becomes a data-collection product instead of a map product, and I need to know that before any UI exists.

Build this:

1. **`/ingest/ingest.py`** - queries the Overpass API for the bbox `[-112.20, 40.35, -111.35, 41.00]`, pulling the way/relation/node types listed in the "Trail ingest" section of `ARCHITECTURE.md`. Merge ways belonging to a hiking relation into single named trails. Handle Overpass rate limiting and timeouts with retry and backoff. Cache the raw Overpass response to disk so reruns during development do not re-hit the API.

2. **`/supabase/migrations/0001_init.sql`** - exactly the schema in `ARCHITECTURE.md`, including the PostGIS extension, all indexes, and the RLS policies. Do not improvise columns.

3. **`/ingest/elevation.py`** - samples Copernicus GLO-30 DEM along each trail at ~20m intervals with `rasterio`, computes gain/loss with a 5m noise threshold, and produces a downsampled elevation profile of at most 200 `[distance_m, elevation_m]` pairs. Read decision D007 before writing the gain calculation. The threshold is the whole point of it.

4. **`/ingest/report.py`** - the actual deliverable of this phase. Prints a coverage report to stdout: total trails, how many have names, total named trail miles, the 30 longest named trails, count of trails with `surface` tagged, count of trailheads found, and any trail whose computed length or elevation gain looks implausible. I am going to read this output and check the top trails against ones I have personally hiked. That check is the gate for Phase 1.

5. **`/ingest/README.md`** - how to run it, what env vars are needed, how long it takes.

Also write `.env.example` with the required variables, and a `requirements.txt`.

## Rules for how you work

- **Ask me before installing anything not already implied by the stack.** Especially anything that adds a build step or a running service.
- **Commit at each logical checkpoint** with real messages. Do not batch the whole phase into one commit.
- **Do not create files I did not ask for.** No `utils.py` grab bags, no speculative abstraction layers, no config systems for one config value.
- **When you hit a decision the docs do not cover, stop and ask.** Do not pick a direction and build on it silently. If you do make a judgment call, note it and I will add it to `DECISIONS.md`.
- **Append to `DECISIONS.md` when a real decision gets made**, using the existing format including the "reverses if" line.
- **Elevation and distance math gets tested.** Write a small test comparing computed values for one known trail against a published figure. Everything else can go untested in this phase.
- No em dashes in code comments, docs, or commit messages.

## What I do not want

Do not build a CLI framework, a plugin architecture, an admin UI, a Docker setup, or a logging abstraction. This is a script that fills a database and prints a report.

Do not run the ingest against production Supabase until I have reviewed the code.

Start by reading the five docs, then tell me your plan for Phase 0 before you write code.
