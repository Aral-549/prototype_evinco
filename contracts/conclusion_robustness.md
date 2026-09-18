# Contract: Conclusion Robustness & Evidence Integrity (`apps/ais/robustness.py`)

## Purpose
Attack the pipeline's own conclusion and report where it breaks.

A single posterior ("MV X at 71%") is conditional on a stack of assumptions nobody
verified: that the slick drifted for 24 hours, that windage is 3%, that Ekman
deflection is 20 degrees, that the met-ocean field was accurate, and that the AIS
track is truthful. This module re-runs the attribution across the space of
*defensible* alternatives to those assumptions and answers three questions:

1. **Stability** — across plausible assumption sets, how often is this still the
   leading vessel?
2. **Breaking point** — what is the smallest change that flips the conclusion, and
   is that change itself plausible?
3. **Integrity** — is the AIS evidence physically self-consistent, or does it show
   the signatures of spoofing or fabrication?

Hands off to: the dossier, which must present a fragile conclusion differently from
a robust one even when both carry the same headline posterior.

## Inputs
- `drift_input`: the `EnsembleDriftInput` used for the headline run
- `tracks`: `{vessel: [AISRecord]}` as used by `attribute()`
- `baseline_top_mmsi`: MMSI the headline run named, or None if it named nobody
- `n_scenarios`: int, default 32 — assumption sets to sample
- Monotonicity requirement: stability must increase with the length of time a vessel
  is demonstrably on station at the release point
- `seed`: int, default 7 — identical seed reproduces an identical audit
- `particles_per_scenario`: int, default 150 — smaller than the headline ensemble;
  the sweep measures rank stability, not the origin itself

## Swept assumptions (each sampled over a defensible range, not an arbitrary one)
| Assumption | Range | Why this range |
|---|---|---|
| `duration_hours` | 0.6x – 1.6x baseline | Time adrift is inferred, never observed |
| `windage_mean` | 0.020 – 0.040 | The accepted empirical span for surface oil |
| `deflection_deg` | 0 – 30 | Reported Ekman deflection varies with sea state |
| `wind_speed` bias | 0.75x – 1.25x | Typical met-ocean model error |
| `current_speed` bias | 0.7x – 1.3x | Surface current error is larger than wind error |
| `capture_radius_km` | 0.5x – 2.0x | Combined ensemble + AIS positional uncertainty |

## Outputs
- `RobustnessReport`:
  - `stability`: float in [0, 1] — share of scenarios naming the same vessel first
  - `verdict_stability`: float — share reaching `probable` or better
  - `posterior_min` / `posterior_median` / `posterior_max` for the baseline vessel
  - `breaking_points`: list of `{parameter, value, baseline_value, new_top, note}`
  - `most_influential`: parameter name whose variation explains the most rank churn
  - `scenarios_run`: int
  - `assessment`: `robust`, `conditional`, or `fragile`
  - `narrative`: list[str], plain-English findings for the dossier
- `IntegrityReport` (per vessel):
  - `plausible`: bool
  - `flags`: list of `{code, severity, detail}` from
    `impossible_speed`, `position_teleport`, `frozen_position_underway`,
    `duplicate_timestamps`, `coarse_quantisation`
  - `max_implied_speed_kn`: float

## Behavior cases (input → expected output)
| # | Input | Expected output | Notes |
|---|-------|------------------|-------|
| 1 | Vessel anchored at the origin across the whole plausible release window | `stability >= 0.75`, assessment `robust` | A genuinely unambiguous case must not be reported as fragile. 0.9 was unreachable: at the extremes of the swept drift duration the origin moves 30-45 km, so even an anchored vessel is legitimately outside the capture radius there. |
| 2 | Vessel matching only at exactly the baseline duration | `stability < 0.45`, assessment `fragile`, at least one breaking point naming `duration_scale` | The case this module exists to catch |
| 3 | Two vessels, one favoured only under short durations and the other under long | `breaking_points` non-empty and `most_influential == 'duration_hours'` | Must identify WHICH assumption carries the conclusion |
| 4 | Same inputs, same seed, twice | Byte-identical report | The audit is itself evidence and must reproduce |
| 5 | `baseline_top_mmsi=None` (nobody named) | Runs without error; `stability` reports how often the sweep *also* names nobody | An insufficient-evidence finding deserves auditing too |
| 6 | AIS track implying 95 kn between two pings | `plausible=False`, flag `impossible_speed` | No merchant vessel exceeds ~30 kn |
| 7 | Track with a 400 km position jump inside 60 s | flag `position_teleport` | The classic AIS spoofing signature |
| 8 | Track reporting 14 kn while the position never changes | flag `frozen_position_underway` | Reported speed contradicts reported position |
| 9 | `n_scenarios=0` | raise `ValueError` | An audit of nothing is not an audit |

## Edge cases that must be covered
- A vessel present in the baseline but absent from some swept scenarios
- Every scenario naming nobody (stability is then defined against the null finding)
- A single-ping track (no implied speed is computable; must not divide by zero)
- Sweep scenarios that raise inside the drift engine — must degrade, not abort
- Runtime: the full sweep must stay within a few seconds so it can run inline

## Explicitly out of scope
- Deciding whether to act on a fragile conclusion — that is the operator's call
- Re-detecting the slick; the sweep varies drift and attribution only
- Proving spoofing. Integrity flags show a track is physically inconsistent, which
  is grounds for review, not a determination of intent.

## Status
- [x] Drafted
- [ ] Reviewed by a human
- [ ] Implementation matches this contract
- [ ] Golden tests exist for every behavior case above
