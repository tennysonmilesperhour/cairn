#!/usr/bin/env python3
"""
Copernicus GLO-30 DEM sampling for the Wasatch trail dataset.

Reads data/normalized/trails.geojson from ingest.py, samples the DEM along each
trail at roughly 20m intervals, and writes back elev_gain_m, elev_loss_m,
elev_min_m, elev_max_m, and a downsampled elevation_profile.

DEM tiles are 1x1 degree GeoTIFFs from the public AWS open data bucket. They are
downloaded once into data/dem/ and reused. The four tiles covering the Wasatch
bbox total about 136 MB.

Gain and loss use a 5m noise threshold. See DECISIONS.md D007 and the note on
gain_loss below, which is where the threshold actually earns its keep.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Geod

REPO_ROOT = Path(__file__).resolve().parent.parent
DEM_DIR = REPO_ROOT / "data" / "dem"
NORMALIZED = REPO_ROOT / "data" / "normalized" / "trails.geojson"

DEM_BASE = os.environ.get(
    "COPERNICUS_DEM_BASE", "https://copernicus-dem-30m.s3.amazonaws.com"
)

SAMPLE_INTERVAL_M = 20.0
NOISE_THRESHOLD_M = 5.0
MAX_PROFILE_POINTS = 200

# Copernicus declares no nodata value, so guard against voids and ocean fill by
# range instead. Nothing in the Wasatch is below sea level or above 9000m.
VALID_MIN_M = -500.0
VALID_MAX_M = 9000.0

GEOD = Geod(ellps="WGS84")


# ---------------------------------------------------------------- DEM access


def tile_id(lat_sw: int, lon_sw: int) -> str:
    ns = "N" if lat_sw >= 0 else "S"
    ew = "E" if lon_sw >= 0 else "W"
    return f"{ns}{abs(lat_sw):02d}_00_{ew}{abs(lon_sw):03d}_00"


def tiles_for_bounds(west: float, south: float, east: float, north: float) -> list[str]:
    return [
        tile_id(lat, lon)
        for lat in range(math.floor(south), math.floor(north) + 1)
        for lon in range(math.floor(west), math.floor(east) + 1)
    ]


def ensure_tile(tid: str, dem_dir: Path = DEM_DIR, attempts: int = 4) -> Path:
    """Download a DEM tile into dem_dir if it is not already there."""
    name = f"Copernicus_DSM_COG_10_{tid}_DEM"
    dest = dem_dir / f"{name}.tif"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    dem_dir.mkdir(parents=True, exist_ok=True)
    url = f"{DEM_BASE}/{name}/{name}.tif"
    tmp = dest.with_suffix(".tif.part")
    backoff = 3.0

    for attempt in range(1, attempts + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as resp:
                if resp.status_code == 404:
                    raise SystemExit(f"DEM tile {tid} does not exist at {url}")
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = 100 * done / total
                            print(
                                f"\r  {tid}: {done/1e6:6.1f}/{total/1e6:.1f} MB "
                                f"({pct:5.1f}%)",
                                end="",
                                file=sys.stderr,
                            )
                print("", file=sys.stderr)
            tmp.rename(dest)
            return dest
        except requests.RequestException as exc:
            tmp.unlink(missing_ok=True)
            if attempt == attempts:
                raise SystemExit(f"could not download DEM tile {tid}: {exc}")
            print(
                f"  {tid}: {exc}. retrying in {backoff:.0f}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
            backoff *= 2

    raise SystemExit(f"could not download DEM tile {tid}")


class DemSampler:
    """Samples elevations from a set of 1x1 degree DEM tiles.

    Points are routed to the tile that contains them, so a trail crossing a tile
    boundary reads correctly instead of falling off the edge of a single raster.
    """

    def __init__(self, dem_dir: Path = DEM_DIR):
        self.dem_dir = dem_dir
        self._open: dict[str, rasterio.DatasetReader] = {}

    def _dataset(self, tid: str) -> rasterio.DatasetReader:
        if tid not in self._open:
            self._open[tid] = rasterio.open(ensure_tile(tid, self.dem_dir))
        return self._open[tid]

    def sample(self, coords: list[tuple[float, float]]) -> np.ndarray:
        """Elevations in metres for (lon, lat) pairs, NaN where unreadable."""
        out = np.full(len(coords), np.nan, dtype=float)
        by_tile: dict[str, list[int]] = defaultdict(list)
        for i, (lon, lat) in enumerate(coords):
            by_tile[tile_id(math.floor(lat), math.floor(lon))].append(i)

        for tid, idxs in by_tile.items():
            src = self._dataset(tid)
            pts = [coords[i] for i in idxs]
            vals = np.array([v[0] for v in src.sample(pts)], dtype=float)
            vals[(vals < VALID_MIN_M) | (vals > VALID_MAX_M)] = np.nan
            out[idxs] = vals
        return out

    def close(self) -> None:
        for src in self._open.values():
            src.close()
        self._open.clear()


# ------------------------------------------------------------ geometry maths


def densify(
    coords: list[tuple[float, float]], interval_m: float = SAMPLE_INTERVAL_M
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Resample a lon/lat polyline at roughly interval_m along its length.

    Segment lengths are geodesic. Positions within a segment are interpolated
    linearly, which is accurate to well under a metre at a 20m step.
    Returns cumulative distances and the sampled points.
    """
    if len(coords) < 2:
        return np.zeros(len(coords)), list(coords)

    points = [coords[0]]

    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        _, _, seg_len = GEOD.inv(lon1, lat1, lon2, lat2)
        if seg_len <= 0:
            continue
        # Split the segment into equal sub-steps no longer than interval_m, then
        # emit the segment's own end vertex. Every original vertex is kept, so the
        # sampled path is the trail rather than a set of chords across its bends.
        # Sampling between vertices only would both shorten the trail and skip the
        # terrain at every switchback.
        substeps = math.ceil(seg_len / interval_m)
        for k in range(1, substeps):
            f = k / substeps
            points.append((lon1 + (lon2 - lon1) * f, lat1 + (lat2 - lat1) * f))
        points.append((lon2, lat2))

    dists = np.empty(len(points))
    dists[0] = 0.0
    for i, ((lon1, lat1), (lon2, lat2)) in enumerate(zip(points, points[1:]), start=1):
        _, _, d = GEOD.inv(lon1, lat1, lon2, lat2)
        dists[i] = dists[i - 1] + d
    return dists, points


def gain_loss(
    elevs: np.ndarray, threshold: float = NOISE_THRESHOLD_M
) -> tuple[float, float]:
    """Cumulative gain and loss with a noise threshold, per DECISIONS.md D007.

    The naive version of this, `if abs(delta) > threshold: gain += delta`, is
    wrong in the opposite direction: a steady climb sampled every 20m rises about
    2m per sample, so every step falls under the threshold and the entire climb
    is discarded. The threshold has to apply to runs, not to individual steps.

    So this walks the series tracking an anchor, which is the last confirmed
    turning point, and a candidate, which is the most extreme value seen since
    that anchor. A run is committed only when the series reverses by at least
    the threshold and the run itself spans at least the threshold. Bumps smaller
    than the threshold are absorbed without moving the anchor, so DEM noise on
    flat ground contributes nothing, while a real climb is credited in full with
    no undercount at reversals.
    """
    clean = elevs[~np.isnan(elevs)]
    if clean.size < 2:
        return 0.0, 0.0

    gain = loss = 0.0
    anchor = candidate = float(clean[0])

    for value in clean[1:]:
        e = float(value)
        if candidate >= anchor:
            # Currently tracking an up-run from the anchor.
            if e > candidate:
                candidate = e
            elif candidate - e >= threshold:
                if candidate - anchor >= threshold:
                    gain += candidate - anchor
                    anchor = candidate
                candidate = e
        else:
            # Currently tracking a down-run from the anchor.
            if e < candidate:
                candidate = e
            elif e - candidate >= threshold:
                if anchor - candidate >= threshold:
                    loss += anchor - candidate
                    anchor = candidate
                candidate = e

    # Flush the run that is still open at the end of the trail.
    if candidate - anchor >= threshold:
        gain += candidate - anchor
    elif anchor - candidate >= threshold:
        loss += anchor - candidate

    return gain, loss


def downsample_profile(
    dists: np.ndarray, elevs: np.ndarray, max_points: int = MAX_PROFILE_POINTS
) -> list[list[float]]:
    """Evenly spaced [distance_m, elevation_m] pairs, endpoints always kept."""
    valid = ~np.isnan(elevs)
    if valid.sum() == 0:
        return []
    d, e = dists[valid], elevs[valid]

    if d.size <= max_points:
        idx = np.arange(d.size)
    else:
        idx = np.unique(np.linspace(0, d.size - 1, max_points).round().astype(int))

    return [[round(float(d[i]), 1), round(float(e[i]), 1)] for i in idx]


def profile_for(
    coords: list[tuple[float, float]], sampler: DemSampler
) -> dict[str, object]:
    """Elevation statistics and profile for one trail geometry."""
    dists, points = densify(coords)
    elevs = sampler.sample(points)
    valid = ~np.isnan(elevs)

    if valid.sum() < 2:
        return {
            "elev_gain_m": None,
            "elev_loss_m": None,
            "elev_min_m": None,
            "elev_max_m": None,
            "elevation_profile": None,
            "dem_samples": int(valid.sum()),
        }

    gain, loss = gain_loss(elevs)
    return {
        "elev_gain_m": round(gain, 1),
        "elev_loss_m": round(loss, 1),
        "elev_min_m": round(float(np.nanmin(elevs)), 1),
        "elev_max_m": round(float(np.nanmax(elevs)), 1),
        "elevation_profile": downsample_profile(dists, elevs),
        "dem_samples": int(valid.sum()),
    }


# ------------------------------------------------------------------ pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=NORMALIZED, help="trails.geojson from ingest.py"
    )
    parser.add_argument(
        "--limit", type=int, help="only process the first N trails, for a quick check"
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"{args.input} not found. Run ingest.py first.")

    fc = json.loads(args.input.read_text())
    features = fc["features"]
    if args.limit:
        features = features[: args.limit]

    lons = [c[0] for f in features for c in f["geometry"]["coordinates"]]
    lats = [c[1] for f in features for c in f["geometry"]["coordinates"]]
    tiles = tiles_for_bounds(min(lons), min(lats), max(lons), max(lats))
    print(f"DEM tiles needed: {', '.join(tiles)}", file=sys.stderr)
    for tid in tiles:
        ensure_tile(tid)

    sampler = DemSampler()
    try:
        for i, feature in enumerate(features, 1):
            coords = [(c[0], c[1]) for c in feature["geometry"]["coordinates"]]
            feature["properties"].update(profile_for(coords, sampler))
            if i % 500 == 0 or i == len(features):
                print(f"\r  elevation: {i}/{len(features)}", end="", file=sys.stderr)
        print("", file=sys.stderr)
    finally:
        sampler.close()

    args.input.write_text(json.dumps(fc))
    print(f"wrote elevation fields into {args.input}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
