"""Stage 1 output boundary: binary/probabilistic mask -> georeferenced spill regions.

Three things changed here relative to the first prototype, each logged in BUGLOG.md:

1. Area is computed geodesically instead of treating a degree of longitude as
   111 km everywhere, which overstated every area (and every volume derived
   from it) by a factor of 1/cos(latitude).
2. Polygon confidence is the mean U-Net posterior inside the contour rather
   than a hardcoded 1.0.
3. Interior holes are preserved, so a ring-shaped slick no longer has its
   centre counted as oil.
"""
import logging

import cv2
import numpy as np

from .geodesy import polygon_area_sq_km, normalize_lon

logger = logging.getLogger('pipeline')


# Bonn Agreement Oil Appearance Code (BAOAC) thickness bands, in micrometres.
# Source: Bonn Agreement Aerial Operations Handbook, Oil Appearance Code.
BONN_THICKNESS_UM = {
    'sheen':                 (0.04, 0.30),
    'rainbow':               (0.30, 5.00),
    'metallic':              (5.00, 50.0),
    'discontinuous_true_colour': (50.0, 200.0),
    'continuous_true_colour':    (200.0, 1000.0),
}

# SAR measures surface-roughness damping, not film thickness. Absent an optical
# or hyperspectral observation the appearance code is unknown, so the default
# spans the range a radar-detectable mineral oil film plausibly occupies.
SAR_DEFAULT_APPEARANCE = 'rainbow'


def estimate_spill_volume(area_sq_km: float, appearance_code: str = SAR_DEFAULT_APPEARANCE) -> dict:
    """Estimate oil volume in cubic metres from slick area via Bonn Agreement bands.

    Returns a range, never a point estimate, and carries its own caveat string.
    A single-look SAR scene cannot measure film thickness; anyone quoting one
    number from this function is over-claiming.
    """
    if area_sq_km is None or area_sq_km <= 0:
        return {
            'volume_m3_min': 0.0, 'volume_m3_max': 0.0,
            'appearance_code': appearance_code, 'thickness_um_min': 0.0,
            'thickness_um_max': 0.0, 'caveat': 'No georeferenced area available.',
        }

    code = appearance_code if appearance_code in BONN_THICKNESS_UM else SAR_DEFAULT_APPEARANCE
    t_min_um, t_max_um = BONN_THICKNESS_UM[code]

    area_m2 = area_sq_km * 1_000_000.0
    # micrometres -> metres is 1e-6
    volume_min = area_m2 * t_min_um * 1e-6
    volume_max = area_m2 * t_max_um * 1e-6

    return {
        'volume_m3_min': round(volume_min, 3),
        'volume_m3_max': round(volume_max, 3),
        'appearance_code': code,
        'thickness_um_min': t_min_um,
        'thickness_um_max': t_max_um,
        'caveat': (
            'SAR measures surface-roughness damping, not film thickness. This range assumes '
            f"Bonn Agreement appearance code '{code}' and is indicative only; confirmation "
            'requires an optical, hyperspectral or in-situ observation.'
        ),
    }


def _contour_stats(contour, prob_map, mask_shape, hole_contours=None):
    """Mean and 90th-percentile posterior strictly inside a contour, holes excluded.

    Holes must be punched out before any statistic is taken. A ring-shaped slick's
    centre is open water: counting it would deflate the region's confidence, and
    the same mask is handed to the look-alike classifier, where including open
    water inside the region would corrupt both the interior-homogeneity and the
    damping-contrast measurements.
    """
    filled = np.zeros(mask_shape, dtype=np.uint8)
    cv2.drawContours(filled, [contour], -1, color=1, thickness=cv2.FILLED)
    if hole_contours:
        cv2.drawContours(filled, hole_contours, -1, color=0, thickness=cv2.FILLED)
    region_mask = filled.astype(bool)

    if prob_map is None:
        return 1.0, 1.0, region_mask

    inside = prob_map[region_mask]
    if inside.size == 0:
        return 0.0, 0.0, region_mask
    return float(inside.mean()), float(np.percentile(inside, 90)), region_mask


def mask_to_polygons(mask: np.ndarray, min_area_pixels: int = 100,
                     prob_map: np.ndarray = None) -> list[dict]:
    """Extract polygons (with interior holes) from a binary mask.

    Args:
        mask: (H, W) uint8, 0 or 255.
        min_area_pixels: discard specks below this pixel area.
        prob_map: optional (H, W) float32 posterior in [0, 1]. When supplied,
            each region's confidence is the mean posterior inside its contour
            instead of a placeholder 1.0.

    Returns:
        List of dicts with keys: polygon, holes, area_pixels, perimeter_pixels,
        centroid, confidence, confidence_p90, shape_complexity, region_mask.
    """
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)

    if prob_map is not None and prob_map.shape[:2] != mask.shape[:2]:
        raise ValueError(
            f'prob_map shape {prob_map.shape[:2]} does not match mask shape {mask.shape[:2]}'
        )

    _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)

    # RETR_CCOMP gives a two-level hierarchy: outer boundaries and their holes.
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]

    results = []
    for idx, contour in enumerate(contours):
        # hierarchy[idx] = [next, previous, first_child, parent]
        if hierarchy[idx][3] != -1:
            continue  # this is a hole; it is collected by its parent below

        outer_area = cv2.contourArea(contour)

        holes = []
        hole_contours = []
        hole_area = 0.0
        child = hierarchy[idx][2]
        while child != -1:
            h_contour = contours[child]
            h_area = cv2.contourArea(h_contour)
            if h_area >= min_area_pixels:
                holes.append(h_contour.reshape(-1, 2).tolist())
                hole_contours.append(h_contour)
                hole_area += h_area
            child = hierarchy[child][0]

        net_area = outer_area - hole_area
        if net_area < min_area_pixels:
            continue

        moments = cv2.moments(contour)
        if moments['m00'] != 0:
            cx = int(moments['m10'] / moments['m00'])
            cy = int(moments['m01'] / moments['m00'])
        else:
            pts = contour.reshape(-1, 2)
            cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())

        conf_mean, conf_p90, region_mask = _contour_stats(
            contour, prob_map, binary.shape, hole_contours)

        perimeter = float(cv2.arcLength(contour, True))
        # Isoperimetric ratio: 1.0 for a perfect circle, larger for elongated or
        # ragged shapes. Ship-discharge slicks are characteristically linear.
        shape_complexity = (
            (perimeter ** 2) / (4.0 * np.pi * outer_area) if outer_area > 0 else 0.0
        )

        results.append({
            'polygon': contour.reshape(-1, 2).tolist(),
            'holes': holes,
            'area_pixels': int(net_area),
            'perimeter_pixels': perimeter,
            'centroid': [cx, cy],
            'confidence': round(conf_mean, 4),
            'confidence_p90': round(conf_p90, 4),
            'shape_complexity': round(float(shape_complexity), 4),
            'region_mask': region_mask,
        })

    results.sort(key=lambda r: r['area_pixels'], reverse=True)
    return results


def pixels_to_geo(polygons: list[dict], image_width: int, image_height: int,
                  bbox: tuple = None) -> list[dict]:
    """Convert pixel contours to geographic coordinates when a bbox is available.

    Without a bbox, coordinates stay in normalised image space and centroids are
    left as None so that no maritime attribution can be built on invented
    coordinates (the Layer 3 georeference gate depends on this).
    """
    processed = []

    if bbox is None:
        for poly in polygons:
            ring = [
                [round(x / image_width, 6), round(y / image_height, 6)]
                for x, y in poly['polygon']
            ]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])

            hole_rings = []
            for hole in poly.get('holes', []):
                hr = [[round(x / image_width, 6), round(y / image_height, 6)] for x, y in hole]
                if hr and hr[0] != hr[-1]:
                    hr.append(hr[0])
                hole_rings.append(hr)

            processed.append({
                'polygon_geojson': {'type': 'Polygon', 'coordinates': [ring] + hole_rings},
                'centroid_lon': None,
                'centroid_lat': None,
                'area_sq_km': None,
                'confidence': poly['confidence'],
                'confidence_p90': poly.get('confidence_p90', poly['confidence']),
                'shape_complexity': poly.get('shape_complexity'),
                'volume_estimate': estimate_spill_volume(None),
                'is_georeferenced': False,
                'region_mask': poly.get('region_mask'),
            })
        return processed

    min_lon, min_lat, max_lon, max_lat = bbox
    lon_range = max_lon - min_lon
    lat_range = max_lat - min_lat

    def to_geo(x, y):
        return [
            normalize_lon(min_lon + (x / image_width) * lon_range),
            max_lat - (y / image_height) * lat_range,
        ]

    for poly in polygons:
        ring = [to_geo(x, y) for x, y in poly['polygon']]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])

        hole_rings = []
        hole_area = 0.0
        for hole in poly.get('holes', []):
            hr = [to_geo(x, y) for x, y in hole]
            if hr and hr[0] != hr[-1]:
                hr.append(hr[0])
            hole_rings.append(hr)
            hole_area += polygon_area_sq_km(hr)

        cx, cy = poly['centroid']
        c_lon, c_lat = to_geo(cx, cy)

        # Geodesic area of the outer ring minus its holes. Correct at any latitude.
        area_sq_km = max(polygon_area_sq_km(ring) - hole_area, 0.0)

        processed.append({
            'polygon_geojson': {'type': 'Polygon', 'coordinates': [ring] + hole_rings},
            'centroid_lon': c_lon,
            'centroid_lat': c_lat,
            'area_sq_km': area_sq_km,
            'confidence': poly['confidence'],
            'confidence_p90': poly.get('confidence_p90', poly['confidence']),
            'shape_complexity': poly.get('shape_complexity'),
            'volume_estimate': estimate_spill_volume(area_sq_km),
            'is_georeferenced': True,
            'region_mask': poly.get('region_mask'),
        })

    return processed
