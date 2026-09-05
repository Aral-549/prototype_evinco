import os
import numpy as np
from PIL import Image


def validate_sar_characteristics(rgb_arr: np.ndarray) -> tuple[bool, str]:
    """Validate whether an image exhibits the statistical physical signatures of SAR imagery

    (single-band/dual-pol channel correlation, absence of solid flat synthetic blocks).

    Rejects non-SAR inputs (colored photos, memes, text screenshots) to avoid out-of-distribution
    false positives, while safely passing single-band, dual-pol, and real satellite SAR scenes.
    """
    if rgb_arr.ndim != 3 or rgb_arr.shape[2] < 3:
        return True, 'Passed (single-band/grayscale SAR)'

    r = rgb_arr[:, :, 0].astype(float)
    g = rgb_arr[:, :, 1].astype(float)
    b = rgb_arr[:, :, 2].astype(float)

    # Signal 1: Channel decorrelation (real SAR exports have R≈G≈B; optical/memes/text differ)
    std_r, std_g, std_b = np.std(r), np.std(g), np.std(b)
    stds = [std_r, std_g, std_b]
    low_variance_count = sum(s <= 1.0 for s in stds)

    if low_variance_count == 3:
        # All channels flat: if means differ, it's a solid non-grayscale color
        mean_diff = max(abs(np.mean(r) - np.mean(g)), abs(np.mean(g) - np.mean(b)), abs(np.mean(r) - np.mean(b)))
        min_corr = 0.0 if mean_diff > 5.0 else 1.0
    elif low_variance_count > 0:
        # Some channels flat while others vary -> completely decorrelated
        min_corr = 0.0
    else:
        corr_rg = np.corrcoef(r.flatten(), g.flatten())[0, 1]
        corr_gb = np.corrcoef(g.flatten(), b.flatten())[0, 1]
        corr_rb = np.corrcoef(r.flatten(), b.flatten())[0, 1]
        min_corr = float(min(corr_rg, corr_gb, corr_rb))

    is_decorrelated = min_corr < 0.98
    is_strongly_decorrelated = min_corr < 0.85

    # Signal 2: Speckle vs flat synthetic zero-variance blocks (text/UI screenshots)
    gray = np.mean(rgb_arr[:, :, :3], axis=-1)
    H, W = gray.shape
    patch_size = 16
    zero_var_patches = 0
    total_patches = 0

    step_y = max(patch_size, H // 32)
    step_x = max(patch_size, W // 32)
    for y in range(0, H - patch_size, step_y):
        for x in range(0, W - patch_size, step_x):
            patch = gray[y:y+patch_size, x:x+patch_size]
            total_patches += 1
            if np.var(patch) < 0.5:
                zero_var_patches += 1

    flat_ratio = zero_var_patches / max(total_patches, 1)
    is_flat_synthetic = flat_ratio > 0.30
    is_mostly_flat = flat_ratio > 0.50

    # Decision rule:
    # 1. Optical photo / colored meme / UI with colored text -> is_strongly_decorrelated -> REJECT
    # 2. Both signals disagree: color decorrelation AND flat synthetic blocks -> REJECT
    # 3. Patch variance is completely zero across large regions (>50% flat computer blocks, e.g. text/docs) -> REJECT
    if is_strongly_decorrelated or (is_decorrelated and is_flat_synthetic) or is_mostly_flat:
        reasons = []
        if is_strongly_decorrelated or is_decorrelated:
            reasons.append(f'channel decorrelation ({min_corr:.3f} < 0.98)')
        if is_mostly_flat:
            reasons.append(f'unnatural zero-variance flat blocks ({flat_ratio*100:.1f}% > 50%)')
        elif is_flat_synthetic:
            reasons.append(f'unnatural zero-variance flat blocks ({flat_ratio*100:.1f}% > 30%)')
        return False, f"OOD Rejection: Input image does not exhibit SAR backscatter signatures [{', '.join(reasons)}]."

    return True, f'Passed SAR verification (min_corr={min_corr:.3f}, flat_ratio={flat_ratio*100:.1f}%)'


def extract_geotiff_bbox(img: Image.Image) -> tuple | None:
    """Extract WGS-84 geographic bounding box from GeoTIFF tags if present.

    Tags: ModelTiepointTag (33922), ModelPixelScaleTag (33550).
    """
    try:
        if not hasattr(img, 'tag_v2'):
            return None

        tiepoint = img.tag_v2.get(33922)
        scale = img.tag_v2.get(33550)

        if tiepoint and scale and len(tiepoint) >= 6 and len(scale) >= 2:
            min_lon = float(tiepoint[3])
            max_lat = float(tiepoint[4])
            max_lon = min_lon + float(img.width * scale[0])
            min_lat = max_lat - float(img.height * scale[1])
            # Basic sanity bounds check
            if -180 <= min_lon <= 180 and -90 <= min_lat <= 90:
                return (min_lon, min_lat, max_lon, max_lat)
    except Exception:
        pass
    return None


def load_image(file_path: str, user_bbox: tuple = None, validate_sar: bool = True) -> tuple[np.ndarray, dict]:
    """Load image, validate SAR characteristics (OOD gate), and extract georeference metadata.

    Returns:
        (image_array, metadata)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Image not found at {file_path}")

    try:
        with Image.open(file_path) as img:
            extracted_bbox = extract_geotiff_bbox(img)
            raw_arr = np.array(img)
    except Exception as exc:
        raise ValueError(f"Unable to decode image file ({exc})")

    if raw_arr.size == 0:
        raise ValueError("Decoded image is empty (0 pixels).")

    # Handle float arrays (common in raw satellite SAR backscatter)
    if np.issubdtype(raw_arr.dtype, np.floating):
        min_val = float(np.nanmin(raw_arr))
        max_val = float(np.nanmax(raw_arr))
        if max_val > min_val:
            norm_arr = (raw_arr - min_val) / (max_val - min_val) * 255.0
        else:
            norm_arr = np.zeros_like(raw_arr)
        arr_uint8 = np.nan_to_num(norm_arr, nan=0.0).clip(0, 255).astype(np.uint8)

    # Handle 16-bit unsigned integers (common in radar amplitude data)
    elif raw_arr.dtype == np.uint16:
        arr_uint8 = (raw_arr / 256.0).clip(0, 255).astype(np.uint8)

    elif raw_arr.dtype != np.uint8:
        min_v = float(raw_arr.min())
        max_v = float(raw_arr.max())
        if max_v > min_v:
            arr_uint8 = ((raw_arr - min_v) / (max_v - min_v) * 255.0).astype(np.uint8)
        else:
            arr_uint8 = np.zeros(raw_arr.shape[:2], dtype=np.uint8)
    else:
        arr_uint8 = raw_arr

    # Normalize channel dimensionality to (H, W, 3)
    if arr_uint8.ndim == 2:
        rgb_arr = np.stack([arr_uint8, arr_uint8, arr_uint8], axis=-1)
    elif arr_uint8.ndim == 3:
        if arr_uint8.shape[2] == 1:
            rgb_arr = np.repeat(arr_uint8, 3, axis=2)
        elif arr_uint8.shape[2] == 3:
            rgb_arr = arr_uint8
        elif arr_uint8.shape[2] >= 4:
            rgb_arr = arr_uint8[:, :, :3]
        elif arr_uint8.shape[2] == 2:
            vv = arr_uint8[:, :, 0].astype(np.float32) + 1e-5
            vh = arr_uint8[:, :, 1].astype(np.float32) + 1e-5
            ratio = np.clip((vh / vv) * 128.0, 0, 255).astype(np.uint8)
            rgb_arr = np.stack([arr_uint8[:, :, 0], arr_uint8[:, :, 1], ratio], axis=-1)
        else:
            raise ValueError(f"Unsupported channel shape: {arr_uint8.shape}")
    else:
        raise ValueError(f"Unsupported image array dimensions: {arr_uint8.ndim}")

    # Layer 1: SAR Out-Of-Distribution (OOD) Validation Gate
    if validate_sar:
        is_valid_sar, reason = validate_sar_characteristics(rgb_arr)
        if not is_valid_sar:
            raise ValueError(reason)

    # Layer 3: Georeference verification
    final_bbox = user_bbox or extracted_bbox
    is_georeferenced = final_bbox is not None

    H, W, _ = rgb_arr.shape
    metadata = {
        'width': W,
        'height': H,
        'num_channels': 3,
        'bbox': final_bbox,
        'is_georeferenced': is_georeferenced,
        'original_dtype': str(raw_arr.dtype),
    }

    return rgb_arr, metadata
