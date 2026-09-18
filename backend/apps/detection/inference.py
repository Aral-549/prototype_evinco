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
        unpickler = _RestrictedUnpickler(f)
        unpickler.persistent_load = _StorageLoader(path)
        state_dict = unpickler.load()

    return state_dict


# Globals a legitimate PyTorch state dict needs to reconstruct itself. Anything
# outside this set is refused: `os.system`, `subprocess.Popen`, `builtins.eval` and
# every other gadget a malicious checkpoint would reach for.
_PICKLE_ALLOWLIST = {
    'torch': {
        'FloatStorage', 'DoubleStorage', 'HalfStorage', 'BFloat16Storage',
        'LongStorage', 'IntStorage', 'ShortStorage', 'CharStorage', 'ByteStorage',
        'BoolStorage', 'ComplexFloatStorage', 'ComplexDoubleStorage', 'Size',
        'dtype', 'device',
    },
    'torch._utils': {'_rebuild_tensor', '_rebuild_tensor_v2', '_rebuild_parameter'},
    'collections': {'OrderedDict', 'defaultdict'},
    'numpy.core.multiarray': {'scalar', '_reconstruct'},
    'numpy': {'dtype', 'ndarray'},
}


class UnsafeCheckpointError(RuntimeError):
    """Raised when a checkpoint tries to reconstruct something outside the allowlist."""


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that refuses any global a state dict has no business referencing.

    A PyTorch checkpoint is a pickle, and unpickling is arbitrary code execution:
    an object with a `__reduce__` returning `(os.system, ("...",))` runs that command
    the instant the file is read, BEFORE any architecture or tensor-shape check can
    reject it. Verified against this codebase -- a 2 KB file advertising
    `val_dice: 0.99` executed a shell command during load.

    That is the ordinary ML supply chain: checkpoints are downloaded from model zoos,
    shared over chat, and dropped into `ai_model/weights/` exactly as this project's
    own hot-swap instructions describe. The file is treated as data, so it has to be
    parsed as data.
    """

    def find_class(self, module, name):
        allowed = _PICKLE_ALLOWLIST.get(module)
        if allowed and name in allowed:
            return super().find_class(module, name)
        raise UnsafeCheckpointError(
            f'Refusing to load checkpoint: it references {module}.{name}, which a '
            f'model state dict has no legitimate reason to reconstruct. This is the '
            f'signature of a checkpoint carrying an executable payload. If this file '
            f'is genuinely trusted, convert it with '
            f'`torch.save(model.state_dict(), path)` from a trusted environment.'
        )


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
    elif arch in ('segformer', 'segformer_b0', 'mit_b0'):
        from .architectures.segformer import SegFormer
        return SegFormer(in_channels=in_channels, num_classes=out_channels)
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
            cls._instance.output_activation = 'logits'
            # Ensemble members: list of (model, meta, activation). Empty means the
            # single-model path is in use.
            cls._instance.ensemble = []
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
            # weights_only=True parses the checkpoint as DATA: tensors, dicts,
            # lists and primitives only, with no global lookups and therefore no
            # code execution. The previous weights_only=False was a confirmed RCE.
            # ALLOW_UNSAFE_CHECKPOINTS exists only for a legacy full-module
            # checkpoint that cannot be re-exported, and is off by default.
            allow_unsafe = bool(getattr(settings, 'ALLOW_UNSAFE_CHECKPOINTS', False))
            try:
                loaded = torch.load(path, map_location=self.device, weights_only=True)
            except Exception as exc:
                if not allow_unsafe:
                    raise UnsafeCheckpointError(
                        f'Checkpoint {path} could not be loaded in safe mode ({exc}). '
                        f'It may contain pickled objects beyond plain tensors, which '
                        f'cannot be parsed without executing code. Re-export it with '
                        f'`torch.save(model.state_dict(), path)` from a trusted '
                        f'environment, or set ALLOW_UNSAFE_CHECKPOINTS=true if you '
                        f'control the file and accept the risk.'
                    ) from exc
                logger.warning(
                    f'ALLOW_UNSAFE_CHECKPOINTS is set; loading {path} with pickle '
                    f'execution enabled. This runs whatever code the file contains.'
                )
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

        # Resolve the head's activation once, now that a model is loaded.
        self.output_activation = self._probe_output_activation()
        self.model_info['output_activation'] = self.output_activation

        self._load_ensemble()
        self._initialized = True

    def _load_ensemble(self):
        """Load additional checkpoints to average with the primary model.

        Two independently-trained architectures fail in different places. Measured
        across the synthetic benchmark suite, the U-Net scores 0.000 effective Dice
        on one scene where SegFormer manages 0.141, and SegFormer scores 0.000 on a
        scene where the U-Net reaches 0.994. Averaging their posteriors inherits
        whichever was right rather than splitting the difference: the ensemble
        reaches 0.613 against 0.590 and 0.401 for the members alone, and on the
        noisiest scene it beats BOTH (0.958 against 0.578 and 0.931).

        This is a structural gain that needs no tuning, which matters because the
        benchmark is synthetic: a threshold fitted to it would not transfer, but
        "average two models at their own thresholds" does.

        A member that fails to load is skipped with a warning rather than taking
        down inference -- degrading to a smaller ensemble is always better than
        serving nothing.
        """
        self.ensemble = []
        paths = list(getattr(settings, 'MODEL_ENSEMBLE', []) or [])
        if not paths:
            return

        for path in paths:
            path = str(path)
            try:
                if os.path.abspath(path) == os.path.abspath(str(self.active_checkpoint)):
                    continue  # already loaded as the primary
                model, meta = self._load_single_checkpoint(path)
                activation = self._probe_activation_for(model, meta)
                self.ensemble.append({
                    'model': model, 'meta': meta, 'activation': activation,
                    'path': path,
                })
                logger.info(f"Ensemble member loaded: {meta.get('name')} ({path})")
            except Exception as exc:
                logger.warning(
                    f'Ensemble member {path} could not be loaded ({exc}); continuing '
                    f'without it.'
                )

        if self.ensemble:
            self.model_info['ensemble_members'] = (
                [self.model_info.get('name')] + [m['meta'].get('name') for m in self.ensemble]
            )
            self.model_info['ensemble_size'] = len(self.ensemble) + 1

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

    def normalize_tile(self, tile: np.ndarray, meta: dict = None) -> np.ndarray:
        """Standardize tile normalization according to model metadata.

        Each ensemble member normalises by its OWN sidecar. Feeding a model inputs
        scaled the way a different model was trained is a silent accuracy loss that
        no test would catch.
        """
        mode = (meta or self.model_info).get('normalization', 'scale_0_1')

        if tile.dtype == np.uint8:
            tile = tile.astype(np.float32) / 255.0
        else:
            tile = tile.astype(np.float32)

        if mode == 'imagenet':
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            tile = (tile - mean) / std

        return tile

    def _probe_output_activation(self) -> str:
        """Determine once, at load time, whether the head emits logits or probabilities.

        BUGLOG: this used to be decided per-tile by inspecting the output range
        (`if out.min() < 0 or out.max() > 1: sigmoid`). That test fails silently
        for any tile whose logits all happen to land inside [0, 1] -- common on
        low-contrast open water -- and raw logits were then read as probabilities,
        inflating scores (logit 0.9 is p=0.71, not p=0.90). Whether a head is
        activated is a property of the checkpoint, not of one tile's values, so
        it is resolved once here and reused.

        An explicit `output_activation` key in model_info.json always wins.
        """
        return self._probe_activation_for(self.model, self.model_info)

    def _probe_activation_for(self, model, meta) -> str:
        """Resolve a model's output activation from metadata, else by probing."""
        declared = str((meta or {}).get('output_activation', '')).lower()
        if declared:
            logger.info(f'Model declares output_activation={declared}; probe skipped.')
        if declared in ('logits', 'linear', 'none'):
            return 'logits'
        if declared in ('sigmoid', 'probability', 'probabilities'):
            return 'sigmoid'

        size = int((meta or {}).get('input_size', 256))
        in_ch = int((meta or {}).get('input_channels', 3))
        # Three probes spanning the input range. A sigmoid head cannot produce a
        # value outside [0, 1] for ANY input; a linear head almost always will
        # for at least one of these.
        probes = [
            torch.zeros((1, in_ch, size, size), device=self.device),
            torch.ones((1, in_ch, size, size), device=self.device),
            torch.full((1, in_ch, size, size), -3.0, device=self.device),
        ]
        with torch.no_grad():
            for probe in probes:
                try:
                    out = model(probe)
                except Exception as exc:
                    logger.warning(
                        f'Activation probe failed ({exc}); assuming raw logits, which is '
                        f'the safe default -- an extra sigmoid on probabilities only '
                        f'compresses scores, whereas a missing one inflates them.'
                    )
                    return 'logits'
                if float(out.min()) < 0.0 or float(out.max()) > 1.0:
                    return 'logits'

        # Reached only when every probe stayed inside [0,1]. That is consistent with a
        # sigmoid head, but ALSO with a logit head whose outputs happen to be confined
        # -- the two are not distinguishable by inspecting outputs, which is the whole
        # reason the original per-tile heuristic was unsound. Declaring
        # `output_activation` in model_info.json is the only reliable answer; this
        # branch is a fallback and says so.
        logger.warning(
            'Activation could not be determined from metadata and was GUESSED as '
            '"sigmoid" because every probe output stayed within [0,1]. A logit head '
            'with confined outputs is indistinguishable here and would be scored too '
            'high. Declare "output_activation": "logits" or "sigmoid" in '
            'model_info.json to remove this ambiguity.'
        )
        return 'sigmoid'

    def predict_single_tile(self, tile: np.ndarray, model=None, activation: str = None,
                            meta: dict = None) -> np.ndarray:
        """Run inference on a single tile. Returns float32 posterior in [0, 1].

        `model`/`activation`/`meta` default to the primary model; ensemble members
        pass their own so each is normalised and activated the way IT was trained,
        rather than inheriting the primary's settings.
        """
        self._ensure_loaded()
        model = model if model is not None else self.model
        activation = activation or self.output_activation
        norm_tile = self.normalize_tile(tile, meta)

        tensor = (
            torch.from_numpy(norm_tile)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(self.device, dtype=torch.float32)
        )

        with torch.no_grad():
            out = model(tensor)
            if activation == 'logits':
                out = torch.sigmoid(out)

        return out.squeeze().cpu().numpy().astype(np.float32).clip(0.0, 1.0)

    @staticmethod
    def _blend_window(size: int) -> np.ndarray:
        """2-D raised-cosine (Hann) weight, high in the tile centre, ~0 at its edge.

        BUGLOG: overlaps used to be fused with `np.maximum`, so a single
        over-confident tile won outright over its neighbours. Every
        disagreement therefore resolved in favour of detection, and U-Net edge
        artefacts -- which are worst exactly at tile borders -- were preserved
        rather than averaged away, leaving visible seams on the stride grid.
        Weighting by distance from the tile centre makes each pixel's posterior
        a smooth average dominated by the tile that saw it with the most
        context.
        """
        w = np.hanning(size + 2)[1:-1].astype(np.float32)  # drop the exact zeros
        window = np.outer(w, w)
        return np.maximum(window, 1e-3)  # never let a pixel have zero total weight

    def predict_proba(self, image: np.ndarray, tta: bool = None) -> tuple:
        """Tiled inference returning the continuous posterior, not a binary mask.

        Args:
            image: (H, W, 3) uint8 or float32.
            tta: run 4-way flip test-time augmentation. Defaults to the
                MODEL_TTA setting. TTA also yields a free epistemic-uncertainty
                map: the per-pixel spread across the augmented views.

        Returns:
            (prob_map, uncertainty_map) -- both (H, W) float32.
            `uncertainty_map` is the std across TTA views, or zeros when tta=False.
        """
        self._ensure_loaded()

        if tta is None:
            tta = bool(getattr(settings, 'MODEL_TTA', False))

        # ── Input purification (adversarial defence) ──────────────
        # An L-inf bounded attack is high-frequency by construction: it has to stay
        # within a couple of grey levels per pixel, so it works by scattering tiny
        # sign-flips across the image. An oil slick is the opposite -- a large,
        # smooth, low-frequency structure. A small median filter therefore destroys
        # the perturbation while leaving the signal essentially intact.
        # Measured: a PGD evasion that drove detection to 0.000 Dice is restored to
        # 0.552 by a 3x3 median, against 0.573 clean and unfiltered.
        purify = int(getattr(settings, 'MODEL_PURIFY', 0) or 0)
        if purify > 1:
            from scipy import ndimage
            image = np.stack(
                [ndimage.median_filter(image[:, :, c], size=purify)
                 for c in range(image.shape[2])], axis=-1)

        H, W, _C = image.shape
        tile_size = int(self.model_info.get('input_size', getattr(settings, 'UNET_INPUT_SIZE', 256)))
        stride = int(self.model_info.get('stride', 224))
        stride = max(1, min(stride, tile_size))

        pad_h = max(tile_size - H, 0) if H < tile_size else (
            0 if H % stride == 0 else stride - (H % stride)
        )
        pad_w = max(tile_size - W, 0) if W < tile_size else (
            0 if W % stride == 0 else stride - (W % stride)
        )

        padded = np.pad(image, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')
        H_pad, W_pad = padded.shape[:2]

        window = self._blend_window(tile_size)

        # Flip transforms as (numpy axes to flip). Identity first.
        views = [()] if not tta else [(), (0,), (1,), (0, 1)]

        # accumulate sum and sum-of-squares across views for mean and std
        acc = np.zeros((len(views), H_pad, W_pad), dtype=np.float32)

        for vi, axes in enumerate(views):
            weight_sum = np.zeros((H_pad, W_pad), dtype=np.float32)
            prob_sum = np.zeros((H_pad, W_pad), dtype=np.float32)

            view_img = np.flip(padded, axis=axes).copy() if axes else padded

            for y in range(0, H_pad - tile_size + 1, stride):
                for x in range(0, W_pad - tile_size + 1, stride):
                    tile = view_img[y:y + tile_size, x:x + tile_size, :]

                    pred = self.predict_single_tile(tile)
                    if self.ensemble:
                        member_preds = [pred]
                        for member in self.ensemble:
                            member_preds.append(self.predict_single_tile(
                                tile, member['model'], member['activation'],
                                member['meta']))

                        combiner = str(getattr(settings, 'MODEL_COMBINER', 'mean')).lower()
                        if combiner == 'max':
                            # Evasion-resistant: an attacker must defeat EVERY member,
                            # because one member still detecting is enough. Averaging
                            # cannot make that claim -- a confident 0 from an attacked
                            # member and a confident 1 from an honest one average to
                            # exactly the decision boundary, so a single compromised
                            # member can veto the rest.
                            pred = np.maximum.reduce(member_preds)
                        else:
                            # Equal-weight average. Unequal weights would need a
                            # validation set to fit, and fitting them on the synthetic
                            # benchmark would not transfer to real imagery.
                            pred = sum(member_preds) / len(member_preds)

                    prob_sum[y:y + tile_size, x:x + tile_size] += pred * window
                    weight_sum[y:y + tile_size, x:x + tile_size] += window

            view_prob = prob_sum / np.maximum(weight_sum, 1e-6)
            # undo the flip so all views land in the same frame
            acc[vi] = np.flip(view_prob, axis=axes) if axes else view_prob

        prob_map = acc.mean(axis=0)[:H, :W]
        uncertainty = (acc.std(axis=0)[:H, :W] if len(views) > 1
                       else np.zeros((H, W), dtype=np.float32))

        return prob_map.astype(np.float32), uncertainty.astype(np.float32)

    def predict(self, image: np.ndarray) -> np.ndarray:
        """Tiled inference returning a binary mask (H, W) uint8 of 0 or 255.

        Retained for backward compatibility. New callers should prefer
        `predict_proba`, which keeps the posterior so that downstream stages can
        report a real confidence instead of a hardcoded 1.0.
        """
        prob_map, _ = self.predict_proba(image)
        threshold = float(self.model_info.get('threshold', getattr(settings, 'UNET_THRESHOLD', 0.5)))
        return (prob_map > threshold).astype(np.uint8) * 255
