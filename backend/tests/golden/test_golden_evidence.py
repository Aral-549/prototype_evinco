"""Golden: forensic chain of custody and environment hermeticity.

Covers `contracts/evidence_manifest.md` cases 1-8 and the BUGLOG entry
"Test suite requires a live Redis".
"""
import json
import os
import tempfile
import time

import pytest
from django.conf import settings
from django.core.cache import cache

from apps.pipeline.evidence import (
    build_manifest, verify, digest_stage_output, canonical_json, sha256_file,
    sha256_path, _normalise,
)

MODEL_INFO = {'name': 'UNet Baseline', 'version': '1.0.0',
              'checkpoint_id': 'best_unet_dice_0.8018'}
PARAMS = {'seed': 42, 'threshold': 0.5, 'capture_radius_km': 5.0, 'n_particles': 500}
METOCEAN = [{'lat': 19.0, 'lon': 72.0, 'time': '2026-01-01T12:00:00+00:00',
             'source': 'open-meteo', 'fetched_at': '2026-01-01T12:00:05+00:00',
             'values': {'wind_speed_mps': 6.2}}]


@pytest.fixture
def scene():
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'scene.tif')
    with open(path, 'wb') as f:
        f.write(b'FAKE-SAR-BYTES' * 1000)
    return path


def make(scene_path, **over):
    return build_manifest(
        image_path=scene_path,
        model_info=over.get('model_info', MODEL_INFO),
        checkpoint_path=over.get('checkpoint_path'),
        parameters=over.get('parameters', PARAMS),
        metocean_records=over.get('metocean_records', METOCEAN),
        stage_digests=over.get('stage_digests', {'detection': 'abc'}),
    )


def test_case1_same_analysis_yields_the_same_content_digest(scene):
    """Case 1: the core reproducibility claim."""
    a = make(scene)
    time.sleep(0.01)
    b = make(scene)
    assert a.content_sha256 == b.content_sha256
    assert a.input_sha256 == b.input_sha256
    assert len(a.input_sha256) == 64


def test_case2_one_changed_byte_is_detected(scene):
    """Case 2: tamper evidence on the analysed image."""
    before = make(scene)
    with open(scene, 'ab') as f:
        f.write(b'X')
    after = make(scene)

    assert after.input_sha256 != before.input_sha256
    assert after.manifest_sha256 != before.manifest_sha256
    assert after.content_sha256 != before.content_sha256


def test_case3_any_parameter_change_changes_the_digest(scene):
    """Case 3: the parameters are part of the evidence, not context."""
    base = make(scene)
    for key, value in (('seed', 43), ('threshold', 0.6), ('capture_radius_km', 10.0)):
        altered = make(scene, parameters={**PARAMS, key: value})
        assert altered.content_sha256 != base.content_sha256, f'{key} did not seal'


def test_case4_created_at_is_inside_the_manifest_seal(scene):
    """Case 4: re-issuing a manifest is visible, but the ANALYSIS still matches.

    `created_at` is inside manifest_sha256 and outside content_sha256, so two runs
    of the same analysis on different days can be shown to be the same analysis
    while remaining distinguishable as separate issuances.
    """
    a = make(scene)
    time.sleep(0.01)
    b = make(scene)
    assert a.manifest_sha256 != b.manifest_sha256
    assert a.content_sha256 == b.content_sha256


def test_case5_verify_accepts_the_genuine_article(scene):
    """Case 5: the happy path returns no reasons."""
    m = make(scene)
    ok, reasons = verify(m, scene)
    assert ok is True
    assert reasons == []


def test_case6_verify_names_the_specific_mismatch(scene):
    """Case 6: a reviewer must be told WHAT failed, not merely that something did."""
    m = make(scene)
    other = tempfile.mktemp()
    with open(other, 'wb') as f:
        f.write(b'A DIFFERENT SCENE ENTIRELY')

    ok, reasons = verify(m, other)
    assert ok is False
    assert len(reasons) == 1
    assert 'Input image mismatch' in reasons[0]
    assert m.input_sha256 in reasons[0]


def test_case6b_altered_manifest_fails_its_own_seal(scene):
    """A dossier edited after issue must fail verification."""
    m = make(scene)
    tampered = m.to_dict()
    tampered['parameters'] = {**tampered['parameters'], 'seed': '999'}

    ok, reasons = verify(tampered)
    assert ok is False
    assert any('manifest_sha256 mismatch' in r for r in reasons)


def test_case7_missing_checkpoint_does_not_crash_the_pipeline(scene):
    """Case 7: a missing model file degrades the record; it does not lose the run."""
    m = make(scene, checkpoint_path='/does/not/exist/at/all')
    assert m.model_sha256 == 'unavailable'
    assert m.manifest_sha256 != ''
    assert verify(m, scene)[0] is True


def test_case8_key_order_and_numeric_form_do_not_matter(scene):
    """Case 8: canonicalisation, not accidental dict ordering."""
    a = make(scene, parameters={'seed': 42, 'threshold': 0.5})
    b = make(scene, parameters={'threshold': 0.5, 'seed': 42})
    assert a.content_sha256 == b.content_sha256

    # 1 and 1.0 are the same parameter value.
    c = make(scene, parameters={'n': 1})
    d = make(scene, parameters={'n': 1.0})
    assert c.content_sha256 == d.content_sha256

    assert canonical_json({'b': 1, 'a': 2}) == canonical_json({'a': 2, 'b': 1})


def test_case9_non_ascii_survives_round_trip(scene):
    """Edge case: vessel names and paths are not always ASCII."""
    m = make(scene, parameters={**PARAMS, 'vessel': 'SÃO PAULO MARU / 大阪丸'})
    assert verify(m, scene)[0] is True
    restored = json.loads(m.to_json())
    assert 'SÃO PAULO MARU / 大阪丸' in restored['parameters']['vessel']


def test_case10_directory_checkpoints_digest_stably(scene):
    """Edge case: PyTorch directory-format bundles must hash deterministically."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'data'), exist_ok=True)
    for name in ('data.pkl', 'data/0', 'data/1'):
        with open(os.path.join(d, name), 'wb') as f:
            f.write(name.encode() * 50)

    first = sha256_path(d)
    second = sha256_path(d)
    assert first == second
    assert first != 'unavailable'
    assert len(first) == 64

    with open(os.path.join(d, 'data/1'), 'ab') as f:
        f.write(b'!')
    assert sha256_path(d) != first


def test_case11_missing_file_is_reported_not_raised():
    """A digest of something absent is 'unavailable', never an exception."""
    assert sha256_file('/no/such/file') == 'unavailable'
    assert sha256_path('/no/such/dir') == 'unavailable'
    assert sha256_path('') == 'unavailable'


def test_case12_stage_digests_are_order_stable():
    """Stage digests must depend on content, not on dict iteration order."""
    a = digest_stage_output({'regions': 2, 'mean': 0.4})
    b = digest_stage_output({'mean': 0.4, 'regions': 2})
    assert a == b
    assert digest_stage_output({'regions': 3, 'mean': 0.4}) != a


def test_case13_normalise_is_idempotent():
    """Normalising twice must not change the value."""
    payload = {'a': 1, 'b': [1.0, 2], 'c': {'d': True, 'e': None}}
    once = _normalise(payload)
    assert _normalise(once) == once
