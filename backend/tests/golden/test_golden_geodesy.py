"""Golden: geodesy, area, confidence and Bonn volume.

Covers BUGLOG "Spill area omits cos(latitude)" and "Interior holes counted inside
region statistics", and contract `contracts/lookalike_discrimination.md` insofar as
it depends on region masks.

Expected values are computed from spherical geometry by hand in each docstring.
They are NOT captured from a previous run.
"""
import math

import numpy as np
import pytest

from apps.detection.geodesy import (
    polygon_area_sq_km, km_per_deg_lon, haversine_km, normalize_lon, KM_PER_DEG_LAT,
)
from apps.detection.postprocessing import (
    mask_to_polygons, pixels_to_geo, estimate_spill_volume,
)


def test_case1_degree_of_longitude_shrinks_with_latitude():
    """Case 1: one degree of longitude is 111.195*cos(lat) km, not 111.195 km.

    Hand values: cos(0)=1, cos(60)=0.5 exactly, cos(19)=0.945519.
    """
    assert km_per_deg_lon(0.0) == pytest.approx(KM_PER_DEG_LAT, rel=1e-9)
    assert km_per_deg_lon(60.0) == pytest.approx(KM_PER_DEG_LAT * 0.5, rel=1e-9)
    assert km_per_deg_lon(19.0) == pytest.approx(KM_PER_DEG_LAT * 0.9455185756, rel=1e-6)
    # The specific regression: the old code used 111.0 at every latitude.
    assert km_per_deg_lon(60.0) < 0.55 * KM_PER_DEG_LAT


def test_case2_one_degree_box_area_by_latitude():
    """Case 2: a 1x1 degree box has ~12364 km2 at the equator and ~half that at 60N.

    Spherical-excess check: area = R^2 * dlon_rad * (sin(lat2) - sin(lat1)).
    Equator: 6371^2 * (pi/180) * (sin 1 - sin 0)  = 12363.6 km2.
    60-61N : 6371^2 * (pi/180) * (sin 61 - sin 60) = 6088.4 km2.
    """
    eq = polygon_area_sq_km([[0, 0], [1, 0], [1, 1], [0, 1]])
    hi = polygon_area_sq_km([[0, 60], [1, 60], [1, 61], [0, 61]])

    R = 6371.0
    expect_eq = R * R * math.radians(1.0) * (math.sin(math.radians(1)) - math.sin(0))
    expect_hi = R * R * math.radians(1.0) * (
        math.sin(math.radians(61)) - math.sin(math.radians(60)))

    assert eq == pytest.approx(expect_eq, rel=1e-6)
    assert hi == pytest.approx(expect_hi, rel=1e-6)
    # The buggy formula returned the same number at both latitudes.
    assert hi < 0.55 * eq


def test_case3_area_is_not_the_naive_111km_product():
    """Case 3: the old naive formula overstates a 19N slick by ~1/cos(19) = 5.8%."""
    bbox_deg = 0.2
    lat = 19.0
    ring = [[72.0, lat], [72.0 + bbox_deg, lat],
            [72.0 + bbox_deg, lat + bbox_deg], [72.0, lat + bbox_deg]]
    actual = polygon_area_sq_km(ring)
    naive = (bbox_deg * 111.0) * (bbox_deg * 111.0)  # what the old code computed

    assert naive > actual
    overstatement = naive / actual
    assert overstatement == pytest.approx(1.058, abs=0.02), (
        f'expected the legacy formula to overstate by ~5.8% at 19N, got '
        f'{(overstatement - 1) * 100:.1f}%'
    )


def test_case4_antimeridian_and_haversine():
    """Case 4: rings and distances must take the short way round the antimeridian."""
    assert normalize_lon(181.0) == pytest.approx(-179.0)
    assert normalize_lon(-181.0) == pytest.approx(179.0)
    # 2 degrees of longitude at the equator, straddling 180.
    d = haversine_km(0.0, 179.0, 0.0, -179.0)
    assert d == pytest.approx(2 * KM_PER_DEG_LAT, rel=2e-3)
    # A small box straddling the antimeridian must not sweep the globe.
    ring = [[179.5, 0.0], [-179.5, 0.0], [-179.5, 1.0], [179.5, 1.0]]
    assert polygon_area_sq_km(ring) < 2.0 * 12364.0


def test_case5_holes_excluded_from_confidence_and_mask():
    """Case 5 (BUGLOG: interior holes counted inside region statistics).

    A 100x100 px oil annulus at posterior 0.90 with a 40x40 px open-water hole at
    0.02. Confidence must be 0.90, the oil's value, not the hole-diluted average
    (8400*0.90 + 1600*0.02)/10000 = 0.759.
    """
    mask = np.zeros((200, 200), np.uint8)
    mask[50:150, 50:150] = 255
    mask[80:120, 80:120] = 0

    prob = np.full((200, 200), 0.02, np.float32)
    prob[50:150, 50:150] = 0.90
    prob[80:120, 80:120] = 0.02

    region = mask_to_polygons(mask, prob_map=prob)[0]

    assert len(region['holes']) == 1
    assert region['confidence'] == pytest.approx(0.90, abs=0.01)
    assert region['confidence'] > 0.85, 'hole pixels are diluting the confidence again'
    # Mask covers the annulus only: 100*100 - 40*40 = 8400 px, allowing for
    # contour discretisation at the boundary.
    assert 8100 <= int(region['region_mask'].sum()) <= 8500


def test_case6_net_area_subtracts_holes():
    """Case 6: a ring's reported area is the annulus, not the filled outer square."""
    mask = np.zeros((200, 200), np.uint8)
    mask[50:150, 50:150] = 255
    mask[80:120, 80:120] = 0
    regions = mask_to_polygons(mask)
    geo = pixels_to_geo(regions, 200, 200, bbox=(72.0, 19.0, 72.2, 19.2))

    outer_only = polygon_area_sq_km(geo[0]['polygon_geojson']['coordinates'][0])
    assert geo[0]['area_sq_km'] < outer_only
    assert geo[0]['area_sq_km'] == pytest.approx(outer_only * 0.84, rel=0.08)


def test_case7_bonn_volume_is_a_range_with_a_caveat():
    """Case 7: 1 km2 of 'rainbow' oil is 0.30-5.0 um thick => 0.3-5.0 m3.

    1 km2 = 1e6 m2. 1e6 * 0.30e-6 m = 0.30 m3. 1e6 * 5.0e-6 m = 5.0 m3.
    """
    v = estimate_spill_volume(1.0, 'rainbow')
    assert v['volume_m3_min'] == pytest.approx(0.30, abs=1e-6)
    assert v['volume_m3_max'] == pytest.approx(5.00, abs=1e-6)
    assert v['volume_m3_min'] < v['volume_m3_max']
    # A single-look SAR scene cannot measure thickness; the caveat must survive.
    assert 'thickness' in v['caveat'].lower()
    assert estimate_spill_volume(None)['volume_m3_max'] == 0.0


def test_case8_ungeoreferenced_regions_get_no_coordinates():
    """Case 8: without a bbox, centroids stay None so nothing can be attributed.

    This is the Layer 3 georeference gate's precondition.
    """
    mask = np.zeros((200, 200), np.uint8)
    mask[50:150, 50:150] = 255
    geo = pixels_to_geo(mask_to_polygons(mask), 200, 200, bbox=None)

    assert geo[0]['centroid_lat'] is None
    assert geo[0]['centroid_lon'] is None
    assert geo[0]['area_sq_km'] is None
    assert geo[0]['is_georeferenced'] is False
