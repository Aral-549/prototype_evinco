"""Rank checkpoints across the synthetic SAR benchmark suite.

Reports two numbers per model, and the gap between them is the point:

  raw        the segmentation head alone, at its own threshold
  effective  after Layer 2 look-alike screening, i.e. what the pipeline actually
             concludes

A head that over-detects is not necessarily a bad head for THIS system, because the
look-alike screen exists to remove exactly the calm-wind patches it flags. Judging a
checkpoint on raw precision alone would select the wrong model.

Clean-water scenes carry no slick, so Dice is undefined for them; they are scored
instead on false-positive area, which is the number that decides whether an operator
can trust an alert.

Usage:
    python ai_model/scripts/benchmark_models.py
    python ai_model/scripts/benchmark_models.py --tta
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
from apps.detection.inference import ModelManager  # noqa: E402
from apps.detection.preprocessing import load_image  # noqa: E402
from apps.detection.postprocessing import mask_to_polygons  # noqa: E402
from apps.detection.lookalike import assess_regions  # noqa: E402

BENCH = settings.CALIBRATION_DIR / 'benchmark'


def screen(prob, pred, gray, reject_below):
    """Apply Layer 2 and return the surviving mask plus keep/reject counts."""
    regions = mask_to_polygons((pred * 255).astype(np.uint8), prob_map=prob)
    if not regions:
        return np.zeros_like(pred), 0, 0
    assessments = assess_regions(gray, regions, prob_map=prob, wind_speed_mps=7.0)
    kept = np.zeros_like(pred)
    n_keep = n_rej = 0
    for r, a in zip(regions, assessments):
        if a.oil_probability >= reject_below:
            kept |= r['region_mask']
            n_keep += 1
        else:
            n_rej += 1
    return kept, n_keep, n_rej


def score(mask, truth):
    inter = int((mask & truth).sum())
    if truth.sum() == 0:
        return None
    return {
        'dice': 2 * inter / max(int(mask.sum()) + int(truth.sum()), 1),
        'iou': inter / max(int((mask | truth).sum()), 1),
        'precision': inter / max(int(mask.sum()), 1),
        'recall': inter / max(int(truth.sum()), 1),
    }


def evaluate(checkpoint, manifest, tta, reject_below):
    mm = ModelManager()
    mm.reload(checkpoint_path=str(checkpoint))

    rows, latencies = [], []
    for scene in manifest['scenes']:
        img, _ = load_image(str(BENCH / f"{scene['name']}.png"))
        truth = np.array(Image.open(BENCH / f"{scene['name']}_truth.png")) > 127
        gray = img[:, :, 0].astype(np.float32) / 255.0

        t0 = time.time()
        prob, _ = mm.predict_proba(img, tta=tta)
        latencies.append((time.time() - t0) * 1000)

        threshold = float(mm.get_model_info().get('threshold', 0.5))
        pred = prob > threshold
        kept, n_keep, n_rej = screen(prob, pred, gray, reject_below)

        rows.append({
            'scene': scene['name'],
            'has_slick': scene['has_slick'],
            'raw': score(pred, truth),
            'eff': score(kept, truth),
            'raw_fp_frac': float(pred.mean()),
            'eff_fp_frac': float(kept.mean()),
            'kept': n_keep,
            'rejected': n_rej,
        })
    return rows, float(np.mean(latencies))


def summarise(rows):
    pos = [r for r in rows if r['has_slick']]
    neg = [r for r in rows if not r['has_slick']]
    return {
        'raw_dice': float(np.mean([r['raw']['dice'] for r in pos])),
        'raw_precision': float(np.mean([r['raw']['precision'] for r in pos])),
        'raw_recall': float(np.mean([r['raw']['recall'] for r in pos])),
        'eff_dice': float(np.mean([r['eff']['dice'] for r in pos])),
        'eff_precision': float(np.mean([r['eff']['precision'] for r in pos])),
        'eff_recall': float(np.mean([r['eff']['recall'] for r in pos])),
        # On clean water, the only meaningful score is how much of the scene the
        # system wrongly calls oil.
        'clean_raw_fp': float(np.mean([r['raw_fp_frac'] for r in neg])) if neg else 0.0,
        'clean_eff_fp': float(np.mean([r['eff_fp_frac'] for r in neg])) if neg else 0.0,
        'clean_scenes_with_any_alert': sum(1 for r in neg if r['eff_fp_frac'] > 0.001),
        'n_clean': len(neg),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tta', action='store_true', help='enable 4-way flip TTA')
    ap.add_argument('--reject-below', type=float, default=None)
    ap.add_argument('--json', help='write full results to this path')
    ap.add_argument('--combiner', choices=['mean', 'max'], help='override ensemble combiner')
    ap.add_argument('--purify', type=int, help='median filter window on the input')
    args = ap.parse_args()

    reject_below = (args.reject_below if args.reject_below is not None
                    else float(getattr(settings, 'LOOKALIKE_REJECT_BELOW', 0.35)))

    if args.combiner:
        settings.MODEL_COMBINER = args.combiner
    if args.purify is not None:
        settings.MODEL_PURIFY = args.purify

    manifest = json.loads((BENCH / 'manifest.json').read_text())

    candidates = {
        'U-Net (31.0M)': settings.DEFAULT_MODEL_CHECKPOINT,
        'SegFormer-B0 (3.7M)': settings.ML_MODELS_DIR / 'best_segformer_b0' / 'best_segformer_b0.pt',
    }

    # The ensemble is evaluated by temporarily disabling it for the single-model
    # rows, so every row is measured under identical conditions.
    ensemble_paths = list(getattr(settings, 'MODEL_ENSEMBLE', []) or [])

    print(f"Benchmark: {len(manifest['scenes'])} scenes "
          f"({sum(1 for s in manifest['scenes'] if s['has_slick'])} with a slick, "
          f"{sum(1 for s in manifest['scenes'] if not s['has_slick'])} clean water)")
    print(f"TTA: {'on' if args.tta else 'off'}   Layer 2 reject below: {reject_below}   "
          f"combiner: {getattr(settings,'MODEL_COMBINER','mean')}   "
          f"purify: {getattr(settings,'MODEL_PURIFY',0) or 'off'}\n")

    results = {}
    settings.MODEL_ENSEMBLE = []          # single-model rows
    for label, path in candidates.items():
        if not os.path.exists(path):
            print(f'  [skip] {label}: {path} not present')
            continue
        rows, latency = evaluate(path, manifest, args.tta, reject_below)
        results[label] = {'rows': rows, 'latency_ms': latency, 'summary': summarise(rows)}

    if ensemble_paths:
        settings.MODEL_ENSEMBLE = ensemble_paths
        rows, latency = evaluate(settings.DEFAULT_MODEL_CHECKPOINT, manifest,
                                 args.tta, reject_below)
        results['Ensemble (both)'] = {'rows': rows, 'latency_ms': latency,
                                      'summary': summarise(rows)}

    hdr = (f"{'model':<22}{'rawDice':>9}{'rawP':>7}{'rawR':>7}"
           f"{'effDice':>9}{'effP':>7}{'effR':>7}{'cleanFP':>9}{'alerts':>8}{'ms':>8}")
    print(hdr)
    print('-' * len(hdr))
    for label, res in results.items():
        s = res['summary']
        alerts = f"{s['clean_scenes_with_any_alert']}/{s['n_clean']}"
        print(f"{label:<22}{s['raw_dice']:>9.3f}{s['raw_precision']:>7.3f}{s['raw_recall']:>7.3f}"
              f"{s['eff_dice']:>9.3f}{s['eff_precision']:>7.3f}{s['eff_recall']:>7.3f}"
              f"{s['clean_eff_fp']*100:>8.2f}%"
              f"{alerts:>8}"
              f"{res['latency_ms']:>8.0f}")

    print('\nPer-scene effective Dice:')
    names = [r['scene'] for r in next(iter(results.values()))['rows']]
    print(f"  {'scene':<22}" + ''.join(f'{l.split(chr(32))[0]:>14}' for l in results))
    for i, name in enumerate(names):
        line = f'  {name:<22}'
        for res in results.values():
            r = res['rows'][i]
            line += (f"{r['eff']['dice']:>14.3f}" if r['has_slick']
                     else f"{r['eff_fp_frac']*100:>13.2f}%")
        print(line)
    print('  (clean-water rows show false-positive area, not Dice)')

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2)
        print(f'\nFull results -> {args.json}')


if __name__ == '__main__':
    main()
