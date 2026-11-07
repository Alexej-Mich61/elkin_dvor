"""HTTP-слой корзины: тонкие views поверх cart.services.

Логика изменения сессии живёт в сервисе; здесь — формы, CSRF (через
{% csrf_token %} в шаблонах), выбор полного шаблона или HTMX-partial
и редиректы POST/Redirect/GET для запросов без HTMX.
"""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.template.response import TemplateResponse

from shop.models import ProductVariant

from .forms import AddToCartForm, PromoCodeForm
from .services import Cart, quantity_limit

HX_REQUEST_HEADER = "HX-Request"


def _is_htmx(request):
    return request.headers.get(HX_REQUEST_HEADER) == "true"


def _contents_response(request, cart, status=200, extra=None):
    """Содержимое корзины + OOB-обновление счётчика в шапке для HTMX.

    extra — дополнительный контекст (например, форма промокода с ошибкой)."""
    context = {"cart": cart, "contents": cart.contents()}
    if extra:
        context.update(extra)
    return TemplateResponse(
        request, "partials/cart_contents_oob.html", context, status=status
    )


def cart_detail(request):
    """Страница корзины. Не индексируется (см. шаблон cart/cart.html)."""
    cart = Cart(request.session)
    context = {"cart": cart, "contents": cart.contents()}
    return render(request, "cart/cart.html", context)


def add_to_cart(request):
    """Добавляет вариант в корзину.

    Без HTMX — редирект на страницу корзины (POST/Redirect/GET);
    с HTMX — partial с сообщением и обновлённым счётчиком в шапке.
    Ошибки валидации для HTMX возвращаются со статусом 422 — в base.html
    через meta htmx-config для 422 разрешён swap, чтобы сообщение
    отобразилось рядом с формой."""
    if request.method != "POST":
        return redirect("cart:detail")

    form = AddToCartForm(request.POST)
    cart = Cart(request.session)

    if not form.is_valid():
        if _is_htmx(request):
            return TemplateResponse(
                request,
                "partials/cart_feedback.html",
                {"form": form, "cart": cart},
                status=422,
            )
        return redirect("cart:detail")

    variant = form.variant
    requested = form.cleaned_data["quantity"]
    limit = quantity_limit(variant)
    # Сервис обрезает количество до остатка — сообщаем об этом в интерфейсе.
    clamped = cart.items.get(variant.pk, 0) + requested > limit
    total = cart.add(variant, requested)

    if _is_htmx(request):
        context = {
            "cart": cart,
            "variant": variant,
            "quantity": requested,
            "cart_total": total,
            "clamped": clamped,
            "limit": limit,
        }
        return TemplateResponse(request, "partials/cart_feedback.html", context)

    messages.success(request, f"«{variant}» — в корзине, всего {total} шт.")
    return redirect("cart:detail")


def update_cart_item(request, variant_id):
    """Меняет количество позиции. quantity <= 0 или кнопка «−» на единице
    удаляет позицию. Число приходит из value нажатой кнопки «−»/«+»
    или из поля quantity — оба варианта работают и без JavaScript."""
    if request.method != "POST":
        return redirect("cart:detail")

    cart = Cart(request.session)
    raw_quantity = request.POST.get("quantity", "")
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        # Нечисловое количество (подделанный запрос): корзину не трогаем.
        quantity = None

    if quantity is not None:
        variant = ProductVariant.objects.filter(pk=variant_id).first()
        if variant is None:
            # Вариант исчез из каталога — убираем позицию целиком.
            cart.remove(variant_id)
        else:
            cart.set_quantity(variant_id, min(quantity, quantity_limit(variant)))

    if _is_htmx(request):
        return _contents_response(request, cart)
    return redirect("cart:detail")


def remove_cart_item(request, variant_id):
    """Убирает позицию из корзины. Идемпотентна: повторный запрос
    по уже отсутствующему варианту просто перерисовывает корзину."""
    cart = Cart(request.session)
    if request.method == "POST":
        cart.remove(variant_id)

    if _is_htmx(request):
        return _contents_response(request, cart)
    return redirect("cart:detail")


def clear_cart(request):
    """Полностью очищает корзину (вместе с промокодом)."""
    cart = Cart(request.session)
    if request.method == "POST":
        cart.clear()

    if _is_htmx(request):
        return _contents_response(request, cart)
    return redirect("cart:detail")


def apply_promo(request):
    """Применяет промокод к корзине.

    Скидка не сохраняется: в сессии остаётся только код, суммы пересчитываются
    через единый расчёт при каждом показе корзины. Без HTMX — редирект
    с сообщением; с HTMX — фрагмент корзины, при ошибке статус 422, чтобы
    причина отобразилась в блоке промокода (htmx-config в base.html)."""
    if request.method != "POST":
        return redirect("cart:detail")

    cart = Cart(request.session)
    form = PromoCodeForm(request.POST)

    if form.is_valid():
        promo, error = cart.apply_promo(form.cleaned_data["code"])
    else:
        promo, error = None, form.errors["code"][0]

    if error is None:
        if _is_htmx(request):
            return _contents_response(request, cart)
        messages.success(request, f"Промокод {promo.code} применён.")
        return redirect("cart:detail")

    if _is_htmx(request):
        return _contents_response(
            request, cart, status=422, extra={"promo_form": form, "promo_error": error}
        )
    messages.error(request, error)
    return redirect("cart:detail")


def remove_promo(request):
    """Убирает промокод из корзины."""
    cart = Cart(request.session)
    if request.method == "POST":
        removed = cart.clear_promo()
        if removed and not _is_htmx(request):
            messages.info(request, "Промокод убран из корзины.")

    if _is_htmx(request):
        return _contents_response(request, cart)
    return redirect("cart:detail")
