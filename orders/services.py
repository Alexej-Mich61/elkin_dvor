"""Единый расчёт подытога, скидки и итога + создание заказа (этап 5).

Этот модуль — единственное место с денежной логикой промокодов: его
используют и корзина (cart.services), и оформление заказа.
Не зависит от request и сессии: принимает только доступные позиции
(цена + количество) и проверяемый промокод.

Правила расчёта:
- деньги округляются до копеек, ROUND_HALF_UP;
- процент считается от подытога доступных позиций;
- фиксированная скидка не опускает итог ниже нуля (обрезается до подытога);
- промокод повторно проверяется при каждом расчёте (validate_for).

Создание заказа (create_order) — короткая транзакция: варианты перезагружаются
и проверяются на активность, суммы и промокод пересчитываются заново,
покупатель ищется осторожно по нормализованному телефону, создаются заказ,
его позиции и публичный номер. Почтовые записи добавятся сюда на этапе 6.
См. docs/architecture.md §6–7, §9.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    Customer,
    Order,
    OrderItem,
    PromoCode,
    build_order_number,
    normalize_phone,
)

MONEY_QUANT = Decimal("0.01")


def money(value):
    """Округление денежного значения до копеек."""
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def calculate_subtotal(lines):
    """Подытог доступных позиций: lines — iterable пар (цена, количество)."""
    return money(
        sum(money(unit_price) * quantity for unit_price, quantity in lines)
    )


def calculate_discount(subtotal, promo):
    """Скидка от подытога. promo — применимый PromoCode (проверен вызывающим)."""
    if promo.discount_type == promo.DISCOUNT_PERCENT:
        return money(subtotal * promo.discount_value / Decimal("100"))
    # Фиксированная скидка обрезается, чтобы итог не ушёл ниже нуля.
    return min(money(promo.discount_value), subtotal)


@dataclass
class Totals:
    """Результат единого расчёта: подытог, скидка, итог и статус промокода."""

    subtotal: Decimal
    discount: Decimal
    total: Decimal
    promo: object | None = None
    promo_error: str | None = None

    @property
    def promo_applied(self):
        return self.promo is not None and self.promo_error is None


def calculate_totals(lines, promo=None, now=None):
    """Считает подытог, скидку и итог по актуальным данным.

    lines — iterable пар (цена, количество) доступных позиций;
    promo — PromoCode или None. Промокод проверяется заново: при любой
    ошибке скидка равна нулю, а причина возвращается в promo_error.
    """
    subtotal = calculate_subtotal(lines)
    promo_error = None
    discount = Decimal("0.00")

    if promo is not None:
        promo_error = promo.validate_for(subtotal, now=now)
        if promo_error is None:
            discount = calculate_discount(subtotal, promo)

    return Totals(
        subtotal=subtotal,
        discount=discount,
        total=money(subtotal - discount),
        promo=promo,
        promo_error=promo_error,
    )


# --- Оформление заказа (этап 5) ---------------------------------------------

# Потолок количества позиции при отсутствии складского учёта (stock=0).
# Дублирует cart.services.MAX_LINE_QUANTITY, чтобы orders не импортировал
# cart (cart уже импортирует orders — был бы цикл).
MAX_LINE_QUANTITY = 100


class CheckoutError(Exception):
    """Бизнес-отказ при оформлении: оформлять нечего (пустая/недоступная корзина)."""


def _quantity_limit(variant):
    """Максимум варианта в заказе: фактический остаток, если он учитывается."""
    return variant.stock if variant.stock > 0 else MAX_LINE_QUANTITY


def find_customer_by_phone(phone):
    """Осторожный поиск покупателя: только однозначное совпадение
    по нормализованному телефону. При неоднозначности — None
    (создаём отдельную запись, см. docs/architecture.md §6)."""
    matches = list(Customer.objects.filter(phone_normalized=normalize_phone(phone)))
    if len(matches) == 1:
        return matches[0]
    return None


@transaction.atomic
def create_order(*, lines, promo_code, name, phone, email, address, note, now=None):
    """Создаёт покупателя (или связывает однозначного), заказ и позиции.

    lines — iterable пар (variant_id, quantity) из сессионной корзины.
    Внутри транзакции варианты загружаются заново, неактивные отсекаются,
    количества обрезаются до остатка, суммы и промокод пересчитываются
    единым расчётом calculate_totals. Возвращает Order.

    Бросает CheckoutError, если нет ни одной доступной позиции.
    """
    from shop.models import ProductVariant  # локально, чтобы не мешать этапу 4

    lines = [(int(variant_id), int(quantity)) for variant_id, quantity in lines]
    variants = {
        variant.pk: variant
        for variant in ProductVariant.objects.filter(
            pk__in=[variant_id for variant_id, _ in lines]
        ).select_related("product__category")
    }

    # Повторная проверка активности: неактивные/удалённые позиции не оформляются.
    available = []
    for variant_id, quantity in lines:
        variant = variants.get(variant_id)
        if (
            variant is None
            or not variant.is_active
            or not variant.product.is_active
            or not variant.product.category.is_active
            or quantity <= 0
        ):
            continue
        available.append((variant, min(quantity, _quantity_limit(variant))))

    if not available:
        raise CheckoutError("В корзине нет товаров, доступных для заказа.")

    promo = None
    if promo_code:
        promo = PromoCode.objects.filter(code=promo_code).first()
    totals = calculate_totals(
        ((variant.price, quantity) for variant, quantity in available),
        promo=promo,
        now=now,
    )

    customer = find_customer_by_phone(phone)
    if customer is None:
        customer = Customer.objects.create(
            name=name, phone=phone, email=email or ""
        )

    order = Order(
        customer=customer,
        name=name,
        phone=phone,
        email=email or "",
        address=address,
        note=note or "",
        subtotal=totals.subtotal,
        discount=totals.discount,
        total=totals.total,
    )
    if totals.promo_applied:
        order.promo_code = totals.promo.code
        order.promo_discount_type = totals.promo.discount_type
        order.promo_discount_value = totals.promo.discount_value
    order.save()

    # Публичный номер детерминирован от ID: «ЁД-2026-000125».
    year = timezone.localtime(order.created_at).year
    order.number = build_order_number(order.pk, year)
    order.save(update_fields=["number"])

    OrderItem.objects.bulk_create(
        OrderItem(
            order=order,
            product=variant.product,
            variant=variant,
            product_name=variant.product.name,
            variant_size=variant.size,
            unit_price=money(variant.price),
            quantity=quantity,
            total_price=money(variant.price * quantity),
        )
        for variant, quantity in available
    )
    return order
