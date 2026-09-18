"""Bayesian vessel attribution against a drift ensemble.

The previous scorer computed

    composite = 0.40 * proximity + 0.35 * temporal + 0.25 * behavioural

where `proximity` came from the minimum distance over all of a vessel's pings and
`temporal` from the minimum time offset over all of them. Those two minima need
not come from the same ping, so the formula rewards "was near the origin at some
point" and "was around at some point" independently. A tanker that passed 1 km
from the reconstructed origin forty hours before the release scored almost as
well as one that sat on the origin at the release time. On a busy lane like the
approaches to Mumbai or the Gulf of Kutch that is the difference between naming
the polluter and naming whoever happened to transit that week.

This module instead asks the question the court will ask: given everything the
drift ensemble says about where and when the oil was released, how probable is it
that THIS vessel released it?

Method
------
The drift ensemble supplies N particles, each a self-consistent hypothesis
(release position, release time). For each vessel we interpolate its AIS track to
each particle's release time and test whether it was within `capture_radius_km`
of that particle's release position. The fraction of particles a vessel captures
is its spatio-temporal likelihood -- an estimate of P(evidence | this vessel did
it) that is joint in space and time by construction, because each particle fixes
both at once.

Anomalous behaviour enters as a multiplicative likelihood ratio, never as an
additive score. Switching off a transponder is not by itself evidence that a
vessel spilled oil; it is evidence that raises the odds for a vessel already
placed at the scene. A vessel the ensemble never places at the scene has a
likelihood of zero, and multiplying zero by any behavioural factor leaves zero.

An explicit "unknown vessel" hypothesis holds prior mass for a dark vessel, a
gap in AIS coverage, or a spoofed identity. When no tracked vessel fits, that
hypothesis wins and the system reports insufficient evidence rather than
promoting the least-bad candidate to prime suspect.
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import timedelta

logger = logging.getLogger('pipeline')

EARTH_R_KM = 6371.0

# Severity-weighted likelihood ratios. A ratio of 1.0 means the behaviour carries
# no evidential weight. These are expert priors, not fitted values; they are
# collected here so they can be replaced with figures estimated from adjudicated
# cases without touching the inference code.
ANOMALY_LIKELIHOOD_RATIOS = {
    'ais_gap_short': 1.15,      # 30-45 min silence
    'ais_gap_long': 1.60,       # > 45 min silence near the release point
    'dark_vessel_gap': 2.10,    # > 45 min silence while within 25 km of the origin
    'speed_drop': 1.35,         # abrupt deceleration, consistent with slowing to discharge
    'loitering': 1.45,          # low-speed milling in one place
    'course_deviation': 1.20,   # departure from a steady transit heading
}

VERDICT_BANDS = (
    (0.60, 'strong'),
    (0.35, 'probable'),
    (0.15, 'weak'),
)


@dataclass
class Anomaly:
    code: str
    severity: float          # 0-1, how pronounced this instance is
    detail: str
    likelihood_ratio: float = 1.0

    def to_dict(self):
        return {
            'code': self.code,
            'severity': round(self.severity, 3),
            'detail': self.detail,
            'likelihood_ratio': round(self.likelihood_ratio, 3),
        }


@dataclass
class AttributionResult:
    vessel: object
    posterior: float
    spatiotemporal_likelihood: float
    behavioural_factor: float
    cpa_km: float
    cpa_time: object
    anomalies: list = field(default_factory=list)
    verdict: str = 'insufficient'
    explanation: list = field(default_factory=list)
    rank: int = 0

    def to_dict(self):
        return {
            'mmsi': getattr(self.vessel, 'mmsi', None),
            'name': getattr(self.vessel, 'name', None),
            'rank': self.rank,
            'posterior': round(self.posterior, 4),
            'spatiotemporal_likelihood': round(self.spatiotemporal_likelihood, 4),
            'behavioural_factor': round(self.behavioural_factor, 3),
            'cpa_km': round(self.cpa_km, 3) if self.cpa_km is not None else None,
            'cpa_time': self.cpa_time.isoformat() if self.cpa_time else None,
            'anomalies': [a.to_dict() for a in self.anomalies],
            'verdict': self.verdict,
            'explanation': list(self.explanation),
        }


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2.0 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def interpolate_position(records: list, target_time, max_gap_s: float = 3600.0):
    """Position of a vessel at `target_time`, linearly interpolated between pings.

    Returns (lat, lon) or None when the target falls outside the track or inside a
    gap longer than `max_gap_s`. Never extrapolates beyond the first or last ping,
    and never interpolates across a long silence -- a vessel that went dark for
    three hours could be anywhere, and inventing a position for it would
    manufacture exactly the evidence this system exists to weigh.

    BUGLOG: the previous scorer used the nearest discrete ping instead. At a
    typical 10-minute AIS reporting interval a vessel making 15 kn moves 4.6 km
    between pings, so the nearest-ping distance overstates the true closest
    approach by up to half that.
    """
    if not records:
        return None
    if len(records) == 1:
        rec = records[0]
        if abs((rec.timestamp - target_time).total_seconds()) <= max_gap_s:
            return (rec.lat, rec.lon)
        return None

    if target_time < records[0].timestamp or target_time > records[-1].timestamp:
        return None

    for i in range(1, len(records)):
        prev, curr = records[i - 1], records[i]
        if prev.timestamp <= target_time <= curr.timestamp:
            span = (curr.timestamp - prev.timestamp).total_seconds()
            if span > max_gap_s:
                return None
            if span <= 0:
                return (prev.lat, prev.lon)
            f = (target_time - prev.timestamp).total_seconds() / span
            lat = prev.lat + f * (curr.lat - prev.lat)
            # Interpolate along the shortest arc so a track crossing the
            # antimeridian does not sweep the long way round the globe.
            dlon = ((curr.lon - prev.lon + 180.0) % 360.0) - 180.0
            lon = ((prev.lon + f * dlon + 180.0) % 360.0) - 180.0
            return (lat, lon)
    return None


def closest_point_of_approach(records: list, origin_lat: float, origin_lon: float,
                              origin_time, window_hours: float = 48.0,
                              samples_per_segment: int = 12,
                              max_gap_s: float = 3600.0):
    """True closest approach to the origin, by subsampling each track segment.

    Returns (distance_km, time) or (None, None) if the track never comes within
    the time window.
    """
    if not records:
        return (None, None)

    best_d, best_t = None, None
    lo = origin_time - timedelta(hours=window_hours)
    hi = origin_time + timedelta(hours=window_hours)

    for i in range(len(records)):
        rec = records[i]
        if lo <= rec.timestamp <= hi:
            d = haversine_km(origin_lat, origin_lon, rec.lat, rec.lon)
            if best_d is None or d < best_d:
                best_d, best_t = d, rec.timestamp

        if i == 0:
            continue
        prev = records[i - 1]
        span = (rec.timestamp - prev.timestamp).total_seconds()
        if span <= 0 or span > max_gap_s:
            continue
        if rec.timestamp < lo or prev.timestamp > hi:
            continue

        for k in range(1, samples_per_segment):
            f = k / samples_per_segment
            t = prev.timestamp + timedelta(seconds=span * f)
            if not (lo <= t <= hi):
                continue
            lat = prev.lat + f * (rec.lat - prev.lat)
            dlon = ((rec.lon - prev.lon + 180.0) % 360.0) - 180.0
            lon = ((prev.lon + f * dlon + 180.0) % 360.0) - 180.0
            d = haversine_km(origin_lat, origin_lon, lat, lon)
            if best_d is None or d < best_d:
                best_d, best_t = d, t

    return (best_d, best_t)


def detect_anomalies_detailed(records: list, origin_lat: float = None,
                              origin_lon: float = None, origin_time=None) -> list:
    """Severity-graded behavioural anomalies along a track.

    Unlike the legacy boolean detector, each finding carries how pronounced it is
    and a likelihood ratio, so that a 12-hour transponder blackout over the
    release point is not weighed the same as a 31-minute reporting gap.
    """
    anomalies = []
    if not records or len(records) < 2:
        return anomalies

    longest_gap_s = 0.0
    longest_gap_at = None
    for i in range(1, len(records)):
        prev, curr = records[i - 1], records[i]
        dt = (curr.timestamp - prev.timestamp).total_seconds()
        if dt > longest_gap_s:
            longest_gap_s = dt
            longest_gap_at = (prev, curr)

        if 0 < dt <= 600 and prev.speed_knots is not None and curr.speed_knots is not None:
            drop = prev.speed_knots - curr.speed_knots
            if drop > 5.0:
                severity = min(1.0, drop / 15.0)
                anomalies.append(Anomaly(
                    'speed_drop', severity,
                    f'Speed fell {drop:.1f} kn (from {prev.speed_knots:.1f} to '
                    f'{curr.speed_knots:.1f}) in {dt / 60:.0f} min at '
                    f'{curr.timestamp.isoformat()}.',
                    1.0 + (ANOMALY_LIKELIHOOD_RATIOS['speed_drop'] - 1.0) * severity,
                ))

    if longest_gap_s > 1800:
        minutes = longest_gap_s / 60.0
        near_origin = False
        if origin_lat is not None and longest_gap_at is not None:
            gap_mid_lat = (longest_gap_at[0].lat + longest_gap_at[1].lat) / 2.0
            gap_mid_lon = (longest_gap_at[0].lon + longest_gap_at[1].lon) / 2.0
            near_origin = haversine_km(origin_lat, origin_lon, gap_mid_lat, gap_mid_lon) <= 25.0

        if near_origin and minutes > 45:
            code = 'dark_vessel_gap'
            detail = (
                f'Transponder silent for {minutes:.0f} min while within 25 km of the '
                f'reconstructed release point.'
            )
        elif minutes > 45:
            code, detail = 'ais_gap_long', f'Transponder silent for {minutes:.0f} min.'
        else:
            code, detail = 'ais_gap_short', f'Transponder silent for {minutes:.0f} min.'

        severity = min(1.0, minutes / 180.0)
        anomalies.append(Anomaly(
            code, severity, detail,
            1.0 + (ANOMALY_LIKELIHOOD_RATIOS[code] - 1.0) * max(severity, 0.35),
        ))

    # Loitering: a single pass over the track, unlike the previous O(n^2) scan.
    if len(records) >= 3:
        anchor = 0
        for i in range(1, len(records)):
            d = haversine_km(records[anchor].lat, records[anchor].lon,
                             records[i].lat, records[i].lon)
            if d > 2.0:
                anchor = i
                continue
            dwell_s = (records[i].timestamp - records[anchor].timestamp).total_seconds()
            if dwell_s > 3600:
                severity = min(1.0, dwell_s / 21600.0)
                anomalies.append(Anomaly(
                    'loitering', severity,
                    f'Remained within a 2 km radius for {dwell_s / 3600:.1f} h from '
                    f'{records[anchor].timestamp.isoformat()}.',
                    1.0 + (ANOMALY_LIKELIHOOD_RATIOS['loitering'] - 1.0) * severity,
                ))
                break

    return anomalies


def _ensemble_spread_km(parsed: list, centre_lat: float, centre_lon: float) -> float:
    """RMS distance of the release hypotheses from their centroid, in km.

    Used as the radius of the region the true source could plausibly occupy, so the
    unknown-vessel hypothesis can be expressed on the same scale as the tracked ones.
    """
    if not parsed:
        return 0.0
    sq = sum(haversine_km(centre_lat, centre_lon, lat, lon) ** 2
             for lat, lon, _ in parsed)
    return math.sqrt(sq / len(parsed))


def attribute(particles: list, tracks: dict, capture_radius_km: float = 5.0,
              prior_unknown: float = 0.25, max_interpolation_gap_s: float = 3600.0,
              origin_lat: float = None, origin_lon: float = None,
              origin_time=None) -> tuple:
    """Posterior probability that each vessel released the detected slick.

    Args:
        particles: [{lat, lon, time}, ...] release hypotheses from the ensemble.
            `time` may be a datetime or an ISO-8601 string.
        tracks: {vessel: [AISRecord sorted by timestamp]}.
        capture_radius_km: a vessel counts as a source for a particle when it was
            within this distance at that particle's release time.
        prior_unknown: prior mass held by the "vessel not in this AIS data"
            hypothesis -- dark vessels, coverage gaps, spoofed identities.

    Returns:
        (results, unknown_posterior). `results` is ranked by posterior descending,
        and all posteriors plus `unknown_posterior` sum to 1.
    """
    if not particles:
        raise ValueError('Cannot attribute without a drift ensemble: particles is empty.')
    if not 0.0 < prior_unknown < 1.0:
        raise ValueError(f'prior_unknown must be in (0, 1), got {prior_unknown}')

    from datetime import datetime as _dt
    parsed = []
    for p in particles:
        t = p['time']
        if isinstance(t, str):
            t = _dt.fromisoformat(t)
        parsed.append((p['lat'], p['lon'], t))

    n_particles = len(parsed)

    if origin_lat is None:
        origin_lat = sum(p[0] for p in parsed) / n_particles
    if origin_lon is None:
        origin_lon = sum(p[1] for p in parsed) / n_particles
    if origin_time is None:
        origin_time = parsed[n_particles // 2][2]

    # Positional-uncertainty scale of the capture kernel, shared by the vessel
    # likelihoods and the unknown-vessel reference so the two stay comparable.
    sigma_ref = max(capture_radius_km / 2.0, 1e-6)

    raw = []
    for vessel, records in tracks.items():
        records = sorted(records, key=lambda r: r.timestamp)

        # Soft capture. A hard disc cannot tell a vessel sitting exactly on the
        # release point from one 4.9 km away -- both score 1.0 -- which throws away
        # the sharpest discriminator available on a crowded lane. The radius really
        # represents combined positional uncertainty (ensemble spread plus AIS fix
        # and interpolation error), which is Gaussian rather than a step, so each
        # particle contributes a weight that decays with distance. The hard radius
        # is retained as a 3-sigma cutoff so distant traffic still costs nothing.
        sigma = sigma_ref
        weight_sum = 0.0
        captured = 0
        for plat, plon, ptime in parsed:
            pos = interpolate_position(records, ptime, max_interpolation_gap_s)
            if pos is None:
                continue
            d = haversine_km(plat, plon, pos[0], pos[1])
            if d > 3.0 * sigma:
                continue
            captured += 1
            weight_sum += math.exp(-0.5 * (d / sigma) ** 2)

        likelihood = weight_sum / float(n_particles)

        anomalies = detect_anomalies_detailed(records, origin_lat, origin_lon, origin_time)
        behavioural = 1.0
        for a in anomalies:
            behavioural *= a.likelihood_ratio

        cpa_km, cpa_time = closest_point_of_approach(
            records, origin_lat, origin_lon, origin_time,
            max_gap_s=max_interpolation_gap_s)

        raw.append({
            'vessel': vessel,
            'likelihood': likelihood,
            'behavioural': behavioural,
            'anomalies': anomalies,
            'cpa_km': cpa_km,
            'cpa_time': cpa_time,
            'captured': captured,
        })

    # ── Bayesian normalisation over vessels + the unknown-vessel hypothesis ──
    # Prior WEIGHTS, normalised at the end -- deliberately not a fixed mass split
    # across however many vessels the query happened to return. Dividing
    # (1 - prior_unknown) by the observed vessel count made the verdict depend on
    # traffic density rather than on evidence: an identical perfect match scored
    # 0.93 ("strong") against no other traffic and 0.06 ("insufficient") with 199
    # irrelevant vessels elsewhere in the window, because each vessel's prior had
    # shrunk 200-fold. A busy lane near Mumbai routinely has 100+ vessels in a 48 h
    # window, so on real AIS data that scheme would have refused to attribute
    # anything. Vessels the ensemble cannot place contribute a likelihood of zero
    # and therefore now change nothing at all.
    prior_vessel = 1.0 - prior_unknown

    # The unknown vessel is by definition one we cannot place, so its likelihood is a
    # reference level rather than something measured. It must however be on the SAME
    # SCALE as the tracked vessels' likelihoods, and a fixed constant is not: a
    # tracked vessel's likelihood is a capture fraction that necessarily shrinks as
    # the drift ensemble spreads out, so against a constant the unknown hypothesis
    # would win automatically on any long hindcast -- not because the evidence
    # favoured a dark vessel, but because two unrelated scales were being compared.
    #
    # The scale-consistent reference is the capture a vessel would achieve by chance
    # alone: an untracked vessel is somewhere in the search area, so its expected
    # kernel weight is the kernel's effective area over the ensemble's. A tracked
    # vessel then has to beat coincidence, which is the question actually being asked.
    kernel_area_km2 = 2.0 * math.pi * sigma_ref * sigma_ref
    spread_km = _ensemble_spread_km(parsed, origin_lat, origin_lon)
    search_area_km2 = math.pi * max(spread_km, sigma_ref) ** 2
    unknown_likelihood = min(1.0, kernel_area_km2 / max(search_area_km2, 1e-9))

    evidence = prior_unknown * unknown_likelihood
    for r in raw:
        evidence += prior_vessel * r['likelihood'] * r['behavioural']

    if evidence <= 0:
        unknown_posterior = 1.0
        posteriors = [0.0] * len(raw)
    else:
        unknown_posterior = (prior_unknown * unknown_likelihood) / evidence
        posteriors = [
            (prior_vessel * r['likelihood'] * r['behavioural']) / evidence for r in raw
        ]

    results = []
    for r, post in zip(raw, posteriors):
        verdict = 'insufficient'
        for threshold, label in VERDICT_BANDS:
            if post >= threshold:
                verdict = label
                break

        explanation = []
        if r['likelihood'] == 0.0:
            explanation.append(
                'This vessel could not be placed within '
                f'{capture_radius_km:.0f} km of any of the {n_particles} reconstructed '
                'release hypotheses at the corresponding release time. No amount of '
                'anomalous behaviour can substitute for that.'
            )
        else:
            explanation.append(
                f"Placed within {capture_radius_km:.0f} km of the release point at the "
                f"release time in {r['captured']} of {n_particles} ensemble members "
                f"({r['likelihood'] * 100:.1f}% of the drift hypotheses)."
            )
        if r['cpa_km'] is not None:
            explanation.append(
                f"Closest approach to the mean reconstructed origin: {r['cpa_km']:.2f} km "
                f"at {r['cpa_time'].isoformat()} (interpolated between AIS reports, not "
                f"the nearest report alone)."
            )
        if r['anomalies']:
            explanation.append(
                'Behavioural evidence raises the odds by a factor of '
                f"{r['behavioural']:.2f}: "
                + '; '.join(a.detail for a in r['anomalies'])
            )
        else:
            explanation.append('No behavioural anomalies detected on this track.')

        results.append(AttributionResult(
            vessel=r['vessel'],
            posterior=post,
            spatiotemporal_likelihood=r['likelihood'],
            behavioural_factor=r['behavioural'],
            cpa_km=r['cpa_km'],
            cpa_time=r['cpa_time'],
            anomalies=r['anomalies'],
            verdict=verdict,
            explanation=explanation,
        ))

    results.sort(key=lambda x: (-x.posterior, str(getattr(x.vessel, 'mmsi', ''))))
    for i, res in enumerate(results):
        res.rank = i + 1

    return results, unknown_posterior


def summarise(results: list, unknown_posterior: float) -> dict:
    """Case-level conclusion, phrased for an operator rather than a developer."""
    if not results or unknown_posterior >= max((r.posterior for r in results), default=0.0):
        return {
            'conclusion': 'insufficient_evidence',
            'unknown_posterior': round(unknown_posterior, 4),
            'headline': (
                'No vessel in the available AIS data can be placed at the reconstructed '
                'release point at the reconstructed release time. The most probable '
                f'explanation ({unknown_posterior * 100:.0f}%) is a source outside this '
                'dataset: a vessel with its transponder off, outside receiver coverage, or '
                'broadcasting a spoofed identity. This case should be escalated for dark-'
                'vessel review, not attributed to the highest-ranked track below.'
            ),
        }

    top = results[0]
    return {
        'conclusion': top.verdict,
        'unknown_posterior': round(unknown_posterior, 4),
        'headline': (
            f"{getattr(top.vessel, 'name', None) or 'Unnamed vessel'} "
            f"(MMSI {getattr(top.vessel, 'mmsi', 'unknown')}) is the most probable source at "
            f"{top.posterior * 100:.0f}% posterior probability, on {top.verdict} evidence. "
            f"The probability that the true source is absent from this AIS data is "
            f"{unknown_posterior * 100:.0f}%."
        ),
    }
