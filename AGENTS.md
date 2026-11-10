# AGENTS.md — инструкции и контекст для ИИ-агентов

## Что это
Интернет-магазин живых новогодних ёлок с доставкой (Ростов-на-Дону). Без онлайн-оплаты:
посетитель оформляет заказ → клиент и менеджер получают письмо с номером заказа →
оплата наличными при доставке. В планах: промокоды и акции.
Стадия: выполнены этапы 0 (основа), 1 (модели каталога и админка),
2 (публичная главная, страницы категорий/товаров, SEO-основа),
3 (сессионная корзина), 4 (промокоды и единый расчёт),
5 (покупатели, оформление заказа, подтверждение, админка заказов),
6 (почтовая очередь в БД, команда `send_order_emails`, логи отправки) и
7 (работа менеджеров: staff-страницы «Заказы» и «Клиентская база», права
группы «Менеджер», Excel-экспорт, вход сотрудников).
Следующий — этап 8 (итоговая проверка, эксплуатация и публикация).

## Документация
- [ROADMAP.md](ROADMAP.md) — порядок этапов, задачи, критерии готовности и текущие отметки выполнения.
- [docs/architecture.md](docs/architecture.md) — целевая архитектура, модели, инварианты, оформление заказа, почтовая очередь и правила безопасности.

Перед началом этапа читать оба документа. Не считать описанную там целевую функциональность уже реализованной.
После изменения плана обновлять `ROADMAP.md`; после изменения архитектурных решений — `docs/architecture.md`.
Этот файл содержит только актуальный рабочий контекст, команды и договорённости, не историю сессий.

## Стек
Python 3.14 · Django 6.1.2 · SQLite · django-tailwind 4.6 (Tailwind CSS 4 + daisyUI 5) ·
python-dotenv · Pillow (обязателен для `ImageField`) · openpyxl 3.1 (Excel-экспорт,
этап 7) · Alpine.js и HTMX (CDN, подключены в `templates/base.html`).
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

# права менеджера (этап 7): создание/синхронизация группы «Менеджер».
# Идемпотентна; запускать после migrate и при изменении состава прав.
# Флаг is_staff на самом пользователе включается вручную (в админке).
venv/Scripts/python.exe manage.py ensure_manager_group

# почтовая очередь (этап 6): однократная отправка готовых писем
venv/Scripts/python.exe manage.py send_order_emails     # до 20 писем; --batch N
send_emails.bat                                          # то же для Windows (двойной клик)
# регулярный запуск — через Планировщик заданий Windows (задание на send_emails.bat,
# например раз в минуту) или cron на Linux; параллельные запуски безопасны.

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
- `orders/` — промокоды, покупатели, оформление заказа (этапы 4–5) и
  почтовая очередь (этап 6):
  - `models.py` — `PromoCode` (см. `PROMO_CODE_PATTERN`, `validate_for`);
    `Customer` (нормализованный телефон с индексом, email, служебная заметка;
    контакты НЕ уникальны), `Order` (публичный номер `ЁД-2026-000125`,
    статус `processing/completed/cancelled` = выполняется/выполнен/отменён,
    снимок контактов/адреса/примечания, подытог/скидка/итог, параметры
    промокода-снимок, auto created_at/updated_at), `OrderItem` (снимок
    названия/размера/цены, служебные FK на товар/вариант `SET_NULL`),
    `ShopSettings` (singleton, в админке: email менеджера для писем о заказах),
    `OutgoingEmail` (очередь: получатель/тема/текст/HTML, статус
    `pending/sending/sent/failed`, попытки, отложенная попытка, последняя
    ошибка, ключ идемпотентности `order:<id>:<kind>`);
  - `services.py` — единый расчёт `calculate_totals` (этап 4) и `create_order`
    (этап 5): короткая транзакция — варианты перезагружаются и проверяются
    на активность, суммы и промокод пересчитываются заново, покупатель
    ищется осторожно по нормализованному телефону (только однозначное
    совпадение), создаются заказ, позиции, номер и две записи почтовой
    очереди (`queue_order_emails`);
  - `emails.py` (этап 6) — построение писем из шаблонов, постановка в очередь
    в транзакции заказа и обработка очереди: атомарный захват (безопасен
    при параллельных обработчиках), повторы (`MAX_ATTEMPTS=5`, пауза
    `RETRY_DELAY=5 мин`), постоянные SMTP-ошибки → `failed` сразу, лог
    logger'ом `orders.mail`;
  - `management/commands/send_order_emails.py` — отправка партии готовых
    писем (`--batch`, по умолчанию 20); запуск — `send_emails.bat` или
    планировщик ОС;
  - staff-страницы менеджера (этап 7) — `/orders/staff/orders/` и
    `/orders/staff/customers/`: списки с фильтрами/поиском/статистикой/
    пагинацией 50, модальные окна просмотра/редактирования/удаления, смена
    статуса прямо в списке, Excel-экспорт (openpyxl). Логика фильтров —
    `staff_services.py`, сборка .xlsx — `exports.py`, тонкие views —
    `staff_views.py`, шаблоны — `templates/orders/staff/`;
    права: авторизован + `is_staff` + разрешение модели (`orders.view_order`
    и т.д.); группа «Менеджер» — команда `ensure_manager_group`;
  - `forms.py` (`CheckoutForm` — имя/телефон/адрес обязательны, email и
    примечание необязательны, телефон: 10–15 цифр после нормализации;
    `OrderFilterForm` и `OrderEditForm` — staff-фильтр и правка контактного
    снимка/статуса, деньги и позиции не редактируются),
    `views.py` (`checkout` — одноразовый токен в сессии против повторного
    submit, корзина чистится после commit; `order_confirmation` — доступ
    только к последнему заказу текущей сессии, URL без ID), `urls.py`,
    `admin.py` (заказы: фильтры по статусу и дате, поиск по номеру/имени/
    телефону/email/адресу, позиции инлайном readonly, снимок readonly,
    статус редактируется, действие «Экспорт в Excel»; покупатели: поиск,
    число заказов, действие «Экспорт в Excel»), `tests.py`.
- `theme/` — Tailwind-приложение (django-tailwind):
  - `static_src/` — источники: `src/styles.css`, `package.json`; там же `node_modules`;
  - `static/css/dist/styles.css` — собранный CSS (генерируется, вручную не править).
- `templates/` — глобальные шаблоны (прописано в `settings.TEMPLATES.DIRS`):
  - `base.html` — каркас (head, SEO-блоки title/meta_description, шапка/подвал через includes, Alpine+HTMX CDN);
  - `home.html` — главная: все секции внутри корневого контейнера
    `bg-pine-deep` (на всю ширину и высоту); hero — изображение и баннер
    `bg-wine` с отступами px-4 от краёв; преимущества (`bg-moss`, иконки
    w-28 / 2xl:w-48), каталог, «популярные дополнения» (`bg-sage`) и контакты
    (`bg-moss`) — вкладки с отступом `mx-4` от краёв экрана; заголовки —
    `font-soyuz`; карточки товаров в каруселях — w-52 sm:w-56;
  - `shop/category.html`, `shop/product.html` — страницы категории и товара (галерея Alpine, выбор размера с HTMX-ценой, JSON-LD);
  - `orders/checkout.html` — форма оформления (звёздочки обязательных полей,
    текст-помощники, сводка заказа); `orders/order_success.html` — подтверждение
    с номером, составом, итогами, кнопкой «Скачать» (JSON заказа для canvas);
  - `orders/emails/` — шаблоны писем очереди (этап 6): текст + HTML + subject
    для покупателя (`order_customer*`) и менеджера (`order_manager*`);
  - `orders/staff/` — staff-страницы менеджера (этап 7): `orders_list.html`
    (фильтры, статистика, таблица, модальные окна просмотра/редактирования/
    удаления), `customers_list.html`, `partials/` (HTMX-контент модалок
    `order_detail.html`, `order_form.html`);
  - `registration/login.html` — страница входа сотрудников (этап 7,
    стандартный `LoginView`; публичной регистрации и сброса пароля нет);
  - `includes/` — повторяющиеся фрагменты (`header.html` — липкая шапка
    (sticky на обёртке `<div x-data>`, z-40): контакты десктопа и кнопки
    входа/меню/админки/выхода/корзины на залитых solid-иконках, боковое меню
    справа для staff (Alpine, z-50), `footer.html`,
    `icon.html` — контурные SVG-иконки + варианты с суффиксом `-solid`
    (залитые, в стилистике иконок плавающей панели, для шапки),
    `mobile_contacts_bar.html` — плавающая панель связи на мобильных);
  - `partials/` — HTMX-фрагменты и карточка товара (`product_card.html`, `variant_price.html`);
  - `robots.txt` — отдаётся через TemplateView с `text/plain`.
- `static/` — глобальная статика:
  - `img/` — фирменные изображения (логотип `logo_elkin_dvor.png`, хиро-ёлки `hero-tree*.webp`);
  - `favicon.ico` — фавикон (подключается в `base.html`);
  - `js/order_card.js` — карточка заказа: кнопка «Скачать» рисует PNG через
    canvas из JSON на странице подтверждения (без запроса к серверу).
- `scripts/demo_catalog.py` — ручной дозапуск демо-товаров (идемпотентный; не часть бизнес-логики).
- `scripts/demo_promos.py` — ручной дозапуск демо-промокодов (идемпотентный, `get_or_create`).
- `ROADMAP.md` — план разработки и статусы этапов.
- `docs/architecture.md` — целевые архитектурные договорённости.
- `.env` — `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, параметры SMTP (`EMAIL_HOST`,
  `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
  `EMAIL_USE_SSL`, `EMAIL_TIMEOUT`, `DEFAULT_FROM_EMAIL`; шаблон — `.env.example`);
  в git не коммитится.
- `db.sqlite3` — локальная БД, в git не коммитится.
- `send_emails.bat` — отправка очереди писем одним двойным кликом (этап 6);
  для регулярной отправки добавить в Планировщик заданий Windows.
- `logs/mail.log` — лог отправки почты (UTF-8, ротация ежедневно, 14 копий);
  создаётся автоматически, в git не коммитится (`*.log`).

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
- `/orders/checkout/` — оформление заказа (GET — форма, POST — создание), name=`orders:checkout`.
- `/orders/success/` — подтверждение последнего заказа текущей сессии (URL без ID), name=`orders:confirmation`.
- `/orders/staff/orders/` — список заказов менеджера, name=`orders:staff_orders` (только staff с `orders.view_order`).
- `/orders/staff/orders/export/` — Excel видимого набора, name=`orders:staff_orders_export`.
- `/orders/staff/orders/<pk>/` — HTMX-фрагмент просмотра заказа, name=`orders:staff_order_detail`.
- `/orders/staff/orders/<pk>/export/` — Excel одного заказа, name=`orders:staff_order_export`.
- `/orders/staff/orders/<pk>/edit/` — модальное редактирование (GET/POST), name=`orders:staff_order_edit`.
- `/orders/staff/orders/<pk>/delete/` — удаление (POST), name=`orders:staff_order_delete`.
- `/orders/staff/orders/<pk>/status/` — смена статуса из списка (POST), name=`orders:staff_order_status`.
- `/orders/staff/customers/` — клиентская база, name=`orders:staff_customers` (только staff с `orders.view_customer`).
- `/orders/staff/customers/export/` и `/orders/staff/customers/export/all/` — Excel найденных / всей базы, names=`orders:staff_customers_export`, `orders:staff_customers_export_all`.
- `/accounts/login/`, `/accounts/logout/` — вход/выход сотрудников (стандартные auth views; logout — POST-формой), names=`login`, `logout`.
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
Промокоды, покупатели и заказы (этапы 4–5) — в `orders/models.py`:
к коду применяется `PromoCode.validate_for` (активность, сроки, минимальная
сумма) при каждом пересчёте; суммы — только через `orders/services.calculate_totals`;
заказ создаётся `orders/services.create_order` в короткой транзакции с
историческим снимком контактов и позиций (миграция `orders.0002_customer_order_orderitem_and_more`).
Подробности — §6–9 `docs/architecture.md`.

## Договорённости кода
- Комментарии в коде — на русском, так и продолжаем.
- Конфиг — через `.env` (`python-dotenv`, `load_dotenv()` в начале settings).
  Без `SECRET_KEY` в `.env` проект не стартует. `DEBUG=True` только из `.env`.
- Email настраивается через `MAILERS = {"default": {...}}` (новый интерфейс Django 6.1,
  не классический `EMAIL_BACKEND`). Параметры mailer'а собираются в settings из `.env`:
  задан `EMAIL_HOST` → SMTP-backend (`OPTIONS`: host/port/username/password/use_tls/
  use_ssl/timeout; `use_tls` и `use_ssl` несовместимы), иначе `console.EmailBackend` —
  письма в консоль, для локальной разработки этого достаточно. Для SMTP подключается
  `config.mail_backends.CertifiSMTPEmailBackend` — верификация TLS по набору certifi
  (или файлу `EMAIL_CA_FILE`): без этого на Windows падает `CERTIFICATE_VERIFY_FAILED`
  у серверов вроде smtp.mail.ru, чьи корни отсутствуют в системном хранилище.
- Почта уходит только через очередь: `create_order` лишь ставит две записи
  `OutgoingEmail` (покупателю — если указан email, менеджеру — на адрес из
  `ShopSettings` в админке); SMTP делает `manage.py send_order_emails`.
- Отправка почты логируется всегда (dev и prod) logger'ом `orders.mail` в
  консоль и `logs/mail.log`. В логе — получатель, номер заказа, результат;
  секретов и тел писем нет.
- Стили: править только `theme/static_src/src/styles.css`; сборку доводить до
  `theme/static/css/dist/` (команды выше). Классы Tailwind/daisyUI — в шаблонах.
  Фирменная палитра задана в `styles.css` поверх встроенной темы daisyUI:
  pine/pine-dark/cream/crimson/frost (фирменные) и палитра главной —
  `pine-deep` #0d2c1a (корневой контейнер, шапка), `moss` #1a472a (преимущества,
  подвал), `sage` #e8ece4 (каталог, дополнения), `wine` #9d0709 (hero-баннер).
  Шрифты — self-hosted (`static/fonts/`, `@font-face` в styles.css): Montserrat
  (основной, `--font-sans`; один файл веса 400 — жирные начертания
  синтезируются, диапазон 400 700), Soyuz Grotesk (коммерческий, локальный .otf;
  заголовки, утилита `font-soyuz`), Marck Script (зарезервирован, не используется).
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
  промокод, checkout, staff-мутации); Alpine.js — только локальное UI-состояние (мобильное
  меню, модалки, боковая панель меню, галерея). Alpine не дублирует состояние корзины и цен.
  Подробности — `docs/architecture.md` §11.
- Staff-страницы (этап 7): фильтры/поиск/статистика/пагинация — в `orders/staff_services.py`,
  Excel — в `orders/exports.py`, views — тонкие (`orders/staff_views.py`). Поиск по тексту —
  в Python (`str.casefold()`): SQLite LIKE сворачивает регистр только ASCII. Потолок
  «последних 100 без фильтров» снимается любым фильтром/поиском. Успешные HTMX-мутации
  staff-страниц возвращают 204 + `HX-Trigger: staff:reload` — страница перезагружает
  список, чтобы фильтры/статистика/строки остались актуальными; CSRF HTMX-запросов вне
  форм обеспечивает `hx-headers` в `base.html`.
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
- Контакты (телефон, Telegram/WhatsApp, адрес) живут в константе `SHOP_CONTACTS`
  в `shop/context_processors.py` (её же используют письма из `orders/emails.py`);
  ссылка Telegram — заглушка `https://t.me/elkin_dvor`, заменить на реальную.
- `send_emails.bat` включает `chcp 65001` и `PYTHONUTF8=1`: без этого console
  backend может упасть с `[Errno 22] Invalid argument` при выводе кириллицы
  в чужую консоль/лог планировщика — письмо тогда уйдёт в повтор, а не в sent.
  Своими запусками `manage.py send_order_emails` учитывай то же самое.
- В Django 6.1 шаблонный комментарий `{# ... #}` НЕ пересекает переводы строк
  (многострочный выводится как текст) — многострочные комментарии только через
  `{% comment %}`.
- Липкая шапка: `sticky` повешен на обёртку `<div x-data>` в `header.html`,
  а не на сам `<header>` — родитель header'а это обёртка высотой самой шапки
  (drawer-шаблон инертен), «липнуть» внутри неё негде; у обёртки родитель —
  `body` на всю высоту страницы.

## Завершение итерации
- Запустить `manage.py check` и относящиеся к изменениям тесты.
- Вручную проверить реализованный сценарий, если он имеет пользовательский интерфейс.
- Просмотреть diff: в нём не должно быть секретов, сгенерированного мусора и незапрошенных изменений.
- Отметить только действительно проверенные задачи в `ROADMAP.md`.
- Обновить этот файл при изменении команд, структуры, окружения или договорённостей.
- Завершать этап отдельным Git-коммитом.
