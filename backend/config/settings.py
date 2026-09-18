import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Declared once, up here, because several blocks below branch on it: the cache
# backend, and the API keys the suite authenticates with.
RUNNING_TESTS = 'pytest' in sys.modules or os.getenv('CACHE_BACKEND') == 'locmem'

# Add ai_model to sys.path
if (REPO_ROOT / 'ai_model').exists() and str(REPO_ROOT / 'ai_model') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'ai_model'))

SECRET_KEY = 'django-insecure-prototype-key-change-in-production'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'corsheaders',
    'rest_framework',
    'drf_spectacular',
    # Project apps
    'apps.detection',
    'apps.drift',
    'apps.ais',
    'apps.pipeline',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            REPO_ROOT / 'frontend' / 'templates',
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ── Database Configuration (PostGIS with SQLite Fallback) ──────
USE_POSTGIS = os.getenv('USE_POSTGIS', 'false').lower() == 'true'

if USE_POSTGIS:
    DATABASES = {
        'default': {
            'ENGINE': 'django.contrib.gis.db.backends.postgis',
            'NAME': os.getenv('DB_NAME', 'oilspill'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }
    if 'django.contrib.gis' not in INSTALLED_APPS:
        INSTALLED_APPS.append('django.contrib.gis')
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [
    p for p in [REPO_ROOT / 'frontend' / 'static', BASE_DIR / 'static'] if p.exists()
]

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── DRF & OpenAPI Spectacular Settings ─────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.pipeline.authentication.APIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'apps.pipeline.permissions.IsAuthenticatedOrUnconfigured',
    ],
}

# ── API authentication ─────────────────────────────────────────
# The console produces material that accuses ships of pollution, so "who submitted
# this scene" is recorded, not optional. Keys are supplied as comma-separated
# label:key pairs, e.g. MARSLICK_API_KEYS="coastguard:abc123,ntro:def456".
# Set REQUIRE_API_KEY=false for an unauthenticated local demo.
def _parse_api_keys(raw: str) -> dict:
    keys = {}
    for pair in (raw or '').split(','):
        pair = pair.strip()
        if not pair:
            continue
        label, _, key = pair.partition(':')
        if key:
            keys[label.strip()] = key.strip()
    return keys


API_KEYS = _parse_api_keys(os.getenv('MARSLICK_API_KEYS', ''))
REQUIRE_API_KEY = os.getenv('REQUIRE_API_KEY', 'true').lower() == 'true'

# Tests authenticate with this key rather than bypassing the permission layer, so
# the auth path is exercised by the suite instead of being disabled in it.
if RUNNING_TESTS:
    API_KEYS = {'test': 'test-key-not-for-production'}

SPECTACULAR_SETTINGS = {
    'TITLE': 'SIH26143 Maritime Oil Spill Detection & Attribution API',
    'DESCRIPTION': 'Automated forensic pipeline for SAR satellite oil slick detection, hydrodynamic drift hindcast, and AIS vessel attribution (NTRO).',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# ── Cache Settings ─────────────────────────────────────────────
# In-process locmem cache — no external service required.
# Metocean API responses are cached here for 30 min; they are
# automatically evicted when the process restarts, which is fine
# for a development/demo server. Add a persistent backend (e.g.
# diskcache or filesystem) if you need the cache to survive restarts.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'marslick-cache',
    }
}


# ── Structured Logging Configuration ───────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'config.logging.JSONFormatter',
        },
        'simple': {
            'format': '[%(asctime)s] %(levelname)s [%(name)s]: %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json' if os.getenv('LOG_JSON', 'true').lower() == 'true' else 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'pipeline': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    }
}

# ── ML Model Configuration (Hot-Swap Enabled) ─────────────────
AI_MODEL_DIR = REPO_ROOT / 'ai_model'
ML_MODELS_DIR = AI_MODEL_DIR / 'weights' if (AI_MODEL_DIR / 'weights').exists() else (BASE_DIR / 'ml_models')
CALIBRATION_DIR = AI_MODEL_DIR / 'calibration_data' if (AI_MODEL_DIR / 'calibration_data').exists() else (BASE_DIR / 'calibration_data')

DEFAULT_MODEL_CHECKPOINT = ML_MODELS_DIR / 'best_unet_dice_0.8018' / 'best_unet'

# Primary active checkpoint path (overridable via environment variable)
MODEL_CHECKPOINT_PATH = Path(os.getenv('MODEL_CHECKPOINT_PATH', str(DEFAULT_MODEL_CHECKPOINT)))
# Guaranteed fallback checkpoint if the primary model fails to load
MODEL_FALLBACK_CHECKPOINT = DEFAULT_MODEL_CHECKPOINT

# Backwards-compatible aliases
UNET_CHECKPOINT = MODEL_CHECKPOINT_PATH
UNET_INPUT_SIZE = int(os.getenv('MODEL_INPUT_SIZE', '256'))
UNET_THRESHOLD = float(os.getenv('MODEL_THRESHOLD', '0.5'))
MODEL_NORMALIZATION = os.getenv('MODEL_NORMALIZATION', 'scale_0_1')
# 4-way flip test-time augmentation: ~4x inference cost, and yields a per-pixel
# epistemic uncertainty map as a by-product. Off by default so the demo stays fast.
# 4-way flip TTA. MEASURED HARMFUL on this task and off by default: SAR carries a
# directional cross-swath incidence gradient, so a flipped tile is an input the model
# never saw during training. On the calibration scene it cost 7 points of Dice
# (0.575 -> 0.506) and 16 points of recall (0.962 -> 0.801) for 4x the compute.
# Kept available because it also yields a per-pixel uncertainty map.
MODEL_TTA = os.getenv('MODEL_TTA', 'false').lower() == 'true'

# ── Model ensemble ─────────────────────────────────────────────
# Averaging two independently-trained architectures. They fail in different places:
# across the synthetic benchmark the U-Net scores 0.000 effective Dice on a scene
# where SegFormer reaches 0.141, and SegFormer scores 0.000 where the U-Net reaches
# 0.994. The average inherits whichever was right instead of splitting the
# difference -- 0.613 effective Dice against 0.590 and 0.401 for the members alone,
# and 0.958 against 0.578/0.931 on the noisiest scene.
# Set MODEL_ENSEMBLE=off to run the primary checkpoint alone.
_SEGFORMER = ML_MODELS_DIR / 'best_segformer_b0' / 'best_segformer_b0.pt'
if os.getenv('MODEL_ENSEMBLE', 'on').lower() in ('off', 'false', '0'):
    MODEL_ENSEMBLE = []
else:
    MODEL_ENSEMBLE = [str(_SEGFORMER)] if _SEGFORMER.exists() else []

# ── Look-Alike Discrimination (Layer 2 safeguard) ──────────────
# SAR dark patches are not all oil. These gate the physics-informed classifier.
LOOKALIKE_WIND_MIN_MPS = float(os.getenv('LOOKALIKE_WIND_MIN_MPS', '3.0'))
LOOKALIKE_WIND_MAX_MPS = float(os.getenv('LOOKALIKE_WIND_MAX_MPS', '12.0'))
LOOKALIKE_REJECT_BELOW = float(os.getenv('LOOKALIKE_REJECT_BELOW', '0.35'))

# ── Drift Ensemble ─────────────────────────────────────────────
DRIFT_ENSEMBLE_PARTICLES = int(os.getenv('DRIFT_ENSEMBLE_PARTICLES', '500'))
DRIFT_ENSEMBLE_SEED = int(os.getenv('DRIFT_ENSEMBLE_SEED', '42'))

# ── Attribution ────────────────────────────────────────────────
ATTRIBUTION_CAPTURE_RADIUS_KM = float(os.getenv('ATTRIBUTION_CAPTURE_RADIUS_KM', '5.0'))
ATTRIBUTION_PRIOR_UNKNOWN = float(os.getenv('ATTRIBUTION_PRIOR_UNKNOWN', '0.25'))

# ── Conclusion robustness audit ────────────────────────────────
ROBUSTNESS_SCENARIOS = int(os.getenv('ROBUSTNESS_SCENARIOS', '32'))
ROBUSTNESS_SEED = int(os.getenv('ROBUSTNESS_SEED', '7'))

# ── Checkpoint loading safety ──────────────────────────────────
# A PyTorch checkpoint is a pickle, and unpickling is arbitrary code execution.
# Verified against this codebase: a 2 KB file advertising `val_dice: 0.99` ran a
# shell command during load, before any architecture check could reject it. Loading
# is therefore done in data-only mode. Enable this ONLY for a legacy full-module
# checkpoint you control and cannot re-export.
ALLOW_UNSAFE_CHECKPOINTS = os.getenv('ALLOW_UNSAFE_CHECKPOINTS', 'false').lower() == 'true'

# ── Adversarial defence ────────────────────────────────────────
# How ensemble members are combined. 'mean' is the more accurate combiner on clean
# imagery; 'max' is the evasion-resistant one, because an attacker must defeat every
# member rather than just one. See ai_model/scripts/benchmark_models.py.
MODEL_COMBINER = os.getenv('MODEL_COMBINER', 'mean').lower()

# Median-filter window applied to the input before inference. 0 or 1 disables it.
# A bounded adversarial perturbation is high-frequency by construction; an oil slick
# is a large smooth structure. A 3x3 median removes the former and keeps the latter.
MODEL_PURIFY = int(os.getenv('MODEL_PURIFY', '0'))

# ── File Upload Limits ─────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024

# ── CORS Configuration for Frontend Development ───────────────
CORS_ALLOW_ALL_ORIGINS = os.getenv('CORS_ALLOW_ALL_ORIGINS', 'true').lower() == 'true'
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:5173',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:5173',
]
CORS_ALLOW_CREDENTIALS = True

