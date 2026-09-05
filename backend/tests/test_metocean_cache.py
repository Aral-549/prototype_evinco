from datetime import datetime, timezone
from django.core.cache import cache
import pytest
from apps.drift.metocean import fetch_metocean_vectors


def test_metocean_caching():
    """Unit Test: Open-Meteo fetching sets and retrieves from Redis cache."""
    lat, lon = 18.95, 72.10
    now = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)

    # Clear any previous key
    hour_key = now.strftime('%Y%m%d_%H')
    cache_key = f"metocean:{lat:.2f}:{lon:.2f}:{hour_key}"
    cache.delete(cache_key)

    # First fetch (miss -> sets cache)
    res1 = fetch_metocean_vectors(lat, lon, now)
    assert 'wind_speed_mps' in res1
    assert 'current_speed_mps' in res1
    assert cache.get(cache_key) is not None

    # Manually modify cache to prove second fetch hits cache
    cached_payload = dict(res1)
    cached_payload['source'] = 'verified_from_redis_cache'
    cache.set(cache_key, cached_payload, timeout=300)

    res2 = fetch_metocean_vectors(lat, lon, now)
    assert res2['source'] == 'verified_from_redis_cache'
