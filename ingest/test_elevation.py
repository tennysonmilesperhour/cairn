"""
Tests for the elevation and distance maths.

Phase 0 tests these two things and nothing else, because they are the numbers the
coverage report is judged on and the ones that are silently wrong when they are
wrong. See DECISIONS.md D007.

Run:  pytest ingest/test_elevation.py -v

Tests are grouped by what they need:
  - the maths tests need nothing and always run
  - the DEM tests download a 38 MB tile on first run and skip without network
  - the known trail test skips until ingest.py has produced trails.geojson
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from elevation import (
    DemSampler,
    NOISE_THRESHOLD_M,
    densify,
    downsample_profile,
    gain_loss,
    profile_for,
    tiles_for_bounds,
)

M_PER_FT = 0.3048
M_PER_MI = 1609.344

NORMALIZED = Path(__file__).resolve().parent.parent / "data" / "normalized" / "trails.geojson"


# ------------------------------------------------------------- gain and loss


def test_steady_climb_is_not_eaten_by_the_threshold():
    """The failure mode that matters most.

    A trail sampled every 20m at a 10 percent grade rises about 2m per sample.
    A threshold applied per step would discard every one of those steps and
    report zero gain for a real climb. The threshold applies to runs instead.
    """
    climb = np.arange(0, 101, 2.0)
    gain, loss = gain_loss(climb)
    assert gain == pytest.approx(100.0, abs=1.0)
    assert loss == pytest.approx(0.0, abs=1.0)

    naive = np.diff(climb)
    assert naive[naive > NOISE_THRESHOLD_M].sum() == 0.0, (
        "per-step thresholding really does return zero here, which is why "
        "gain_loss tracks runs instead"
    )


def test_flat_trail_with_dem_noise_reports_almost_no_gain():
    """The other failure mode: DEM jitter on flat ground inflating gain.

    Eight kilometres of dead flat trail carrying realistic GLO-30 pixel to pixel
    noise. Summing raw differences invents hundreds of metres of climb. The
    threshold has to remove essentially all of it. Some residue is expected and
    correct, since a genuine 5m step and a 5m noise excursion are the same
    number, so this asserts a suppression ratio rather than a bare zero.
    """
    rng = np.random.default_rng(0)
    flat = 1500.0 + rng.normal(0, 1.5, 400)

    diffs = np.diff(flat)
    unthresholded = float(diffs[diffs > 0].sum())
    gain, loss = gain_loss(flat)

    assert unthresholded > 200.0, "sanity: raw summation should be badly inflated"
    assert gain < 0.05 * unthresholded, (
        f"threshold removed too little: {gain:.1f}m of {unthresholded:.1f}m"
    )
    assert gain < 25.0, "under 25m of phantom gain across 8km of flat trail"
    assert loss < 25.0


def test_rolling_terrain_credits_each_run_in_full():
    """No undercount at reversals: gain is committed peak to valley, not lagged."""
    series = np.concatenate(
        [np.arange(0, 51, 2.0), np.arange(48, 19, -2.0), np.arange(22, 71, 2.0)]
    )
    gain, loss = gain_loss(series)
    assert gain == pytest.approx(100.0, abs=2.0)
    assert loss == pytest.approx(30.0, abs=2.0)


def test_sub_threshold_bumps_do_not_move_the_anchor():
    """A 3m bump on an otherwise flat trail is noise, not 3m of gain."""
    gain, loss = gain_loss(np.array([0.0, 3.0, -3.0, 3.0, -3.0, 0.0]))
    assert gain == 0.0
    assert loss == 0.0


def test_pure_descent():
    gain, loss = gain_loss(np.arange(100, -1, -2.0))
    assert gain == pytest.approx(0.0, abs=1.0)
    assert loss == pytest.approx(100.0, abs=1.0)


def test_nan_samples_are_skipped_not_treated_as_zero():
    gain, loss = gain_loss(np.array([0.0, np.nan, 10.0, np.nan, 20.0]))
    assert gain == pytest.approx(20.0)
    assert loss == pytest.approx(0.0)


def test_too_short_to_have_gain():
    assert gain_loss(np.array([])) == (0.0, 0.0)
    assert gain_loss(np.array([1500.0])) == (0.0, 0.0)


# ---------------------------------------------------------------- geometry


def test_densify_preserves_geodesic_length():
    """Resampling must not change how long the trail is."""
    from pyproj import Geod

    coords = [(-111.80, 40.60), (-111.80, 40.65), (-111.75, 40.65)]
    dists, points = densify(coords)

    geod = Geod(ellps="WGS84")
    truth = sum(
        geod.inv(a[0], a[1], b[0], b[1])[2] for a, b in zip(coords, coords[1:])
    )
    assert dists[-1] == pytest.approx(truth, rel=1e-4)
    assert len(points) == len(dists)


def test_densify_spacing_never_exceeds_the_interval():
    dists, _ = densify([(-111.80, 40.60), (-111.80, 40.65)])
    steps = np.diff(dists)
    assert steps.max() <= 20.0 + 1e-6
    assert np.median(steps) == pytest.approx(20.0, abs=0.5)


def test_densify_keeps_every_original_vertex():
    """A chord across a bend both shortens the trail and skips its terrain."""
    corner = [(-111.80, 40.60), (-111.80, 40.65), (-111.75, 40.65)]
    _, points = densify(corner)
    for vertex in corner:
        assert any(
            abs(p[0] - vertex[0]) < 1e-12 and abs(p[1] - vertex[1]) < 1e-12
            for p in points
        ), f"vertex {vertex} was dropped"


def test_densify_handles_degenerate_geometry():
    dists, points = densify([(-111.8, 40.6)])
    assert len(points) == 1
    dists, points = densify([(-111.8, 40.6), (-111.8, 40.6)])
    assert dists[-1] == pytest.approx(0.0)


def test_profile_is_capped_at_two_hundred_points():
    dists = np.arange(0, 20000, 20.0)
    elevs = 1500 + 300 * np.sin(dists / 2000)
    profile = downsample_profile(dists, elevs)
    assert len(profile) <= 200
    assert profile[0][0] == pytest.approx(0.0)
    assert profile[-1][0] == pytest.approx(dists[-1])
    assert all(len(pair) == 2 for pair in profile)


def test_profile_keeps_short_trails_intact():
    dists = np.arange(0, 200, 20.0)
    elevs = np.linspace(1500, 1560, len(dists))
    profile = downsample_profile(dists, elevs)
    assert len(profile) == len(dists)


def test_tiles_for_bounds_covers_the_wasatch_bbox():
    tiles = tiles_for_bounds(-112.20, 40.35, -111.35, 41.00)
    assert "N40_00_W112_00" in tiles
    assert "N40_00_W113_00" in tiles  # the strip west of -112
    assert all(t.startswith(("N40", "N41")) for t in tiles)


# --------------------------------------------------------------- DEM checks


@pytest.fixture(scope="module")
def sampler():
    try:
        s = DemSampler()
        s.sample([(-111.9778, 40.7884)])
    except (SystemExit, OSError) as exc:
        pytest.skip(f"DEM tile unavailable: {exc}")
    yield s
    s.close()


def test_dem_matches_a_published_elevation(sampler):
    """Salt Lake City International Airport, published field elevation 4,227 ft.

    A large flat airfield, so an approximate coordinate still lands on ground at
    the published height. Named summits are deliberately not used here: a 30m DEM
    smooths sharp peaks by a few hundred feet, so a summit disagreement would
    measure the DEM's resolution rather than catch a real bug.
    """
    published_m = 4227 * M_PER_FT
    got = sampler.sample([(-111.9778, 40.7884)])[0]
    assert not math.isnan(got)
    assert got == pytest.approx(published_m, abs=25.0)


def test_dem_returns_plausible_wasatch_elevations(sampler):
    """Catches a wrong tile, a wrong datum, or feet-for-metres across the bbox."""
    lons = np.linspace(-112.15, -111.40, 12)
    lats = np.linspace(40.40, 40.95, 12)
    pts = [(float(lon), float(lat)) for lon in lons for lat in lats]
    vals = sampler.sample(pts)
    good = vals[~np.isnan(vals)]

    assert good.size > 100
    assert good.min() > 1200.0, "valley floor should not be below the Great Salt Lake"
    assert good.max() < 3700.0, "nothing in the bbox is higher than Timpanogos"


def test_profile_for_returns_a_consistent_record(sampler):
    """A real 5km line up the Wasatch front should gain elevation monotonically."""
    coords = [(-111.7900, 40.6300), (-111.7500, 40.6300)]
    record = profile_for(coords, sampler)

    assert record["dem_samples"] > 100
    assert record["elev_min_m"] < record["elev_max_m"]
    assert record["elev_gain_m"] >= 0 and record["elev_loss_m"] >= 0
    assert record["elev_max_m"] - record["elev_min_m"] <= record["elev_gain_m"] + record["elev_loss_m"]
    assert len(record["elevation_profile"]) <= 200


# ------------------------------------------------- known trail, needs ingest

# One trail with a widely published figure, checked end to end once ingest.py
# has run. Sources disagree with each other by roughly 10 percent on trail
# statistics, so the tolerance is 15 percent: tight enough to catch a broken
# gain calculation, loose enough not to fail on which guidebook was consulted.
KNOWN_TRAIL = {
    "name": "Lake Blanche",
    "published_gain_ft": 2720,
    "published_roundtrip_mi": 6.9,
    "tolerance": 0.15,
}


def _load_named_trail(substring: str) -> dict | None:
    if not NORMALIZED.exists():
        return None
    fc = json.loads(NORMALIZED.read_text())
    matches = [
        f
        for f in fc["features"]
        if (f["properties"].get("name") or "").lower().startswith(substring.lower())
        and f["properties"].get("elev_gain_m") is not None
    ]
    if not matches:
        return None
    return max(matches, key=lambda f: f["properties"]["length_m"])


def test_known_trail_matches_published_figures():
    """Compare one hiked trail against its published distance and gain.

    An out and back is published as a round trip, while OSM stores the trail
    once. So published round trip distance is compared against twice the
    computed length, and published round trip gain against the computed one way
    gain, because the return leg is all descent and adds no gain.
    """
    feature = _load_named_trail(KNOWN_TRAIL["name"])
    if feature is None:
        pytest.skip(
            f"no ingested trail matching {KNOWN_TRAIL['name']!r} with elevation. "
            "Run ingest.py then elevation.py first."
        )

    props = feature["properties"]
    computed_rt_mi = 2 * props["length_m"] / M_PER_MI
    computed_gain_ft = props["elev_gain_m"] / M_PER_FT
    tol = KNOWN_TRAIL["tolerance"]

    assert computed_rt_mi == pytest.approx(
        KNOWN_TRAIL["published_roundtrip_mi"], rel=tol
    ), f"distance: computed {computed_rt_mi:.1f} mi round trip"
    assert computed_gain_ft == pytest.approx(
        KNOWN_TRAIL["published_gain_ft"], rel=tol
    ), f"gain: computed {computed_gain_ft:.0f} ft"
