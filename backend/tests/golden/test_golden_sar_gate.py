"""Golden: Layer 1 SAR domain gate.

Covers the BUGLOG entry "Shipped calibration image is not SAR and the domain gate
passed it". The decisive property is speckle: SAR is a coherent imaging system, so
every resolution cell carries multiplicative noise and the local coefficient of
variation stays near 1/sqrt(L) everywhere, including inside dark regions. No
incoherent image -- photo, render, painting, screenshot -- has that property.

Positive controls are generated from the speckle model rather than captured from a
previous run, so they remain valid ground truth independently of this codebase.
"""
import io

import numpy as np
import pytest
from PIL import Image
from scipy import ndimage

from apps.detection.preprocessing import validate_sar_characteristics, speckle_statistics

H = W = 400


def backscatter_field(h=H, w=W):
    """Smooth radar cross-section with a cross-swath incidence gradient."""
    yy, xx = np.mgrid[0:h, 0:w]
    return 0.5 + 0.2 * np.sin(xx / 60.0) + 0.15 * np.cos(yy / 80.0)


def synthetic_sar(looks=4, seed=0, h=H, w=W):
    """L-look gamma-speckled SAR amplitude as a uint8 RGB array."""
    rng = np.random.default_rng(seed)
    sar = backscatter_field(h, w) * rng.gamma(shape=looks, scale=1.0 / looks, size=(h, w))
    a = (np.clip(sar / sar.max(), 0, 1) * 255).astype(np.uint8)
    return np.stack([a] * 3, axis=-1)


# ── Positive controls: every one of these MUST pass ──────────────────────────

@pytest.mark.parametrize("looks", [1, 2, 4, 16, 64])
def test_case1_speckled_sar_accepted_at_every_look_count(looks):
    """Single-look through heavily multilooked SAR all remain admissible."""
    ok, reason = validate_sar_characteristics(synthetic_sar(looks=looks))
    assert ok, f"{looks}-look SAR was rejected: {reason}"


def test_case2_despeckled_sar_still_accepted():
    """Operational products are often speckle-filtered; that must not reject them."""
    rng = np.random.default_rng(1)
    sar = backscatter_field() * rng.gamma(4.0, 0.25, (H, W))
    filtered = ndimage.uniform_filter(sar, 3)
    a = (np.clip(filtered / filtered.max(), 0, 1) * 255).astype(np.uint8)
    ok, reason = validate_sar_characteristics(np.stack([a] * 3, -1))
    assert ok, f"despeckled SAR was rejected: {reason}"


def test_case3_jpeg_compressed_sar_still_accepted():
    """A SAR export round-tripped through lossy JPEG remains admissible."""
    buf = io.BytesIO()
    Image.fromarray(synthetic_sar(looks=4, seed=2)).save(buf, "JPEG", quality=60)
    buf.seek(0)
    ok, reason = validate_sar_characteristics(np.array(Image.open(buf).convert("RGB")))
    assert ok, f"JPEG-compressed SAR was rejected: {reason}"


def test_case4_dark_slick_region_does_not_trigger_rejection():
    """A scene containing a large dark slick is still SAR: dark regions are speckled too."""
    rng = np.random.default_rng(3)
    field = backscatter_field()
    field[120:280, 80:330] *= 0.2
    sar = field * rng.gamma(4.0, 0.25, (H, W))
    a = (np.clip(sar / sar.max(), 0, 1) * 255).astype(np.uint8)
    ok, reason = validate_sar_characteristics(np.stack([a] * 3, -1))
    assert ok, f"a SAR scene containing a slick was rejected: {reason}"


# ── Negative controls: every one of these MUST be rejected ───────────────────

def test_case5_shipped_calibration_artwork_is_rejected():
    """The regression itself.

    `ai_model/calibration_data/known_sar_spill.jpg` is documented as a ground-truth
    SAR scene with a confirmed slick. It is digital artwork of a person's head. It
    passed the original gate because that gate tested only channel correlation and
    zero-variance blocks, and near-greyscale artwork satisfies both. The model
    hot-swap validation used this file for its behavioural comparison, so every
    checkpoint was being benchmarked against a drawing.
    """
    from django.conf import settings

    path = settings.CALIBRATION_DIR / "known_sar_spill.jpg"
    if not path.exists():
        pytest.skip("legacy calibration artwork no longer present")

    arr = np.array(Image.open(path).convert("RGB"))
    ok, reason = validate_sar_characteristics(arr)

    assert not ok, "the artwork shipped as a SAR calibration image was accepted as SAR"
    assert "speckle" in reason.lower()

    stats = speckle_statistics(arr.mean(axis=2))
    assert stats["median_cv"] < 0.18
    assert stats["smooth_fraction"] > 0.15


def test_case6_smooth_gradient_rejected():
    """A rendered gradient has no speckle anywhere."""
    yy, xx = np.mgrid[0:H, 0:W]
    grad = ((xx + yy) / (H + W) * 255).astype(np.uint8)
    ok, reason = validate_sar_characteristics(np.stack([grad] * 3, -1))
    assert not ok
    assert "speckle" in reason.lower()


def test_case7_blurred_image_rejected():
    """Blurring destroys speckle; the result is no longer a coherent radar image."""
    rng = np.random.default_rng(4)
    blurred = ndimage.gaussian_filter(rng.normal(120, 30, (H, W)), 8)
    a = np.clip(blurred, 0, 255).astype(np.uint8)
    ok, _ = validate_sar_characteristics(np.stack([a] * 3, -1))
    assert not ok


def test_case8_colour_photo_still_rejected():
    """The original channel-decorrelation path must keep working."""
    optical = np.zeros((H, W, 3), np.uint8)
    optical[:, :, 0] = 200
    optical[:, :, 1] = 90
    optical[:, :, 2] = 40
    ok, reason = validate_sar_characteristics(optical)
    assert not ok
    assert "decorrelation" in reason.lower() or "speckle" in reason.lower()


# ── The replacement calibration asset ────────────────────────────────────────

def test_case9_replacement_calibration_scene_is_admissible_sar():
    """The generated calibration scene must itself pass the gate it calibrates."""
    from django.conf import settings

    path = settings.CALIBRATION_DIR / "synthetic_sar_calibration.png"
    if not path.exists():
        pytest.skip("run ai_model/calibration_data/make_calibration_scene.py first")

    arr = np.array(Image.open(path).convert("RGB"))
    ok, reason = validate_sar_characteristics(arr)
    assert ok, f"the replacement calibration scene fails the SAR gate: {reason}"

    stats = speckle_statistics(arr.mean(axis=2))
    assert stats["median_cv"] > 0.18
    assert stats["smooth_fraction"] < 0.15


def test_case10_replacement_scene_has_ground_truth():
    """A calibration asset without a known answer cannot calibrate anything."""
    import json
    from django.conf import settings

    meta_path = settings.CALIBRATION_DIR / "synthetic_sar_calibration.json"
    truth_path = settings.CALIBRATION_DIR / "synthetic_sar_calibration_truth.png"
    if not meta_path.exists():
        pytest.skip("run ai_model/calibration_data/make_calibration_scene.py first")

    meta = json.loads(meta_path.read_text())
    assert truth_path.exists()
    assert meta["slick_pixels"] > 0
    assert meta["lookalike_pixels"] > 0
    # It must declare that it is synthetic; citing it as real performance would be
    # a misrepresentation.
    assert meta["kind"] == "synthetic"
    assert "synthetic" in meta["caveat"].lower()

    truth = np.array(Image.open(truth_path)) > 127
    assert int(truth.sum()) == meta["slick_pixels"]
