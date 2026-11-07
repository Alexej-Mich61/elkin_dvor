"""Счётчик товаров в корзине для шапки.

Считается только по сессии, без запросов к базе на каждой странице;
актуальные цены и суммы строятся отдельно в cart.services.Cart.contents()."""
from .services import Cart


def cart_counter(request):
    return {"cart_count": Cart(request.session).count()}
