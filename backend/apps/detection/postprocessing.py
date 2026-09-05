import cv2
import numpy as np

def mask_to_polygons(mask: np.ndarray, min_area_pixels: int = 100) -> list[dict]:
    """
    Extracts polygons from a binary mask.
    """
    # Ensure mask is uint8 and binary (0 and 255)
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    
    # Threshold just to be safe
    _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    results = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area >= min_area_pixels:
            # Calculate centroid
            M = cv2.moments(contour)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
            else:
                cx, cy = 0, 0
                
            # Convert contour to list of points
            polygon = contour.reshape(-1, 2).tolist()
            
            # Since mask is thresholded, confidence is just 1.0 for detected areas 
            # (or we could compute mean on soft probs, but we only have binary mask here)
            confidence = 1.0
            
            results.append({
                "polygon": polygon,
                "area_pixels": int(area),
                "centroid": [cx, cy],
                "confidence": confidence
            })
            
    return results

def pixels_to_geo(polygons: list[dict], image_width: int, image_height: int, bbox: tuple = None) -> list[dict]:
    """Converts pixel contours to geographic coordinates if bbox is provided.

    If bbox is None, strictly keeps coordinates in image pixel space and marks
    is_georeferenced=False, setting centroids to None to prevent false maritime attribution.
    """
    processed_polygons = []

    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        lon_range = max_lon - min_lon
        lat_range = max_lat - min_lat

        for poly_data in polygons:
            poly_pixels = poly_data["polygon"]
            geo_polygon = []
            for x, y in poly_pixels:
                lon = min_lon + (x / image_width) * lon_range
                lat = max_lat - (y / image_height) * lat_range
                geo_polygon.append([lon, lat])

            if geo_polygon and geo_polygon[0] != geo_polygon[-1]:
                geo_polygon.append(geo_polygon[0])

            cx, cy = poly_data["centroid"]
            c_lon = min_lon + (cx / image_width) * lon_range
            c_lat = max_lat - (cy / image_height) * lat_range
            area_sq_km = poly_data["area_pixels"] * ((lon_range * 111.0) / image_width) * ((lat_range * 111.0) / image_height)

            processed_polygons.append({
                "polygon_geojson": {
                    "type": "Polygon",
                    "coordinates": [geo_polygon]
                },
                "centroid_lon": c_lon,
                "centroid_lat": c_lat,
                "area_sq_km": area_sq_km,
                "confidence": poly_data["confidence"],
                "is_georeferenced": True,
            })
    else:
        # Non-georeferenced image: do NOT invent coordinates!
        for poly_data in polygons:
            poly_pixels = poly_data["polygon"]
            # Store pixel coordinates normalized to [0, 1] for relative overlay
            pixel_polygon = []
            for x, y in poly_pixels:
                pixel_polygon.append([round(x / image_width, 5), round(y / image_height, 5)])

            if pixel_polygon and pixel_polygon[0] != pixel_polygon[-1]:
                pixel_polygon.append(pixel_polygon[0])

            processed_polygons.append({
                "polygon_geojson": {
                    "type": "Polygon",
                    "coordinates": [pixel_polygon]
                },
                "centroid_lon": None,
                "centroid_lat": None,
                "area_sq_km": None,
                "confidence": poly_data["confidence"],
                "is_georeferenced": False,
            })

    return processed_polygons
