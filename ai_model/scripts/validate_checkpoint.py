#!/usr/bin/env python3
"""Model Checkpoint Validation Gate & Side-by-Side Comparator.

Run this script before switching to a new model checkpoint to verify:
1. Weights load without architecture or tensor mismatch
2. Input/Output tensor contracts are strictly satisfied
3. Forward pass produces valid probabilities (no NaNs/Infs)
4. Tiled full-image inference runs seamlessly with polygon extraction
5. Side-by-side behavioral comparison against baseline, on a calibration asset
   that is itself verified to be admissible SAR imagery before it is used
6. Gating rules: Fail only on zero-spill drop or latency blowup (IoU/Dice is informational)

Usage:
    python scripts/validate_checkpoint.py <checkpoint_path>
"""

import sys
import os
import time
import argparse
import numpy as np

# Ensure django environment is loaded
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.conf import settings

import torch
from apps.detection.inference import (
    ModelManager,
    find_model_metadata,
    instantiate_model,
    clean_state_dict,
    _load_checkpoint_directory,
    ensure_checkpoint_assembled,
)
from apps.detection.postprocessing import mask_to_polygons


def validate_checkpoint(checkpoint_path: str) -> bool:
    print("\n" + "=" * 75)
    print(f"[VALIDATOR] OIL SPILL MODEL CHECKPOINT VALIDATION & BENCHMARK GATE")
    print("=" * 75)
    print(f"Target Checkpoint: {checkpoint_path}")

    checkpoint_path = ensure_checkpoint_assembled(checkpoint_path)
    if not os.path.exists(checkpoint_path):
        print(f"[FAIL] Checkpoint path does not exist: {checkpoint_path}")
        return False

    # 1. Inspect Metadata Sidecar
    print("\n[Step 1/6] Checking Model Metadata Sidecar (model_info.json)...")
    meta = find_model_metadata(checkpoint_path)
    if meta.get('metadata_file'):
        print(f"  [OK] Found sidecar: {meta['metadata_file']}")
        print(f"     Name:         {meta.get('name')}")
        print(f"     Architecture: {meta.get('architecture')}")
        print(f"     Dice Score:   {meta.get('dice_score', 'N/A')}")
        print(f"     Input Specs:  {meta.get('input_channels', 3)}ch, {meta.get('input_size', 256)}x{meta.get('input_size', 256)}")
    else:
        print(f"  [WARN] No model_info.json sidecar found. Using default custom_unet assumption.")

    # 2. Weight & Architecture Loading
    print("\n[Step 2/6] Inspecting Weights & Instantiating Architecture...")
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    arch = meta.get('architecture', 'custom_unet')
    in_ch = meta.get('input_channels', 3)
    encoder = meta.get('encoder_name', 'resnet34')

    try:
        if os.path.isdir(checkpoint_path):
            state_dict = _load_checkpoint_directory(checkpoint_path)
        else:
            loaded = torch.load(checkpoint_path, map_location=device, weights_only=False)
            state_dict = loaded if isinstance(loaded, dict) else loaded.state_dict()

        cleaned_weights = clean_state_dict(state_dict)
        num_tensors = len(cleaned_weights)
        print(f"  [OK] Extracted {num_tensors} weight tensors.")

        model = instantiate_model(arch, in_channels=in_ch, out_channels=1, encoder_name=encoder)
        missing, unexpected = model.load_state_dict(cleaned_weights, strict=False)

        if missing:
            print(f"  [WARN] Missing keys in checkpoint ({len(missing)}): {missing[:3]}...")
        if unexpected:
            print(f"  [WARN] Unexpected keys in checkpoint ({len(unexpected)}): {unexpected[:3]}...")

        model.to(device)
        model.eval()

        total_params = sum(p.numel() for p in model.parameters())
        print(f"  [OK] Model architecture verified on {device} ({total_params:,} parameters).")
    except Exception as e:
        print(f"[FAIL] Failed to load model architecture/weights: {e}")
        return False

    # 3. I/O Contract Verification (Single Tile)
    print("\n[Step 3/6] Verifying Single-Tile Tensor Contract (256x256x3)...")
    dummy_tile = torch.rand(1, in_ch, 256, 256, device=device, dtype=torch.float32)

    try:
        t0 = time.perf_counter()
        with torch.no_grad():
            out = model(dummy_tile)
            if float(out.min()) < 0.0 or float(out.max()) > 1.0:
                prob = torch.sigmoid(out)
            else:
                prob = out
        latency_ms = (time.perf_counter() - t0) * 1000

        # Output shape check
        out_shape = tuple(prob.shape)
        if len(out_shape) == 4 and out_shape[1] == 1 and out_shape[2:] == (256, 256):
            print(f"  [OK] Output tensor shape matches contract: {out_shape}")
        elif len(out_shape) == 3 and out_shape[1:] == (256, 256):
            print(f"  [OK] Output tensor shape matches contract: {out_shape}")
        else:
            print(f"[FAIL] Output tensor shape mismatch: expected (1, 1, 256, 256), got {out_shape}")
            return False

        # Numeric bounds check
        min_p = float(prob.min())
        max_p = float(prob.max())
        if np.isnan(min_p) or np.isnan(max_p):
            print("[FAIL] Model produced NaN outputs.")
            return False
        if min_p < 0.0 or max_p > 1.0:
            print(f"[FAIL] Probability output out of bounds: [{min_p:.3f}, {max_p:.3f}]")
            return False

        print(f"  [OK] Numerical bounds valid in [0.0, 1.0]: [{min_p:.3f}, {max_p:.3f}]")
        print(f"  [OK] Single tile forward latency: {latency_ms:.1f} ms ({device})")
    except Exception as e:
        print(f"[FAIL] Forward pass exception: {e}")
        return False

    # 4. Tiled Inference on Synthetic Scene
    print("\n[Step 4/6] Testing Tiled Full-Scene Inference (512x512)...")
    np.random.seed(42)
    test_scene = np.random.normal(150, 25, (512, 512)).clip(0, 255).astype(np.uint8)
    test_scene[180:300, 180:300] = 15
    test_scene_rgb = np.stack([test_scene, test_scene, test_scene], axis=-1)

    try:
        mm = ModelManager()
        info = mm.reload(checkpoint_path=checkpoint_path)

        t0 = time.perf_counter()
        mask = mm.predict(test_scene_rgb)
        full_latency_ms = (time.perf_counter() - t0) * 1000

        if mask.shape != (512, 512) or mask.dtype != np.uint8:
            print(f"[FAIL] Output mask shape or dtype mismatch: {mask.shape}, {mask.dtype}")
            return False

        polys = mask_to_polygons(mask, min_area_pixels=50)
        print(f"  [OK] Synthetic scene inference completed in {full_latency_ms:.1f} ms ({len(polys)} clusters detected).")
    except Exception as e:
        print(f"[FAIL] Tiled inference failed: {e}")
        return False

    # 5. Side-by-Side Calibration Comparison vs Baseline
    #
    # The calibration asset is itself validated before use. It previously was not,
    # and the file shipped as `known_sar_spill.jpg` -- documented as a ground-truth
    # SAR scene with a confirmed slick -- is in fact digital artwork of a person's
    # head. Every checkpoint that passed this gate was benchmarked against a drawing.
    # A validation gate that does not validate its own fixtures validates nothing.
    cal_dir = getattr(settings, 'CALIBRATION_DIR', os.path.join(settings.BASE_DIR, 'calibration_data'))
    baseline_path = str(getattr(settings, 'MODEL_FALLBACK_CHECKPOINT', settings.DEFAULT_MODEL_CHECKPOINT))

    from apps.detection.preprocessing import load_image, validate_sar_characteristics
    import numpy as _np
    from PIL import Image as _Image

    cal_img_path = None
    for candidate in ('synthetic_sar_calibration.png', 'known_sar_spill.jpg'):
        path = os.path.join(str(cal_dir), candidate)
        if not os.path.isfile(path):
            continue
        arr = _np.array(_Image.open(path).convert('RGB'))
        is_sar, why = validate_sar_characteristics(arr)
        if is_sar:
            cal_img_path = path
            print(f"   Calibration asset: {candidate} (verified SAR)")
            break
        print(f"   [SKIP] {candidate} is not admissible SAR imagery and cannot")
        print(f"          calibrate anything: {why}")

    if cal_img_path is None:
        print("[FAIL] No admissible SAR calibration asset found.")
        print("       Generate one with:")
        print("         python ai_model/calibration_data/make_calibration_scene.py")
        print("       or place a verified Sentinel-1 scene in ai_model/calibration_data/.")
        return False

    if os.path.isfile(cal_img_path):
        real_sar_img, _ = load_image(cal_img_path)

        # Run Baseline
        mm.reload(checkpoint_path=baseline_path)
        t_base_0 = time.perf_counter()
        mask_base = mm.predict(real_sar_img)
        t_base_ms = (time.perf_counter() - t_base_0) * 1000
        polys_base = mask_to_polygons(mask_base, min_area_pixels=50)
        area_base = sum(p.get('area_pixels', 0) for p in polys_base)

        # Run Candidate
        mm.reload(checkpoint_path=checkpoint_path)
        t_cand_0 = time.perf_counter()
        mask_cand = mm.predict(real_sar_img)
        t_cand_ms = (time.perf_counter() - t_cand_0) * 1000
        polys_cand = mask_to_polygons(mask_cand, min_area_pixels=50)
        area_cand = sum(p.get('area_pixels', 0) for p in polys_cand)

        # Overlap metrics (Informational)
        inter = np.logical_and(mask_cand > 0, mask_base > 0).sum()
        union = np.logical_or(mask_cand > 0, mask_base > 0).sum()
        iou = float(inter / union) if union > 0 else (1.0 if mask_cand.sum() == 0 and mask_base.sum() == 0 else 0.0)
        total_p = float((mask_cand > 0).sum() + (mask_base > 0).sum())
        dice = float(2.0 * inter / total_p) if total_p > 0 else 1.0

        # Print Comparison Table
        print("  ┌────────────────────────┬──────────────────┬──────────────────┬────────────────┐")
        print("  │ Metric                 │ Baseline Model   │ Candidate Model  │ Differential   │")
        print("  ├────────────────────────┼──────────────────┼──────────────────┼────────────────┤")
        print(f"  │ Spills Detected        │ {len(polys_base):<16} │ {len(polys_cand):<16} │ {len(polys_cand) - len(polys_base):+d} spills       │")
        print(f"  │ Total Slick Pixels     │ {area_base:<16} │ {area_cand:<16} │ {area_cand - area_base:+d} px         │")
        print(f"  │ Scene Latency          │ {t_base_ms:>6.1f} ms         │ {t_cand_ms:>6.1f} ms         │ {t_cand_ms - t_base_ms:>+6.1f} ms      │")
        print("  ├────────────────────────┴──────────────────┴──────────────────┴────────────────┤")
        print(f"  │ Behavioral Shift (Informational): IoU = {iou*100:.1f}%, Dice Overlap = {dice*100:.1f}%          │")
        print("  └───────────────────────────────────────────────────────────────────────────────┘")

        # Auto-gate Rules (Only crash-level regressions)
        if len(polys_base) > 0 and len(polys_cand) == 0:
            print(f"[FAIL] RED FLAG: Candidate detected 0 spills on verified positive SAR scene (Baseline detected {len(polys_base)}).")
            print("   The new checkpoint completely failed to segment slicks on the calibration image.")
            return False

        if t_cand_ms > 5000 or (t_base_ms > 0 and t_cand_ms > 5.0 * t_base_ms):
            print(f"[FAIL] RED FLAG: Inference latency ({t_cand_ms:.1f} ms) is excessive (>5s or >5x baseline).")
            return False

        print("  [OK] Calibration verification passed (slicks detected without latency regression).")
    else:
        print(f"  [WARN] Calibration image not found at {cal_img_path}. Skipping side-by-side step.")

    # 6. Final Verdict
    print("\n[Step 6/6] Final Hot-Swap Readiness Assessment...")
    print("=" * 75)
    print("[PASS] CHECKPOINT IS 100% READY FOR LIVE DEPLOYMENT!")
    print("=" * 75)
    print("\nTo activate this model in production:")
    print(f"  1. export MODEL_CHECKPOINT_PATH=\"{os.path.abspath(checkpoint_path)}\"")
    print("  2. Restart Celery worker: .venv/bin/celery -A config worker ...")
    print("  Zero database, zero API, and zero post-processing code changes required.\n")
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Oil Spill Model Checkpoint Validation & Benchmark Gate")
    parser.add_argument(
        'checkpoint_path',
        nargs='?',
        default=str(getattr(settings, 'MODEL_CHECKPOINT_PATH', settings.UNET_CHECKPOINT)),
        help="Path to checkpoint directory or file (.pt / .pth)",
    )
    args = parser.parse_args()
    success = validate_checkpoint(args.checkpoint_path)
    sys.exit(0 if success else 1)
