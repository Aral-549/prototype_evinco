"""Golden: U-Net inference contract.

Covers the BUGLOG entries "Sigmoid silently skipped when logits happen to land
inside [0,1]", "Every detected polygon reported confidence 1.0" and "Tile overlap
fused with max(), biasing toward false positives".

Uses purpose-built stub heads rather than the shipped checkpoint, so each defect is
reproduced by construction instead of by luck of the scene. On the shipped
`best_unet_dice_0.8018` weights the sigmoid defect happens not to fire on the
bundled calibration image (0 of 12 tiles), which is exactly why a synthetic head is
needed to pin it.
"""
import numpy as np
import pytest
import torch
import torch.nn as nn

from apps.detection.inference import ModelManager


class ConfinedLogitHead(nn.Module):
    """A head whose raw logits always land inside [0, 1].

    This is the input that defeats the old range-inspection heuristic
    `if out.min() < 0 or out.max() > 1: sigmoid(out)`. Logit 0.9 is p=0.7109, but
    the heuristic reads it as p=0.90.
    """

    def forward(self, x):
        return torch.full((x.shape[0], 1, x.shape[2], x.shape[3]), 0.9,
                          device=x.device, dtype=torch.float32)


class PreActivatedHead(nn.Module):
    """A head that already emits probabilities; sigmoid must NOT be applied twice."""

    def forward(self, x):
        return torch.sigmoid(
            torch.full((x.shape[0], 1, x.shape[2], x.shape[3]), 2.0,
                       device=x.device, dtype=torch.float32))


class CentreBrightHead(nn.Module):
    """Emits a high logit only in the central quarter of whatever tile it sees.

    Under max() fusion, a pixel seen at the centre of ANY tile is stamped with that
    tile's high value and never averaged down, so overlap regions inherit the most
    confident view rather than the consensus.
    """

    def forward(self, x):
        h, w = x.shape[2], x.shape[3]
        out = torch.full((x.shape[0], 1, h, w), -6.0, device=x.device)
        out[:, :, h // 4:3 * h // 4, w // 4:3 * w // 4] = 6.0
        return out


@pytest.fixture
def manager():
    """A ModelManager wired to a stub head, restored afterwards.

    ModelManager is a singleton, so its state is saved and put back to avoid
    leaking a stub into other tests.
    """
    mm = ModelManager()
    saved = (mm.model, dict(mm.model_info), mm._initialized, mm.output_activation)

    def install(model, info=None, activation=None):
        mm.model = model
        mm.model_info = {'input_size': 64, 'stride': 32, 'threshold': 0.5,
                         'normalization': 'scale_0_1', 'input_channels': 3,
                         **(info or {})}
        mm._initialized = True
        mm.device = torch.device('cpu')
        mm.output_activation = activation or mm._probe_output_activation()
        return mm

    yield install
    mm.model, mm.model_info, mm._initialized, mm.output_activation = saved


def test_case1_declared_activation_is_authoritative(manager):
    """Case 1: a head whose logits sit inside [0,1] is still a logit head.

    Output inspection CANNOT settle this: a sigmoid head and a logit head whose
    values happen to be confined to [0,1] produce identical observations. That is
    precisely why the original per-tile range heuristic was unsound, and moving the
    same heuristic to load time does not make it sound -- it only makes it
    consistent. The activation must be declared by the checkpoint, and the shipped
    model_info.json does declare it.
    """
    mm = manager(ConfinedLogitHead(), info={'output_activation': 'logits'})
    mm.output_activation = mm._probe_output_activation()
    assert mm.output_activation == 'logits'

    tile = np.full((64, 64, 3), 128, np.uint8)
    prob = mm.predict_single_tile(tile)
    # sigmoid(0.9) = 0.710950, NOT 0.9
    assert prob.mean() == pytest.approx(0.710950, abs=1e-4), (
        'raw logits are being read as probabilities again'
    )
    assert prob.mean() != pytest.approx(0.9, abs=0.01)


def test_case1b_shipped_checkpoint_declares_its_activation():
    """The production checkpoint must never depend on the fallback guess."""
    import json
    from django.conf import settings
    info = json.loads(
        (settings.ML_MODELS_DIR / 'best_unet_dice_0.8018' / 'model_info.json').read_text())
    assert info.get('output_activation') == 'logits'


def test_case1c_undeclared_ambiguous_head_warns_that_it_guessed(manager, caplog):
    """When it must guess, it must say so rather than guessing quietly."""
    import logging
    mm = manager(ConfinedLogitHead(), info={'output_activation': ''})
    with caplog.at_level(logging.WARNING, logger='pipeline'):
        result = mm._probe_output_activation()
    assert result == 'sigmoid'
    assert any('GUESSED' in r.message for r in caplog.records), (
        'an ambiguous activation was resolved silently'
    )


def test_case2_preactivated_head_is_not_squashed_twice(manager):
    """Case 2: a genuine sigmoid head must be left alone."""
    mm = manager(PreActivatedHead())
    assert mm.output_activation == 'sigmoid'

    prob = mm.predict_single_tile(np.full((64, 64, 3), 128, np.uint8))
    assert prob.mean() == pytest.approx(torch.sigmoid(torch.tensor(2.0)).item(), abs=1e-4)


def test_case3_declared_activation_overrides_the_probe(manager):
    """Case 3: model_info.json is authoritative when it states the activation."""
    mm = manager(ConfinedLogitHead(), info={'output_activation': 'sigmoid'})
    mm.output_activation = mm._probe_output_activation()
    assert mm.output_activation == 'sigmoid'
    prob = mm.predict_single_tile(np.full((64, 64, 3), 128, np.uint8))
    assert prob.mean() == pytest.approx(0.9, abs=1e-4)


def test_case4_probabilities_are_always_in_range(manager):
    """Case 4: the posterior handed downstream must be a valid probability."""
    mm = manager(ConfinedLogitHead())
    prob, _ = mm.predict_proba(np.full((128, 128, 3), 40, np.uint8))
    assert prob.min() >= 0.0 and prob.max() <= 1.0
    assert prob.dtype == np.float32


def test_case5_predict_proba_preserves_the_posterior(manager):
    """Case 5 (BUGLOG: every polygon reported confidence 1.0).

    `predict` still returns a binary mask, but the continuous posterior must be
    reachable so downstream stages can report a real confidence.
    """
    mm = manager(CentreBrightHead())
    image = np.full((128, 128, 3), 40, np.uint8)

    prob, uncertainty = mm.predict_proba(image)
    mask = mm.predict(image)

    assert prob.shape == (128, 128)
    assert mask.shape == (128, 128)
    assert set(np.unique(mask)).issubset({0, 255})
    # The posterior carries intermediate values; the mask cannot.
    assert len(np.unique(prob)) > 2
    assert uncertainty.shape == (128, 128)


def test_case6_polygon_confidence_comes_from_the_posterior():
    """Case 6: confidence is the mean posterior inside the contour, not 1.0."""
    from apps.detection.postprocessing import mask_to_polygons

    mask = np.zeros((200, 200), np.uint8)
    mask[50:150, 50:150] = 255
    prob = np.zeros((200, 200), np.float32)
    prob[50:150, 50:150] = 0.62

    region = mask_to_polygons(mask, prob_map=prob)[0]
    assert region['confidence'] == pytest.approx(0.62, abs=0.01)
    assert region['confidence'] != 1.0

    # Without a posterior the legacy placeholder is preserved for compatibility.
    assert mask_to_polygons(mask)[0]['confidence'] == 1.0


def test_case7_hann_window_weights_the_tile_centre():
    """Case 7 (BUGLOG: max() fusion).

    The blend weight must fall smoothly from the tile centre to its edge and never
    reach zero, or edge pixels would have no total weight.
    """
    w = ModelManager._blend_window(64)
    assert w.shape == (64, 64)
    assert w[32, 32] > w[16, 32] > w[2, 32] > 0.0
    assert w.min() > 0.0
    assert w[32, 32] == pytest.approx(w.max())
    # Symmetric, so fusion does not favour one side of a tile.
    assert np.allclose(w, w.T, atol=1e-6)
    assert np.allclose(w, np.flipud(w), atol=1e-6)


def test_case8_overlap_is_averaged_not_maxed(manager):
    """Case 8: an overlap pixel must reflect the consensus, not the loudest tile.

    With CentreBrightHead every pixel that lands in some tile's centre would be
    stamped 1.0 under max() fusion, so the output would be almost entirely
    saturated. Weighted averaging must leave a graded map instead.
    """
    mm = manager(CentreBrightHead())
    prob, _ = mm.predict_proba(np.full((160, 160, 3), 40, np.uint8))

    saturated = float((prob > 0.99).mean())
    assert saturated < 0.90, (
        f'{saturated * 100:.0f}% of pixels are saturated; overlaps look like max() fusion'
    )
    assert 0.0 < prob.mean() < 1.0
    assert len(np.unique(np.round(prob, 3))) > 5, 'expected a graded map, not a step'


def test_case9_tta_returns_an_uncertainty_map(manager):
    """TTA averages four flip views and reports their per-pixel spread."""
    mm = manager(CentreBrightHead())
    image = np.full((128, 128, 3), 40, np.uint8)

    _, no_tta_unc = mm.predict_proba(image, tta=False)
    prob_tta, tta_unc = mm.predict_proba(image, tta=True)

    assert np.allclose(no_tta_unc, 0.0), 'uncertainty is only defined across TTA views'
    assert prob_tta.shape == (128, 128)
    assert tta_unc.min() >= 0.0


def test_case10_small_image_is_padded_not_rejected(manager):
    """An image smaller than one tile must still produce a full-size posterior."""
    mm = manager(ConfinedLogitHead())
    prob, _ = mm.predict_proba(np.full((30, 40, 3), 90, np.uint8))
    assert prob.shape == (30, 40)
    assert np.isfinite(prob).all()
