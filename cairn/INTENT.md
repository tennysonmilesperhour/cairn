# INTENT.md

## The single goal

A person with no signal, standing at a trailhead in Little Cottonwood Canyon, can open Cairn on their phone, see where they are on a real map, see the trail they are on, and hit record. Nothing else matters until that works.

## Success criteria for v1

Binary, testable in the field:

1. Airplane mode, cold start, app loads in under 3 seconds.
2. Downloaded region renders basemap and trails with zero network.
3. GPS blue dot tracks correctly and stays accurate on a 5-mile hike.
4. Recorded track survives the app being backgrounded, the screen locking, and the browser being killed.
5. Elevation gain on a recorded track is within 10% of a known reference for the same trail.
6. Battery cost of a 3-hour recording is under 25% on a mid-range phone.

If 4 and 6 fail, the PWA approach is wrong and a native shell becomes the next decision.

## Phasing

**Phase 0: Data proof.** Ingest Wasatch trails from Overpass into Supabase with PostGIS. Compute elevation profiles. Confirm the data is actually good enough (named trails, plausible geometry, connected segments). If OSM coverage in the Wasatch is poor, the whole project changes shape. Verify this before writing UI.

**Phase 1: Online map.** MapLibre rendering Protomaps basemap plus trail overlay. Search. Trail detail view with elevation profile. No auth, no offline, no recording.

**Phase 2: Offline.** Service worker, pmtiles caching, IndexedDB trail store, region download flow with progress and size disclosure.

**Phase 3: Recording.** Geolocation watch, IndexedDB write-ahead, wake lock, track detail view, GPX export.

**Phase 4: Sync.** Optional Supabase auth. Saved trails and recorded tracks sync across devices. Everything before this works fully logged out.

Ship each phase to Vercel before starting the next. Do not build phase 3 while phase 1 is unproven.

## Anti-goals

- Do not add a review system to fill screen space.
- Do not build an admin dashboard. Query Supabase directly.
- Do not optimize for a hypothetical second region until the first one is used on real hikes.
- Do not add a paid tier "for sustainability." If cost becomes a problem, reduce cost.

## Definition of done for the project

The builder stops using AllTrails.
