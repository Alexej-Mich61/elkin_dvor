# URL-маршруты

Актуальный список маршрутов (подключаются в `config/urls.py` и `urls.py` приложений).
При добавлении/изменении маршрутов обновлять этот список.

- `/` — `shop.views.home`, name=`shop:home` (данные каталога из БД).
- `/catalog/<category_slug>/` — `shop.views.category_detail`, name=`shop:category`.
- `/catalog/<category_slug>/<product_slug>/` — `shop.views.product_detail`, name=`shop:product`.
- `/catalog/<category_slug>/<product_slug>/price/?variant=<id>` — HTMX-фрагмент цены, name=`shop:variant_price`.
- `/privacy/` — политика конфиденциальности (TemplateView), name=`shop:privacy`.
- `/personal-data/` — политика обработки персональных данных (TemplateView), name=`shop:personal_data`.
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
