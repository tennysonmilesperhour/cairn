# Cairn

A free, offline-capable trail app for the Wasatch Front.

Offline maps, GPS track recording, and saved routes, with no paywall and no account required.

## Status

Phase 0: data proof. Ingesting OpenStreetMap trail coverage and validating it before any UI is built.

## Stack

Next.js 15, TypeScript, Supabase (PostGIS), MapLibre GL, Protomaps, Vercel.

## Docs

| File | Contents |
|---|---|
| `CONTEXT.md` | What this is, scope, what it explicitly does not do |
| `INTENT.md` | Goals, testable success criteria, phasing |
| `ARCHITECTURE.md` | Stack rationale, schema, data pipeline, offline design |
| `DECISIONS.md` | Decision log with rationale and reversal conditions |
| `IDENTITY.md` | Voice and visual direction |
| `HANDOFF.md` | Claude Code kickoff prompt for Phase 0 |

## Data

Trail data from OpenStreetMap, licensed ODbL. Elevation from Copernicus GLO-30 DEM.

## License

MIT for the code. Trail data carries its own ODbL terms and requires attribution.
