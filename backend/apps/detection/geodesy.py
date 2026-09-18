"""Geodetic helpers shared by the detection and drift stages.

Centralised here because getting a degree of longitude wrong is the single
easiest way to produce a confidently incorrect area, volume or drift distance,
and the same conversion was previously open-coded in several places.
"""
import math

# WGS-84 mean radius, metres. Matches the value already used by the drift engine.
R_EARTH_M = 6_371_000.0
R_EARTH_KM = 6371.0

# Length of one degree of latitude, km. Constant to within 1% over the globe.
KM_PER_DEG_LAT = 111.195


def km_per_deg_lon(latitude_deg: float) -> float:
    """Length of one degree of longitude in km at the given latitude.

    This is `KM_PER_DEG_LAT * cos(lat)`. Omitting the cosine is the cause of
    BUGLOG entry "Spill area omits cos(latitude)".
    """
    return KM_PER_DEG_LAT * math.cos(math.radians(latitude_deg))


def polygon_area_sq_km(ring_lonlat: list) -> float:
    """Geodesic area of a closed lon/lat ring, in square kilometres.

    Uses the spherical excess formula (L'Huilier / Green's theorem on the
    sphere), which is exact for a spherical Earth and therefore correct at any
    latitude, across the equator, and for rings of any size. Orientation is
    ignored; the absolute area is returned.

    Args:
        ring_lonlat: [[lon, lat], ...]. May or may not repeat the first point.

    Returns:
        Area in km^2. Returns 0.0 for degenerate rings of fewer than 3 points.
    """
    pts = list(ring_lonlat)
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return 0.0

    total = 0.0
    n = len(pts)
    for i in range(n):
        lon1, lat1 = pts[i]
        lon2, lat2 = pts[(i + 1) % n]
        # Shortest-path longitude difference, so rings spanning the antimeridian
        # accumulate correctly instead of sweeping the long way round the globe.
        dlon = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
        total += dlon * (2.0 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))

    return abs(total * R_EARTH_KM * R_EARTH_KM / 2.0)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2.0 * R_EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def normalize_lon(lon: float) -> float:
    """Wrap a longitude into [-180, 180)."""
    return ((lon + 180.0) % 360.0) - 180.0
