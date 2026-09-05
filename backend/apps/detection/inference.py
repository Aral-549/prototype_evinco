import json
import logging
import os
import pickle
import numpy as np
import torch
import torch.nn as nn
from django.conf import settings

logger = logging.getLogger('pipeline')


# ── Baseline UNet Architecture ─────────────────────────────────
class ConvBlock(nn.Module):
    """Conv block matching the training code's structure.

    The checkpoint stores weights under `enc1.conv.0.weight` etc.,
    which means the training code used a Module with a `.conv`
    Sequential attribute rather than a bare Sequential.
    """

    def __init__(self, in_c, out_c):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_c, out_c, 3, padding=1),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_c, out_c, 3, padding=1),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.conv(x)


class UNet(nn.Module):
    """Custom 4-stage UNet matching best_unet_dice_0.8018 weights."""

    def __init__(self, in_channels=3, out_channels=1):
        super().__init__()
        self.enc1 = ConvBlock(in_channels, 64)
        self.enc2 = ConvBlock(64, 128)
        self.enc3 = ConvBlock(128, 256)
        self.enc4 = ConvBlock(256, 512)
        self.pool = nn.MaxPool2d(2)
        self.bottleneck = ConvBlock(512, 1024)
        self.up4 = nn.ConvTranspose2d(1024, 512, kernel_size=2, stride=2)
        self.dec4 = ConvBlock(1024, 512)
        self.up3 = nn.ConvTranspose2d(512, 256, kernel_size=2, stride=2)
        self.dec3 = ConvBlock(512, 256)
        self.up2 = nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2)
        self.dec2 = ConvBlock(256, 128)
        self.up1 = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.dec1 = ConvBlock(128, 64)
        self.final = nn.Conv2d(64, out_channels, kernel_size=1)

    def forward(self, x):
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        e4 = self.enc4(self.pool(e3))
        b = self.bottleneck(self.pool(e4))
        d4 = self.dec4(torch.cat([self.up4(b), e4], dim=1))
        d3 = self.dec3(torch.cat([self.up3(d4), e3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))
        return self.final(d1)


# ── Checkpoint & Metadata Loaders ──────────────────────────────
def _load_checkpoint_directory(path: str):
    """Load a PyTorch checkpoint saved in directory format (data.pkl + data/<key>)."""

    class _StorageLoader:
        def __init__(self, data_dir):
            self.data_dir = data_dir
            self._cache = {}

        def __call__(self, saved_id):
            if not isinstance(saved_id, tuple) or saved_id[0] != 'storage':
                raise RuntimeError(f'Unknown persistent_load id: {saved_id}')

            storage_type = saved_id[1]
            key = str(saved_id[2])
            numel = saved_id[4]

            if key in self._cache:
                return self._cache[key]

            data_path = os.path.join(self.data_dir, 'data', key)
            nbytes = os.path.getsize(data_path)
            untyped = torch.UntypedStorage.from_file(
                data_path, shared=False, nbytes=nbytes
            )

            dtype = (
                storage_type.dtype
                if hasattr(storage_type, 'dtype')
                else torch.float32
            )
            typed = torch.storage.TypedStorage(
                wrap_storage=untyped, dtype=dtype, _internal=True
            )
            self._cache[key] = typed
            return typed

    pkl_path = os.path.join(path, 'data.pkl')
    with open(pkl_path, 'rb') as f:
        unpickler = pickle.Unpickler(f)
        unpickler.persistent_load = _StorageLoader(path)
        state_dict = unpickler.load()

    return state_dict


def find_model_metadata(checkpoint_path: str) -> dict:
    """Discover model_info.json sidecar next to the checkpoint or in parent folders."""
    candidates = [
        os.path.join(checkpoint_path, 'model_info.json'),
        os.path.join(os.path.dirname(checkpoint_path), 'model_info.json'),
        os.path.join(os.path.dirname(os.path.dirname(checkpoint_path)), 'model_info.json'),
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data['metadata_file'] = c
                    return data
            except Exception as e:
                logger.warning(f"Could not parse model metadata sidecar at {c}: {e}")

    # Default fallback metadata
    base_name = os.path.basename(os.path.normpath(checkpoint_path))
    return {
        "name": base_name or "Unknown UNet",
        "version": "1.0.0",
        "architecture": "custom_unet",
        "checkpoint_id": base_name,
        "dice_score": None,
        "iou_score": None,
        "input_channels": 3,
        "input_size": getattr(settings, 'UNET_INPUT_SIZE', 256),
        "stride": 224,
        "normalization": getattr(settings, 'MODEL_NORMALIZATION', 'scale_0_1'),
        "threshold": getattr(settings, 'UNET_THRESHOLD', 0.5),
        "metadata_file": None,
    }


def clean_state_dict(state_dict: dict) -> dict:
    """Unwrap common nested keys (state_dict, model) and strip DistributedDataParallel prefixes."""
    if isinstance(state_dict, dict):
        for wrapper_key in ('state_dict', 'model_state_dict', 'model'):
            if wrapper_key in state_dict and isinstance(state_dict[wrapper_key], dict):
                state_dict = state_dict[wrapper_key]
                break

    cleaned = {}
    for k, v in state_dict.items():
        name = k
        if name.startswith('module.'):
            name = name[7:]
        elif name.startswith('model.'):
            name = name[6:]
        cleaned[name] = v
    return cleaned


def instantiate_model(architecture: str, in_channels: int = 3, out_channels: int = 1, encoder_name: str = 'resnet34'):
    """Factory creating the model backbone according to metadata specification."""
    arch = (architecture or 'custom_unet').lower()
    if arch in ('custom_unet', 'unet'):
        return UNet(in_channels=in_channels, out_channels=out_channels)
    elif arch in ('smp_unet', 'segmentation_models_pytorch'):
        try:
            import segmentation_models_pytorch as smp
            return smp.Unet(
                encoder_name=encoder_name,
                encoder_weights=None,
                in_channels=in_channels,
                classes=out_channels,
            )
        except ImportError:
            logger.warning("segmentation_models_pytorch not installed; falling back to custom UNet")
            return UNet(in_channels=in_channels, out_channels=out_channels)
    else:
        logger.info(f"Unrecognized architecture '{arch}', defaulting to custom UNet.")
        return UNet(in_channels=in_channels, out_channels=out_channels)


def ensure_checkpoint_assembled(path: str) -> str:
    """If path does not exist, automatically reassemble from .part_* chunks if present."""
    if not os.path.exists(path):
        import glob
        chunks = sorted(glob.glob(f"{path}.part_*"))
        if chunks:
            logger.info(f"Assembling split checkpoint {path} from {len(chunks)} chunks...")
            with open(path, 'wb') as outfile:
                for chunk in chunks:
                    with open(chunk, 'rb') as infile:
                        outfile.write(infile.read())
            logger.info(f"Successfully assembled {path} ({os.path.getsize(path)} bytes)")
    return path


# ── Model Manager Singleton (Hot-Swap & Fail-Safe Enabled) ──────
class ModelManager:
    """Singleton that loads the active ML model, enforces I/O contracts,

    and performs automatic fail-safe fallback if a newly configured checkpoint fails.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance.model = None
            cls._instance.model_info = {}
            cls._instance.active_checkpoint = None
            cls._instance.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        return cls._instance

    def _load_single_checkpoint(self, path: str):
        """Attempt to load a model and weights from path."""
        path = ensure_checkpoint_assembled(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Checkpoint path does not exist: {path}")

        meta = find_model_metadata(path)
        arch = meta.get('architecture', 'custom_unet')
        in_ch = meta.get('input_channels', 3)
        encoder = meta.get('encoder_name', 'resnet34')

        # Check if full TorchScript model
        if not os.path.isdir(path):
            try:
                ts_model = torch.jit.load(path, map_location=self.device)
                ts_model.eval()
                return ts_model, meta
            except Exception:
                # Not a TorchScript file; proceed to standard weight loading
                pass

        # Load weights
        if os.path.isdir(path):
            state_dict = _load_checkpoint_directory(path)
        else:
            loaded = torch.load(path, map_location=self.device, weights_only=False)
            if isinstance(loaded, nn.Module):
                loaded.eval()
                return loaded, meta
            state_dict = loaded

        cleaned_weights = clean_state_dict(state_dict)

        # Build and populate architecture
        model = instantiate_model(arch, in_channels=in_ch, out_channels=1, encoder_name=encoder)
        model.load_state_dict(cleaned_weights)
        model.to(self.device)
        model.eval()
        return model, meta

    def _ensure_loaded(self, force_reload: bool = False):
        if self._initialized and not force_reload:
            return

        primary_path = str(getattr(settings, 'MODEL_CHECKPOINT_PATH', settings.UNET_CHECKPOINT))
        fallback_path = str(getattr(settings, 'MODEL_FALLBACK_CHECKPOINT', primary_path))

        try:
            logger.info(f"Loading primary oil spill detection model from: {primary_path}")
            model, meta = self._load_single_checkpoint(primary_path)
            meta['is_fallback'] = False
            self.model = model
            self.model_info = meta
            self.active_checkpoint = primary_path
            logger.info(
                f"Model successfully loaded: '{meta.get('name')}' "
                f"(Dice: {meta.get('dice_score')}, Device: {self.device})"
            )
        except Exception as exc:
            logger.error(
                f"FAIL-SAFE TRIGGERED: Failed to load primary model checkpoint '{primary_path}': {exc}. "
                f"Attempting automatic fallback to known-good checkpoint '{fallback_path}'..."
            )
            try:
                model, meta = self._load_single_checkpoint(fallback_path)
                meta['is_fallback'] = True
                meta['fallback_reason'] = str(exc)
                self.model = model
                self.model_info = meta
                self.active_checkpoint = fallback_path
                logger.warning(
                    f"Fail-safe fallback successful: Loaded '{meta.get('name')}' from {fallback_path}"
                )
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Fatal ML Error: Neither primary checkpoint ({primary_path}) nor "
                    f"fallback checkpoint ({fallback_path}) could be loaded. "
                    f"Primary error: {exc}. Fallback error: {fallback_exc}"
                ) from fallback_exc

        self._initialized = True

    def reload(self, checkpoint_path: str = None) -> dict:
        """Dynamically reload the model from a new checkpoint path without server restart."""
        if checkpoint_path:
            settings.MODEL_CHECKPOINT_PATH = checkpoint_path
        self._ensure_loaded(force_reload=True)
        return self.get_model_info()

    def get_model_info(self) -> dict:
        """Return metadata of currently active model."""
        self._ensure_loaded()
        return dict(self.model_info)

    def normalize_tile(self, tile: np.ndarray) -> np.ndarray:
        """Standardize tile normalization according to model metadata."""
        mode = self.model_info.get('normalization', 'scale_0_1')

        if tile.dtype == np.uint8:
            tile = tile.astype(np.float32) / 255.0
        else:
            tile = tile.astype(np.float32)

        if mode == 'imagenet':
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            tile = (tile - mean) / std

        return tile

    def predict_single_tile(self, tile: np.ndarray) -> np.ndarray:
        """Run inference on a single 256x256x3 tile.

        Returns probability map (256, 256) as float32 in [0, 1].
        """
        self._ensure_loaded()
        norm_tile = self.normalize_tile(tile)

        tensor = (
            torch.from_numpy(norm_tile)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(self.device, dtype=torch.float32)
        )

        with torch.no_grad():
            out = self.model(tensor)
            # Apply sigmoid only if output is unbounded raw logits
            min_val = float(out.min())
            max_val = float(out.max())
            if min_val < 0.0 or max_val > 1.0:
                prob = torch.sigmoid(out)
            else:
                prob = out

        return prob.squeeze().cpu().numpy().astype(np.float32)

    def predict(self, image: np.ndarray) -> np.ndarray:
        """Run tiled inference on a full image.

        Args:
            image: (H, W, 3) uint8 or float32 array.

        Returns:
            Binary mask (H, W) as uint8, values 0 or 255.
        """
        self._ensure_loaded()

        H, W, _C = image.shape
        tile_size = int(self.model_info.get('input_size', getattr(settings, 'UNET_INPUT_SIZE', 256)))
        stride = int(self.model_info.get('stride', 224))
        threshold = float(self.model_info.get('threshold', getattr(settings, 'UNET_THRESHOLD', 0.5)))

        # Pad so we can tile evenly
        pad_h = max(tile_size - H, 0) if H < tile_size else (
            0 if H % stride == 0 else stride - (H % stride)
        )
        pad_w = max(tile_size - W, 0) if W < tile_size else (
            0 if W % stride == 0 else stride - (W % stride)
        )

        padded = np.pad(
            image, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect'
        )
        H_pad, W_pad = padded.shape[:2]

        prob_mask = np.zeros((H_pad, W_pad), dtype=np.float32)

        for y in range(0, H_pad - tile_size + 1, stride):
            for x in range(0, W_pad - tile_size + 1, stride):
                tile = padded[y : y + tile_size, x : x + tile_size, :]
                pred = self.predict_single_tile(tile)
                prob_mask[y : y + tile_size, x : x + tile_size] = np.maximum(
                    prob_mask[y : y + tile_size, x : x + tile_size], pred
                )

        binary_mask = (prob_mask[:H, :W] > threshold).astype(np.uint8) * 255
        return binary_mask
