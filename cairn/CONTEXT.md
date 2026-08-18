# CONTEXT.md

## What this is

Cairn is a free, offline-capable trail app. Web-first PWA. No paywall, no account required to browse, no upsell.

It exists because the dominant trail app (AllTrails) paywalls the three features that matter most in the field: offline maps, GPS route recording, and saved routes. Those are all now solvable in a browser at near-zero hosting cost.

## Scope of v1

One region: the Wasatch Front, Utah. Roughly `[-112.20, 40.35, -111.35, 41.00]`.

Regional scope is a deliberate constraint, not a limitation. It keeps the trail dataset under ~10k features, keeps the offline basemap under ~200MB, and lets the whole thing be validated by walking outside.

## What v1 does

- Browse and search trails on a map
- View a trail: distance, elevation gain/loss, elevation profile, surface, trailhead location
- Download a region for offline use (basemap tiles + trail geometry)
- Record a GPS track while hiking, offline, and save it
- Review recorded tracks after the fact

## What v1 explicitly does not do

- Reviews, ratings, photos, comments, social feeds. These require critical mass that a new app does not have. Building them empty makes the app look dead.
- Turn-by-turn routing or route planning by drawing. Later.
- Native iOS/Android apps. PWA only until the PWA is proven insufficient.
- Multi-region. One region done well first.

## Who it is for

Initially: the builder and their SLC hiking circle. This is a tool built to be used, not a startup. Growth is a later question and may never be the question.

## Prior art worth knowing

Organic Maps and OsmAnd already do free offline OSM hiking with tracking. They are good. Their weakness is UX and their strength is coverage. Cairn wins by being pleasant and regionally deep, not by having more trails.

## Non-negotiables

- Free to use, permanently. No feature is gated.
- Works with no signal. Offline is the default assumption, not a mode.
- Costs the operator under $10/month to run at small scale.
- Data comes from open sources with compatible licensing (ODbL for OSM, attributed properly).
