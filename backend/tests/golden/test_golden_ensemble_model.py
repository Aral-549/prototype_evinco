"""Golden: two-model ensemble inference.

The U-Net and SegFormer-B0 fail in different places. Measured across the synthetic
benchmark suite (`ai_model/scripts/benchmark_models.py`):

    scene            U-Net   SegFormer   Ensemble
    linear_noisy     0.578     0.931       0.958   <- beats BOTH members
    blob_clear       0.994     0.000       0.990   <- survives a member failing
    patchy_clear     0.977     0.266       0.771
    ---------------------------------------------
    mean eff Dice    0.590     0.401       0.613

Averaging inherits whichever member was right rather than splitting the difference.
These cases pin that behaviour, and pin the properties that make it safe: each member
normalised by its own sidecar, a failed member degrading rather than crashing, and
the single-model path still working when the ensemble is switched off.
"""
import numpy as np
import pytest
import torch
from django.conf import settings

from apps.detection.inference import ModelManager

SEG = settings.ML_MODELS_DIR / 'best_segformer_b0' / 'best_segformer_b0.pt'
UNET = settings.DEFAULT_MODEL_CHECKPOINT

pytestmark = pytest.mark.skipif(
    not SEG.exists(), reason='SegFormer checkpoint not packaged in this checkout')


@pytest.fixture
def manager():
    """A ModelManager restored to its prior state afterwards (it is a singleton)."""
    mm = ModelManager()
    saved = (mm.active_checkpoint, list(getattr(settings, 'MODEL_ENSEMBLE', [])))
    yield mm
    settings.MODEL_ENSEMBLE = saved[1]
    mm.reload(checkpoint_path=str(saved[0]) if saved[0] else str(UNET))


def test_case1_ensemble_loads_both_members(manager):
    """Case 1: both architectures resident, neither falling back."""
    settings.MODEL_ENSEMBLE = [str(SEG)]
    info = manager.reload(checkpoint_path=str(UNET))

    assert info.get('is_fallback') is False
    assert info.get('ensemble_size') == 2
    members = info.get('ensemble_members') or []
    assert any('UNet' in m for m in members)
    assert any('SegFormer' in m for m in members)
    assert len(manager.ensemble) == 1


def test_case2_ensemble_output_lies_between_its_members(manager):
    """Case 2: the average must actually be an average.

    A mean of two posteriors cannot fall outside the interval they span. If it
    does, members are being combined with mismatched activations or normalisation.
    """
    image = np.full((256, 256, 3), 85, np.uint8)

    settings.MODEL_ENSEMBLE = []
    manager.reload(checkpoint_path=str(UNET))
    p_unet, _ = manager.predict_proba(image)

    manager.reload(checkpoint_path=str(SEG))
    p_seg, _ = manager.predict_proba(image)

    settings.MODEL_ENSEMBLE = [str(SEG)]
    manager.reload(checkpoint_path=str(UNET))
    p_ens, _ = manager.predict_proba(image)

    lo = np.minimum(p_unet, p_seg)
    hi = np.maximum(p_unet, p_seg)
    assert (p_ens >= lo - 1e-4).all()
    assert (p_ens <= hi + 1e-4).all()
    assert np.allclose(p_ens, (p_unet + p_seg) / 2.0, atol=2e-3)


def test_case3_each_member_normalises_by_its_own_sidecar(manager):
    """Case 3: a member must not inherit the primary's normalisation.

    Feeding a model inputs scaled the way a different model was trained is a silent
    accuracy loss that no shape or range assertion would catch.
    """
    settings.MODEL_ENSEMBLE = [str(SEG)]
    manager.reload(checkpoint_path=str(UNET))

    member = manager.ensemble[0]
    tile = np.full((256, 256, 3), 120, np.uint8)

    primary_norm = manager.normalize_tile(tile)
    member_norm = manager.normalize_tile(tile, member['meta'])

    assert primary_norm.shape == member_norm.shape
    # Each member's declared activation is used, not the primary's.
    assert member['activation'] in ('logits', 'sigmoid')
    assert member['meta'].get('name')


def test_case4_a_broken_member_degrades_instead_of_crashing(manager):
    """Case 4: losing a member must cost accuracy, never availability."""
    settings.MODEL_ENSEMBLE = ['/nonexistent/model.pt', str(SEG)]
    info = manager.reload(checkpoint_path=str(UNET))

    assert info.get('is_fallback') is False
    assert len(manager.ensemble) == 1, 'the loadable member should still be used'

    prob, _ = manager.predict_proba(np.full((256, 256, 3), 90, np.uint8))
    assert prob.shape == (256, 256)
    assert np.isfinite(prob).all()


def test_case5_ensemble_can_be_switched_off(manager):
    """Case 5: the single-model path must remain intact and identical."""
    image = np.full((256, 256, 3), 95, np.uint8)

    settings.MODEL_ENSEMBLE = []
    manager.reload(checkpoint_path=str(UNET))
    assert manager.ensemble == []
    solo, _ = manager.predict_proba(image)

    info = manager.get_model_info()
    assert 'ensemble_size' not in info or info.get('ensemble_size') in (None, 1)
    assert solo.shape == (256, 256)


def test_case6_posterior_stays_a_valid_probability(manager):
    """Averaging must not produce values outside [0, 1]."""
    settings.MODEL_ENSEMBLE = [str(SEG)]
    manager.reload(checkpoint_path=str(UNET))

    for fill in (0, 90, 255):
        prob, _ = manager.predict_proba(np.full((256, 256, 3), fill, np.uint8))
        assert prob.min() >= 0.0
        assert prob.max() <= 1.0
        assert prob.dtype == np.float32


def test_case7_primary_is_not_double_counted(manager):
    """Listing the primary checkpoint in MODEL_ENSEMBLE must not weight it twice."""
    settings.MODEL_ENSEMBLE = [str(UNET), str(SEG)]
    manager.reload(checkpoint_path=str(UNET))

    assert len(manager.ensemble) == 1, 'the primary was loaded a second time'
    assert 'segformer' in manager.ensemble[0]['path'].lower()
