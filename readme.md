# Ёлкин двор

Интернет-магазин живых новогодних ёлок с доставкой по Ростову-на-Дону.

Без онлайн-оплаты: покупатель оформляет заказ на сайте и получает письмо с номером
заказа, менеджер магазина — письмо с деталями заказа, оплата — наличными при доставке.
В планах — промокоды и акции.

Стек: Django 6, SQLite, Tailwind CSS + daisyUI, HTMX, Alpine.js.

## Подготовка (один раз)

1. Скопируйте `.env.example` в `.env` и задайте `SECRET_KEY`.
2. Установите зависимости:
   ```bash
   venv\Scripts\pip install -r requirements.txt
   ```
3. Примените миграции:
   ```bash
   venv\Scripts\python manage.py migrate
   ```

## Запуск сервера для ручной проверки (PyCharm)

**Способ 1 — терминал PyCharm (Alt+F12):**

```bash
venv\Scripts\python manage.py runserver
```

Если в PyCharm включено автоматическое активирование venv для терминала
(Settings → Tools → Terminal → Activate virtualenv), то venv уже активен и можно короче:

```bash
python manage.py runserver
```

**Способ 2 — конфигурация запуска (PyCharm Professional):**

Run → Edit Configurations → «+» → **Django Server** → задайте имя (например, `runserver`) → OK.
Дальше сервер запускается зелёной кнопкой Run.

Открыть в браузере: http://127.0.0.1:8000/

## Во время вёрстки

Во втором терминале держите включённым компилятор стилей — CSS пересобирается
при каждом изменении:

```bash
venv\Scripts\python manage.py tailwind start
```
