from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.cart_detail, name="detail"),
    path("add/", views.add_to_cart, name="add"),
    path("update/<int:variant_id>/", views.update_cart_item, name="update"),
    path("remove/<int:variant_id>/", views.remove_cart_item, name="remove"),
    path("clear/", views.clear_cart, name="clear"),
    path("promo/", views.apply_promo, name="promo_apply"),
    path("promo/remove/", views.remove_promo, name="promo_remove"),
]
