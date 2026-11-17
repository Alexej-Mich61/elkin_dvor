# Структура проекта

Назначение файлов и каталогов (актуальное состояние). Поддерживать вместе с `AGENTS.md`:
при добавлении/переименовании файлов или каталогов обновлять этот список.

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
    `bg-pine-deep` (на всю ширину и высоту, фон растягивается на весь экран);
    hero — изображение и баннер `bg-wine`; преимущества (`bg-moss`, иконки —
    PNG `static/img/advantages/*.png`, единый размер h-28 / 2xl:h-48),
    каталог, «популярные дополнения» (`bg-sage`) и контакты
    (`bg-moss`) — `container mx-auto px-4`, как staff-страницы (максимум
    1536px на 2xl+, не растягиваются на весь экран); заголовки — `font-soyuz`;
    карточки товаров в каруселях — w-52 sm:w-56;
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
