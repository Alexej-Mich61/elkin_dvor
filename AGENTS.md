# AGENTS.md — память для сессий

## Что это
Интернет-магазин живых новогодних ёлок с доставкой (Ростов-на-Дону). Без онлайн-оплаты:
посетитель оформляет заказ → клиент и менеджер получают письмо с номером заказа →
оплата наличными при доставке. В планах: промокоды и акции.
Стадия: заготовка — моделей, views, форм и своих миграций пока нет.

## Стек
Python 3.14 · Django 6.1.2 · SQLite · django-tailwind 4.6 (Tailwind CSS 4 + daisyUI 5) ·
django-browser-reload · python-dotenv · Alpine.js (CDN, подключён в base.html).

## Команды (Windows, venv в ./venv)
```bash
# установка зависимостей
venv/Scripts/pip.exe install -r requirements.txt

# dev-сервер + компилятор Tailwind в одном терминале (основной способ)
venv/Scripts/python.exe manage.py tailwind start        # http://127.0.0.1:8000/
# сервер без пересборки стилей
venv/Scripts/python.exe manage.py runserver

# миграции
venv/Scripts/python.exe manage.py makemigrations
venv/Scripts/python.exe manage.py migrate

# тесты
venv/Scripts/python.exe manage.py test                  # тестов пока нет — команда пустая

# проверки; отдельного линтера НЕТ, используем системные чеки Django
venv/Scripts/python.exe manage.py check
```
Завершение `tailwind start` — Ctrl+C. Нужен Node.js.

## Структура
- `config/` — пакет проекта: `settings.py`, `urls.py`, `wsgi/asgi.py`. settings-модуль: `config.settings`.
- `shop/` — приложение магазина (сейчас заготовки: models/views/admin/tests пустые).
- `theme/` — Tailwind-приложение (django-tailwind):
  - `static_src/` — источники: `src/styles.css`, `package.json`; там же `node_modules`;
  - `static/css/dist/styles.css` — собранный CSS (генерируется, вручную не править).
- `templates/` — глобальные шаблоны (прописано в `settings.TEMPLATES.DIRS`); `base.html` = каркас сайта и главная.
- `static/` — глобальная статика (`js/` пока пуст, для кастомного JS).
- `.env` — `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (шаблон — `.env.example`); в git не коммитится.
- `db.sqlite3` — локальная БД, в git не коммитится.

## Маршруты (config/urls.py)
- `/` — `TemplateView` → `templates/base.html`, name=`home`.
- `__reload__/` — django-browser-reload, только для разработки.

## Модели и связи
Нет (`shop/models.py` пуст). В БД применены только contrib-миграции (auth, admin, sessions).
Кастомного user model нет и не планируется — используется стоковый `auth_user`.

## Договорённости кода
- Комментарии в коде — на русском, так и продолжаем.
- Конфиг — через `.env` (`python-dotenv`, `load_dotenv()` в начале settings).
  Без `SECRET_KEY` в `.env` проект не стартует. `DEBUG=True` только из `.env`.
- Email настраивается через `MAILERS = {"default": {...}}` (новый интерфейс Django 6.1,
  не классический `EMAIL_BACKEND`); сейчас стоит `console.EmailBackend` — письма в консоль.
- Стили: править только `theme/static_src/src/styles.css`; сборку доводить до
  `theme/static/css/dist/` (команды выше). Классы Tailwind/daisyUI — в шаблонах.
- В `base.html` CSS подключается тегом `{% tailwind_css %}`, JS-интерактив — Alpine.js.
- Стиль именования — стандартный Django: `snake_case` для файлов/полей, `PascalCase` для классов.
- После правок моделей: `makemigrations` → `migrate`. Пустые миграции не коммитить без нужды.
- Новые URL приложений — подключать через `include()` в `config/urls.py`.

## Особенности и грабли
- `NPM_BIN_PATH` в settings жёстко прописан под Windows (`C:\Program Files\nodejs\npm.cmd`) —
  на другой машине обновить путь. Без Node.js `tailwind start` не работает.
- `requirements.txt` — в кодировке UTF-16 LE с BOM: pip его читает, но не пересохранять
  текстовым редактором «вслепую», следить за кодировкой.
- Два `base.html`: `templates/base.html` (сайт) и `theme/templates/base.html` (демо
  django-tailwind) — не путать.
- `django_browser_reload.middleware` включён всегда; `__reload__/` — только dev.
- `LANGUAGE_CODE = "en-us"`, `TIME_ZONE = "UTC"` при русскоязычном сайте — сознательно
  отложено, менять при необходимости (отразится на датах/периодах акций).
- `ALLOWED_HOSTS` читается из `.env`; с `DEBUG=False` без него — ошибки.
- Линтер не настроен, тестов нет — минимальная проверка: `manage.py check`.
