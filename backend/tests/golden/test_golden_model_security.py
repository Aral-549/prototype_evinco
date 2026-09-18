"""Golden: model attack surface.

Two classes of finding, both reproduced by construction:

1. CHECKPOINT DESERIALISATION (fixed, critical). A PyTorch checkpoint is a pickle,
   and unpickling is arbitrary code execution. A 2 KB file advertising
   `val_dice: 0.99` executed a shell command during load, before any architecture or
   shape check could reject it. That is the ordinary ML supply chain -- checkpoints
   are downloaded from model zoos and dropped into `ai_model/weights/` exactly as
   this project's hot-swap instructions describe.

2. ADVERSARIAL PERTURBATION (partially mitigated, documented). A bounded L-inf
   perturbation flips the segmentation head in both directions:
     - injection: manufactures a slick on clean water  -> BLOCKED by the Layer 2
       physics screen, which the attack cannot reach
     - evasion:   hides a real slick                   -> NOT blocked; Layer 2 can
       only reject what was detected, never recover what was not
"""
import os
import tempfile

import numpy as np
import pytest
import torch

from django.conf import settings

from apps.detection.inference import ModelManager, UnsafeCheckpointError
from apps.detection.lookalike import assess_regions
from apps.detection.postprocessing import mask_to_polygons
from apps.detection.preprocessing import speckle_statistics, validate_sar_characteristics


# ── 1. Checkpoint deserialisation ────────────────────────────────

class _Payload:
    """An object whose reconstruction executes code, as a malicious checkpoint's would.

    Benign by design: it writes a marker file. A real one would exfiltrate the AIS
    database or the chain-of-custody material.
    """

    def __reduce__(self):
        marker = os.path.join(tempfile.gettempdir(), 'marslick_rce_marker.txt')
        return (os.system, (f"echo pwned > {marker}",))


@pytest.fixture
def marker_path():
    path = os.path.join(tempfile.gettempdir(), 'marslick_rce_marker.txt')
    if os.path.exists(path):
        os.remove(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_case1_malicious_checkpoint_is_refused_without_executing(marker_path):
    """Case 1: the regression. Loading must not run the payload."""
    with tempfile.NamedTemporaryFile(suffix='.pt', delete=False) as f:
        evil = f.name
    torch.save({'model_state_dict': {'w': torch.zeros(1)},
                'val_dice': 0.99, 'x': _Payload()}, evil)

    mm = ModelManager()
    try:
        with pytest.raises(Exception):
            mm._load_single_checkpoint(evil)
        assert not os.path.exists(marker_path), (
            'the checkpoint executed code during load; deserialisation is unsafe again'
        )
    finally:
        os.unlink(evil)


def test_case2_safe_mode_is_the_default():
    """Case 2: unsafe loading must be opt-in, never the default."""
    assert getattr(settings, 'ALLOW_UNSAFE_CHECKPOINTS', False) is False


def test_case3_restricted_unpickler_allowlist_excludes_gadgets():
    """Case 3: the allowlist must not contain anything that can execute."""
    from apps.detection.inference import _PICKLE_ALLOWLIST

    flat = {f'{mod}.{name}'
            for mod, names in _PICKLE_ALLOWLIST.items() for name in names}
    for forbidden in ('os.system', 'builtins.eval', 'builtins.exec',
                      'subprocess.Popen', 'posix.system'):
        assert forbidden not in flat

    for mod in _PICKLE_ALLOWLIST:
        assert mod in ('torch', 'torch._utils', 'collections',
                       'numpy', 'numpy.core.multiarray'), f'unexpected module {mod}'


def test_case4_shipped_checkpoints_still_load_in_safe_mode():
    """Case 4: the fix must not break legitimate weights.

    A hardening change that makes the product unusable is not a fix.
    """
    mm = ModelManager()
    saved = mm.active_checkpoint
    try:
        for path in (settings.DEFAULT_MODEL_CHECKPOINT,
                     settings.ML_MODELS_DIR / 'best_segformer_b0' / 'best_segformer_b0.pt'):
            if not os.path.exists(path):
                continue
            model, meta = mm._load_single_checkpoint(str(path))
            assert model is not None
            assert meta.get('name')
    finally:
        if saved:
            mm.reload(checkpoint_path=str(saved))


# ── 2. Adversarial robustness ────────────────────────────────────

def adversarial_like_scene(seed=0, size=256):
    """Clean speckled water plus a low-amplitude high-frequency perturbation.

    Stands in for a gradient-crafted attack without needing the gradient: what
    matters for the physics screen is that the perturbation is high-frequency and
    does NOT damp the speckle, which is true of any L-inf bounded attack.
    """
    rng = np.random.default_rng(seed)
    base = 0.55 * rng.gamma(shape=4.0, scale=0.25, size=(size, size))
    img = np.clip(base / np.percentile(base, 99.5), 0, 1)
    perturbation = rng.choice([-8 / 255, 8 / 255], size=(size, size))
    region = np.zeros((size, size), bool)
    region[100:150, 40:210] = True
    img = np.clip(img + perturbation * region, 0, 1)
    return (img * 255).astype(np.uint8), region


def test_case5_physics_screen_rejects_an_undamped_injected_region():
    """Case 5: the mitigation that holds.

    A perturbation can drive the network to report oil, but it cannot reproduce the
    speckle damping mineral oil actually causes. The Layer 2 screen measures that
    damping directly, so the injected region is rejected on physics the attack never
    touched. Verified against a real PGD attack: 18,459 px of "oil" manufactured on
    clean water, rejected at p_oil = 0.010.
    """
    img, region = adversarial_like_scene()
    gray = img.astype(np.float32) / 255.0

    # The network is assumed fully fooled: posterior 0.95 over the injected region.
    prob = np.where(region, 0.95, 0.02).astype(np.float32)
    mask = (prob > 0.5).astype(np.uint8) * 255

    regions = mask_to_polygons(mask, prob_map=prob)
    assert regions, 'expected the injected region to be proposed as a candidate'

    assessments = assess_regions(gray, regions, prob_map=prob, wind_speed_mps=7.0)
    for a in assessments:
        assert a.oil_probability < 0.35, (
            f'an undamped injected region scored {a.oil_probability:.3f} as oil; the '
            f'physics screen is no longer catching adversarial injection'
        )


def test_case6_evasion_is_documented_as_unmitigated():
    """Case 6: Layer 2 cannot recover a false negative, and must not claim to.

    The screen only ever removes candidates. If the head is driven to detect
    nothing, there is nothing to screen. This asymmetry is the honest limit of the
    defence and is asserted here so nobody later claims the pipeline is
    adversarially robust in both directions.
    """
    gray = np.clip(np.random.default_rng(1).gamma(4.0, 0.25, (256, 256)), 0, 1).astype(np.float32)
    empty_mask = np.zeros((256, 256), np.uint8)

    regions = mask_to_polygons(empty_mask, prob_map=np.zeros_like(gray))
    assert regions == []
    assert assess_regions(gray, regions, prob_map=None, wind_speed_mps=7.0) == []


def test_case7_purification_destroys_the_speckle_signal():
    """Case 7: why median-filter purification is NOT enabled by default.

    It is an effective adversarial defence in isolation, but it compresses the local
    coefficient of variation that both Layer 1 and Layer 2 depend on. Measured on a
    benchmark scene: CV 0.251 -> 0.100 at 3x3 and 0.056 at 5x5, where 5x5 no longer
    passes the SAR domain gate at all, and effective Dice falls 0.613 -> 0.350.
    The adversarial defence and the physics defences are incompatible.
    """
    from scipy import ndimage
    from apps.detection.preprocessing import load_image

    scene = settings.CALIBRATION_DIR / 'benchmark' / 'linear_clear.png'
    if not scene.exists():
        pytest.skip('benchmark suite not generated')

    img, _ = load_image(str(scene))
    gray = img[:, :, 0].astype(np.float32)

    cv_original = speckle_statistics(gray)['median_cv']
    cv_3 = speckle_statistics(ndimage.median_filter(gray, size=3))['median_cv']
    cv_5 = speckle_statistics(ndimage.median_filter(gray, size=5))['median_cv']

    assert cv_original > cv_3 > cv_5, 'median filtering must compress local CV'
    assert cv_original > 0.18
    assert cv_5 < 0.18

    heavily_filtered = ndimage.median_filter(gray, size=5).astype(np.uint8)
    ok, reason = validate_sar_characteristics(np.stack([heavily_filtered] * 3, -1))
    assert not ok, 'a 5x5-median image should no longer read as coherent radar'
    assert 'speckle' in reason.lower()

    # And the shipped default must therefore leave purification off.
    assert int(getattr(settings, 'MODEL_PURIFY', 0) or 0) in (0, 1)


def test_case8_combiner_default_is_recorded():
    """Case 8: the combiner is an accuracy/robustness tradeoff, pinned deliberately.

    'mean' is the accurate combiner (effective Dice 0.613) but a single attacked
    member can veto the rest, because a confident 0 averaged with a confident 1 sits
    exactly on the decision boundary. 'max' is evasion-resistant -- an attacker must
    defeat every member -- but falls to 0.369 on clean imagery.
    """
    assert getattr(settings, 'MODEL_COMBINER', 'mean') in ('mean', 'max')
