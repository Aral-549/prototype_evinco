"""Layer 2 safeguard: physics-informed discrimination of oil from SAR look-alikes.

A U-Net trained on oil-spill masks learns "dark region on water". That is not a
sufficient definition of oil. The dominant false-positive sources in operational
SAR oil monitoring all produce dark patches too:

  - low-wind / calm zones   (no capillary waves to backscatter at all)
  - biogenic / algal slicks (natural surfactants, also damp capillary waves)
  - rain cells and downbursts
  - upwelling, current shear, wind shadows behind land or platforms
  - grease ice

This module does not ask "is it dark?" but "does it damp the sea surface the way
mineral oil damps it, in wind conditions where oil could both persist and be
visible?" Each feature is a documented physical discriminator, combined in a
transparent logistic model whose per-feature log-odds contributions are returned
alongside the score, so that the dossier can state *why* a region was accepted or
rejected rather than producing an unexplainable number.

Calibration status: the feature set and their directions are grounded in the
published SAR oil-spill literature, but the logistic weights below are expert
priors, not values fitted to a labelled look-alike corpus. They are deliberately
kept in one table (`WEIGHTS`) so that fitting them on real data is a drop-in
change. Anything presented to an authority must carry that caveat.
"""
import logging
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

logger = logging.getLogger('pipeline')


# Logistic weights, in log-odds. Positive => evidence FOR mineral oil.
# Each feature is scaled to [0, 1] before weighting (see _scale docstrings).
WEIGHTS = {
    'bias': -1.20,
    # Darkness is NECESSARY for a slick but nowhere near sufficient: a calm zone is
    # exactly as dark. Weighted at 3.40 it saturated for both and drowned the
    # features that actually discriminate, so a calm-zone decoy scored 0.99
    # "probable oil". Its real evidential value is asymmetric -- its ABSENCE rules
    # oil out, its presence says little -- so it is weighted modestly here and the
    # discrimination is carried by speckle damping and shape.
    'damping_contrast': 1.80,
    'edge_sharpness': 1.60,     # oil has a defined boundary; calm zones fade out
    'interior_homogeneity': 3.00,  # speckle damping: the real oil-vs-calm discriminator
    'shape_elongation': 1.40,   # ship discharges are linear, drawn out along track
    'wind_plausibility': 3.00,  # applied as a penalty only, see below
    'model_confidence': 1.40,   # the U-Net's own posterior, not discarded
}

# Features whose evidential value is *conditional on there being a wind-roughened
# sea to damp in the first place*. On a glassy sea (wind below the ~3 m/s Bragg
# threshold) a dark, sharply bounded patch is exactly what the calm zone itself
# looks like, so these measurements stop discriminating oil from not-oil and their
# contribution is scaled down by the wind plausibility. Wind is therefore a GATE on
# the backscatter argument, not another independent vote alongside it -- treating it
# as merely additive let a textbook-looking slick at 1.5 m/s still score 0.98.
WIND_GATED_FEATURES = ('damping_contrast', 'edge_sharpness', 'interior_homogeneity')

VERDICT_THRESHOLDS = (0.35, 0.65)  # < lower => lookalike, > upper => oil

# The reported probability is clamped away from 0 and 1. These weights are expert
# priors rather than values fitted to a labelled look-alike corpus, so the model is
# not calibrated well enough to justify asserting certainty about anything. Saying
# "99%" where the evidence supports "very likely" is the kind of over-claim that
# discredits an evidentiary tool the first time it is wrong.
PROBABILITY_CLAMP = (0.01, 0.99)


@dataclass
class LookAlikeAssessment:
    """Per-region oil-vs-lookalike judgement with a faithful explanation."""
    oil_probability: float
    verdict: str
    features: dict = field(default_factory=dict)
    contributions: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'oil_probability': round(self.oil_probability, 4),
            'verdict': self.verdict,
            'features': {k: round(v, 4) for k, v in self.features.items()},
            'contributions': {k: round(v, 4) for k, v in self.contributions.items()},
            'notes': list(self.notes),
        }


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def wind_plausibility(wind_speed_mps: float, low: float = 3.0, high: float = 12.0) -> float:
    """Plausibility in [0, 1] that a slick is both visible and persistent at this wind.

    Below `low` the sea is glassy: there are no capillary waves for oil to damp, so
    a dark patch is far more likely to be the calm zone itself than a slick. Above
    `high`, wind-driven mixing disperses surface oil into the water column and
    re-roughens the surface, so a persistent detectable slick is unlikely. The
    plateau between the two is where SAR oil detection actually works.
    """
    if wind_speed_mps is None:
        return 0.5  # uninformative: do not push the score either way
    w = float(wind_speed_mps)
    if w <= 0.0:
        return 0.0
    if w < low:
        return max(0.0, w / low) ** 2      # sharp penalty as the sea goes glassy
    if w <= high:
        return 1.0
    # taper off over the next 8 m/s rather than cutting to zero
    return max(0.0, 1.0 - (w - high) / 8.0)


def _background_annulus(region_mask: np.ndarray, dilation_px: int = 25) -> np.ndarray:
    """Ring of sea surrounding the region, used as the local backscatter reference.

    Local rather than global, because SAR scenes have a strong incidence-angle
    brightness gradient across the swath; comparing a near-range region against a
    far-range mean would manufacture contrast that is not there.
    """
    dilated = ndimage.binary_dilation(region_mask, iterations=dilation_px)
    return dilated & ~region_mask


def assess_region(gray: np.ndarray, region_mask: np.ndarray, prob_map: np.ndarray = None,
                  wind_speed_mps: float = None, shape_complexity: float = None
                  ) -> LookAlikeAssessment:
    """Score one candidate region as mineral oil versus look-alike.

    Args:
        gray: (H, W) float32 in [0, 1], SAR backscatter proxy.
        region_mask: (H, W) bool, True inside the candidate.
        prob_map: (H, W) float32 U-Net posterior, optional.
        wind_speed_mps: 10 m wind at the scene; None disables the wind gate.
        shape_complexity: isoperimetric ratio from postprocessing, optional.

    Returns:
        LookAlikeAssessment whose `contributions` sum exactly to the logit.
    """
    if gray.ndim != 2:
        raise ValueError(f'gray must be 2-D, got shape {gray.shape}')
    if region_mask.shape != gray.shape:
        raise ValueError(
            f'region_mask shape {region_mask.shape} does not match gray shape {gray.shape}'
        )
    if prob_map is not None and prob_map.shape != gray.shape:
        raise ValueError(
            f'prob_map shape {prob_map.shape} does not match gray shape {gray.shape}'
        )

    notes = []
    inside = gray[region_mask]
    n_inside = int(inside.size)

    if n_inside == 0:
        return LookAlikeAssessment(0.0, 'probable_lookalike', {}, {},
                                   ['Empty region mask; nothing to assess.'])

    annulus = _background_annulus(region_mask)
    outside = gray[annulus]

    coverage = n_inside / float(gray.size)
    if outside.size < max(32, n_inside * 0.05):
        # Region fills most of the scene, or hugs the border: no honest local reference.
        notes.append(
            f'Local background sample too small ({outside.size} px) for a reliable contrast '
            f'measurement; region covers {coverage * 100:.1f}% of the scene. '
            f'Damping contrast treated as uninformative.'
        )
        damping_contrast = 0.5
        edge_sharpness = 0.5
    else:
        mean_in = float(inside.mean())
        mean_out = float(outside.mean())

        # ── Feature 1: damping contrast ───────────────────────────
        # Mineral oil suppresses Bragg capillary waves strongly: typically 5-15 dB
        # below the surrounding sea. Expressed as a relative drop so it is
        # independent of absolute scene brightness and gain settings.
        rel_drop = (mean_out - mean_in) / max(mean_out, 1e-6)
        # 0 -> no damping (not oil); 0.5+ -> strong damping (very oil-like)
        damping_contrast = float(np.clip(rel_drop / 0.5, 0.0, 1.0))

        # ── Feature 2: edge sharpness ─────────────────────────────
        # Oil has a surface-tension-defined boundary and produces a steep
        # backscatter step. A low-wind calm zone grades smoothly into the
        # surrounding sea because the wind field itself grades smoothly.
        boundary = ndimage.binary_dilation(region_mask, iterations=2) & \
            ~ndimage.binary_erosion(region_mask, iterations=2)
        if boundary.sum() > 0:
            grad_y, grad_x = np.gradient(gray.astype(np.float32))
            grad_mag = np.hypot(grad_x, grad_y)
            edge_strength = float(grad_mag[boundary].mean())
            scene_grad = float(grad_mag.mean()) + 1e-6
            # Ratio of boundary gradient to typical scene gradient. 3x is sharp.
            edge_sharpness = float(np.clip((edge_strength / scene_grad) / 3.0, 0.0, 1.0))
        else:
            edge_sharpness = 0.5
            notes.append('Region too small to measure an edge gradient.')

    # ── Feature 3: speckle damping (interior homogeneity) ─────────
    # THE discriminator against a calm-wind look-alike, and the one that has to be
    # measured correctly or it silently measures darkness twice.
    #
    # SAR speckle is MULTIPLICATIVE: the local standard deviation scales with the
    # local mean. So any dark region has a low absolute standard deviation, and an
    # interior-flatness feature built on raw std rewards a calm zone exactly as much
    # as it rewards oil. Measured that way on a controlled scene, a true slick and a
    # calm-zone decoy both scored 0.99 "probable oil".
    #
    # Dividing by the mean removes the brightness dependence. Oil genuinely
    # suppresses the Bragg-scattering texture, so its coefficient of variation falls
    # well below the surrounding sea; a calm zone is darker but its speckle
    # statistics are untouched. On that same scene the CV ratio was 0.56 for the
    # slick against 0.99 for the decoy -- a clean separation where raw std had none.
    cv_in = float(inside.std()) / max(float(inside.mean()), 1e-6)
    if outside.size >= 32:
        cv_out = float(outside.std()) / max(float(outside.mean()), 1e-6)
    else:
        cv_out = float(gray.std()) / max(float(gray.mean()), 1e-6)

    cv_ratio = cv_in / max(cv_out, 1e-6)
    # ratio 1.0 (speckle untouched, i.e. a calm zone) -> 0
    # ratio 0.4 (strongly damped, i.e. oil)           -> 1
    interior_homogeneity = float(np.clip((1.0 - cv_ratio) / 0.6, 0.0, 1.0))

    # ── Feature 4: shape elongation ───────────────────────────────
    # An operational discharge is laid down along the vessel's track, giving a
    # long, thin slick. Calm zones and rain cells are compact blobs. The
    # isoperimetric ratio is 1.0 for a circle and grows with elongation.
    if shape_complexity is None:
        shape_elongation = 0.5
        notes.append('Shape complexity unavailable; elongation treated as uninformative.')
    else:
        # 1.0 (circle) -> 0.0 ; 4.0+ (markedly elongated/ragged) -> 1.0
        shape_elongation = float(np.clip((shape_complexity - 1.0) / 3.0, 0.0, 1.0))

    # ── Feature 5: wind plausibility ──────────────────────────────
    wind_plaus = wind_plausibility(wind_speed_mps)
    if wind_speed_mps is None:
        notes.append(
            'No met-ocean wind available for this scene; the low-wind/high-wind gate was '
            'skipped and contributes neutrally. A wind value would materially sharpen this '
            'assessment.'
        )
    elif wind_speed_mps < 3.0:
        notes.append(
            f'Wind {wind_speed_mps:.1f} m/s is below the ~3 m/s Bragg threshold. The sea '
            f'surface is too smooth to backscatter, so a dark patch here is more consistent '
            f'with a calm zone than with a mineral oil slick.'
        )
    elif wind_speed_mps > 12.0:
        notes.append(
            f'Wind {wind_speed_mps:.1f} m/s exceeds ~12 m/s. Wind-driven mixing disperses '
            f'surface oil into the water column, so a persistent detectable slick is '
            f'physically unlikely at this wind speed.'
        )

    # ── Feature 6: the model's own posterior ──────────────────────
    if prob_map is not None:
        model_conf = float(prob_map[region_mask].mean())
    else:
        model_conf = 0.5
        notes.append('No posterior map supplied; model confidence treated as uninformative.')

    features = {
        'damping_contrast': damping_contrast,
        'edge_sharpness': edge_sharpness,
        'interior_homogeneity': interior_homogeneity,
        'shape_elongation': shape_elongation,
        'wind_plausibility': wind_plaus,
        'model_confidence': model_conf,
    }

    # ── Transparent logistic combination ──────────────────────────
    # Features are centred at 0.5 so that an uninformative feature contributes
    # exactly zero log-odds rather than silently biasing the result.
    contributions = {'bias': WEIGHTS['bias']}
    for name, value in features.items():
        if name == 'wind_plausibility':
            # Wind enters as a PENALTY, never as support. Workable wind does not
            # argue that a dark patch is oil; it merely fails to argue against it.
            # Centring this feature at 0.5 like the others made "the wind was fine"
            # worth +3 log-odds on its own, which was enough to carry a calm-zone
            # decoy to "probable oil". Unknown wind contributes exactly zero rather
            # than a penalty -- we do not punish a scene for missing met-ocean data.
            contributions[name] = (
                0.0 if wind_speed_mps is None
                else WEIGHTS[name] * (value - 1.0) * 2.0
            )
            continue

        contribution = WEIGHTS[name] * (value - 0.5) * 2.0
        if name in WIND_GATED_FEATURES and contribution > 0:
            # Only positive (pro-oil) backscatter evidence is gated. Evidence
            # *against* oil -- no damping, diffuse edges -- stays at full strength
            # regardless of wind: those readings rule oil out on their own.
            contribution *= wind_plaus
        contributions[name] = contribution

    logit = sum(contributions.values())
    probability = min(max(_sigmoid(logit), PROBABILITY_CLAMP[0]), PROBABILITY_CLAMP[1])

    low, high = VERDICT_THRESHOLDS
    if probability < low:
        verdict = 'probable_lookalike'
    elif probability > high:
        verdict = 'probable_oil'
    else:
        verdict = 'ambiguous'

    # Name the single strongest piece of evidence in each direction.
    ranked = sorted(
        ((k, v) for k, v in contributions.items() if k != 'bias'),
        key=lambda kv: kv[1],
    )
    if ranked:
        notes.append(
            f'Strongest evidence for oil: {ranked[-1][0]} ({ranked[-1][1]:+.2f} log-odds). '
            f'Strongest evidence against: {ranked[0][0]} ({ranked[0][1]:+.2f} log-odds).'
        )

    return LookAlikeAssessment(
        oil_probability=probability,
        verdict=verdict,
        features=features,
        contributions=contributions,
        notes=notes,
    )


def assess_regions(gray: np.ndarray, regions: list, prob_map: np.ndarray = None,
                   wind_speed_mps: float = None) -> list:
    """Assess every region produced by `mask_to_polygons`.

    Each region dict must carry a `region_mask`. Returns a parallel list of
    LookAlikeAssessment. Regions without a mask receive an uninformative
    assessment rather than being silently dropped.
    """
    out = []
    for region in regions:
        mask = region.get('region_mask')
        if mask is None:
            out.append(LookAlikeAssessment(
                0.5, 'ambiguous', {}, {},
                ['No pixel mask retained for this region; look-alike screening skipped.'],
            ))
            continue
        out.append(assess_region(
            gray=gray,
            region_mask=mask,
            prob_map=prob_map,
            wind_speed_mps=wind_speed_mps,
            shape_complexity=region.get('shape_complexity'),
        ))
    return out
