"""Golden: SegFormer-B0 architecture reconstruction and hot-swap.

The checkpoint `best_segformer_b0.pth` stores its tensors under a custom module
layout matching neither `segmentation_models_pytorch` nor HuggingFace's SegFormer.
With no matching architecture in the repository, pointing MODEL_CHECKPOINT_PATH at
it caused the fail-safe to silently fall back to the U-Net: the run succeeded, the
API responded, and the weaker model served every request.

These cases pin the reconstruction so that a refactor cannot quietly reintroduce
that failure.
"""
import json

import numpy as np
import pytest
import torch
from django.conf import settings

from apps.detection.architectures.segformer import SegFormer
from apps.detection.inference import (
    ModelManager, instantiate_model, clean_state_dict, _load_checkpoint_directory,
)

WEIGHTS = settings.ML_MODELS_DIR / 'best_segformer_b0' / 'best_segformer_b0.pt'
SIDECAR = settings.ML_MODELS_DIR / 'best_segformer_b0' / 'model_info.json'

pytestmark = pytest.mark.skipif(
    not WEIGHTS.exists(), reason='SegFormer checkpoint not packaged in this checkout')


def load_weights():
    sd = torch.load(WEIGHTS, map_location='cpu', weights_only=False)
    return clean_state_dict(sd)


def test_case1_architecture_matches_the_checkpoint_exactly():
    """Case 1: every tensor must be claimed, with no silent partial load.

    `strict=True` is the point. A partial load would leave randomly-initialised
    layers inside a model whose output is presented as evidence.
    """
    model = SegFormer()
    weights = load_weights()

    model_keys = set(model.state_dict())
    ckpt_keys = set(weights)

    assert ckpt_keys - model_keys == set(), f'checkpoint keys absent from the model: {sorted(ckpt_keys - model_keys)[:5]}'
    assert model_keys - ckpt_keys == set(), f'model keys absent from the checkpoint: {sorted(model_keys - ckpt_keys)[:5]}'

    model.load_state_dict(weights, strict=True)


def test_case2_is_a_mit_b0_of_the_expected_shape():
    """Case 2: the reconstruction is MiT-B0, not an approximation of it."""
    weights = load_weights()

    dims = [32, 64, 160, 256]
    for i, d in enumerate(dims):
        assert weights[f'segformer.stages.{i}.patch_embeddings.proj.weight'].shape[0] == d
        # depth 2 at every stage
        assert f'segformer.stages.{i}.blocks.1.mlp.fc1.weight' in weights
        assert f'segformer.stages.{i}.blocks.2.mlp.fc1.weight' not in weights
        # MLP ratio 4
        mlp = weights[f'segformer.stages.{i}.blocks.0.mlp.fc1.weight'].shape
        assert mlp[0] == mlp[1] * 4

    # Spatial reduction ratios 8, 4, 2, then none at the deepest stage.
    for i, ratio in enumerate((8, 4, 2)):
        k = f'segformer.stages.{i}.blocks.0.attention.sequence_reduction.sequence_reduction.weight'
        assert weights[k].shape[2] == ratio
    assert ('segformer.stages.3.blocks.0.attention.sequence_reduction'
            '.sequence_reduction.weight') not in weights

    # Binary head.
    assert weights['decode_head.classifier.weight'].shape[0] == 1
    # linear_fuse carries no bias in this checkpoint.
    assert 'decode_head.linear_fuse.bias' not in weights


def test_case3_forward_preserves_input_resolution():
    """Case 3: the head works at stride 4; output must be restored to input size.

    The rest of the pipeline assumes a posterior the same shape as the scene.
    """
    model = SegFormer()
    model.load_state_dict(load_weights(), strict=True)
    model.eval()

    for size in (256, 320):
        with torch.no_grad():
            out = model(torch.randn(1, 3, size, size))
        assert out.shape == (1, 1, size, size)
        assert torch.isfinite(out).all()


def test_case4_emits_logits_not_probabilities():
    """Case 4: the head is unactivated, and the sidecar must declare that.

    Declaring it is what keeps the activation probe out of the loop: output-range
    inspection cannot distinguish a sigmoid head from a logit head whose values
    happen to be confined to [0, 1].
    """
    model = SegFormer()
    model.load_state_dict(load_weights(), strict=True)
    model.eval()

    with torch.no_grad():
        out = model(torch.randn(1, 3, 256, 256) * 3.0)
    assert out.min() < 0.0, 'expected raw logits, got values confined to [0, 1]'

    info = json.loads(SIDECAR.read_text())
    assert info['output_activation'] == 'logits'
    assert info['architecture'] == 'segformer_b0'


def test_case5_factory_builds_it_by_name():
    """Case 5: `instantiate_model` must recognise the architecture string.

    This is the exact link that was missing: the weights existed, the sidecar
    could name them, but nothing could build the module.
    """
    for alias in ('segformer', 'segformer_b0', 'mit_b0'):
        assert isinstance(instantiate_model(alias, in_channels=3, out_channels=1),
                          SegFormer), f'alias {alias!r} did not build a SegFormer'


def test_case6_hot_swap_loads_it_without_falling_back():
    """Case 6: the regression itself.

    Before the architecture existed, this reload silently fell back to the U-Net
    and reported success.
    """
    mm = ModelManager()
    saved = mm.active_checkpoint
    try:
        info = mm.reload(checkpoint_path=str(WEIGHTS))
        assert info.get('is_fallback') is False, (
            f"hot-swap fell back to the baseline: {info.get('fallback_reason')}")
        assert 'SegFormer' in info.get('name', '')
        assert mm.output_activation == 'logits'

        prob, _ = mm.predict_proba(np.full((256, 256, 3), 90, np.uint8))
        assert prob.shape == (256, 256)
        assert 0.0 <= prob.min() and prob.max() <= 1.0
    finally:
        if saved:
            mm.reload(checkpoint_path=str(saved))


def test_case7_packaged_weights_carry_no_optimizer_state():
    """Case 7: only what affects a prediction belongs in an evidentiary artefact.

    The training checkpoint bundles optimizer momentum, which is two thirds of its
    45 MB and has no bearing on the output. Shipping it would mean the
    chain-of-custody digest covers bytes irrelevant to the result.
    """
    sd = torch.load(WEIGHTS, map_location='cpu', weights_only=False)
    assert isinstance(sd, dict)
    assert 'optimizer_state_dict' not in sd
    assert all(hasattr(v, 'shape') for v in sd.values()), 'non-tensor entries present'
    assert WEIGHTS.stat().st_size < 20 * 1024 * 1024


def test_case8_sidecar_does_not_overclaim_the_metrics():
    """Case 8: the reported Dice is from the training run's own validation split.

    Presenting it as directly comparable with the U-Net's figure, without knowing
    both were evaluated on the same split, would be an unsupported claim.
    """
    info = json.loads(SIDECAR.read_text())
    assert info['dice_score'] == pytest.approx(0.8245, abs=1e-3)
    assert info['iou_score'] == pytest.approx(0.7294, abs=1e-3)
    assert 'not directly comparable' in info['notes'].lower()
    assert info['trained_epochs'] == 9
