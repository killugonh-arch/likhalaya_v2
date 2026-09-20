from pathlib import Path
import os
from datetime import timedelta
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-likhalaya-pdl-marketplace-change-in-production-2026'
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [
    '10.178.80.208', '127.0.0.1', 'localhost',
    '192.168.1.7', '192.168.254.139', '192.168.254.160',
    '.onrender.com',  # render deployment
]

_LOCAL_INSECURE_TEST = os.environ.get('DJANGO_INSECURE_LOCAL', 'False') == 'True'

if not DEBUG:
    if not _LOCAL_INSECURE_TEST:
        SECURE_SSL_REDIRECT = True
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # local apps
    'store',
    'accounts',
    'orders',
    'dashboard',
    # api
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'axes',
    'api',
    # cloudinary
    'cloudinary',
    'cloudinary_storage',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serve static files on render
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'likhalaya_project.middleware.StaffIdleTimeoutMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'likhalaya_project.middleware.RestrictDjangoAdminMiddleware',
    'axes.middleware.AxesMiddleware',  # must be last
]

ROOT_URLCONF = 'likhalaya_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'likhalaya_project.context_processors.global_context',
            ],
        },
    },
]
WSGI_APPLICATION = 'likhalaya_project.wsgi.application'

# use postgres on render, sqlite locally
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'

# cloudinary for all media (images + videos)
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY'),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET'),
}
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# videos use cloudinary video storage
CLOUDINARY_VIDEO_STORAGE = 'cloudinary_storage.storage.VideoMediaCloudinaryStorage'

# gcash qr config
GCASH_ACCOUNT_NAME = os.environ.get('GCASH_ACCOUNT_NAME', 'Deniel Bryan Perea')
GCASH_ACCOUNT_NUMBER = os.environ.get('GCASH_ACCOUNT_NUMBER', '09751548542')
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.CustomUser'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',  # must be first
    'accounts.backends.UsernameOrEmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# 5 failed logins locks account+ip for 1 hour
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_USERNAME_CALLABLE = 'accounts.axes_utils.get_username'
AXES_HTTP_RESPONSE_CODE = 429
AXES_LOCKOUT_TEMPLATE = 'accounts/locked.html'

if os.environ.get('DJANGO_BEHIND_PROXY', 'False') == 'True':
    AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR']
    AXES_IPWARE_PROXY_COUNT = int(os.environ.get('DJANGO_PROXY_COUNT', '1'))
else:
    AXES_IPWARE_META_PRECEDENCE_ORDER = ['REMOTE_ADDR']

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

CART_SESSION_ID = 'cart'

from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'secondary',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

# email - set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD env vars
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = f'Likhalaya <{EMAIL_HOST_USER}>' if EMAIL_HOST_USER else 'Likhalaya <noreply@likhalaya.local>'

# fallback to console if no credentials set
if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
        'user': '120/minute',
        'login': '5/minute',
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
        'security_file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'security.log',
        },
    },
    'loggers': {
        'security': {
            'handlers': ['console', 'security_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'axes': {
            'handlers': ['console', 'security_file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=14),
    'ROTATE_REFRESH_TOKENS': True,
}

CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'False') == 'True'
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if os.environ.get('CORS_ALLOWED_ORIGINS') else []

# message encryption key - set via env var in production
MESSAGE_ENCRYPTION_KEY = os.environ.get(
    'MESSAGE_ENCRYPTION_KEY',
    'Yj9y5oNQ5o3cQb1t9zW1nQwqz6XwK1r9Cq8y2s5aB0o='  # dev only
)