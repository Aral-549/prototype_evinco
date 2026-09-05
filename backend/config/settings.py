import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

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
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'SIH26143 Maritime Oil Spill Detection & Attribution API',
    'DESCRIPTION': 'Automated forensic pipeline for SAR satellite oil slick detection, hydrodynamic drift hindcast, and AIS vessel attribution (NTRO).',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# ── Celery Broker & Task Queue Settings ─────────────────────────
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ROUTES = {
    'apps.detection.tasks.*': {'queue': 'detection_queue'},
    'apps.drift.tasks.*': {'queue': 'drift_queue'},
    'apps.ais.tasks.*': {'queue': 'ais_queue'},
    'apps.pipeline.tasks.*': {'queue': 'default'},
}

# ── Redis Cache Settings ───────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.getenv('REDIS_CACHE_URL', 'redis://localhost:6379/2'),
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

