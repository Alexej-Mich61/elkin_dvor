# AGENTS.md — инструкции и контекст для ИИ-агентов

## Что это
Интернет-магазин живых новогодних ёлок с доставкой (Ростов-на-Дону). Без онлайн-оплаты:
посетитель оформляет заказ → клиент и менеджер получают письмо с номером заказа →
оплата наличными при доставке. В планах: промокоды и акции.
Стадия: выполнены этапы 0 (основа), 1 (модели каталога и админка),
2 (публичная главная, страницы категорий/товаров, SEO-основа) и
3 (сессионная корзина: добавление, количество, удаление, HTMX + обычные POST).
Оформление заказа и промокоды пока не реализованы; следующий — этап 4.

## Документация
- [ROADMAP.md](ROADMAP.md) — порядок этапов, задачи, критерии готовности и текущие отметки выполнения.
- [docs/architecture.md](docs/architecture.md) — целевая архитектура, модели, инварианты, оформление заказа, почтовая очередь и правила безопасности.

Перед началом этапа читать оба документа. Не считать описанную там целевую функциональность уже реализованной.
После изменения плана обновлять `ROADMAP.md`; после изменения архитектурных решений — `docs/architecture.md`.
Этот файл содержит только актуальный рабочий контекст, команды и договорённости, не историю сессий.

## Стек
Python 3.14 · Django 6.1.2 · SQLite · django-tailwind 4.6 (Tailwind CSS 4 + daisyUI 5) ·
python-dotenv · Pillow (обязателен для `ImageField`) · Alpine.js и HTMX (CDN, подключены в `templates/base.html`).
django-browser-reload — только при `DEBUG=True`.

## Команды (Windows, venv в ./venv)
```bash
# установка зависимостей
venv/Scripts/pip.exe install -r requirements.txt

# dev-режим: два терминала
# терминал 1 — компилятор Tailwind в режиме watch
venv/Scripts/python.exe manage.py tailwind start
# терминал 2 — Django-сервер
venv/Scripts/python.exe manage.py runserver                     # http://127.0.0.1:8000/

# миграции
venv/Scripts/python.exe manage.py makemigrations
venv/Scripts/python.exe manage.py migrate

# тесты
venv/Scripts/python.exe manage.py test                  # тесты shop, cart и orders

# проверки; отдельного линтера НЕТ, используем системные чеки Django
venv/Scripts/python.exe manage.py check
```
Завершение `tailwind start` — Ctrl+C. Нужен Node.js.

## Структура
- `config/` — пакет проекта: `settings.py`, `urls.py`, `wsgi/asgi.py`. settings-модуль: `config.settings`.
- `shop/` — приложение магазина:
  - модели каталога (`models.py`), админка (`admin.py`), тесты моделей и публичного каталога (`tests.py`);
  - публичные views (`views.py`) и URL (`urls.py`): главная, категория, товар, HTMX-цена варианта;
  - `sitemaps.py` (Category/Product для sitemap.xml), `context_processors.py` (контакты магазина
    на всех страницах: телефон, мессенджеры, адрес — править там), `templatetags/shop_extras.py`
    (формат цен, диапазон цен, размеры, основное изображение).
- `cart/` — сессионная корзина (этап 3) и промокод в корзине (этап 4):
  - `services.py` — класс `Cart` поверх сессии: хранятся только `{variant_id: quantity}`
    и нормализованный код промокода (`cart_promo`), цены/скидки/суммы каждый раз
    считаются по актуальному каталогу и промокодам через единый расчёт
    `orders.services.calculate_totals` (`Cart.contents()`);
    операции `add/set_quantity/remove/clear/apply_promo/clear_promo`; потолок позиции
    `MAX_LINE_QUANTITY = 100`, при `stock > 0` лимит = остаток (обрезание с заметкой
    в интерфейсе); `clear()` убирает и промокод;
  - `views.py` — тонкие views (страница корзины, add/update/remove/clear,
    apply_promo/remove_promo): HTMX-ответы через partials с OOB-обновлением
    счётчика в шапке (`#cart-link`), без HTMX — POST/Redirect/GET на страницу
    корзины с сообщением;
  - `forms.py` (`AddToCartForm` — валидация активности варианта; `PromoCodeForm` —
    формат кода: только цифры и буквы латиницы/кириллицы), `urls.py`,
    `context_processors.py` (`cart_count` для шапки, без запросов к БД),
    `tests.py` (операции корзины, промокод, HTTP-сценарии).
- `orders/` — промокоды и единый расчёт (этап 4):
  - `models.py` — `PromoCode`: нормализованный уникальный код (trim + upper,
    только цифры/буквы лат/кирилл, см. `PROMO_CODE_PATTERN`), активность, тип скидки
    (процент/фиксированная), величина, минимальная сумма заказа, период действия;
    `validate_for(subtotal, now)` — проверка применимости с текстом причины отказа;
  - `services.py` — единый расчёт `calculate_totals(lines, promo, now)`: подытог,
    скидка, итог; округление до копеек `ROUND_HALF_UP`, итог не ниже нуля.
    Модели заказов и покупателей — этап 5.
- `theme/` — Tailwind-приложение (django-tailwind):
  - `static_src/` — источники: `src/styles.css`, `package.json`; там же `node_modules`;
  - `static/css/dist/styles.css` — собранный CSS (генерируется, вручную не править).
- `templates/` — глобальные шаблоны (прописано в `settings.TEMPLATES.DIRS`):
  - `base.html` — каркас (head, SEO-блоки title/meta_description, шапка/подвал через includes, Alpine+HTMX CDN);
  - `home.html` — главная: баннер, преимущества, каталог по категориям, «популярные дополнения», контакты;
  - `shop/category.html`, `shop/product.html` — страницы категории и товара (галерея Alpine, выбор размера с HTMX-ценой, JSON-LD);
  - `includes/` — повторяющиеся фрагменты (`header.html`, `footer.html`, `icon.html` — контурные SVG-иконки, `mobile_contacts_bar.html` — плавающая панель связи на мобильных);
  - `partials/` — HTMX-фрагменты и карточка товара (`product_card.html`, `variant_price.html`);
  - `robots.txt` — отдаётся через TemplateView с `text/plain`.
- `static/` — глобальная статика:
  - `img/` — фирменные изображения (логотип `logo_elkin_dvor.png`, хиро-ёлки `hero-tree*.webp`);
  - `favicon.ico` — фавикон (подключается в `base.html`);
  - `js/` — пока пуст, для кастомного JS.
- `scripts/demo_catalog.py` — ручной дозапуск демо-товаров (идемпотентный; не часть бизнес-логики).
- `scripts/demo_promos.py` — ручной дозапуск демо-промокодов (идемпотентный, `get_or_create`).
- `ROADMAP.md` — план разработки и статусы этапов.
- `docs/architecture.md` — целевые архитектурные договорённости.
- `.env` — `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (шаблон — `.env.example`); в git не коммитится.
- `db.sqlite3` — локальная БД, в git не коммитится.

## Маршруты (config/urls.py)
- `/` — `shop.views.home`, name=`shop:home` (данные каталога из БД).
- `/catalog/<category_slug>/` — `shop.views.category_detail`, name=`shop:category`.
- `/catalog/<category_slug>/<product_slug>/` — `shop.views.product_detail`, name=`shop:product`.
- `/catalog/<category_slug>/<product_slug>/price/?variant=<id>` — HTMX-фрагмент цены, name=`shop:variant_price`.
- `/cart/` — страница корзины, name=`cart:detail`.
- `/cart/add/` — добавление в корзину (POST), name=`cart:add`.
- `/cart/update/<variant_id>/` — изменение количества (POST, quantity в value кнопки «−»/«+»), name=`cart:update`.
- `/cart/remove/<variant_id>/` — удаление позиции (POST), name=`cart:remove`.
- `/cart/clear/` — очистка корзины (POST), name=`cart:clear`.
- `/cart/promo/` — применение промокода (POST, поле `code`), name=`cart:promo_apply`.
- `/cart/promo/remove/` — удаление промокода из корзины (POST), name=`cart:promo_remove`.
- `/sitemap.xml`, `/robots.txt` — SEO (django.contrib.sitemaps; домен сайта задаётся в админке Sites).
- `/admin/` — стандартная админка Django.
- `__reload__/` и раздача `/media/` — подключаются только при `DEBUG=True`.

## Модели и связи
Реализованы модели каталога в `shop/models.py` (миграции `shop.0001_initial`, `shop.0002_category_is_addon`):
- `Category` — slug генерируется из названия при пустом значении (`build_unique_slug`,
  кириллица сохраняется), есть `sort_order`, `is_active`, `is_addon` (категория дополнительных
  товаров — выводится в секции «популярные дополнения» на главной), SEO-поля.
- `Product` — FK на категорию с `PROTECT`, несимметричный M2M `related_products` на себя
  (self-рекомендация запрещена в `clean()`), slug аналогично категории.
- `ProductVariant` — размер хранится текстовым полем `size` (отдельная модель `Size` не нужна);
  уникальность `(product, size)` и constraint'ы `price >= 0`, `stock >= 0`.
- `ProductImage` — `upload_to='products/images/'`, одно основное изображение на товар
  (conditional UniqueConstraint + проверка в `clean()`), сортировка: основное первым.
Кастомного user model нет и не планируется — используется стоковый `auth_user`.
Публичный каталог показывает только активные товары/варианты/категории и товары
хотя бы с одним активным вариантом (см. `shop.views.public_products_queryset`).
Промокоды (этап 4) — в `orders/models.py`: к коду применяется `PromoCode.validate_for`
(активность, сроки, минимальная сумма) при каждом пересчёте; суммы — только
через `orders/services.calculate_totals`. Целевые модели заказов и покупателей
описаны в `docs/architecture.md` (этап 5), пока не созданы.

## Договорённости кода
- Комментарии в коде — на русском, так и продолжаем.
- Конфиг — через `.env` (`python-dotenv`, `load_dotenv()` в начале settings).
  Без `SECRET_KEY` в `.env` проект не стартует. `DEBUG=True` только из `.env`.
- Email настраивается через `MAILERS = {"default": {...}}` (новый интерфейс Django 6.1,
  не классический `EMAIL_BACKEND`); сейчас стоит `console.EmailBackend` — письма в консоль.
- Стили: править только `theme/static_src/src/styles.css`; сборку доводить до
  `theme/static/css/dist/` (команды выше). Классы Tailwind/daisyUI — в шаблонах.
  Фирменная палитра (зелёный/красный/сливочный) и декоративный класс `bg-snow` заданы
  в `styles.css` поверх встроенной темы daisyUI; шрифт Nunito подключается в `base.html`.
- В `base.html` CSS подключается тегом `{% tailwind_css %}`, скрипты — Alpine.js и HTMX (CDN).
- Корзина сессионная: в сессии только `{variant_id: quantity}`; вся логика — в
  `cart/services.py`, views не содержат логики изменения сессии. Подробности — §8 `docs/architecture.md`.
- HTMX 2.x по умолчанию НЕ свопает ответы 4xx/5xx. В `base.html` через
  `<meta name="htmx-config">` для статуса 422 разрешён swap — views корзины
  возвращают фрагменты с ошибками валидации (показываются в цели запроса).
  Счётчик в шапке обновляется out-of-band (`hx-swap-oob` на `#cart-link`).
- Кнопки «−»/«+» в корзине — submit-кнопки с `name="quantity"` и value=новое
  количество: работают и без JavaScript, и с HTMX (htmx шлёт value нажатой кнопки).
- Разделение ответственности: HTMX — серверные действия (размер/цена, корзина, счётчик,
  промокод, checkout); Alpine.js — только локальное UI-состояние (мобильное меню, модалки,
  галерея). Alpine не дублирует состояние корзины и цен. Подробности — `docs/architecture.md` §11.
- Стиль именования — стандартный Django: `snake_case` для файлов/полей, `PascalCase` для классов.
- После правок моделей: `makemigrations` → `migrate`. Пустые миграции не коммитить без нужды.
- Новые URL приложений — подключать через `include()` в `config/urls.py`.
- Цены, скидки и итоги заказа рассчитывать только на сервере; не доверять суммам из браузера.
- Основной контент и критичные формы строить на серверных шаблонах; HTMX использовать как улучшение, не как обязательное условие SEO.
- Не добавлять Redis, Celery, отдельный API, приложение `users` и другие новые зависимости без отдельного обоснования.
- Выполнять работу по одному этапу roadmap; не смешивать её с незапрошенным крупным рефакторингом.

## Особенности и грабли
- `tailwind start` в django-tailwind 4.6 запускает ТОЛЬКО компилятор Tailwind (watch),
  Django-сервер не стартует — dev-режим требует двух терминалов (см. команды выше).
- `NPM_BIN_PATH` берётся из окружения, по умолчанию `npm.cmd` на Windows / `npm` иначе.
  django-tailwind запускает npm через subprocess без shell, поэтому на Windows нужен
  именно `npm.cmd`. Нестандартный путь к Node — задать `NPM_BIN_PATH` в `.env`.
- `requirements.txt` — UTF-8 без BOM (перекодирован из UTF-16); не пересохранять «вслепую».
- Два `base.html`: `templates/base.html` (каркас сайта) и `theme/templates/base.html`
  (демо django-tailwind) — не путать.
- `django_browser_reload` (приложение, middleware, URL) подключается только при `DEBUG=True`;
  в production его нет.
- Django кэширует скомпилированные шаблоны в памяти процесса; при `runserver --noreload`
  правки шаблонов НЕ подхватываются (stat-автоинвалидация не работает) — сервер
  нужно перезапускать вручную, иначе ручная проверка увидит старые partials.
- Локаль `ru-ru`, зона `Europe/Moscow`; `USE_TZ=True` — в БД время в UTC, показ по Москве.
- `ALLOWED_HOSTS` читается из `.env`; с `DEBUG=False` без него — ошибки.
- Линтер не настроен — минимальная проверка: `manage.py check` и `manage.py test`.
- Slug'и каталога создаются с `allow_unicode=True` (кириллица), поэтому стандартный
  конвертер `<slug:...>` Django (только ASCII) не подходит — в `shop/urls.py` зарегистрирован
  `UnicodeSlugConverter` (`uslug`). URL в sitemap отдаются в percent-encoding — это нормально.
- daisyUI 5.7 НЕ поддерживает объекты кастомных тем в `@plugin "daisyui" { themes: {...} }`
  (объект молча игнорируется). Палитра проекта переопределяется в `styles.css` через
  переменные в `:root` (специфичность выше, чем у `:where(:root)` из темы daisyUI);
  подключена только светлая тема (`themes: "light --default"`), автотёмная по
  `prefers-color-scheme` отключена.
- Демо-фото товаров в `media/products/images/` — сгенерированные заглушки (цветные квадраты
  с подписью), а не битые картинки.
- `manage.py shell -c "..."` через Git Bash портит кириллицу в аргументе
  (строки попадают в БД битые). Скрипты с кириллицей запускать из UTF-8-файла:
  `manage.py shell -c "exec(compile(open('scripts/x.py', encoding='utf-8').read(), 'x.py', 'exec'))"`.
- Нормализация промокода — только trim + верхний регистр: «Ё» и «Е» считаются
  разными символами, код «ЁЛКА10» не совпадёт с «ЕЛКА10».
- Контакты (телефон, Telegram/WhatsApp, адрес) живут в `shop/context_processors.py`;
  ссылка Telegram — заглушка `https://t.me/elkin_dvor`, заменить на реальную.

## Завершение итерации
- Запустить `manage.py check` и относящиеся к изменениям тесты.
- Вручную проверить реализованный сценарий, если он имеет пользовательский интерфейс.
- Просмотреть diff: в нём не должно быть секретов, сгенерированного мусора и незапрошенных изменений.
- Отметить только действительно проверенные задачи в `ROADMAP.md`.
- Обновить этот файл при изменении команд, структуры, окружения или договорённостей.
- Завершать этап отдельным Git-коммитом.
