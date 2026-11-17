# Особенности и грабли

Известные особенности окружения и инструментов. Перед отладкой «странного»
поведения проверить список — возможно, это уже известная особенность.

- `tailwind start` в django-tailwind 4.6 запускает ТОЛЬКО компилятор Tailwind (watch),
  Django-сервер не стартует — dev-режим требует двух терминалов (команды в `AGENTS.md`).
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
