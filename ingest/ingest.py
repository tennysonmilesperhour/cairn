#!/usr/bin/env python3
"""
Overpass ingest for the Wasatch Front trail dataset.

Queries the Overpass API for the region bbox, merges the ways of each hiking
relation into a single trail, and writes normalized GeoJSON to data/normalized/.
Optionally upserts the result into Supabase Postgres.

The raw Overpass response is cached to disk keyed by endpoint and query text, so
reruns during development do not re-hit the API. Delete the cache file or pass
--refresh to force a new fetch.

Run order for phase 0:
    python ingest/ingest.py
    python ingest/elevation.py
    python ingest/report.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from pyproj import Geod
from shapely.geometry import LineString, mapping
from shapely.ops import linemerge

# Wasatch Front. See DECISIONS.md D004.
BBOX = (-112.20, 40.35, -111.35, 41.00)  # west, south, east, north
REGION_ID = "wasatch"
REGION_NAME = "Wasatch Front"

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUT_DIR = REPO_ROOT / "data" / "normalized"

# Overpass returns these when it is busy or the query outgrew its slot.
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6
INITIAL_BACKOFF_S = 5.0
MAX_BACKOFF_S = 240.0

GEOD = Geod(ellps="WGS84")


def build_query(bbox: tuple[float, float, float, float], timeout_s: int) -> str:
    """Overpass QL for the feature types in the ARCHITECTURE.md trail ingest section.

    Overpass orders bbox as south,west,north,east.
    """
    west, south, east, north = bbox
    b = f"{south},{west},{north},{east}"
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        "(\n"
        f'  way["highway"~"^(path|footway|track|bridleway)$"]({b});\n'
        f'  way["highway"="steps"]({b});\n'
        f'  relation["route"="hiking"]({b});\n'
        f'  node["amenity"="parking"][~"."~"trailhead"]({b});\n'
        f'  node["highway"="trailhead"]({b});\n'
        ");\n"
        "out geom;\n"
    )


def cache_path(endpoint: str, query: str) -> Path:
    digest = hashlib.sha256(f"{endpoint}\n{query}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"overpass-{digest}.json"


def fetch_overpass(
    query: str,
    endpoint: str,
    http_timeout_s: int,
    refresh: bool,
) -> dict:
    """Fetch the Overpass response, using the on-disk cache when present.

    Retries rate limits, gateway timeouts, and connection failures with
    exponential backoff and jitter. Honors Retry-After when Overpass sends it.
    """
    path = cache_path(endpoint, query)
    if path.exists() and not refresh:
        age_h = (time.time() - path.stat().st_mtime) / 3600
        size_mb = path.stat().st_size / 1e6
        print(
            f"cache hit: {path.relative_to(REPO_ROOT)} "
            f"({size_mb:.1f} MB, {age_h:.1f} h old)",
            file=sys.stderr,
        )
        return json.loads(path.read_text())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    backoff = INITIAL_BACKOFF_S

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(
            f"overpass: attempt {attempt}/{MAX_ATTEMPTS} to {endpoint}",
            file=sys.stderr,
        )
        try:
            resp = requests.post(
                endpoint,
                data={"data": query},
                timeout=http_timeout_s,
                headers={"User-Agent": "cairn-ingest/0.1 (phase 0 coverage survey)"},
            )
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(f"overpass unreachable after {MAX_ATTEMPTS} attempts: {exc}")
            wait = _jitter(backoff)
            print(f"  connection error: {exc}. retrying in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            continue

        if resp.status_code in RETRY_STATUS:
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(
                    f"overpass returned {resp.status_code} on the final attempt. "
                    "Try again later or use a mirror via OVERPASS_ENDPOINT."
                )
            wait = _retry_after(resp) or _jitter(backoff)
            print(
                f"  http {resp.status_code} (busy or over quota). retrying in {wait:.0f}s",
                file=sys.stderr,
            )
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            continue

        if resp.status_code != 200:
            raise SystemExit(
                f"overpass returned http {resp.status_code}: {resp.text[:500]}"
            )

        try:
            payload = resp.json()
        except ValueError:
            # Overpass reports query syntax errors as an HTML page with http 200.
            raise SystemExit(f"overpass returned non-JSON: {resp.text[:500]}")

        # A server-side timeout or memory abort arrives as http 200 with a remark.
        remark = payload.get("remark", "")
        if "error" in remark.lower() or "timed out" in remark.lower():
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(f"overpass runtime error: {remark}")
            wait = _jitter(backoff)
            print(f"  runtime error: {remark.strip()}. retrying in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            continue

        path.write_text(json.dumps(payload))
        print(
            f"cached {len(payload.get('elements', []))} elements to "
            f"{path.relative_to(REPO_ROOT)} ({path.stat().st_size / 1e6:.1f} MB)",
            file=sys.stderr,
        )
        return payload

    raise SystemExit("overpass: exhausted retries")


def _retry_after(resp: requests.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(float(raw), MAX_BACKOFF_S)
    except ValueError:
        return None


def _jitter(backoff: float) -> float:
    return backoff * (0.75 + 0.5 * random.random())


def coords_of(element: dict) -> list[tuple[float, float]]:
    """Overpass 'out geom' geometry as (lon, lat) pairs, dropping clipped nodes."""
    return [
        (pt["lon"], pt["lat"])
        for pt in element.get("geometry") or []
        if pt is not None and "lon" in pt and "lat" in pt
    ]


def length_m(coords: list[tuple[float, float]]) -> float:
    """Geodesic length on the WGS84 ellipsoid. Planar length is wrong at this latitude."""
    if len(coords) < 2:
        return 0.0
    lons, lats = zip(*coords)
    return float(GEOD.line_length(lons, lats))


def merge_relation(members: list[dict]) -> tuple[LineString | None, dict]:
    """Merge the way members of a hiking relation into one LineString.

    Equivalent to ST_LineMerge. Relations whose members do not form a single
    contiguous line come back as several components, which is common: gaps in
    the OSM data, mapped alternates, and approach spurs all cause it. The
    LineString column cannot hold a MultiLineString, so the longest component
    becomes the trail geometry and the discarded length is recorded so the
    coverage report can show how much this costs. See DECISIONS.md D012.
    """
    lines = []
    for member in members:
        if member.get("type") != "way":
            continue
        coords = coords_of(member)
        if len(coords) >= 2:
            lines.append(LineString(coords))

    if not lines:
        return None, {"merge_components": 0, "merge_dropped_m": 0.0}

    merged = linemerge(lines) if len(lines) > 1 else lines[0]
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    part_lengths = [length_m(list(p.coords)) for p in parts]
    keep_idx = part_lengths.index(max(part_lengths))

    stats = {
        "merge_components": len(parts),
        "merge_dropped_m": round(sum(part_lengths) - part_lengths[keep_idx], 1),
        "merge_member_ways": len(lines),
    }
    return parts[keep_idx], stats


def derive_surface(own_tags: dict, members: list[dict]) -> tuple[str | None, str | None]:
    """Surface for a merged relation.

    Prefers the relation's own tag. Falls back to the most common surface among
    member ways, because a route relation rarely carries surface itself while its
    members usually do, and reporting those trails as untagged would understate
    real coverage. Returns (surface, source). See DECISIONS.md D013.
    """
    if own_tags.get("surface"):
        return own_tags["surface"], "relation"

    member_surfaces = Counter(
        m.get("tags", {}).get("surface")
        for m in members
        if m.get("type") == "way" and m.get("tags", {}).get("surface")
    )
    if not member_surfaces:
        return None, None
    return member_surfaces.most_common(1)[0][0], "members"


def normalize(osm: dict) -> tuple[list[dict], list[dict], dict]:
    """Turn the raw Overpass payload into trail and trailhead records."""
    elements = osm.get("elements", [])
    ways = {e["id"]: e for e in elements if e.get("type") == "way"}
    relations = [e for e in elements if e.get("type") == "relation"]
    nodes = [e for e in elements if e.get("type") == "node"]

    trails: list[dict] = []
    consumed_way_ids: set[int] = set()
    skipped = Counter()

    # Hiking relations first, so their member ways do not also appear as orphans.
    for rel in relations:
        members = rel.get("members", [])
        for m in members:
            if m.get("type") == "way":
                consumed_way_ids.add(m["ref"])

        geom, merge_stats = merge_relation(members)
        if geom is None:
            skipped["relation_no_geometry"] += 1
            continue

        rel_tags = rel.get("tags", {})
        surface, surface_source = derive_surface(rel_tags, members)
        coords = list(geom.coords)
        tags = dict(rel_tags)
        tags.update(merge_stats)
        if surface_source:
            tags["surface_source"] = surface_source

        trails.append(
            {
                "osm_type": "relation",
                "osm_id": rel["id"],
                "name": rel_tags.get("name"),
                "coords": coords,
                "length_m": round(length_m(coords), 1),
                "surface": surface,
                "tags": tags,
            }
        )

    # Orphan ways. Named ones are standalone trails, unnamed ones are connector
    # segments: still stored and rendered, but is_named is false so search skips them.
    for way_id, way in ways.items():
        if way_id in consumed_way_ids:
            continue
        coords = coords_of(way)
        if len(coords) < 2:
            skipped["way_no_geometry"] += 1
            continue
        way_tags = way.get("tags", {})
        trails.append(
            {
                "osm_type": "way",
                "osm_id": way_id,
                "name": way_tags.get("name"),
                "coords": coords,
                "length_m": round(length_m(coords), 1),
                "surface": way_tags.get("surface"),
                "tags": way_tags,
            }
        )

    trailheads = []
    for node in nodes:
        node_tags = node.get("tags", {})
        trailheads.append(
            {
                "osm_id": node["id"],
                "name": node_tags.get("name"),
                "lon": node["lon"],
                "lat": node["lat"],
                "has_parking": node_tags.get("amenity") == "parking",
                "has_toilets": node_tags.get("toilets") in ("yes", "designated")
                or node_tags.get("amenity") == "toilets",
                "tags": node_tags,
            }
        )

    stats = {
        "elements": len(elements),
        "ways_returned": len(ways),
        "relations_returned": len(relations),
        "ways_consumed_by_relations": len(consumed_way_ids & set(ways)),
        "skipped": dict(skipped),
    }
    return trails, trailheads, stats


def to_feature_collection(trails: list[dict], trailheads: list[dict]) -> tuple[dict, dict]:
    trail_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(LineString(t["coords"])),
                "properties": {k: v for k, v in t.items() if k != "coords"},
            }
            for t in trails
        ],
    }
    trailhead_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [th["lon"], th["lat"]]},
                "properties": {k: v for k, v in th.items() if k not in ("lon", "lat")},
            }
            for th in trailheads
        ],
    }
    return trail_fc, trailhead_fc


def write_supabase(trails: list[dict], trailheads: list[dict], dsn: str) -> None:
    """Upsert into Postgres. Requires the 0001_init migration to have been applied."""
    import psycopg2
    from psycopg2.extras import Json, execute_batch

    west, south, east, north = BBOX
    bbox_wkt = (
        f"POLYGON(({west} {south},{east} {south},{east} {north},"
        f"{west} {north},{west} {south}))"
    )
    pmtiles_url = os.environ.get("PMTILES_URL", "")

    conn = psycopg2.connect(dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into regions (id, name, bbox, pmtiles_url, trail_count, updated_at)
                values (%s, %s, st_geomfromtext(%s, 4326), %s, %s, now())
                on conflict (id) do update set
                  name = excluded.name,
                  bbox = excluded.bbox,
                  pmtiles_url = excluded.pmtiles_url,
                  trail_count = excluded.trail_count,
                  updated_at = now()
                """,
                (REGION_ID, REGION_NAME, bbox_wkt, pmtiles_url, len(trails)),
            )

            execute_batch(
                cur,
                """
                insert into trails (
                  region_id, osm_id, osm_type, name, geom, length_m,
                  elev_gain_m, elev_loss_m, elev_min_m, elev_max_m,
                  elevation_profile, surface, tags, updated_at
                )
                values (
                  %s, %s, %s, %s, st_geomfromtext(%s, 4326), %s,
                  %s, %s, %s, %s, %s, %s, %s, now()
                )
                on conflict (osm_type, osm_id) do update set
                  region_id = excluded.region_id,
                  name = excluded.name,
                  geom = excluded.geom,
                  length_m = excluded.length_m,
                  elev_gain_m = excluded.elev_gain_m,
                  elev_loss_m = excluded.elev_loss_m,
                  elev_min_m = excluded.elev_min_m,
                  elev_max_m = excluded.elev_max_m,
                  elevation_profile = excluded.elevation_profile,
                  surface = excluded.surface,
                  tags = excluded.tags,
                  updated_at = now()
                """,
                [
                    (
                        REGION_ID,
                        t["osm_id"],
                        t["osm_type"],
                        t["name"],
                        LineString(t["coords"]).wkt,
                        t["length_m"],
                        t.get("elev_gain_m"),
                        t.get("elev_loss_m"),
                        t.get("elev_min_m"),
                        t.get("elev_max_m"),
                        Json(t["elevation_profile"]) if t.get("elevation_profile") else None,
                        t["surface"],
                        Json(t["tags"]),
                    )
                    for t in trails
                ],
                page_size=500,
            )

            execute_batch(
                cur,
                """
                insert into trailheads (
                  region_id, osm_id, name, geom, has_parking, has_toilets, tags
                )
                values (%s, %s, %s, st_setsrid(st_makepoint(%s, %s), 4326), %s, %s, %s)
                on conflict (osm_id) do update set
                  region_id = excluded.region_id,
                  name = excluded.name,
                  geom = excluded.geom,
                  has_parking = excluded.has_parking,
                  has_toilets = excluded.has_toilets,
                  tags = excluded.tags
                """,
                [
                    (
                        REGION_ID,
                        th["osm_id"],
                        th["name"],
                        th["lon"],
                        th["lat"],
                        th["has_parking"],
                        th["has_toilets"],
                        Json(th["tags"]),
                    )
                    for th in trailheads
                ],
                page_size=500,
            )
    finally:
        conn.close()

    print(
        f"supabase: upserted {len(trails)} trails and {len(trailheads)} trailheads",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the on-disk cache and re-query Overpass",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("OVERPASS_ENDPOINT", DEFAULT_ENDPOINT),
        help=f"Overpass endpoint (default {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--query-timeout",
        type=int,
        default=int(os.environ.get("OVERPASS_TIMEOUT", "300")),
        help="Overpass server-side timeout in seconds (default 300)",
    )
    parser.add_argument(
        "--write-supabase",
        action="store_true",
        help="upsert into Postgres using SUPABASE_DB_URL. Off by default.",
    )
    args = parser.parse_args()

    query = build_query(BBOX, args.query_timeout)
    osm = fetch_overpass(
        query,
        endpoint=args.endpoint,
        http_timeout_s=args.query_timeout + 60,
        refresh=args.refresh,
    )

    trails, trailheads, stats = normalize(osm)
    print(
        f"normalized {len(trails)} trails and {len(trailheads)} trailheads "
        f"from {stats['elements']} elements",
        file=sys.stderr,
    )
    if stats["skipped"]:
        print(f"skipped: {stats['skipped']}", file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trail_fc, trailhead_fc = to_feature_collection(trails, trailheads)
    (OUT_DIR / "trails.geojson").write_text(json.dumps(trail_fc))
    (OUT_DIR / "trailheads.geojson").write_text(json.dumps(trailhead_fc))
    (OUT_DIR / "ingest_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"wrote {OUT_DIR.relative_to(REPO_ROOT)}/trails.geojson", file=sys.stderr)
    print(f"wrote {OUT_DIR.relative_to(REPO_ROOT)}/trailheads.geojson", file=sys.stderr)

    if args.write_supabase:
        dsn = os.environ.get("SUPABASE_DB_URL")
        if not dsn:
            raise SystemExit("--write-supabase needs SUPABASE_DB_URL to be set")
        write_supabase(trails, trailheads, dsn)
    else:
        print(
            "not writing to Supabase. Run elevation.py next, then pass "
            "--write-supabase once the elevation fields are filled in.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
