# Contract: Look-Alike Discrimination (`apps/detection/lookalike.py`)

## Purpose
Assign each candidate dark region from the U-Net a calibrated probability that it is
genuine mineral oil rather than a SAR "look-alike" (low-wind calm patch, biogenic/algal
slick, rain cell, upwelling, grease ice). Returns a per-region score plus a human-readable
per-feature breakdown for the evidentiary dossier.

Hands off to: `postprocessing.pixels_to_geo` (geometry/area) and `pipeline.orchestrator`
(gating). This module does NOT decide whether to discard a region; it only scores.

## Inputs
- `gray`: `np.ndarray (H, W)` float32, SAR backscatter proxy normalised to [0, 1]
- `region_mask`: `np.ndarray (H, W)` bool, True inside the candidate region
- `prob_map`: `np.ndarray (H, W)` float32 in [0, 1], U-Net posterior
- `wind_speed_mps`: `float | None`, 10 m wind at the scene. None = unknown, gate disabled.

## Outputs
- `LookAlikeAssessment` dataclass:
  - `oil_probability`: float in [0, 1]
  - `verdict`: one of `probable_oil`, `ambiguous`, `probable_lookalike`
  - `features`: dict of named float features (each in [0, 1] after scaling)
  - `contributions`: dict of named float log-odds contributions, sums to the final logit
  - `notes`: list[str] plain-English explanation lines

## Behavior cases (input → expected output)
| # | Input | Expected output | Notes |
|---|-------|------------------|-------|
| 1 | Dark, sharply bounded, homogeneous, elongated region; wind 7 m/s | `oil_probability > 0.65`, verdict `probable_oil` | Textbook ship-discharge slick |
| 2 | Same geometry, wind 1.5 m/s | `oil_probability` strictly lower than case 1; verdict `probable_lookalike` or `ambiguous` | Calm sea cannot sustain contrast; classic false positive |
| 3 | Same geometry, wind 16 m/s | `oil_probability` strictly lower than case 1 | High wind disperses slicks; detection implausible |
| 4 | Region whose mean intensity ≈ surrounding background (damping ≈ 0) | `oil_probability < 0.35` | No backscatter damping ⇒ not oil |
| 5 | Region with diffuse edges and high interior variance | lower score than a sharp, smooth region, all else equal | Biogenic / wind-shadow signature |
| 6 | `wind_speed_mps=None` | Score computed from image features only; `notes` records that the wind gate was skipped | Never fabricate a wind value |
| 7 | Any valid input | `sum(contributions.values())` equals the pre-sigmoid logit within 1e-9 | Explanation must be faithful, not decorative |

## Edge cases that must be covered
- Region touching the image border (background annulus is clipped, not wrapped)
- Region covering >90% of the scene (no valid background to compare against)
- Region of exactly 1 pixel (degenerate perimeter/area shape metric)
- All-constant image (zero variance → no division by zero)
- `prob_map` and `gray` shape mismatch → raise `ValueError`, never silently broadcast

## Explicitly out of scope
- Deciding the final detection threshold (orchestrator's job)
- Geographic projection or area in km² (`postprocessing.py`)
- Estimating spill volume (`postprocessing.estimate_spill_volume`)

## Status
- [x] Drafted
- [ ] Reviewed by a human
- [ ] Implementation matches this contract
- [ ] Golden tests exist for every behavior case above
