# CLAUDE.md

Project: Cairn, a free offline trail app for the Wasatch Front.

## Read first
Before any task, read `CONTEXT.md`, `INTENT.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `IDENTITY.md`.
`DECISIONS.md` records why each choice was made and what would reverse it. Read the relevant
entry before changing anything it covers.

## Stack
Next.js 15 App Router, TypeScript, React 19, Tailwind, MapLibre GL v5, Protomaps pmtiles on
Cloudflare R2, Supabase Postgres with PostGIS, Vercel. Ingest is Python in GitHub Actions.

## Working rules
- Phases ship in order. Do not build a later phase while an earlier one is unverified.
- Ask before adding a dependency that introduces a build step or a running service.
- Do not create files that were not asked for. No speculative abstractions.
- Stop and ask when a decision is not covered by the docs. Do not choose silently.
- Append real decisions to `DECISIONS.md` in the existing format.
- Commit at logical checkpoints with descriptive messages.
- No em dashes anywhere: code, comments, docs, commit messages.

## Domain gotchas that have already caused bugs elsewhere
- Never compute elevation gain from phone GPS altitude. Use DEM sampling with a 5m noise
  threshold. See D007.
- Never show a computed difficulty rating. See D006.
- Write every GPS point to IndexedDB immediately during recording. Never batch. See D009.
- Request a screen wake lock while recording or iOS will suspend the page.
- OSM attribution must be visible on the map, not in settings. License requirement.
