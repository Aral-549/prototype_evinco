import os
import tempfile
import numpy as np
from PIL import Image
import pytest
from rest_framework.test import APIClient
from apps.pipeline.models import PipelineRun


@pytest.mark.django_db
def test_full_pipeline_sync_execution():
    """Integration Test: POST image to pipeline with sync=true -> assert completed status."""
    client = APIClient()

    # Create synthetic test SAR image with realistic speckle noise (256x256)
    np.random.seed(42)
    base = np.random.normal(180, 20, (256, 256)).clip(0, 255).astype(np.uint8)
    base[90:160, 90:160] = 20  # dark anomaly
    arr = np.stack([base, base, base], axis=-1)

    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        Image.fromarray(arr).save(tmp.name)
        with open(tmp.name, 'rb') as fp:
            response = client.post(
                '/api/v1/pipeline/run/?sync=true',
                {
                    'image': fp,
                    'wind_speed_mps': 5.0,
                    'wind_direction_deg': 180.0,
                    'current_speed_mps': 0.3,
                    'current_direction_deg': 90.0,
                    'drift_duration_hours': 12.0,
                },
                format='multipart'
            )

    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'completed'
    assert data['spills_detected'] >= 0
    assert 'detection_job' in data
    assert data['detection_job']['result_mask'] is not None
