# DECISIONS.md

Append-only. Each entry: what was decided, why, and what would reverse it.

---

## D001. PWA before native
**Decided:** Build as a Progressive Web App. No React Native, no Swift, no Capacitor in v1.
**Why:** The stack is already Next.js/Supabase/Vercel. Browser APIs now cover the required surface: geolocation watch, IndexedDB, Cache API, wake lock, installable manifest. Shipping a native app adds app store review, two codebases, and a build toolchain for a hypothesis that is not yet proven.
**Reverses if:** iOS background geolocation gaps make recorded tracks unusable in field testing, or battery cost exceeds 25% for a 3-hour recording. Fallback is Capacitor wrapping the same web app, not a rewrite.

---

## D002. Protomaps over Mapbox or a self-hosted tile server
**Decided:** Basemap is a single `.pmtiles` archive on Cloudflare R2, read via HTTP range requests.
**Why:** It is the only option where the exact same artifact serves both online and offline use, with no server and no per-tile billing. Mapbox offline requires their native SDK and their pricing scales with usage. A self-hosted tile server is a running cost and an ops burden.
**Reverses if:** pmtiles range-request caching proves unreliable across target browsers.

---

## D003. Cloudflare R2 over S3 or Supabase Storage
**Decided:** R2 for the pmtiles archive.
**Why:** Zero egress fees. A 200MB file downloaded by a few hundred users would generate meaningful S3 bandwidth charges. Supabase Storage on the free tier has a bandwidth cap that a single region download could blow through.
**Reverses if:** R2 range-request support or CORS handling causes problems.

---

## D004. Regional scope, Wasatch Front only
**Decided:** One region in v1, bbox `[-112.20, 40.35, -111.35, 41.00]`.
**Why:** Keeps the trail table small, keeps the offline download viable at a couple hundred megabytes, and makes correctness verifiable by walking outside. Multi-region is a data and storage problem, not a product insight, and can wait.
**Reverses if:** never in v1. Region is already a first-class table so expansion is additive.

---

## D005. No reviews, ratings, or photos in v1
**Decided:** Zero social features.
**Why:** Community content only works with critical mass. An empty review section makes a new app look abandoned and is worse than no review section. The paywalled features people actually miss are offline maps and recording, not reviews.
**Reverses if:** the app has real recurring users who ask for it. Not before.

---

## D006. No difficulty ratings
**Decided:** Show distance, gain, max elevation, surface. Do not show "Easy / Moderate / Hard."
**Why:** OSM has `sac_scale` but coverage in Utah is thin and inconsistent. Inventing a difficulty formula from distance and gain produces confidently wrong labels, which is a safety problem in the Wasatch where a short trail can be genuinely dangerous. Numbers are honest.
**Reverses if:** a defensible data source for difficulty appears.

---

## D007. Elevation from DEM, not from GPS altitude
**Decided:** All elevation gain figures derive from Copernicus GLO-30 DEM sampling, with a 5m noise threshold. Phone GPS altitude is recorded but never used for gain calculation.
**Why:** Consumer GPS vertical error is routinely 10 to 30 meters and oscillates. Summing raw GPS altitude deltas over a hike produces gain figures inflated by 2x or more. This is the single most common bug in amateur trail apps.
**Reverses if:** barometric altimeter data becomes accessible and proves better.

---

## D008. Auth is optional and deferred to phase 4
**Decided:** The app is fully functional logged out. Everything stores locally. Auth exists only to sync across devices.
**Why:** A signup wall on a free tool is the exact friction the project exists to remove. It also removes an entire class of blocking work from the critical path.
**Reverses if:** never. Auth stays optional permanently.

---

## D009. IndexedDB write-per-point during recording
**Decided:** Every accepted GPS point writes to IndexedDB synchronously as it arrives. No batching.
**Why:** Mobile browsers kill backgrounded tabs without warning. Batching means losing whatever is in the buffer. The write cost is negligible at one point every few seconds.
**Reverses if:** profiling shows write contention, which is unlikely at this frequency.

---

## D010. Data proof before UI
**Decided:** Phase 0 is ingest and manual verification of OSM Wasatch coverage. No UI work starts until the data is confirmed good.
**Why:** The entire project rests on OSM having decent named-trail coverage in the Wasatch. If it does not, the product is a data-collection problem instead of an app problem, which is a completely different build. Finding that out after building a map UI wastes the UI.
**Reverses if:** nothing. This is a sequencing decision.

---

## D011. Dark mode is required, not a preference
**Decided:** Ship both themes in phase 1.
**Why:** Primary use is dawn and dusk in canyons. This is a functional requirement, not a styling nicety.
**Reverses if:** nothing.
