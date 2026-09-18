"""Golden: conclusion robustness audit and AIS evidence integrity.

Covers `contracts/conclusion_robustness.md` cases 1-9.

The point of this module is to stop the system presenting a fragile conclusion and a
robust one in the same voice, so the tests are built around controlled fixtures whose
true fragility is known by construction:

  - A vessel anchored at the release point across the whole plausible release window
    is as strong as maritime attribution gets, and must read as robust.
  - Two vessels, each favoured at a different drift duration, is a genuinely
    undecidable case, and must read as fragile with the drift duration named as the
    assumption carrying the conclusion.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from apps.drift.engines.ensemble import EnsembleDriftEngine, EnsembleDriftInput
from apps.ais.robustness import (
    audit_conclusion, check_track_integrity, _sample_scenarios, SWEEP_RANGES,
)

T0 = datetime(2026, 1, 15, 3, 30, tzinfo=timezone.utc)


@dataclass
class Rec:
    timestamp: object
    lat: float
    lon: float
    speed_knots: float = 12.0


@dataclass(frozen=True)
class Ves:
    mmsi: str
    name: str


def drift_input(duration=24.0):
    return EnsembleDriftInput(
        start_lat=19.10, start_lon=72.10, detection_time=T0,
        wind_speed_mps=6.0, wind_direction_deg=225.0,
        current_speed_mps=0.4, current_direction_deg=90.0,
        duration_hours=duration,
    )


def baseline_run(di):
    return EnsembleDriftEngine().compute(
        EnsembleDriftInput(**{**vars(di), 'n_particles': 500, 'seed': 42}))


def anchored(lat, lon, t0, hours=33, step_min=10):
    """A vessel demonstrably on station at one point across a wide window."""
    n = int(hours * 60 / step_min)
    return [Rec(t0 + timedelta(minutes=step_min * i), lat, lon, 1.0)
            for i in range(-n, n + 1)]


def transit(lat, lon, t0):
    """A vessel passing through in a narrow window: present only briefly."""
    return [Rec(t0 + timedelta(minutes=10 * i), lat + 0.02 * i, lon + 0.02 * i, 14.0)
            for i in range(-4, 5)]


def test_case1_anchored_vessel_reads_as_robust():
    """Case 1: the strongest case a real investigation can produce."""
    di = drift_input()
    base = baseline_run(di)
    v = Ves('111111111', 'ANCHORED')

    report = audit_conclusion(
        di, {v: anchored(base.origin_lat, base.origin_lon, base.origin_time)},
        '111111111', n_scenarios=32)

    assert report.stability >= 0.75
    assert report.assessment == 'robust'
    assert report.scenarios_run == 32
    assert report.posterior_median > 0.4


def test_case2_conclusion_that_holds_only_at_one_duration_reads_as_fragile():
    """Case 2: THE case this module exists to catch.

    Two vessels, one at the origin implied by a short drift and one at the origin
    implied by a long drift. The headline run names whichever matches the assumed
    24 h. That conclusion is an artefact of the assumption, and must be reported as
    such rather than as a 70-percent finding.
    """
    di = drift_input()
    engine = EnsembleDriftEngine()
    short = engine.compute(EnsembleDriftInput(
        **{**vars(di), 'duration_hours': 16.0, 'n_particles': 300, 'seed': 1}))
    long_ = engine.compute(EnsembleDriftInput(
        **{**vars(di), 'duration_hours': 34.0, 'n_particles': 300, 'seed': 1}))

    tracks = {
        Ves('222222222', 'SHORT'): transit(short.origin_lat, short.origin_lon,
                                           short.origin_time),
        Ves('333333333', 'LONG'): transit(long_.origin_lat, long_.origin_lon,
                                          long_.origin_time),
    }

    report = audit_conclusion(di, tracks, '222222222', n_scenarios=32)

    assert report.stability < 0.45
    assert report.assessment == 'fragile'
    assert any('contingent' in line or 'lead for investigation' in line
               for line in report.narrative)


def test_case3_names_the_assumption_carrying_the_conclusion():
    """Case 3: it is not enough to say "fragile"; say WHICH assumption decides it."""
    di = drift_input()
    engine = EnsembleDriftEngine()
    short = engine.compute(EnsembleDriftInput(
        **{**vars(di), 'duration_hours': 16.0, 'n_particles': 300, 'seed': 1}))
    long_ = engine.compute(EnsembleDriftInput(
        **{**vars(di), 'duration_hours': 34.0, 'n_particles': 300, 'seed': 1}))

    report = audit_conclusion(di, {
        Ves('222222222', 'SHORT'): transit(short.origin_lat, short.origin_lon,
                                           short.origin_time),
        Ves('333333333', 'LONG'): transit(long_.origin_lat, long_.origin_lon,
                                          long_.origin_time),
    }, '222222222', n_scenarios=32)

    assert report.most_influential == 'duration_scale'
    assert report.breaking_points
    assert all(bp['parameter'] == 'duration_scale' for bp in report.breaking_points)
    # A breaking point must state a change, not "X rather than X".
    for bp in report.breaking_points:
        assert bp['note']
        assert bp['value']


def test_case4_audit_is_reproducible():
    """Case 4: the audit is itself evidence, so it must reproduce exactly."""
    di = drift_input()
    base = baseline_run(di)
    tracks = {Ves('111111111', 'A'): anchored(base.origin_lat, base.origin_lon,
                                              base.origin_time, hours=14)}

    a = audit_conclusion(di, tracks, '111111111', n_scenarios=16, seed=5)
    b = audit_conclusion(di, tracks, '111111111', n_scenarios=16, seed=5)
    assert a.to_dict() == b.to_dict()

    c = audit_conclusion(di, tracks, '111111111', n_scenarios=16, seed=6)
    assert c.to_dict() != a.to_dict()


def test_case5_null_finding_is_also_audited():
    """Case 5: "insufficient evidence" is a conclusion and deserves the same scrutiny.

    If no vessel was named, the audit reports how often the sweep also names nobody.
    A null finding that flips to an accusation under mild assumption changes is just
    as misleading as the reverse.
    """
    di = drift_input()
    far = Ves('999999999', 'ELSEWHERE')
    report = audit_conclusion(
        di, {far: anchored(25.0, 80.0, T0, hours=12)}, None, n_scenarios=16)

    assert report.scenarios_run == 16
    assert report.baseline_mmsi == ''
    assert 0.0 <= report.stability <= 1.0
    assert report.narrative


def test_case6_impossible_speed_is_flagged():
    """Case 6: no merchant vessel sustains 100 kn."""
    recs = [Rec(T0, 19.0, 72.0, 12.0),
            Rec(T0 + timedelta(minutes=10), 19.0, 72.30, 12.0)]
    rep = check_track_integrity('123456789', recs)

    assert rep.plausible is False
    assert any(f['code'] == 'impossible_speed' for f in rep.flags)
    assert rep.max_implied_speed_kn > 40.0


def test_case7_position_teleport_is_flagged():
    """Case 7: the classic injected/replayed AIS position signature."""
    recs = [Rec(T0, 19.0, 72.0, 12.0),
            Rec(T0 + timedelta(seconds=60), 19.0, 75.8, 12.0)]
    rep = check_track_integrity('123456789', recs)

    assert rep.plausible is False
    assert any(f['code'] == 'position_teleport' for f in rep.flags)


def test_case8_speed_contradicting_position_is_flagged():
    """Case 8: 14 kn reported while the position never moves."""
    recs = [Rec(T0, 19.0, 72.0, 14.0),
            Rec(T0 + timedelta(minutes=30), 19.0, 72.0, 14.0)]
    rep = check_track_integrity('123456789', recs)

    assert rep.plausible is False
    assert any(f['code'] == 'frozen_position_underway' for f in rep.flags)


def test_case8b_honest_track_is_not_flagged():
    """A legitimate track with ordinary GNSS jitter must pass cleanly.

    This is the false-positive guard. An integrity check that fires on honest data
    would train operators to ignore it, which is worse than not having it.
    """
    rng = np.random.default_rng(3)
    recs = [Rec(T0 + timedelta(minutes=10 * i),
                19.0 + 0.004 * i + rng.normal(0, 3e-5),
                72.0 + 0.004 * i + rng.normal(0, 3e-5), 12.3)
            for i in range(30)]
    rep = check_track_integrity('123456789', recs)

    assert rep.plausible is True
    assert rep.flags == []


def test_case9_zero_scenarios_is_an_error():
    """Case 9: an audit of nothing is not an audit."""
    di = drift_input()
    with pytest.raises(ValueError):
        audit_conclusion(di, {}, None, n_scenarios=0)


def test_case10_stability_increases_with_time_on_station():
    """Monotonicity: the longer a vessel is demonstrably at the release point, the
    more robust the attribution to it must be. A sweep that did not respect this
    would not be measuring what it claims to measure.
    """
    di = drift_input()
    base = baseline_run(di)
    v = Ves('111111111', 'ANCHORED')

    scores = []
    for hours in (6, 14, 33):
        report = audit_conclusion(
            di,
            {v: anchored(base.origin_lat, base.origin_lon, base.origin_time, hours=hours)},
            '111111111', n_scenarios=32)
        scores.append(report.stability)

    assert scores[0] < scores[1] <= scores[2], f'not monotonic: {scores}'


def test_case11_scenarios_are_stratified_over_the_declared_ranges():
    """Every swept value must lie inside the range the contract declares, and the
    sample must cover that range rather than clustering in its middle.
    """
    scenarios = _sample_scenarios(32, seed=7)
    assert len(scenarios) == 32

    for key, (lo, hi) in SWEEP_RANGES.items():
        values = np.array([s[key] for s in scenarios])
        assert values.min() >= lo
        assert values.max() <= hi
        # Stratified sampling must reach both ends, not hover near the centre.
        assert values.min() < lo + 0.2 * (hi - lo)
        assert values.max() > hi - 0.2 * (hi - lo)


def test_case12_single_ping_track_does_not_divide_by_zero():
    """Edge case: a track with one report has no implied speed."""
    rep = check_track_integrity('123456789', [Rec(T0, 19.0, 72.0, 5.0)])
    assert rep.plausible is True
    assert rep.max_implied_speed_kn == 0.0
    assert check_track_integrity('123456789', []).plausible is True
