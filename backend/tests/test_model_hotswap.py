import os
import tempfile
import numpy as np
import pytest
import torch
from django.conf import settings
from apps.detection.inference import ModelManager, find_model_metadata


def test_model_info_sidecar_metadata():
    """Verify ModelManager loads and exposes model_info.json sidecar metadata."""
    mm = ModelManager()
    info = mm.get_model_info()

    assert info is not None
    assert info.get('architecture') == 'custom_unet'
    assert info.get('dice_score') == 0.8018
    assert info.get('input_channels') == 3
    assert info.get('input_size') == 256
    assert info.get('threshold') == 0.5
    assert info.get('is_fallback') is False


def test_failsafe_fallback_on_invalid_checkpoint():
    """Verify ModelManager gracefully falls back to baseline when given an invalid checkpoint."""
    mm = ModelManager()

    # Pass a non-existent checkpoint path
    fake_path = "/tmp/non_existent_oil_spill_checkpoint.pth"
    fallback_info = mm.reload(checkpoint_path=fake_path)

    # Must NOT raise exception; must be active on fallback
    assert fallback_info['is_fallback'] is True
    assert fake_path in fallback_info['fallback_reason']
    assert fallback_info['name'] == 'UNet Baseline (4-Stage Custom)'

    # Inference must still function on fallback model
    synthetic_sar = np.random.normal(128, 20, (256, 256, 3)).clip(0, 255).astype(np.uint8)
    mask = mm.predict(synthetic_sar)
    assert mask.shape == (256, 256)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)).issubset({0, 255})

    # Restore default checkpoint
    mm.reload(checkpoint_path=str(settings.DEFAULT_MODEL_CHECKPOINT))


def test_io_contract_compliance():
    """Verify I/O contract: 256x256x3 in -> [0, 1] prob tile -> (H, W) {0, 255} binary mask."""
    mm = ModelManager()
    mm._ensure_loaded()

    # Single tile contract
    tile = np.random.normal(120, 25, (256, 256, 3)).clip(0, 255).astype(np.uint8)
    prob_tile = mm.predict_single_tile(tile)

    assert prob_tile.shape == (256, 256)
    assert prob_tile.dtype == np.float32
    assert float(prob_tile.min()) >= 0.0
    assert float(prob_tile.max()) <= 1.0

    # Full image arbitrary dimensions contract
    full_image = np.random.normal(120, 25, (300, 450, 3)).clip(0, 255).astype(np.uint8)
    mask = mm.predict(full_image)

    assert mask.shape == (300, 450)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)).issubset({0, 255})
