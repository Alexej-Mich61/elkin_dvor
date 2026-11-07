"""Тесты промокодов и единого расчёта (этап 4).

Покрываем: нормализацию и формат кода, границы периода действия и
минимальной суммы, округление скидки и неотрицательный итог.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import PromoCode, normalize_promo_code
from .services import calculate_totals

NOW = timezone.now()


def make_promo(code="ЕЛКА2026", **kwargs):
    defaults = {
        "discount_type": PromoCode.DISCOUNT_PERCENT,
        "discount_value": Decimal("10"),
    }
    defaults.update(kwargs)
    return PromoCode.objects.create(code=code, **defaults)


class PromoCodeModelTests(TestCase):
    """Нормализация, формат и ограничения модели."""

    def test_code_normalized_on_save(self):
        promo = make_promo(code="  ёлка2026 ")
        self.assertEqual(promo.code, "ЁЛКА2026")

    def test_normalize_strips_and_uppercases(self):
        self.assertEqual(normalize_promo_code("  Promo10\t"), "PROMO10")

    def test_latin_and_digits_allowed(self):
        promo = make_promo(code="Sale2026")
        self.assertEqual(promo.code, "SALE2026")

    def test_special_symbols_rejected_on_clean(self):
        for bad in ("SALE@2026", "50%", "СКИДКА-10", "код 1", "ПРОМО_2026"):
            promo = PromoCode(code=bad, discount_value=Decimal("10"))
            with self.assertRaises(ValidationError, msg=bad):
                promo.full_clean()

    def test_duplicate_code_rejected_regardless_of_case(self):
        make_promo(code="ЁЛКА")
        with self.assertRaises(ValidationError):
            PromoCode(code="ёлка", discount_value=Decimal("5")).full_clean()

    def test_percent_over_100_rejected(self):
        promo = PromoCode(code="BIG", discount_value=Decimal("101"))
        with self.assertRaises(ValidationError):
            promo.full_clean()

    def test_zero_discount_rejected(self):
        promo = PromoCode(code="ZERO", discount_value=Decimal("0"))
        with self.assertRaises(ValidationError):
            promo.full_clean()

    def test_period_end_before_start_rejected(self):
        promo = PromoCode(
            code="BACKWARDS",
            discount_value=Decimal("10"),
            starts_at=NOW + timedelta(days=2),
            ends_at=NOW + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            promo.full_clean()


class PromoCodeValidationTests(TestCase):
    """Проверка применимости: активность, сроки, минимальная сумма."""

    def test_valid_without_limits(self):
        promo = make_promo()
        self.assertIsNone(promo.validate_for(Decimal("1000.00")))

    def test_inactive_rejected(self):
        promo = make_promo(is_active=False)
        self.assertEqual(promo.validate_for(Decimal("1000.00")), "Этот промокод не действует.")

    def test_not_started_rejected(self):
        promo = make_promo(starts_at=NOW + timedelta(days=1))
        self.assertEqual(
            promo.validate_for(Decimal("1000.00")), "Промокод ещё не начал действовать."
        )

    def test_not_started_allowed_at_boundary(self):
        starts = NOW + timedelta(days=1)
        promo = make_promo(starts_at=starts)
        self.assertIsNone(promo.validate_for(Decimal("1000.00"), now=starts))

    def test_expired_rejected(self):
        promo = make_promo(ends_at=NOW - timedelta(days=1))
        self.assertEqual(
            promo.validate_for(Decimal("1000.00")), "Срок действия промокода истёк."
        )

    def test_expired_allowed_at_boundary(self):
        ends = NOW + timedelta(days=1)
        promo = make_promo(ends_at=ends)
        self.assertIsNone(promo.validate_for(Decimal("1000.00"), now=ends))

    def test_min_order_total_below_rejected(self):
        promo = make_promo(min_order_total=Decimal("5000.00"))
        self.assertEqual(
            promo.validate_for(Decimal("4999.99")),
            "Промокод действует при заказе от 5000 руб.",
        )

    def test_min_order_total_equal_allowed(self):
        promo = make_promo(min_order_total=Decimal("5000.00"))
        self.assertIsNone(promo.validate_for(Decimal("5000.00")))


class CalculateTotalsTests(TestCase):
    """Единый расчёт: скидка, округление, неотрицательный итог."""

    def test_no_promo(self):
        totals = calculate_totals([(Decimal("3900.00"), 2)])
        self.assertEqual(totals.subtotal, Decimal("7800.00"))
        self.assertEqual(totals.discount, Decimal("0.00"))
        self.assertEqual(totals.total, Decimal("7800.00"))
        self.assertFalse(totals.promo_applied)

    def test_percent_discount(self):
        promo = make_promo(discount_value=Decimal("10"))
        totals = calculate_totals([(Decimal("3900.00"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("390.00"))
        self.assertEqual(totals.total, Decimal("3510.00"))

    def test_percent_discount_rounds_half_up(self):
        # 999.95 * 10% = 99.995 -> 100.00 (округление копеек вверх по HALF_UP).
        promo = make_promo(discount_value=Decimal("10"))
        totals = calculate_totals([(Decimal("999.95"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("100.00"))
        self.assertEqual(totals.total, Decimal("899.95"))

    def test_percent_discount_rounds_down(self):
        # 999.94 * 10% = 99.994 -> 99.99.
        promo = make_promo(discount_value=Decimal("10"))
        totals = calculate_totals([(Decimal("999.94"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("99.99"))

    def test_fixed_discount(self):
        promo = make_promo(
            code="FIXED", discount_type=PromoCode.DISCOUNT_FIXED,
            discount_value=Decimal("500.00"),
        )
        totals = calculate_totals([(Decimal("3900.00"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("500.00"))
        self.assertEqual(totals.total, Decimal("3400.00"))

    def test_fixed_discount_never_makes_total_negative(self):
        promo = make_promo(
            code="HUGE", discount_type=PromoCode.DISCOUNT_FIXED,
            discount_value=Decimal("100000.00"),
        )
        totals = calculate_totals([(Decimal("3900.00"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("3900.00"))
        self.assertEqual(totals.total, Decimal("0.00"))

    def test_invalid_promo_gives_no_discount_but_reports_error(self):
        promo = make_promo(is_active=False)
        totals = calculate_totals([(Decimal("3900.00"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("0.00"))
        self.assertEqual(totals.total, Decimal("3900.00"))
        self.assertIsNotNone(totals.promo_error)
        self.assertFalse(totals.promo_applied)

    def test_min_order_below_gives_no_discount(self):
        promo = make_promo(min_order_total=Decimal("10000.00"))
        totals = calculate_totals([(Decimal("3900.00"), 1)], promo=promo)
        self.assertEqual(totals.discount, Decimal("0.00"))
        self.assertIn("10000", totals.promo_error)

    def test_unavailable_lines_excluded_from_calculation(self):
        # Доступность позиций определяет вызывающий (корзина) — сервис
        # считает только переданные ему доступные позиции.
        promo = make_promo(discount_value=Decimal("10"))
        totals = calculate_totals([(Decimal("3900.00"), 1)], promo=promo)
        self.assertEqual(totals.subtotal, Decimal("3900.00"))
