"""Оформление заказа и подтверждение (этап 5).

Views тонкие: проверка корзины и формы, вызов сервиса создания заказа,
очистка корзины после успешного commit и редиректы. Повторный submit
гасится сочетанием POST/Redirect/GET, очистки корзины после commit
и одноразового checkout-token в сессии (см. docs/architecture.md §9).
"""
import json
import secrets

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from cart.services import Cart
from shop.context_processors import contacts as shop_contacts

from .forms import CheckoutForm
from .models import Order
from .services import CheckoutError, create_order

# Одноразовый токен оформления: защита от повторного submit формы.
CHECKOUT_TOKEN_SESSION_KEY = "checkout_token"
# ID заказа, доступного для просмотра в этой сессии (последний оформленный).
# Подтверждение произвольного заказа по перебору ID так не открывается.
LAST_ORDER_SESSION_KEY = "last_order_id"


def checkout(request):
    """Форма оформления. Пустую или полностью недоступную корзину оформить нельзя."""
    cart = Cart(request.session)
    contents = cart.contents()

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        # Токен выдаётся на GET формы; после успешного заказа сгорает.
        token = request.session.get(CHECKOUT_TOKEN_SESSION_KEY)
        token_ok = bool(token) and token == request.POST.get("ct")
        if not contents.available_lines:
            messages.error(request, "В корзине нет товаров, доступных для заказа.")
            return redirect("cart:detail")
        if not token_ok:
            messages.error(
                request, "Форма оформления устарела — попробуйте отправить ещё раз."
            )
            return redirect("orders:checkout")

        if form.is_valid():
            try:
                order = create_order(
                    lines=cart.items.items(),
                    promo_code=cart.promo_code,
                    **form.cleaned_data,
                )
            except CheckoutError:
                messages.error(
                    request, "В корзине нет товаров, доступных для заказа."
                )
                return redirect("cart:detail")

            # Корзину чистим только после успешного commit транзакции.
            cart.clear()
            request.session.pop(CHECKOUT_TOKEN_SESSION_KEY, None)
            request.session[LAST_ORDER_SESSION_KEY] = order.pk
            messages.success(
                request, f"Заказ {order.number} оформлен. Спасибо за покупку!"
            )
            return redirect("orders:confirmation")

        # Ошибки валидации: форма вернётся с данными и пояснениями у полей.
        return render(
            request,
            "orders/checkout.html",
            {"form": form, "contents": contents, "checkout_token": token},
        )

    if not contents.available_lines:
        messages.error(request, "В корзине нет товаров, доступных для заказа.")
        return redirect("cart:detail")

    token = secrets.token_urlsafe(16)
    request.session[CHECKOUT_TOKEN_SESSION_KEY] = token
    return render(
        request,
        "orders/checkout.html",
        {"form": CheckoutForm(), "contents": contents, "checkout_token": token},
    )


def order_confirmation(request):
    """Подтверждение последнего заказа текущей сессии.

    Доступ только через сессию: URL без ID, произвольный заказ по перебору
    не открывается. Без оформленного заказа — на главную."""
    order = None
    order_id = request.session.get(LAST_ORDER_SESSION_KEY)
    if order_id:
        order = (
            Order.objects.filter(pk=order_id)
            .select_related("customer")
            .prefetch_related("items")
            .first()
        )
    if order is None:
        return redirect("shop:home")

    # Данные для карточки заказа (кнопка «Скачать»): JSON уходит в браузер,
    # где canvas рисует изображение без дополнительного запроса к серверу.
    card = {
        "shop": "Ёлкин двор",
        "number": order.number,
        "date": timezone.localtime(order.created_at).strftime("%d.%m.%Y %H:%M"),
        "name": order.name,
        "phone": order.phone,
        "address": order.address,
        "items": [
            {
                "name": item.product_name,
                "size": item.variant_size,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "total_price": str(item.total_price),
            }
            for item in order.items.all()
        ],
        "subtotal": str(order.subtotal),
        "discount": str(order.discount),
        "promo_code": order.promo_code,
        "total": str(order.total),
        "shop_phone": shop_contacts(request)["SHOP_PHONE_DISPLAY"],
    }
    return render(
        request,
        "orders/order_success.html",
        {"order": order, "order_card_json": json.dumps(card, ensure_ascii=False)},
    )
