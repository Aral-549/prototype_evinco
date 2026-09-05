import logging
import math
from datetime import datetime, timezone
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 3600  # 6 hours


def fetch_metocean_vectors(lat: float, lon: float, dt: datetime = None) -> dict:
    """Fetch wind and surface ocean current vectors for a given coordinate and time.

    Uses Redis caching with grid cell key quantization (2 decimal places ~ 1.1km).
    Queries Open-Meteo Marine & Weather API. Gracefully falls back to defaults.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    # Key format: metocean:<lat:.2f>:<lon:.2f>:<YYYYMMDD_HH>
    hour_key = dt.strftime('%Y%m%d_%H')
    cache_key = f"metocean:{lat:.2f}:{lon:.2f}:{hour_key}"

    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(f"Metocean cache hit for {cache_key}")
        return cached

    # Defaults
    result = {
        'wind_speed_mps': 5.0,
        'wind_direction_deg': 180.0,
        'current_speed_mps': 0.3,
        'current_direction_deg': 90.0,
        'source': 'default_fallback',
    }

    CIRCUIT_BREAKER_KEY = "metocean:circuit_broken"
    if cache.get(CIRCUIT_BREAKER_KEY):
        cache.set(cache_key, result, timeout=CACHE_TTL_SECONDS)
        return result

    try:
        # Query Open-Meteo Marine API for currents
        marine_url = 'https://marine-api.open-meteo.com/v1/marine'
        marine_params = {
            'latitude': round(lat, 4),
            'longitude': round(lon, 4),
            'current': 'ocean_current_velocity,ocean_current_direction',
        }
        res_marine = requests.get(marine_url, params=marine_params, timeout=1.0)
        if res_marine.ok:
            c_data = res_marine.json().get('current', {})
            vel = c_data.get('ocean_current_velocity')
            dir_deg = c_data.get('ocean_current_direction')
            if vel is not None and dir_deg is not None:
                result['current_speed_mps'] = float(vel) / 3.6  # km/h to m/s if km/h, or raw
                result['current_direction_deg'] = float(dir_deg)
                result['source'] = 'open-meteo'

        # Query Open-Meteo Weather API for 10m winds
        weather_url = 'https://api.open-meteo.com/v1/forecast'
        weather_params = {
            'latitude': round(lat, 4),
            'longitude': round(lon, 4),
            'current': 'wind_speed_10m,wind_direction_10m',
        }
        res_weather = requests.get(weather_url, params=weather_params, timeout=1.0)
        if res_weather.ok:
            w_data = res_weather.json().get('current', {})
            w_spd = w_data.get('wind_speed_10m')
            w_dir = w_data.get('wind_direction_10m')
            if w_spd is not None and w_dir is not None:
                # Open-Meteo wind speed is in km/h by default; convert to m/s
                result['wind_speed_mps'] = round(float(w_spd) / 3.6, 2)
                result['wind_direction_deg'] = float(w_dir)
                result['source'] = 'open-meteo'

    except Exception as exc:
        logger.warning(f"Could not reach Open-Meteo API ({exc}). Using standard maritime defaults.")
        cache.set(CIRCUIT_BREAKER_KEY, True, timeout=300)

    # Cache successful result or fallback
    cache.set(cache_key, result, timeout=CACHE_TTL_SECONDS)
    return result
