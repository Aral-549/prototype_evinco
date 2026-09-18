# Contract: Monte Carlo Drift Ensemble (`apps/drift/engines/ensemble.py`)

## Purpose
Reconstruct the probability distribution over an oil slick's release point and release
time by advecting N stochastic particles backward through a time-varying met-ocean field.
Replaces the single deterministic trajectory and its fabricated
`origin_uncertainty_km = 2.0 + 0.5 * duration` with an uncertainty derived from the
ensemble's own spread.

Hands off to: `apps.ais.attribution` (which consumes the ensemble members directly, not
just the mean origin) and the map layer (confidence contours).

## Inputs
- `EnsembleDriftInput` extends `DriftInput` with:
  - `n_particles`: int, default 500, range [1, 20000]
  - `seed`: int, default 42 — identical seed + identical inputs must give identical output
  - `wind_speed_sigma_frac`: float, default 0.20 (relative 1-sigma on wind speed)
  - `wind_dir_sigma_deg`: float, default 15.0
  - `current_speed_sigma_frac`: float, default 0.30
  - `current_dir_sigma_deg`: float, default 20.0
  - `windage_mean` / `windage_sigma`: float, default 0.030 / 0.005 (wind drift factor α)
  - `deflection_deg`: float, default 20.0 — Coriolis/Ekman deflection of the wind-driven
    component; applied clockwise (to the right of the wind) in the Northern Hemisphere and
    counter-clockwise in the Southern, selected by the sign of `start_lat`
  - `diffusion_m2_s`: float, default 5.0 — horizontal turbulent diffusivity
  - `metocean_provider`: optional callable `(lat, lon, datetime) -> dict`; when supplied the
    field is re-sampled each step instead of held constant

## Outputs
- `EnsembleDriftOutput` extends `DriftOutput` with:
  - `origin_lat` / `origin_lon`: ensemble mean release position
  - `origin_uncertainty_km`: radius containing 50% of particles (not a formula)
  - `radius_50_km`, `radius_90_km`: float
  - `confidence_polygon_50`, `confidence_polygon_90`: GeoJSON Polygon, convex hull of the
    corresponding particle quantile set
  - `particles`: list of `{lat, lon, time, windage}` — one release estimate per member
  - `evaporated_fraction`: float in [0, 1], oil lost to evaporation over the hindcast
  - `weathering_warning`: str, non-empty when the hindcast exceeds plausible slick lifetime
  - `hindcast_trajectory`: mean trajectory, oldest-first (unchanged contract)

## Behavior cases (input → expected output)
| # | Input | Expected output | Notes |
|---|-------|------------------|-------|
| 1 | All sigmas = 0, diffusion = 0, deflection = 0, n=1 | Origin equals `LagrangianDriftEngine` output to 1e-4 deg (~11 m) | Reduces to the existing, tested physics. The residual is not error: the ensemble integrates with RK2 and the deterministic engine with forward Euler, so they evaluate cos(lat) at slightly different points. Measured residual 5.3e-6 deg (0.6 m) over a 24 h hindcast. |
| 2 | Same input, same seed, run twice | Byte-identical origin, radii and particle list | Court-grade reproducibility |
| 3 | Same input, different seed | Origin differs, but by less than `radius_90_km` | Sampling noise must not dominate |
| 4 | `duration_hours` 12 → 48, sigmas fixed | `radius_50_km` strictly increases | Uncertainty must grow with hindcast length |
| 5 | `n_particles` 100 → 5000 | `radius_50_km` converges (change < 15%) | Estimator stability |
| 6 | `start_lat = +19` vs `start_lat = -19`, identical wind | Wind-driven component deflects to opposite sides | Hemisphere-correct Coriolis |
| 7 | Wind 12 m/s, duration 36 h | `evaporated_fraction > 0.3`, `weathering_warning` non-empty | Light fractions gone; attribution weaker |
| 8 | `n_particles = 0` | raise `ValueError` | Never return an empty ensemble silently |

## Edge cases that must be covered
- Hindcast crossing the ±180° antimeridian (longitude must wrap, not run to ±540)
- Start latitude within 0.5° of a pole (cos(lat) → 0 must not produce infinite longitude step)
- `metocean_provider` raising an exception mid-trajectory → fall back to the static field for
  that step and record the degradation in the output, never abort the run
- Zero wind and zero current (particles spread by diffusion only)

## Explicitly out of scope
- Fetching met-ocean data (`apps/drift/metocean.py`)
- Shoreline interaction / beaching (documented limitation, future OpenDrift engine)
- Vessel scoring (`apps/ais/attribution.py`)

## Status
- [x] Drafted
- [ ] Reviewed by a human
- [ ] Implementation matches this contract
- [ ] Golden tests exist for every behavior case above
