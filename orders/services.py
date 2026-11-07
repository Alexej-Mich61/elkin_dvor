"""Единый расчёт подытога, скидки и итога.

Этот модуль — единственное место с денежной логикой промокодов: его
используют и корзина (cart.services), и на этапе 5 — оформление заказа.
Не зависит от request и сессии: принимает только доступные позиции
(цена + количество) и проверяемый промокод.

Правила:
- деньги округляются до копеек, ROUND_HALF_UP;
- процент считается от подытога доступных позиций;
- фиксированная скидка не опускает итог ниже нуля (обрезается до подытога);
- промокод повторно проверяется при каждом расчёте (validate_for).
См. docs/architecture.md §7.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

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
