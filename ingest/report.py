#!/usr/bin/env python3
"""
Phase 0 coverage report.

Reads data/normalized/trails.geojson and trailheads.geojson and prints what OSM
actually has for the Wasatch Front. This is the gate for phase 1: if named trail
coverage is thin, Cairn is a data collection problem rather than a map problem,
and that needs to be known before any UI exists. See DECISIONS.md D010.

Run:  python ingest/report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NORMALIZED = REPO_ROOT / "data" / "normalized"

M_PER_MI = 1609.344
M_PER_FT = 0.3048

LONGEST_N = 30

# Bounds for the implausibility checks. These are deliberately loose. Anything
# flagged is a prompt to go look at the trail in OSM, not a verdict.
MAX_PLAUSIBLE_LENGTH_M = 150_000       # longer than any single Wasatch route
MIN_PLAUSIBLE_LENGTH_M = 10
MAX_PLAUSIBLE_GRADE = 0.50             # 50 percent average grade over the trail
MIN_LENGTH_FOR_GRADE_M = 500           # stairs and short connectors are legitimately steep
MAX_PLAUSIBLE_GAIN_M = 3_000           # Timpanogos from the valley is about 1,500
WASATCH_MIN_ELEV_M = 1_200             # Great Salt Lake sits near 1,280
WASATCH_MAX_ELEV_M = 3_600             # Timpanogos summit is 3,582
MAX_MERGE_DROP_FRACTION = 0.25         # relation merge discarding a quarter of itself


def rule(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run ingest.py first.")
    return json.loads(path.read_text())["features"]


def summarize(trails: list[dict], trailheads: list[dict]) -> None:
    props = [f["properties"] for f in trails]
    named = [p for p in props if p.get("name")]
    unnamed = [p for p in props if not p.get("name")]
    with_elev = [p for p in props if p.get("elev_gain_m") is not None]

    named_m = sum(p["length_m"] for p in named)
    total_m = sum(p["length_m"] for p in props)

    rule("Coverage")
    print(f"  trails total                {len(props):>10,}")
    print(
        f"  named                       {len(named):>10,}"
        f"   ({100 * len(named) / max(len(props), 1):.1f}%)"
    )
    print(f"  unnamed connector segments  {len(unnamed):>10,}")
    print(f"  trailheads                  {len(trailheads):>10,}")
    print()
    print(f"  named trail miles           {named_m / M_PER_MI:>10,.1f}")
    print(f"  total trail miles           {total_m / M_PER_MI:>10,.1f}")

    by_type = Counter(p["osm_type"] for p in props)
    print()
    print(f"  from hiking relations       {by_type.get('relation', 0):>10,}")
    print(f"  from standalone ways        {by_type.get('way', 0):>10,}")

    rule("Surface tagging")
    tagged = [p for p in props if p.get("surface")]
    named_tagged = [p for p in named if p.get("surface")]
    print(f"  trails with surface         {len(tagged):>10,}"
          f"   ({100 * len(tagged) / max(len(props), 1):.1f}%)")
    print(f"  named trails with surface   {len(named_tagged):>10,}"
          f"   ({100 * len(named_tagged) / max(len(named), 1):.1f}%)")
    sources = Counter(p.get("tags", {}).get("surface_source") for p in tagged)
    if sources.get("members"):
        print(f"    of which inherited from relation members: {sources['members']:,}")
    print()
    for surface, count in Counter(p["surface"] for p in tagged).most_common(8):
        print(f"    {surface:<24s} {count:>8,}")

    rule("Elevation")
    if not with_elev:
        print("  no elevation computed yet. Run elevation.py.")
    else:
        print(f"  trails with elevation       {len(with_elev):>10,}"
              f"   ({100 * len(with_elev) / max(len(props), 1):.1f}%)")
        gains = sorted(p["elev_gain_m"] for p in with_elev)
        mid = gains[len(gains) // 2]
        print(f"  median gain                 {mid / M_PER_FT:>10,.0f} ft")
        print(f"  max gain                    {gains[-1] / M_PER_FT:>10,.0f} ft")
        lo = min(p["elev_min_m"] for p in with_elev)
        hi = max(p["elev_max_m"] for p in with_elev)
        print(f"  elevation range        {lo / M_PER_FT:>8,.0f} to {hi / M_PER_FT:,.0f} ft")


def longest_named(trails: list[dict], limit: int = LONGEST_N) -> None:
    named = [f["properties"] for f in trails if f["properties"].get("name")]
    named.sort(key=lambda p: p["length_m"], reverse=True)

    rule(f"{limit} longest named trails")
    print(
        f"  {'#':>3} {'name':<42} {'mi':>7} {'gain ft':>9} "
        f"{'surface':<12} {'osm':<14}"
    )
    for i, p in enumerate(named[:limit], 1):
        gain = p.get("elev_gain_m")
        gain_s = f"{gain / M_PER_FT:,.0f}" if gain is not None else "-"
        name = (p["name"] or "")[:42]
        osm = f"{p['osm_type'][:3]}/{p['osm_id']}"
        print(
            f"  {i:>3} {name:<42} {p['length_m'] / M_PER_MI:>7.2f} {gain_s:>9} "
            f"{(p.get('surface') or '-'):<12} {osm:<14}"
        )
    print("\n  Cross check these against trails you have actually hiked.")
    print("  Look up any that seem wrong at https://www.openstreetmap.org/<osm>")


def implausible(trails: list[dict]) -> int:
    """Flag anything whose numbers do not survive a sanity check."""
    findings: dict[str, list[str]] = {}

    def flag(kind: str, p: dict, detail: str) -> None:
        label = p.get("name") or f"(unnamed {p['osm_type']} {p['osm_id']})"
        findings.setdefault(kind, []).append(
            f"{label[:44]:<44} {detail}  {p['osm_type'][:3]}/{p['osm_id']}"
        )

    for feature in trails:
        p = feature["properties"]
        length = p.get("length_m") or 0.0

        if length < MIN_PLAUSIBLE_LENGTH_M:
            flag("Length under 10m", p, f"{length:.1f} m")
        elif length > MAX_PLAUSIBLE_LENGTH_M:
            flag("Length over 150km", p, f"{length / M_PER_MI:,.1f} mi")

        gain = p.get("elev_gain_m")
        if gain is None:
            continue

        if gain > MAX_PLAUSIBLE_GAIN_M:
            flag("Gain over 3,000m", p, f"{gain / M_PER_FT:,.0f} ft")
        # Only applied over a real distance. highway=steps is part of the trail
        # network in the Wasatch and a flight of stairs genuinely exceeds 50%.
        if length > MIN_LENGTH_FOR_GRADE_M and gain / length > MAX_PLAUSIBLE_GRADE:
            flag(
                "Average grade over 50%",
                p,
                f"{100 * gain / length:.0f}% over {length / M_PER_MI:.2f} mi",
            )

        lo, hi = p.get("elev_min_m"), p.get("elev_max_m")
        if lo is not None and lo < WASATCH_MIN_ELEV_M:
            flag("Elevation below the valley floor", p, f"min {lo / M_PER_FT:,.0f} ft")
        if hi is not None and hi > WASATCH_MAX_ELEV_M:
            flag("Elevation above Timpanogos", p, f"max {hi / M_PER_FT:,.0f} ft")

        dropped = p.get("tags", {}).get("merge_dropped_m") or 0.0
        if dropped and length and dropped / (length + dropped) > MAX_MERGE_DROP_FRACTION:
            flag(
                "Relation merge discarded a large share",
                p,
                f"{dropped / M_PER_MI:.2f} mi dropped of "
                f"{(length + dropped) / M_PER_MI:.2f} mi, "
                f"{p['tags'].get('merge_components')} components",
            )

        if p.get("dem_samples") == 0:
            flag("No DEM samples", p, "outside the DEM tiles")

    rule("Implausible values")
    if not findings:
        print("  none")
        return 0

    total = 0
    for kind, rows in sorted(findings.items()):
        print(f"\n  {kind}  ({len(rows)})")
        for row in rows[:15]:
            print(f"    {row}")
        if len(rows) > 15:
            print(f"    ... and {len(rows) - 15} more")
        total += len(rows)
    return total


def merge_quality(trails: list[dict]) -> None:
    """How well hiking relations actually merged, which the LineString column hides."""
    rels = [
        f["properties"]
        for f in trails
        if f["properties"]["osm_type"] == "relation"
        and f["properties"].get("tags", {}).get("merge_components")
    ]
    if not rels:
        return

    contiguous = [p for p in rels if p["tags"]["merge_components"] == 1]
    dropped_m = sum(p["tags"].get("merge_dropped_m", 0.0) for p in rels)

    rule("Hiking relation merge quality")
    print(f"  relations                   {len(rels):>10,}")
    print(
        f"  merged to one line          {len(contiguous):>10,}"
        f"   ({100 * len(contiguous) / len(rels):.1f}%)"
    )
    print(f"  miles dropped               {dropped_m / M_PER_MI:>10,.1f}")
    if dropped_m / M_PER_MI > 20:
        print(
            "\n  A large drop here means many relations are not contiguous lines.\n"
            "  See DECISIONS.md D012 for why only the longest component is kept."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=NORMALIZED)
    parser.add_argument("--longest", type=int, default=LONGEST_N)
    args = parser.parse_args()

    trails = load(args.dir / "trails.geojson")
    trailheads = load(args.dir / "trailheads.geojson")

    print("Cairn phase 0 coverage report")
    print("Wasatch Front, bbox -112.20 40.35 -111.35 41.00")
    print("Trail data from OpenStreetMap, ODbL. Elevation from Copernicus GLO-30.")

    summarize(trails, trailheads)
    merge_quality(trails)
    longest_named(trails, args.longest)
    flagged = implausible(trails)

    print()
    if flagged:
        print(f"{flagged} value(s) flagged for a look.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
