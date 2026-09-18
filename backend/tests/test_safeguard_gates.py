import tempfile
import numpy as np
from PIL import Image
import pytest
from rest_framework.test import APIClient
from apps.detection.preprocessing import validate_sar_characteristics, load_image


def speckled_sar_with_slick(size=256, seed=42):
    """A SAR-like scene containing a genuinely damped slick.

    The fixtures here previously used `np.random.normal(120, 25, ...)` with a flat
    dark square stamped into it. That is additive noise with a painted-on patch,
    and once Layer 2 look-alike screening was added the patch was correctly
    rejected: its speckle statistics were identical to the surrounding "sea", which
    is the signature of a calm zone rather than oil. These tests are about the
    georeference gate and met-ocean plumbing, not about detection, so the fixture is
    now a scene that actually contains a slick: multiplicative gamma speckle, with a
    region damped in BOTH mean and speckle variance, as mineral oil is.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    sigma0 = 0.55 - 0.10 * (xx / size)

    slick = np.zeros((size, size), bool)
    slick[90:170, 60:200] = True

    sigma0 = np.where(slick, sigma0 * 0.20, sigma0)
    looks = np.where(slick, 64.0, 4.0)          # oil damps speckle as well as mean
    amplitude = np.sqrt(sigma0 * rng.gamma(shape=looks, scale=1.0 / looks))

    img = np.clip(amplitude / np.percentile(amplitude, 99.5), 0, 1)
    base = (img * 255).astype(np.uint8)
    return np.stack([base, base, base], axis=-1)


def test_layer1_ood_rejection_for_optical_and_screenshot():
    """Verify Layer 1 rejects optical color photos and screenshot-like flat blocks."""
    # 1. Optical RGB photo (uncorrelated channels)
    optical_img = np.zeros((100, 100, 3), dtype=np.uint8)
    optical_img[:, :, 0] = 250  # bright red
    optical_img[:, :, 1] = 10   # dark green
    optical_img[:, :, 2] = 10   # dark blue
    is_valid, reason = validate_sar_characteristics(optical_img)
    assert not is_valid
    assert "channel decorrelation" in reason

    # 2. Text screenshot (single channel rendered, but >30% zero-variance patches)
    # A typical document: pure white background with small dark text
    doc_img = np.full((128, 128, 3), 255, dtype=np.uint8)
    doc_img[20:25, 20:80] = 0  # one line of text
    is_valid, reason = validate_sar_characteristics(doc_img)
    assert not is_valid
    assert "flat blocks" in reason


def test_layer1_sar_acceptance():
    """Verify Layer 1 accepts authentic SAR images with speckle variance."""
    # Synthetic SAR with speckle noise
    np.random.seed(42)
    base = np.random.normal(120, 25, (256, 256)).clip(0, 255).astype(np.uint8)
    sar_img = np.stack([base, base, base], axis=-1)
    is_valid, reason = validate_sar_characteristics(sar_img)
    assert is_valid
    assert "Passed SAR verification" in reason


@pytest.mark.django_db
def test_layer3_georeference_gate_unanchored():
    """Verify unanchored images halt at Layer 3 without running drift or AIS attribution."""
    client = APIClient()
    client.credentials(HTTP_X_API_KEY='test-key-not-for-production')

    # Create synthetic SAR image
    arr = speckled_sar_with_slick()

    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        Image.fromarray(arr).save(tmp.name)
        with open(tmp.name, 'rb') as fp:
            response = client.post(
                '/api/v1/pipeline/run/?sync=true',
                {'image': fp},
                format='multipart'
            )

    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'completed'
    assert data['stage'] == 'georeference_gated'
    assert data['is_georeferenced'] is False
    assert data['suspects_ranked'] == 0
    assert 'Georeference Gate Active' in data['error_message']


@pytest.mark.django_db
def test_layer3_georeferenced_with_explicit_bbox():
    """Verify explicitly bounded images pass Layer 3 and proceed to drift hindcast."""
    client = APIClient()
    client.credentials(HTTP_X_API_KEY='test-key-not-for-production')

    # Create synthetic SAR image
    arr = speckled_sar_with_slick()

    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        Image.fromarray(arr).save(tmp.name)
        with open(tmp.name, 'rb') as fp:
            response = client.post(
                '/api/v1/pipeline/run/?sync=true',
                {
                    'image': fp,
                    'bbox_min_lon': 71.5,
                    'bbox_min_lat': 18.5,
                    'bbox_max_lon': 72.5,
                    'bbox_max_lat': 19.5,
                },
                format='multipart'
            )

    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'completed'
    assert data['is_georeferenced'] is True
    assert data['bbox_min_lon'] == 71.5
    assert data['bbox_min_lat'] == 18.5
    assert data.get('metocean_source') in ('open-meteo', 'default_fallback')


@pytest.mark.django_db
def test_metocean_source_manual_override():
    """Verify operator manual wind/current parameters are tagged as manual_override."""
    client = APIClient()
    client.credentials(HTTP_X_API_KEY='test-key-not-for-production')

    arr = speckled_sar_with_slick()

    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        Image.fromarray(arr).save(tmp.name)
        with open(tmp.name, 'rb') as fp:
            response = client.post(
                '/api/v1/pipeline/run/?sync=true',
                {
                    'image': fp,
                    'bbox_min_lon': 71.5,
                    'bbox_min_lat': 18.5,
                    'bbox_max_lon': 72.5,
                    'bbox_max_lat': 19.5,
                    'wind_speed_mps': 12.5,  # Custom operator input
                    'wind_direction_deg': 225.0,
                },
                format='multipart'
            )

    assert response.status_code == 201
    data = response.json()
    assert data['metocean_source'] == 'manual_override'

