"""Generate a physically-faithful synthetic SAR calibration scene with ground truth.

Why this exists
---------------
The file shipped as `known_sar_spill.jpg`, documented as "Ground-truth SAR image
with confirmed oil slick for calibration", is not SAR imagery at all: it is a piece
of digital artwork. It passed the Layer 1 domain gate because that gate only tested
channel correlation and zero-variance blocks, both of which near-greyscale artwork
satisfies. `validate_checkpoint.py` used it for the side-by-side behavioural
comparison, so the model hot-swap gate was benchmarking checkpoints against a
drawing.

This script produces a replacement that is synthetic but statistically honest, so
the validation gate has a positive control with a KNOWN answer:

  - Multiplicative gamma speckle, the defining property of coherent radar imaging.
    An L-look intensity image has local CV ~ 1/sqrt(L); this generates 4-look.
  - A cross-swath incidence-angle brightness gradient, as a real Sentinel-1 GRD has.
  - A damped slick region: darker, and with REDUCED speckle variance, because oil
    suppresses the capillary waves that produce Bragg scattering. Getting this right
    matters -- simply painting a dark patch would not exercise the look-alike
    discriminator, which measures damping contrast and interior homogeneity.
  - A low-wind look-alike patch: equally dark, but WITHOUT reduced speckle, which is
    what a calm zone actually looks like. A good model should find the slick and
    reject this one.

Synthetic data is a substitute for, not a replacement for, a labelled Sentinel-1
scene. Anything published from this must say so. The right long-term fix is a real
scene with a verified slick from the Copernicus Open Access Hub.

Usage:  python make_calibration_scene.py
"""
import json
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
H = W = 768
LOOKS = 4
SEED = 26143  # the problem statement number, so the scene is reproducible


def main():
    rng = np.random.default_rng(SEED)
    yy, xx = np.mgrid[0:H, 0:W]

    # Underlying radar cross-section: open sea plus a cross-swath incidence gradient.
    sigma0 = 0.55 - 0.18 * (xx / W) + 0.04 * np.sin(yy / 90.0)

    # Ground truth: an elongated slick laid along a vessel track, as a discharge is.
    slick = np.zeros((H, W), bool)
    t = np.linspace(0, 1, 1400)
    cx = 120 + t * 520
    cy = 300 + 110 * np.sin(t * 2.1)
    for x0, y0 in zip(cx, cy):
        half = 13 + 7 * np.sin(x0 / 70.0)
        y1, y2 = int(y0 - half), int(y0 + half)
        slick[max(0, y1):min(H, y2), int(x0):int(x0) + 3] = True

    # A calm-wind look-alike: just as dark, but speckle is NOT damped.
    lookalike = ((xx - 560) ** 2 / 95.0 ** 2 + (yy - 600) ** 2 / 62.0 ** 2) < 1.0

    sigma0 = np.where(slick, sigma0 * 0.20, sigma0)       # oil damps Bragg scattering
    sigma0 = np.where(lookalike, sigma0 * 0.24, sigma0)   # calm zone: dark for another reason

    # Oil also reduces speckle variance; a calm zone does not.
    looks = np.where(slick, LOOKS * 4.0, LOOKS)
    speckle = rng.gamma(shape=looks, scale=1.0 / looks)

    intensity = sigma0 * speckle
    amplitude = np.sqrt(np.clip(intensity, 0, None))
    img = np.clip(amplitude / np.percentile(amplitude, 99.5), 0, 1)
    img8 = (img * 255).astype(np.uint8)

    rgb = np.stack([img8] * 3, axis=-1)
    Image.fromarray(rgb).save(os.path.join(HERE, "synthetic_sar_calibration.png"))
    Image.fromarray((slick * 255).astype(np.uint8)).save(
        os.path.join(HERE, "synthetic_sar_calibration_truth.png"))

    meta = {
        "name": "synthetic_sar_calibration",
        "kind": "synthetic",
        "seed": SEED,
        "looks": LOOKS,
        "size": [H, W],
        "slick_pixels": int(slick.sum()),
        "slick_fraction": round(float(slick.mean()), 5),
        "lookalike_pixels": int(lookalike.sum()),
        "ground_truth_mask": "synthetic_sar_calibration_truth.png",
        "caveat": (
            "Synthetic. Speckle statistics, the incidence gradient and the damping "
            "behaviour are physically faithful, but this is not a real Sentinel-1 scene "
            "and must never be cited as detection performance on real imagery. It exists "
            "so the validation gate has a positive control with a known answer."
        ),
    }
    with open(os.path.join(HERE, "synthetic_sar_calibration.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Wrote synthetic_sar_calibration.png  ({H}x{W}, {LOOKS}-look)")
    print(f"  slick pixels     : {meta['slick_pixels']} ({meta['slick_fraction']*100:.2f}%)")
    print(f"  look-alike pixels: {meta['lookalike_pixels']}")


if __name__ == "__main__":
    main()
