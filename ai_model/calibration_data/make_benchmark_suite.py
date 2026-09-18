"""Generate a multi-scene SAR benchmark with ground truth, for model selection.

Choosing a production model from a single scene is not evidence, it is an anecdote.
This builds a suite that varies the things that actually change a detector's
behaviour, so a comparison between checkpoints means something:

  - slick geometry      linear discharge, patchy fragments, a compact blob
  - speckle             1-look (noisy) through 16-look (multilooked)
  - damping contrast    faint slicks near the detection limit, and obvious ones
  - look-alikes         calm-wind patches that are just as dark but NOT speckle-damped
  - clean water         scenes with NO slick at all, to measure the false-positive rate

That last category matters most and is the one usually missing: a detector that
never sees a negative scene has never been asked how often it invents a spill.

Synthetic, and honestly so. Speckle statistics, the incidence gradient and the
damping physics are faithful, but this is not Sentinel-1 data and no figure measured
here should be quoted as real-world performance. It exists to rank checkpoints
against each other under identical, controlled conditions.
"""
import json
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'benchmark')
SIZE = 512


def base_field(rng, size=SIZE):
    """Open sea with a cross-swath incidence-angle gradient."""
    yy, xx = np.mgrid[0:size, 0:size]
    return 0.55 - 0.16 * (xx / size) + 0.04 * np.sin(yy / 70.0)


def linear_slick(size, rng, width=11, amp=90):
    m = np.zeros((size, size), bool)
    t = np.linspace(0, 1, 1600)
    cx = 60 + t * (size - 130)
    cy = size * 0.45 + amp * np.sin(t * 2.3 + rng.random())
    for x0, y0 in zip(cx, cy):
        h = width + 5 * np.sin(x0 / 60.0)
        m[max(0, int(y0 - h)):min(size, int(y0 + h)), int(x0):int(x0) + 3] = True
    return m


def patchy_slick(size, rng):
    m = np.zeros((size, size), bool)
    for _ in range(5):
        cx, cy = rng.integers(90, size - 90, 2)
        rx, ry = rng.integers(22, 55), rng.integers(12, 30)
        yy, xx = np.mgrid[0:size, 0:size]
        m |= (((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2) < 1.0
    return m


def blob_slick(size, rng):
    cx, cy = rng.integers(150, size - 150, 2)
    yy, xx = np.mgrid[0:size, 0:size]
    return (((xx - cx) / 70.0) ** 2 + ((yy - cy) / 58.0) ** 2) < 1.0


def ellipse(size, rng, scale=1.0):
    cx, cy = rng.integers(110, size - 110, 2)
    yy, xx = np.mgrid[0:size, 0:size]
    return (((xx - cx) / (62 * scale)) ** 2 + ((yy - cy) / (44 * scale)) ** 2) < 1.0


def render(rng, slick, lookalike, looks, damp, size=SIZE):
    """Compose a scene. Oil damps mean AND speckle; a calm zone damps only the mean."""
    sigma0 = base_field(rng, size)
    sigma0 = np.where(slick, sigma0 * damp, sigma0)
    if lookalike is not None:
        sigma0 = np.where(lookalike, sigma0 * damp, sigma0)

    look_map = np.full((size, size), float(looks))
    look_map = np.where(slick, looks * 8.0, look_map)   # oil suppresses texture
    amp = np.sqrt(sigma0 * rng.gamma(shape=look_map, scale=1.0 / look_map))
    img = np.clip(amp / np.percentile(amp, 99.5), 0, 1)
    return (img * 255).astype(np.uint8)


SCENES = [
    # name,                geometry,      looks, damping, look-alike scale
    ('linear_clear',       'linear',      4,  0.20, 1.0),
    ('linear_faint',       'linear',      4,  0.45, 1.0),
    ('linear_noisy',       'linear',      1,  0.22, 1.0),
    ('linear_multilook',   'linear',     16,  0.20, 1.0),
    ('patchy_clear',       'patchy',      4,  0.22, 1.2),
    ('patchy_faint',       'patchy',      4,  0.48, 1.0),
    ('blob_clear',         'blob',        4,  0.20, 1.4),
    ('blob_noisy',         'blob',        2,  0.24, 1.0),
    ('clean_water_calm',   'none',        4,  0.22, 1.6),
    ('clean_water_rough',  'none',        1,  0.30, 1.2),
    ('clean_water_plain',  'none',        8,  1.00, None),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = []

    for idx, (name, geom, looks, damp, la_scale) in enumerate(SCENES):
        rng = np.random.default_rng(26143 + idx * 17)

        if geom == 'linear':
            slick = linear_slick(SIZE, rng)
        elif geom == 'patchy':
            slick = patchy_slick(SIZE, rng)
        elif geom == 'blob':
            slick = blob_slick(SIZE, rng)
        else:
            slick = np.zeros((SIZE, SIZE), bool)

        la = ellipse(SIZE, rng, la_scale) if la_scale else None
        if la is not None:
            la = la & ~slick

        img = render(rng, slick, la, looks, damp)

        Image.fromarray(np.stack([img] * 3, -1)).save(os.path.join(OUT, f'{name}.png'))
        Image.fromarray((slick * 255).astype(np.uint8)).save(
            os.path.join(OUT, f'{name}_truth.png'))

        manifest.append({
            'name': name,
            'geometry': geom,
            'looks': looks,
            'damping': damp,
            'has_slick': bool(slick.any()),
            'slick_pixels': int(slick.sum()),
            'lookalike_pixels': int(la.sum()) if la is not None else 0,
            'slick_fraction': round(float(slick.mean()), 5),
        })

    with open(os.path.join(OUT, 'manifest.json'), 'w') as f:
        json.dump({
            'suite': 'synthetic_sar_benchmark',
            'version': '1.0.0',
            'size': SIZE,
            'seed_base': 26143,
            'scenes': manifest,
            'caveat': (
                'Synthetic. Speckle statistics, the incidence gradient and the damping '
                'physics are faithful; this is not Sentinel-1 data. Use it to RANK '
                'checkpoints under identical conditions, never to quote absolute '
                'real-world performance.'
            ),
        }, f, indent=2)

    n_pos = sum(1 for m in manifest if m['has_slick'])
    print(f'Wrote {len(manifest)} scenes to {OUT}')
    print(f'  {n_pos} with a slick, {len(manifest) - n_pos} clean water (false-positive controls)')


if __name__ == '__main__':
    main()
