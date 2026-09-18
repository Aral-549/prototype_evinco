import logging
import math
from datetime import datetime, timezone
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
# 1.0 s was too aggressive for a marine API over a conference Wi-Fi link; a
# timeout is not a reason to silently fall back to invented defaults.
REQUEST_TIMEOUT_S = float(__import__('os').getenv('METOCEAN_TIMEOUT_S', '4.0'))


def _cache_get(key, default=None):
    """Read from cache, treating an unreachable cache as a miss.

    Redis is a cache here: it stores met-ocean values that can always be
    re-fetched. Losing it must cost latency, never availability. Before this,
    `cache.get()` sat outside the try/except guarding the HTTP call, so a Redis
    outage raised ConnectionError straight out of `fetch_metocean_vectors` and
    killed the whole analysis run -- including runs that had a perfectly good
    manual met-ocean override and never needed the network at all.
    """
    try:
        return cache.get(key, default)
    except Exception as exc:
        logger.warning(f'Cache unavailable on read ({exc}); proceeding without it.')
        return default


def _cache_set(key, value, timeout=None):
    """Write to cache, tolerating an unreachable cache."""
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as exc:
        logger.warning(f'Cache unavailable on write ({exc}); result not cached.')


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

    cached = _cache_get(cache_key)
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
    if _cache_get(CIRCUIT_BREAKER_KEY):
        _cache_set(cache_key, result, timeout=CACHE_TTL_SECONDS)
        return result

    try:
        # Query Open-Meteo Marine API for currents
        marine_url = 'https://marine-api.open-meteo.com/v1/marine'
        marine_params = {
            'latitude': round(lat, 4),
            'longitude': round(lon, 4),
            'current': 'ocean_current_velocity,ocean_current_direction',
            # Request the unit explicitly. The previous code divided by 3.6 with the
            # comment "km/h to m/s if km/h, or raw" -- i.e. it did not know which unit
            # it had received, and a wrong guess here is a 3.6x error in the dominant
            # term of the drift equation.
            'current_velocity_unit': 'ms',
            'timeformat': 'iso8601',
        }
        res_marine = requests.get(marine_url, params=marine_params, timeout=REQUEST_TIMEOUT_S)
        if res_marine.ok:
            payload = res_marine.json()
            c_data = payload.get('current', {})
            vel = c_data.get('ocean_current_velocity')
            dir_deg = c_data.get('ocean_current_direction')
            if vel is not None and dir_deg is not None:
                units = payload.get('current_units', {})
                vel_unit = str(units.get('ocean_current_velocity', 'ms')).lower()
                speed = float(vel)
                if vel_unit in ('kmh', 'km/h'):
                    speed /= 3.6
                elif vel_unit in ('kn', 'knots'):
                    speed *= 0.514444
                result['current_speed_mps'] = speed
                result['current_direction_deg'] = float(dir_deg)
                result['source'] = 'open-meteo'

        # Query Open-Meteo Weather API for 10m winds
        weather_url = 'https://api.open-meteo.com/v1/forecast'
        weather_params = {
            'latitude': round(lat, 4),
            'longitude': round(lon, 4),
            'current': 'wind_speed_10m,wind_direction_10m',
            'wind_speed_unit': 'ms',
        }
        res_weather = requests.get(weather_url, params=weather_params, timeout=REQUEST_TIMEOUT_S)
        if res_weather.ok:
            w_data = res_weather.json().get('current', {})
            w_spd = w_data.get('wind_speed_10m')
            w_dir = w_data.get('wind_direction_10m')
            if w_spd is not None and w_dir is not None:
                w_units = res_weather.json().get('current_units', {})
                w_unit = str(w_units.get('wind_speed_10m', 'ms')).lower()
                speed = float(w_spd)
                if w_unit in ('kmh', 'km/h'):
                    speed /= 3.6
                elif w_unit in ('kn', 'knots'):
                    speed *= 0.514444
                elif w_unit == 'mph':
                    speed *= 0.44704
                result['wind_speed_mps'] = round(speed, 2)
                result['wind_direction_deg'] = float(w_dir)
                result['source'] = 'open-meteo'

    except Exception as exc:
        logger.warning(f"Could not reach Open-Meteo API ({exc}). Using standard maritime defaults.")
        _cache_set(CIRCUIT_BREAKER_KEY, True, timeout=300)

    # Cache successful result or fallback
    _cache_set(cache_key, result, timeout=CACHE_TTL_SECONDS)
    return result


def make_trajectory_provider(records: list = None, enable_network: bool = True):
    """Build the time-varying met-ocean callable used by the drift ensemble.

    The ensemble re-samples the field as it walks the trajectory backward, rather
    than holding one vector for 24-48 hours (BUGLOG: "Single met-ocean sample held
    constant across the whole hindcast"). Every sample taken is appended to
    `records`, which becomes the met-ocean provenance section of the evidence
    manifest -- so a reviewer can see exactly which field values drove the result
    and when they were retrieved.

    Args:
        records: list to append provenance entries to.
        enable_network: when False, the provider serves cache-or-default only.
            Used by tests and offline demos so a run never depends on the venue's
            internet connection.
    """
    from datetime import datetime as _dt, timezone as _tz
    if records is None:
        records = []

    def provider(lat: float, lon: float, when):
        if enable_network:
            values = fetch_metocean_vectors(lat, lon, when)
        else:
            cache_key = f"metocean:{lat:.2f}:{lon:.2f}:{when.strftime('%Y%m%d_%H')}"
            values = _cache_get(cache_key) or {
                'wind_speed_mps': 5.0, 'wind_direction_deg': 180.0,
                'current_speed_mps': 0.3, 'current_direction_deg': 90.0,
                'source': 'offline_default',
            }
        records.append({
            'lat': round(float(lat), 4),
            'lon': round(float(lon), 4),
            'time': when.isoformat(),
            'source': values.get('source', 'unknown'),
            'fetched_at': _dt.now(_tz.utc).isoformat(),
            'values': {
                'wind_speed_mps': values.get('wind_speed_mps'),
                'wind_direction_deg': values.get('wind_direction_deg'),
                'current_speed_mps': values.get('current_speed_mps'),
                'current_direction_deg': values.get('current_direction_deg'),
            },
        })
        return values

    provider.records = records
    return provider


def fetch_metocean_timeseries(lat: float, lon: float, start, end) -> dict:
    """Fetch the hourly wind and current field for a whole window in ONE request.

    The per-step provider issues an HTTP call for every hour of the hindcast: a 24 h
    trajectory cost 24 round trips and roughly 34 s of wall clock, which alone blew
    the project's "under 60 seconds" claim. Open-Meteo returns hourly series
    natively, so the entire window is retrieved once and interpolated locally.

    Returns {'hours': [datetime...], 'wind_speed_mps': [...], ...} or {} on failure.
    """
    from datetime import datetime as _dt, timedelta as _td

    if start > end:
        start, end = end, start
    # Pad by an hour each side so the endpoints are always interpolable.
    start = start - _td(hours=1)
    end = end + _td(hours=1)

    cache_key = (f"metocean_ts:{lat:.2f}:{lon:.2f}:"
                 f"{start.strftime('%Y%m%d_%H')}:{end.strftime('%Y%m%d_%H')}")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    out = {}
    try:
        common = {
            'latitude': round(lat, 4), 'longitude': round(lon, 4),
            'start_date': start.strftime('%Y-%m-%d'),
            'end_date': end.strftime('%Y-%m-%d'),
            'timeformat': 'iso8601',
        }
        w = requests.get('https://api.open-meteo.com/v1/forecast', timeout=REQUEST_TIMEOUT_S,
                         params={**common, 'hourly': 'wind_speed_10m,wind_direction_10m',
                                 'wind_speed_unit': 'ms'})
        m = requests.get('https://marine-api.open-meteo.com/v1/marine', timeout=REQUEST_TIMEOUT_S,
                         params={**common,
                                 'hourly': 'ocean_current_velocity,ocean_current_direction',
                                 'current_velocity_unit': 'ms'})
        if not w.ok:
            return {}

        wh = w.json().get('hourly', {})
        times = [_dt.fromisoformat(t).replace(tzinfo=timezone.utc) for t in wh.get('time', [])]
        if not times:
            return {}

        out = {
            'hours': times,
            'wind_speed_mps': wh.get('wind_speed_10m', []),
            'wind_direction_deg': wh.get('wind_direction_10m', []),
            'current_speed_mps': [None] * len(times),
            'current_direction_deg': [None] * len(times),
            'source': 'open-meteo-timeseries',
        }

        if m.ok:
            mh = m.json().get('hourly', {})
            m_times = [_dt.fromisoformat(t).replace(tzinfo=timezone.utc)
                       for t in mh.get('time', [])]
            by_time = {
                t: (v, d) for t, v, d in zip(
                    m_times, mh.get('ocean_current_velocity', []),
                    mh.get('ocean_current_direction', []))
            }
            for i, t in enumerate(times):
                v, d = by_time.get(t, (None, None))
                out['current_speed_mps'][i] = v
                out['current_direction_deg'][i] = d
    except Exception as exc:
        logger.warning(f'Met-ocean time-series fetch failed ({exc}).')
        return {}

    _cache_set(cache_key, out, timeout=CACHE_TTL_SECONDS)
    return out


def make_timeseries_provider(lat: float, lon: float, start, end, records: list = None,
                             fallback: dict = None):
    """A time-varying provider backed by ONE batched fetch instead of N round trips.

    Falls back to `fallback` (typically the single-point sample already taken) for
    any hour the series does not cover, so a partial response degrades the run
    rather than failing it.
    """
    from datetime import datetime as _dt

    if records is None:
        records = []
    fallback = fallback or {
        'wind_speed_mps': 5.0, 'wind_direction_deg': 180.0,
        'current_speed_mps': 0.3, 'current_direction_deg': 90.0,
        'source': 'default_fallback',
    }

    series = fetch_metocean_timeseries(lat, lon, start, end)

    def _at(when):
        if not series or not series.get('hours'):
            return dict(fallback)
        hours = series['hours']
        # Nearest hour; the field is only resolved hourly anyway.
        idx = min(range(len(hours)), key=lambda i: abs((hours[i] - when).total_seconds()))
        values = {}
        for key in ('wind_speed_mps', 'wind_direction_deg',
                    'current_speed_mps', 'current_direction_deg'):
            v = series[key][idx] if idx < len(series[key]) else None
            values[key] = fallback[key] if v is None else float(v)
        values['source'] = series.get('source', 'open-meteo-timeseries')
        return values

    def provider(plat, plon, when):
        values = _at(when)
        records.append({
            'lat': round(float(plat), 4), 'lon': round(float(plon), 4),
            'time': when.isoformat(), 'source': values.get('source', 'unknown'),
            'fetched_at': _dt.now(timezone.utc).isoformat(),
            'values': {k: values.get(k) for k in (
                'wind_speed_mps', 'wind_direction_deg',
                'current_speed_mps', 'current_direction_deg')},
        })
        return values

    provider.records = records
    provider.series_available = bool(series)
    return provider
