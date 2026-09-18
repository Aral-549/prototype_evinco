"""Adversarial self-audit: try to break the conclusion, then report where it breaks.

A posterior on its own is not a finding. "MV X at 71%" is conditional on a stack of
assumptions that nobody measured: that the slick drifted for 24 hours, that windage
is 3%, that Ekman deflection is 20 degrees, that the met-ocean model was right, and
that the AIS track is honest. Change any of them and the answer may change.

That is the first question a defence lawyer asks and the first question an
enforcement officer asks before detaining a ship, so the system should answer it
rather than wait to be asked. This module re-runs the attribution across the space
of *defensible* alternatives and reports:

  stability      - how often the same vessel still comes first
  breaking point - the smallest plausible change that flips the conclusion
  integrity      - whether the AIS evidence is even physically self-consistent

A conclusion that survives its own audit is worth acting on. One that holds only at
exactly the assumed drift duration is worth investigating further, and saying so is
more useful than a confident number that quietly depends on a guess.
"""
import logging
import math
from dataclasses import dataclass, field, asdict

import numpy as np

from apps.drift.engines.ensemble import EnsembleDriftEngine, EnsembleDriftInput

from .attribution import attribute, haversine_km

logger = logging.getLogger('pipeline')

# Ranges are defensible spans from the literature and from met-ocean model error,
# not arbitrary wiggle. An audit that perturbs assumptions beyond what anyone would
# defend proves nothing; the point is that every scenario here is a world a
# reasonable expert would accept.
SWEEP_RANGES = {
    'duration_scale': (0.60, 1.60),      # time adrift is inferred, never observed
    'windage_mean': (0.020, 0.040),      # accepted empirical span for surface oil
    'deflection_deg': (0.0, 30.0),       # Ekman deflection varies with sea state
    'wind_scale': (0.75, 1.25),          # typical met-ocean wind error
    'current_scale': (0.70, 1.30),       # surface current error exceeds wind error
    'capture_scale': (0.50, 2.00),       # combined ensemble + AIS positional error
}

# Merchant traffic tops out around 25 kn; container ships rarely exceed 24.
# Anything materially above this between two reports is not a ship, it is bad data.
MAX_PLAUSIBLE_SPEED_KN = 40.0
TELEPORT_KM = 50.0
TELEPORT_WINDOW_S = 300.0

# Calibrated so the three bands actually discriminate across realistic cases, not
# derived from theory. Measured against controlled fixtures: a vessel anchored at the
# release point across the whole plausible release window reaches ~0.78; one on
# station for only a few hours reaches ~0.47; two candidates favoured at different
# drift durations reach ~0.03. A 0.80 cut made "robust" unreachable even for the
# strongest case a real investigation could produce, which would have made the label
# meaningless. Because drift duration is never directly observed, most genuine cases
# land in "conditional" -- that is a true statement about maritime forensics, not a
# defect in the instrument.
ASSESSMENT_BANDS = ((0.75, 'robust'), (0.45, 'conditional'))


@dataclass
class RobustnessReport:
    stability: float
    verdict_stability: float
    posterior_min: float
    posterior_median: float
    posterior_max: float
    breaking_points: list = field(default_factory=list)
    most_influential: str = ''
    scenarios_run: int = 0
    assessment: str = 'fragile'
    narrative: list = field(default_factory=list)
    baseline_mmsi: str = ''

    def to_dict(self):
        return asdict(self)


@dataclass
class IntegrityReport:
    mmsi: str
    plausible: bool
    max_implied_speed_kn: float
    flags: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# ── AIS evidence integrity ───────────────────────────────────────

def check_track_integrity(mmsi: str, records: list) -> IntegrityReport:
    """Is this AIS track physically self-consistent?

    AIS is an unauthenticated broadcast. A transponder can be made to report any
    position, identity or speed, and the "shadow fleet" does exactly that to defeat
    attribution. None of these checks prove spoofing -- they show a track is
    physically impossible, which is grounds for review rather than a determination
    of intent. Saying that precisely matters: an accusation of falsifying AIS is a
    separate and more serious allegation than the spill itself.
    """
    flags = []
    max_speed = 0.0

    ordered = sorted(records, key=lambda r: r.timestamp)
    if len(ordered) < 2:
        return IntegrityReport(mmsi, True, 0.0, flags)

    for i in range(1, len(ordered)):
        prev, curr = ordered[i - 1], ordered[i]
        dt_s = (curr.timestamp - prev.timestamp).total_seconds()
        dist_km = haversine_km(prev.lat, prev.lon, curr.lat, curr.lon)

        if dt_s <= 0:
            if dist_km > 0.5:
                flags.append({
                    'code': 'duplicate_timestamps',
                    'severity': 0.7,
                    'detail': (
                        f'Two reports share timestamp {curr.timestamp.isoformat()} but are '
                        f'{dist_km:.1f} km apart. One vessel cannot be in two places.'
                    ),
                })
            continue

        implied_kn = (dist_km / (dt_s / 3600.0)) / 1.852
        max_speed = max(max_speed, implied_kn)

        if implied_kn > MAX_PLAUSIBLE_SPEED_KN:
            flags.append({
                'code': 'impossible_speed',
                'severity': min(1.0, implied_kn / 100.0),
                'detail': (
                    f'{implied_kn:.0f} kn implied between reports at '
                    f'{prev.timestamp.isoformat()} and {curr.timestamp.isoformat()} '
                    f'({dist_km:.1f} km in {dt_s / 60:.1f} min). No merchant vessel '
                    f'sustains this.'
                ),
            })

        if dist_km > TELEPORT_KM and dt_s < TELEPORT_WINDOW_S:
            flags.append({
                'code': 'position_teleport',
                'severity': 1.0,
                'detail': (
                    f'Position jumped {dist_km:.0f} km in {dt_s:.0f} s. This is the '
                    f'classic signature of an injected or replayed AIS position.'
                ),
            })

        if (dist_km < 0.02 and dt_s > 600
                and prev.speed_knots is not None and prev.speed_knots > 5.0):
            flags.append({
                'code': 'frozen_position_underway',
                'severity': 0.8,
                'detail': (
                    f'Reported speed {prev.speed_knots:.1f} kn for {dt_s / 60:.0f} min '
                    f'while the reported position did not change. Speed and position '
                    f'contradict each other.'
                ),
            })

    # Coarse quantisation: real GNSS fixes vary in the fourth decimal. A track
    # snapped to a coarse grid suggests synthesised rather than observed positions.
    lats = np.array([r.lat for r in ordered])
    lons = np.array([r.lon for r in ordered])
    # Advisory only, and deliberately never decisive: public AIS archives are often
    # distributed rounded to a fixed number of decimals, which produces exactly this
    # pattern on entirely genuine data. It is kept because a synthesised track shows
    # it too, but it is capped below the severity that marks a track implausible and
    # it demands a long track before firing at all.
    if len(lats) >= 20:
        residual = np.concatenate([
            np.abs(lats * 10000 - np.round(lats * 10000)),
            np.abs(lons * 10000 - np.round(lons * 10000)),
        ])
        if float(residual.mean()) < 0.002:
            flags.append({
                'code': 'coarse_quantisation',
                'severity': 0.4,
                'detail': (
                    'Every reported position lands exactly on a coarse grid. Genuine GNSS '
                    'fixes carry finer variation, though some public AIS archives are '
                    'distributed pre-rounded, so this is advisory and not on its own a '
                    'reason to doubt the track.'
                ),
            })

    # De-duplicate repeated codes, keeping the most severe instance of each.
    best = {}
    for f in flags:
        if f['code'] not in best or f['severity'] > best[f['code']]['severity']:
            best[f['code']] = f
    deduped = sorted(best.values(), key=lambda f: -f['severity'])

    return IntegrityReport(
        mmsi=mmsi,
        plausible=not any(f['severity'] >= 0.7 for f in deduped),
        max_implied_speed_kn=round(max_speed, 2),
        flags=deduped,
    )


# ── Counterfactual sweep ─────────────────────────────────────────

def _sample_scenarios(n: int, seed: int) -> list:
    """Latin-hypercube-style sample over the assumption ranges.

    Stratified rather than purely random so a modest number of scenarios still
    covers each range evenly. A clustered sample would understate fragility by
    never visiting the edges of what is defensible.
    """
    rng = np.random.default_rng(seed)
    keys = list(SWEEP_RANGES)
    out = []

    strata = {}
    for k in keys:
        lo, hi = SWEEP_RANGES[k]
        edges = np.linspace(lo, hi, n + 1)
        picks = edges[:-1] + rng.random(n) * (edges[1:] - edges[:-1])
        strata[k] = rng.permutation(picks)

    for i in range(n):
        out.append({k: float(strata[k][i]) for k in keys})
    return out


def audit_conclusion(drift_input, tracks: dict, baseline_top_mmsi: str = None,
                     n_scenarios: int = 32, seed: int = 7,
                     particles_per_scenario: int = 150,
                     base_capture_radius_km: float = 5.0,
                     prior_unknown: float = 0.25) -> RobustnessReport:
    """Re-run drift and attribution across defensible alternative assumptions."""
    if n_scenarios <= 0:
        raise ValueError(f'n_scenarios must be >= 1, got {n_scenarios}')

    engine = EnsembleDriftEngine()
    scenarios = _sample_scenarios(n_scenarios, seed)

    winners = []
    posteriors = []
    verdicts = []
    records = []

    for idx, sc in enumerate(scenarios):
        try:
            out = engine.compute(EnsembleDriftInput(
                start_lat=drift_input.start_lat,
                start_lon=drift_input.start_lon,
                detection_time=drift_input.detection_time,
                wind_speed_mps=drift_input.wind_speed_mps * sc['wind_scale'],
                wind_direction_deg=drift_input.wind_direction_deg,
                current_speed_mps=drift_input.current_speed_mps * sc['current_scale'],
                current_direction_deg=drift_input.current_direction_deg,
                duration_hours=drift_input.duration_hours * sc['duration_scale'],
                windage_mean=sc['windage_mean'],
                deflection_deg=sc['deflection_deg'],
                n_particles=particles_per_scenario,
                # Vary the seed per scenario so sampling noise is not shared across
                # the sweep, which would otherwise understate the spread.
                seed=seed + idx,
            ))

            results, unknown = attribute(
                particles=out.particles,
                tracks=tracks,
                capture_radius_km=base_capture_radius_km * sc['capture_scale'],
                prior_unknown=prior_unknown,
                origin_lat=out.origin_lat,
                origin_lon=out.origin_lon,
                origin_time=out.origin_time,
            )
        except Exception as exc:
            # A single failed scenario degrades the audit's resolution; it must not
            # take down the audit, and silently dropping it would overstate stability.
            logger.warning(f'Robustness scenario {idx} failed ({exc}); recorded as indeterminate.')
            winners.append(None)
            records.append({'scenario': sc, 'top': None, 'posterior': 0.0})
            continue

        top = results[0] if results else None
        named = (top and unknown < top.posterior)
        top_mmsi = getattr(top.vessel, 'mmsi', None) if named else None

        winners.append(top_mmsi)
        verdicts.append(top.verdict if named else 'insufficient')

        if baseline_top_mmsi:
            match = next((r for r in results
                          if getattr(r.vessel, 'mmsi', None) == baseline_top_mmsi), None)
            posteriors.append(match.posterior if match else 0.0)
        else:
            posteriors.append(unknown)

        records.append({'scenario': sc, 'top': top_mmsi,
                        'posterior': posteriors[-1]})

    stability = float(np.mean([w == baseline_top_mmsi for w in winners])) if winners else 0.0
    verdict_stability = (
        float(np.mean([v in ('strong', 'probable') for v in verdicts])) if verdicts else 0.0
    )

    p = np.array(posteriors) if posteriors else np.array([0.0])

    # ── Which assumption actually carries the conclusion? ──
    # For each swept parameter, compare its mean value in scenarios that held the
    # baseline conclusion against those that flipped it. The parameter with the
    # largest standardised separation is the one the answer depends on.
    influence = {}
    held = [r for r in records if r['top'] == baseline_top_mmsi]
    flipped = [r for r in records if r['top'] != baseline_top_mmsi]

    if held and flipped:
        for k in SWEEP_RANGES:
            a = np.array([r['scenario'][k] for r in held])
            b = np.array([r['scenario'][k] for r in flipped])
            lo, hi = SWEEP_RANGES[k]
            span = (hi - lo) or 1.0
            influence[k] = abs(float(a.mean()) - float(b.mean())) / span

    most_influential = max(influence, key=influence.get) if influence else ''

    # ── Breaking points: the flipped scenarios closest to the baseline ──
    breaking_points = []
    if flipped and most_influential:
        baseline_values = {
            'duration_scale': 1.0,
            'windage_mean': drift_input.windage_mean,
            'deflection_deg': drift_input.deflection_deg,
            'wind_scale': 1.0,
            'current_scale': 1.0,
            'capture_scale': 1.0,
        }
        base_val = baseline_values.get(most_influential, 1.0)
        span = SWEEP_RANGES[most_influential][1] - SWEEP_RANGES[most_influential][0]

        # Only report a flip as a "breaking point" if the assumption actually MOVED.
        # When a conclusion flips even at essentially the baseline assumptions, the
        # nearest flipped scenario is one with no meaningful change, which produced
        # statements of the form "if it had drifted 24 h rather than the assumed
        # 24 h". That is not a breaking point, it means the baseline itself sits on
        # a knife edge, and that is reported separately and more honestly.
        meaningful = [r for r in flipped
                      if abs(r['scenario'][most_influential] - base_val) > 0.02 * span]

        if not meaningful:
            breaking_points.append({
                'parameter': most_influential,
                'value': 'no change required',
                'baseline_value': str(base_val),
                'new_top': flipped[0]['top'] or 'no vessel named',
                'note': (
                    'The conclusion flips under assumption sets that are essentially the '
                    'baseline ones. It is not that some particular change breaks it; the '
                    'baseline finding is already on a knife edge and two candidates are '
                    'effectively tied.'
                ),
            })

        ranked = sorted(meaningful, key=lambda r: abs(
            r['scenario'][most_influential] - base_val))

        seen_values = set()
        for r in ranked:
            if len(breaking_points) >= 3:
                break
            val = r['scenario'][most_influential]
            bucket = round(val, 2)
            if bucket in seen_values:
                continue
            seen_values.add(bucket)
            if most_influential == 'duration_scale':
                note = (
                    f'If the slick had drifted for '
                    f'{drift_input.duration_hours * val:.1f} h rather than the assumed '
                    f'{drift_input.duration_hours:.1f} h, the leading candidate changes.'
                )
                shown = f'{drift_input.duration_hours * val:.1f} h'
            elif most_influential == 'windage_mean':
                note = (
                    f'At a wind drift factor of {val * 100:.1f}% rather than '
                    f'{drift_input.windage_mean * 100:.1f}%, the leading candidate changes. '
                    f'Both values are within the accepted range for surface oil.'
                )
                shown = f'{val * 100:.1f}%'
            elif most_influential == 'capture_scale':
                note = (
                    f'Widening the positional tolerance to '
                    f'{base_capture_radius_km * val:.1f} km changes the leading candidate.'
                )
                shown = f'{base_capture_radius_km * val:.1f} km'
            else:
                note = (
                    f'Varying {most_influential.replace("_", " ")} to {val:.2f} changes '
                    f'the leading candidate.'
                )
                shown = f'{val:.2f}'

            breaking_points.append({
                'parameter': most_influential,
                'value': shown,
                'baseline_value': str(baseline_values.get(most_influential, '')),
                'new_top': r['top'] or 'no vessel named',
                'note': note,
            })

    assessment = 'fragile'
    for threshold, label in ASSESSMENT_BANDS:
        if stability >= threshold:
            assessment = label
            break

    # ── Narrative ──
    narrative = []
    subject = f'MMSI {baseline_top_mmsi}' if baseline_top_mmsi else 'the no-attribution finding'

    narrative.append(
        f'The conclusion was re-tested against {len(scenarios)} alternative assumption sets, '
        f'each drawn from ranges a domain expert would accept. {subject} remained the '
        f'finding in {stability * 100:.0f}% of them.'
    )

    if assessment == 'robust':
        narrative.append(
            'The finding does not depend on any single assumption: it survives the full '
            'span of defensible drift durations, windage factors and met-ocean error.'
        )
    elif assessment == 'conditional':
        narrative.append(
            'The finding holds across most of the assumption space but not all of it. The '
            'breaking points below are within what an expert would accept, so they should '
            'be resolved before the conclusion is relied on.'
        )
    else:
        narrative.append(
            'The finding is contingent. It does not survive ordinary variation in '
            'assumptions that were never independently measured, and should be treated as '
            'a lead for investigation rather than as an attribution.'
        )

    if most_influential:
        pretty = most_influential.replace('_', ' ')
        narrative.append(
            f'The conclusion is most sensitive to {pretty}. That is the quantity to pin '
            f'down first -- an independent estimate of it would do more to settle this case '
            f'than any additional AIS data.'
        )

    if baseline_top_mmsi and len(p) > 1:
        narrative.append(
            f'Across the sweep the posterior for {subject} ranged from {p.min() * 100:.0f}% '
            f'to {p.max() * 100:.0f}% (median {float(np.median(p)) * 100:.0f}%).'
        )

    return RobustnessReport(
        stability=round(stability, 4),
        verdict_stability=round(verdict_stability, 4),
        posterior_min=round(float(p.min()), 4),
        posterior_median=round(float(np.median(p)), 4),
        posterior_max=round(float(p.max()), 4),
        breaking_points=breaking_points,
        most_influential=most_influential,
        scenarios_run=len(scenarios),
        assessment=assessment,
        narrative=narrative,
        baseline_mmsi=baseline_top_mmsi or '',
    )
