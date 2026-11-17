# Модели и связи

Актуальное состояние реализованных моделей (кратко). Целевые договорённости и
обоснования решений — в §5–9 [docs/architecture.md](architecture.md).

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
