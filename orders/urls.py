from django.urls import path

from . import staff_views, views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("success/", views.order_confirmation, name="confirmation"),
    # Staff-страницы менеджера и администратора (этап 7)
    path("staff/orders/", staff_views.orders_list, name="staff_orders"),
    path("staff/orders/export/", staff_views.orders_export, name="staff_orders_export"),
    path("staff/orders/<int:pk>/", staff_views.order_detail, name="staff_order_detail"),
    path("staff/orders/<int:pk>/export/", staff_views.order_export, name="staff_order_export"),
    path("staff/orders/<int:pk>/edit/", staff_views.order_edit, name="staff_order_edit"),
    path("staff/orders/<int:pk>/delete/", staff_views.order_delete, name="staff_order_delete"),
    path("staff/orders/<int:pk>/status/", staff_views.order_status, name="staff_order_status"),
    path("staff/customers/", staff_views.customers_list, name="staff_customers"),
    path("staff/customers/export/", staff_views.customers_export, name="staff_customers_export"),
    path(
        "staff/customers/export/all/",
        staff_views.customers_export_all,
        name="staff_customers_export_all",
    ),
]
