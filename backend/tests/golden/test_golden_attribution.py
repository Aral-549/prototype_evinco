"""Golden: Bayesian vessel attribution.

Covers `contracts/bayesian_attribution.md` cases 1-8 and the BUGLOG entries
"Proximity and time scored independently" and "Attribution verdict depended on
traffic density, not evidence".

Uses lightweight stand-ins for Vessel/AISRecord so these cases run without a
database: the attribution module only needs `.timestamp`, `.lat`, `.lon`,
`.speed_knots` on records and `.mmsi` / `.name` on vessels.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from apps.ais.attribution import (
    attribute, summarise, interpolate_position, closest_point_of_approach,
    detect_anomalies_detailed, haversine_km,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


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


def tight_ensemble(n=200, lat=19.0, lon=72.0, when=T0):
    return [{'lat': lat, 'lon': lon, 'time': when} for _ in range(n)]


def station_keeping(lat, lon, when=T0, span=6, speed=12.0):
    """A vessel holding position, reporting every 10 minutes."""
    return [Rec(when + timedelta(minutes=10 * i), lat, lon, speed)
            for i in range(-span, span + 1)]


def test_case1_vessel_at_the_origin_at_the_origin_time():
    """Case 1: an unambiguous match must be reported as strong."""
    v = Ves('111111111', 'ON SCENE')
    results, unknown = attribute(tight_ensemble(), {v: station_keeping(19.0, 72.0)})

    assert results[0].vessel is v
    assert results[0].posterior > 0.70
    assert results[0].verdict == 'strong'
    assert results[0].spatiotemporal_likelihood > 0.9
    assert unknown < 0.30


def test_case2_right_place_wrong_time_is_not_evidence():
    """Case 2 (BUGLOG: proximity and time scored independently).

    A vessel that passed 1 km from the reconstructed origin FORTY HOURS before the
    release. The legacy scorer gave this a high proximity term and a composite
    score close to a genuine match. The joint likelihood must be zero.
    """
    v = Ves('222222222', 'WRONG TIME')
    track = [Rec(T0 - timedelta(hours=40) + timedelta(minutes=10 * i), 19.009, 72.0)
             for i in range(12)]

    results, unknown = attribute(tight_ensemble(), {v: track})

    assert results[0].spatiotemporal_likelihood == 0.0
    assert results[0].posterior == 0.0
    assert results[0].verdict == 'insufficient'
    assert unknown == pytest.approx(1.0)
    assert summarise(results, unknown)['conclusion'] == 'insufficient_evidence'


def test_case3_identical_vessels_tie_exactly():
    """Case 3: no tie-breaking by MMSI or dict insertion order."""
    particles = [{'lat': 19.0 + d, 'lon': 72.0, 'time': T0}
                 for d in (-0.004, -0.002, 0.0, 0.002, 0.004)] * 40
    a, b = Ves('333333333', 'TWIN A'), Ves('444444444', 'TWIN B')
    ta, tb = station_keeping(19.02, 72.0), station_keeping(18.98, 72.0)

    forward, _ = attribute(particles, {a: ta, b: tb})
    reverse, _ = attribute(particles, {b: tb, a: ta})

    assert forward[0].posterior == pytest.approx(forward[1].posterior, abs=1e-9)
    assert forward[0].posterior == pytest.approx(reverse[0].posterior, abs=1e-12)


def test_case4_refuses_to_accuse_when_nobody_fits():
    """Case 4: the unknown-vessel hypothesis must win rather than the least-bad track."""
    v = Ves('555555555', 'FAR AWAY')
    results, unknown = attribute(tight_ensemble(), {v: station_keeping(21.0, 74.0)})
    summary = summarise(results, unknown)

    assert results[0].posterior < 0.25
    assert unknown > results[0].posterior
    assert all(r.verdict == 'insufficient' for r in results)
    assert summary['conclusion'] == 'insufficient_evidence'
    assert 'dark-vessel' in summary['headline'] or 'transponder' in summary['headline']


def test_case5_irrelevant_traffic_does_not_dilute_a_match():
    """Case 5 (BUGLOG: verdict depended on traffic density).

    A busy lane carries 100+ vessels in a 48 h window. Vessels the ensemble cannot
    place contribute zero likelihood and must therefore change nothing. Before the
    fix, the same perfect match fell from 0.93 ("strong") to 0.06 ("insufficient")
    as decoys were added.
    """
    culprit = Ves('111111111', 'PERFECT MATCH')
    baseline = None

    for n_decoys in (0, 9, 49, 199):
        tracks = {culprit: station_keeping(19.0, 72.0)}
        for i in range(n_decoys):
            tracks[Ves(f'9{i:08d}', f'DECOY {i}')] = station_keeping(25.0 + i * 0.01, 80.0)

        results, unknown = attribute(tight_ensemble(), tracks)
        top = next(r for r in results if r.vessel is culprit)

        if baseline is None:
            baseline = top.posterior
            assert top.verdict == 'strong'
        assert top.posterior == pytest.approx(baseline, abs=1e-9), (
            f'{n_decoys} irrelevant vessels changed the posterior from {baseline:.4f} '
            f'to {top.posterior:.4f}'
        )
        assert top.verdict == 'strong'


def test_case5b_genuine_competition_still_splits_the_mass():
    """Case 5b: the fix must not make every candidate score highly.

    Distinct from case 5: these vessels all genuinely match, so the mass SHOULD
    divide among them.
    """
    posteriors = []
    for k in (1, 2, 3):
        tracks = {Ves(str(i) * 9, f'RIVAL {i}'): station_keeping(19.0, 72.0)
                  for i in range(k)}
        results, _ = attribute(tight_ensemble(), tracks)
        posteriors.append(results[0].posterior)

    assert posteriors[0] > posteriors[1] > posteriors[2]


def test_case6_cpa_is_interpolated_not_nearest_ping():
    """Case 6 (BUGLOG: nearest discrete ping overstates closest approach).

    A vessel reports at 19.10N one hour before the release and 18.90N one hour
    after, passing directly over 19.00N in between. The nearest ping is 11.1 km
    away; the true closest approach is 0 km.
    """
    recs = [Rec(T0 - timedelta(hours=1), 19.10, 72.0),
            Rec(T0 + timedelta(hours=1), 18.90, 72.0)]

    nearest_ping = min(haversine_km(19.0, 72.0, r.lat, r.lon) for r in recs)
    cpa_km, cpa_time = closest_point_of_approach(recs, 19.0, 72.0, T0, max_gap_s=7200)

    assert nearest_ping == pytest.approx(11.1, abs=0.5)
    assert cpa_km < 1.0
    assert cpa_km < nearest_ping
    assert T0 - timedelta(minutes=15) <= cpa_time <= T0 + timedelta(minutes=15)


def test_case7_never_interpolates_across_a_long_silence():
    """Case 7: a vessel dark for three hours could be anywhere. Invent nothing."""
    recs = [Rec(T0 - timedelta(hours=3), 19.0, 72.0),
            Rec(T0 + timedelta(hours=3), 19.0, 72.0)]

    assert interpolate_position(recs, T0, max_gap_s=3600.0) is None
    # Within the allowed gap it does interpolate, linearly.
    ok = [Rec(T0 - timedelta(minutes=10), 19.0, 72.0),
          Rec(T0 + timedelta(minutes=10), 19.2, 72.0)]
    lat, lon = interpolate_position(ok, T0, max_gap_s=3600.0)
    assert lat == pytest.approx(19.1, abs=1e-9)
    assert lon == pytest.approx(72.0, abs=1e-9)


def test_case8_empty_ensemble_is_an_error():
    """Case 8: attribution without a drift ensemble is meaningless."""
    with pytest.raises(ValueError):
        attribute([], {Ves('1' * 9, 'X'): station_keeping(19.0, 72.0)})
    with pytest.raises(ValueError):
        attribute(tight_ensemble(), {}, prior_unknown=0.0)


def test_case9_posteriors_always_normalise():
    """Invariant: all vessel posteriors plus the unknown hypothesis sum to 1."""
    tracks = {
        Ves('111111111', 'NEAR'): station_keeping(19.0, 72.0),
        Ves('222222222', 'MID'): station_keeping(19.02, 72.0),
        Ves('333333333', 'FAR'): station_keeping(21.0, 74.0),
    }
    results, unknown = attribute(tight_ensemble(), tracks)
    assert sum(r.posterior for r in results) + unknown == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= r.posterior <= 1.0 for r in results)
    assert 0.0 <= unknown <= 1.0


def test_case10_soft_capture_discriminates_by_distance():
    """A vessel on the origin must outrank one at the edge of the capture radius.

    A hard capture disc scored both at exactly 1.0, discarding the sharpest
    discriminator available on a crowded lane.
    """
    tracks = {
        Ves('111111111', 'ON ORIGIN'): station_keeping(19.0, 72.0),
        Ves('222222222', 'TWO KM'): station_keeping(19.018, 72.0),
        Ves('333333333', 'FOUR KM'): station_keeping(19.0405, 72.0),
    }
    results, _ = attribute(tight_ensemble(), tracks, capture_radius_km=5.0)

    by_name = {r.vessel.name: r for r in results}
    assert (by_name['ON ORIGIN'].spatiotemporal_likelihood
            > by_name['TWO KM'].spatiotemporal_likelihood
            > by_name['FOUR KM'].spatiotemporal_likelihood)
    assert results[0].vessel.name == 'ON ORIGIN'


def test_case11_behaviour_breaks_ties_but_never_creates_attribution():
    """Case 11: anomalies are a multiplier on presence, not a substitute for it."""
    clean = Ves('666666666', 'CLEAN')
    dark = Ves('777777777', 'WENT DARK')

    dark_track = sorted(
        [Rec(T0 - timedelta(minutes=100), 19.01, 72.0),
         Rec(T0 - timedelta(minutes=10), 19.01, 72.0)]
        + [Rec(T0 + timedelta(minutes=10 * i), 19.01, 72.0) for i in range(7)],
        key=lambda r: r.timestamp)

    results, _ = attribute(tight_ensemble(),
                           {clean: station_keeping(19.01, 72.0), dark: dark_track})
    assert results[0].vessel is dark
    assert results[0].behavioural_factor > 1.0

    # But an absent vessel with every anomaly in the book still scores zero.
    absent = Ves('888888888', 'ABSENT AND SUSPICIOUS')
    far_dark = sorted(
        [Rec(T0 - timedelta(minutes=200), 30.0, 90.0),
         Rec(T0 + timedelta(minutes=10), 30.0, 90.0)],
        key=lambda r: r.timestamp)
    results2, unknown2 = attribute(tight_ensemble(), {absent: far_dark})
    assert results2[0].spatiotemporal_likelihood == 0.0
    assert results2[0].posterior == 0.0


def test_case12_anomaly_severity_is_graded():
    """A 12-hour blackout must not weigh the same as a 31-minute reporting gap."""
    short_gap = [Rec(T0, 19.0, 72.0), Rec(T0 + timedelta(minutes=31), 19.0, 72.0),
                 Rec(T0 + timedelta(minutes=41), 19.0, 72.0)]
    long_gap = [Rec(T0, 19.0, 72.0), Rec(T0 + timedelta(hours=12), 19.0, 72.0),
                Rec(T0 + timedelta(hours=12, minutes=10), 19.0, 72.0)]

    a_short = detect_anomalies_detailed(short_gap, 19.0, 72.0, T0)
    a_long = detect_anomalies_detailed(long_gap, 19.0, 72.0, T0)

    gap_short = next(a for a in a_short if a.code.startswith('ais_gap')
                     or a.code == 'dark_vessel_gap')
    gap_long = next(a for a in a_long if a.code.startswith('ais_gap')
                    or a.code == 'dark_vessel_gap')

    assert gap_long.severity > gap_short.severity
    assert gap_long.likelihood_ratio > gap_short.likelihood_ratio


def test_case13_single_record_and_duplicate_timestamps():
    """Edge cases: one ping cannot be interpolated; a zero-length segment cannot divide."""
    one = [Rec(T0, 19.0, 72.0)]
    assert interpolate_position(one, T0, 3600.0) == (19.0, 72.0)
    assert interpolate_position(one, T0 + timedelta(hours=5), 3600.0) is None

    dup = [Rec(T0, 19.0, 72.0), Rec(T0, 19.5, 72.5)]
    assert interpolate_position(dup, T0, 3600.0) is not None  # no ZeroDivisionError
    assert detect_anomalies_detailed([], None, None, None) == []
