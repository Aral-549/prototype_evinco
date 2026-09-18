"""Shared test fixtures.

Tests authenticate with a real API key rather than switching authentication off.
A suite that disables the permission layer proves the product works only in the one
configuration nobody deploys.
"""
import pytest
from rest_framework.test import APIClient

TEST_API_KEY = 'test-key-not-for-production'


@pytest.fixture
def api_client():
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=TEST_API_KEY)
    return client
