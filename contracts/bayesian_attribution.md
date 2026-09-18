# Contract: Bayesian Vessel Attribution (`apps/ais/attribution.py`)

## Purpose
Given a drift ensemble and a set of AIS tracks, compute for each candidate vessel the
posterior probability that it released the detected slick — including an explicit
"unattributed / unknown vessel" hypothesis so the system can report *insufficient evidence*
rather than always naming a top suspect.

Replaces the ad-hoc `0.40*prox + 0.35*temporal + 0.25*behavioural` weighted sum, in which
proximity and time were evaluated independently and a vessel could score highly for being
near the origin at completely the wrong time.

## Inputs
- `particles`: list of `{lat, lon, time}` release estimates from the drift ensemble
- `tracks`: mapping `vessel -> list[AISRecord]` ordered by timestamp
- `capture_radius_km`: float, default 5.0 — a vessel counts as a candidate source for a
  given particle if its interpolated position at that particle's release time is within
  this radius
- `prior_unknown`: float in (0, 1), default 0.25 — prior mass reserved for a vessel that is
  absent from the AIS data (dark vessel, out of coverage, spoofed identity)
- `max_interpolation_gap_s`: float, default 3600 — never interpolate a position across a gap
  longer than this; the track is treated as absent instead

## Outputs
- list of `AttributionResult`, ranked by `posterior` descending:
  - `vessel`, `posterior` (float, all posteriors + `unknown_posterior` sum to 1.0 ± 1e-9)
  - `spatiotemporal_likelihood`: fraction of particles captured by this vessel
  - `behavioural_factor`: float ≥ 1.0, multiplicative evidence from anomalies
  - `cpa_km`, `cpa_time`: true closest point of approach from the interpolated track,
    not the nearest discrete ping
  - `anomalies`: list of `{code, severity, detail}`
  - `verdict`: `strong`, `probable`, `weak`, or `insufficient`
  - `explanation`: list[str]

## Behavior cases (input → expected output)
| # | Input | Expected output | Notes |
|---|-------|------------------|-------|
| 1 | One vessel sitting on the origin at the origin time; no others | `posterior > 0.70`, verdict `strong` | Clear-cut attribution |
| 2 | One vessel 1 km from origin but 40 h before origin time | `spatiotemporal_likelihood ≈ 0`, verdict `insufficient` | The precise failure of the old weighted sum |
| 3 | Two identical vessels equidistant, same time | Posteriors equal within 1e-6 | No tie-breaking by MMSI or insertion order |
| 4 | No vessel within `capture_radius_km` of any particle | All posteriors < `prior_unknown`; `unknown_posterior` is the largest hypothesis; every verdict `insufficient` | Must refuse to accuse |
| 5 | Two vessels equally close; one has a 90-min AIS gap over the origin | The vessel with the gap ranks first | Behaviour breaks ties, never creates attribution on its own |
| 6 | Vessel with pings 2 h apart straddling the origin | CPA is interpolated between pings and is < the nearest-ping distance | Fixes discrete-ping CPA error |
| 7 | Vessel whose only pings are 3 h apart (> `max_interpolation_gap_s`) | Not interpolated across the gap; contributes no likelihood from that interval | Never invent a position |
| 8 | Empty `particles` | raise `ValueError` | Attribution without an ensemble is meaningless |

## Edge cases that must be covered
- A vessel with exactly one AIS record (no interpolation possible)
- Two records with an identical timestamp (zero-duration segment, no division by zero)
- A track crossing the antimeridian between two pings
- Particle times outside the entire AIS coverage window
- All vessels captured by every particle (likelihoods saturate; posteriors must still normalise)

## Explicitly out of scope
- Ingesting AIS data (`apps/ais/ingest.py`)
- Producing the drift ensemble (`apps/drift/engines/ensemble.py`)
- The legacy `score_vessels` weighted ranking, which is retained for backward compatibility

## Status
- [x] Drafted
- [ ] Reviewed by a human
- [ ] Implementation matches this contract
- [ ] Golden tests exist for every behavior case above
