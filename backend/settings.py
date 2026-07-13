import os
from pathlib import Path
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Cargar variables de entorno desde .env ─────────────────────────────────
_env_path = BASE_DIR / '.env'
if _env_path.exists():
    for _line in _env_path.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _key, _, _val = _line.partition('=')
            os.environ.setdefault(_key.strip(), _val.strip())

# ── Seguridad ───────────────────────────────────────────────────────────────
DEBUG       = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-fallback-key-change-me!'
    else:
        raise ImproperlyConfigured('SECRET_KEY no está definido en .env (requerido fuera de DEBUG).')

_hosts_raw = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1')
ALLOWED_HOSTS = [h.strip() for h in _hosts_raw.split(',') if h.strip()]

# En Railway hay que setear CSRF_TRUSTED_ORIGINS con el dominio real de producción
# (p. ej. "https://scs-frontend.up.railway.app"), separado por comas si hay más de uno.
CSRF_TRUSTED_ORIGINS = os.environ.get(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:5173,https://localhost:5173'
).split(',')

# URL del frontend, usada para armar links absolutos en correos (p. ej. el
# link al folio del FUS en las notificaciones).
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173')

# ── Aplicaciones ────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'autenticacion',
    'catalogos',
    'solicitudes',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'
ASGI_APPLICATION  = 'backend.asgi.application'

# ── Channel Layer — Redis si REDIS_URL está definido (requiere channels_redis
#    instalado); si no, InMemoryChannelLayer (solo válido con un único worker).
_redis_url = os.environ.get('REDIS_URL')
if _redis_url:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [_redis_url]},
        }
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

# ── Base de datos ────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME':     os.environ.get('DB_NAME',     'SCS'),
        'USER':     os.environ.get('DB_USER',     'root'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST':     os.environ.get('DB_HOST',     'localhost'),
        'PORT':     os.environ.get('DB_PORT',     '3306'),
    }
}

# ── Validación de contraseñas ────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── CORS ─────────────────────────────────────────────────────────────────────
# CORS_ALLOW_ALL_ORIGINS ('*') no funciona con cookies cross-origin (refresh
# token httpOnly), así que siempre se usa una lista explícita de orígenes.
_cors_raw = os.environ.get('CORS_ORIGINS', '')
if _cors_raw:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
else:
    CORS_ALLOWED_ORIGINS = ['http://localhost:5173', 'https://localhost:5173']  # solo desarrollo local sin .env

CORS_ALLOW_CREDENTIALS = True

# ── JWT ──────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '300/minute',
        'login': '10/minute',
        'otp':   '5/minute',
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
}

# ── Internacionalización ─────────────────────────────────────────────────────
LANGUAGE_CODE = 'es-mx'
TIME_ZONE      = 'America/Mexico_City'
USE_I18N       = True
USE_TZ         = True

# ── Static / Media ───────────────────────────────────────────────────────────
STATIC_URL = 'static/'
MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Correo electrónico ───────────────────────────────────────────────────────
EMAIL_BACKEND      = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST         = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT         = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS      = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
EMAIL_HOST_USER    = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD= os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@anam.gob.mx')
