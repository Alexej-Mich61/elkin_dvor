# config/settings.py
from pathlib import Path
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = os.getenv('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Для sitemap.xml (sites + sitemaps)
    "django.contrib.sites",
    "django.contrib.sitemaps",
    # Сторонние пакеты
    'tailwind',  # Утилиты Tailwind для Django
    # Наши приложения
    'theme',  # Стили Tailwind
    'shop', # <--- приложение магазина
    'cart', # <--- сессионная корзина
    'orders', # <--- промокоды и расчёт (заказы — этап 5)
]

# Dev-only приложения подключаем только при DEBUG, не попадают в production
if DEBUG:
    INSTALLED_APPS += ['django_browser_reload']  # Автообновление страницы в браузере при разработке

# Настройка Tailwind
TAILWIND_APP_NAME = 'theme'
# Путь к npm: из окружения; по умолчанию npm ищется в PATH.
# На Windows нужен именно npm.cmd: django-tailwind запускает его через subprocess без shell.
NPM_BIN_PATH = os.getenv('NPM_BIN_PATH', 'npm.cmd' if os.name == 'nt' else 'npm')

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    MIDDLEWARE += ['django_browser_reload.middleware.BrowserReloadMiddleware']

ROOT_URLCONF = "config.urls"

# Для sitemap.xml: единственный сайт проекта (домен задаётся в админке).
SITE_ID = 1

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        'DIRS': [BASE_DIR / 'templates'], # <--- папка шаблонов
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Контакты магазина (телефон, мессенджеры, адрес) для всех страниц
                "shop.context_processors.contacts",
                # Счётчик товаров в корзине для шапки
                "cart.context_processors.cart_counter",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "ru-ru"

TIME_ZONE = "Europe/Moscow"

USE_I18N = True

USE_TZ = True


# Настройка статики
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] # Папка для наших JS и картинок
STATIC_ROOT = BASE_DIR / 'staticfiles' # Целевая папка collectstatic при развёртывании

# Медиа: загружаемые файлы (изображения товаров и т.п.)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration
# Новый интерфейс Django 6.1: MAILERS вместо классических EMAIL_* настроек.
# SMTP-параметры читаем из .env; если EMAIL_HOST не задан — console backend:
# письма выводятся в консоль, этого достаточно для локальной разработки.
if os.getenv("EMAIL_HOST"):
    _default_mailer = {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": os.getenv("EMAIL_HOST"),
            "port": int(os.getenv("EMAIL_PORT", "465")),
            "username": os.getenv("EMAIL_HOST_USER", ""),
            "password": os.getenv("EMAIL_HOST_PASSWORD", ""),
            "use_tls": os.getenv("EMAIL_USE_TLS", "False") == "True",
            "use_ssl": os.getenv("EMAIL_USE_SSL", "True") == "True",
            "timeout": int(os.getenv("EMAIL_TIMEOUT", "15")),
        },
    }
else:
    _default_mailer = {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    }

MAILERS = {"default": _default_mailer}
# Отправитель исходящих писем (по умолчанию — адрес, реальный задаётся в .env).
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@elkin-dvor.ru")

# Логирование отправки почты: отдельный файл + консоль, и в dev, и в prod.
# Обработчика писем крутит планировщик ОС (например, send_emails.bat).
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "mail": {
            "format": "[{asctime}] {levelname}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "mail_console": {
            "class": "logging.StreamHandler",
            "formatter": "mail",
        },
        "mail_file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": LOGS_DIR / "mail.log",
            "when": "midnight",
            "backupCount": 14,
            "encoding": "utf-8",
            "formatter": "mail",
        },
    },
    "loggers": {
        # Logger почтовой очереди (orders/emails.py): результат постановки
        # в очередь и отправки писем. Без секретов и тел писем.
        "orders.mail": {
            "handlers": ["mail_console", "mail_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
