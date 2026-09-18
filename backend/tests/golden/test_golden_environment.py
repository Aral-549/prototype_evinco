"""Golden: the suite must run on a clean clone with no external services.

Covers the BUGLOG entry "Test suite requires a live Redis". A judge cloning this
repository has no Redis, no Postgres and no network. If the documented test count
cannot be reproduced in that state, the number is not evidence of anything.
"""
import pytest
from django.conf import settings
from django.core.cache import cache


def test_case1_cache_backend_is_hermetic_under_pytest():
    """Case 1: pytest must not require a Redis server."""
    backend = settings.CACHES['default']['BACKEND']
    assert 'locmem' in backend.lower(), (
        f'tests are configured against {backend}; a clean clone has no Redis and '
        f'the suite will fail with ConnectionError'
    )
    assert settings.RUNNING_TESTS is True


def test_case2_cache_round_trips_without_a_server():
    """Case 2: the cache API the met-ocean layer depends on actually works."""
    cache.set('golden:probe', {'wind_speed_mps': 6.2}, timeout=60)
    assert cache.get('golden:probe') == {'wind_speed_mps': 6.2}
    cache.delete('golden:probe')
    assert cache.get('golden:probe') is None


def test_case3_database_is_sqlite_by_default():
    """Case 3: no Postgres/PostGIS required for the default developer path."""
    engine = settings.DATABASES['default']['ENGINE']
    assert 'sqlite' in engine or settings.USE_POSTGIS


def test_case4_metocean_falls_back_without_network(monkeypatch):
    """Case 4: an unreachable met-ocean API yields documented defaults, not a crash."""
    import apps.drift.metocean as metocean

    def no_network(*args, **kwargs):
        raise OSError('network unreachable')

    monkeypatch.setattr(metocean.requests, 'get', no_network)
    cache.clear()

    from datetime import datetime, timezone
    result = metocean.fetch_metocean_vectors(
        19.0, 72.0, datetime(2026, 1, 1, 12, tzinfo=timezone.utc))

    assert result['source'] == 'default_fallback'
    assert result['wind_speed_mps'] == 5.0
    cache.clear()


def test_case5_offline_trajectory_provider_never_touches_the_network(monkeypatch):
    """Case 5: the offline provider must be usable for a venue demo with no wifi."""
    import apps.drift.metocean as metocean
    from datetime import datetime, timezone

    def explode(*args, **kwargs):
        raise AssertionError('offline provider attempted a network call')

    monkeypatch.setattr(metocean.requests, 'get', explode)
    cache.clear()

    records = []
    provider = metocean.make_trajectory_provider(records, enable_network=False)
    values = provider(19.0, 72.0, datetime(2026, 1, 1, 12, tzinfo=timezone.utc))

    assert values['source'] == 'offline_default'
    assert len(records) == 1
    assert records[0]['source'] == 'offline_default'
    assert 'fetched_at' in records[0]
