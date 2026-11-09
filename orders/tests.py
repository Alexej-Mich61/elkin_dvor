"""Тесты промокодов и единого расчёта (этап 4).

Покрываем: нормализацию и формат кода, границы периода действия и
минимальной суммы, округление скидки и неотрицательный итог.
"""
import io
import smtplib
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from shop.models import Category, Product, ProductVariant

from . import exports, staff_services
from .emails import MAX_ATTEMPTS, queue_order_emails
from .forms import CheckoutForm, OrderEditForm, OrderFilterForm
from .models import (
    Customer,
    Order,
    OrderItem,
    OutgoingEmail,
    PromoCode,
    ShopSettings,
    build_order_number,
    normalize_email,
    normalize_phone,
    normalize_promo_code,
)
from .services import (
    CheckoutError,
    calculate_totals,
    create_order,
    find_customer_by_phone,
)

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


# --- Этап 5: покупатели и оформление заказа ----------------------------------

CONTACT = {
    "name": "Мария",
    "phone": "+7 (918) 123-45-67",
    "email": "",
    "address": "ул. Таганрогская, 140/4, кв. 12",
    "note": "",
}


class ContactNormalizationTests(TestCase):
    """Нормализация телефона и email для поиска покупателя."""

    def test_phone_keeps_digits_only(self):
        self.assertEqual(normalize_phone("+7 (918) 123-45-67"), "79181234567")
        self.assertEqual(normalize_phone("  8(918)123-45-67 "), "79181234567")
        self.assertEqual(normalize_phone("9181234567"), "9181234567")

    def test_phone_empty_becomes_empty_string(self):
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(None), "")

    def test_email_lowercased_and_stripped(self):
        self.assertEqual(normalize_email("  User@Example.COM "), "user@example.com")


class CheckoutFormTests(TestCase):
    """Валидация формы оформления: обязательность и формат полей."""

    def test_required_fields(self):
        form = CheckoutForm(data={})
        self.assertFalse(form.is_valid())
        for field in ("name", "phone", "address"):
            self.assertIn(field, form.errors)
        # Email и примечание необязательны.
        self.assertNotIn("email", form.errors)
        self.assertNotIn("note", form.errors)

    def test_short_name_rejected(self):
        form = CheckoutForm(data={**CONTACT, "name": "Я"})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_phone_without_enough_digits_rejected(self):
        form = CheckoutForm(data={**CONTACT, "phone": "123"})
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_phone_with_brackets_and_dashes_accepted(self):
        form = CheckoutForm(data={**CONTACT, "phone": "8 (918) 123-45-67"})
        self.assertTrue(form.is_valid(), form.errors)
        # В заказ уходит введённый вид, нормализация — только для поиска.
        self.assertEqual(form.cleaned_data["phone"], "8 (918) 123-45-67")

    def test_email_optional_and_normalized(self):
        form = CheckoutForm(data={**CONTACT, "email": "  User@Example.com "})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "user@example.com")

    def test_invalid_email_rejected_politely(self):
        form = CheckoutForm(data={**CONTACT, "email": "не-email"})
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)


class CreateOrderServiceTests(TestCase):
    """Создание заказа: снимки, деньги, покупатель, номер."""

    def setUp(self):
        self.category = Category.objects.create(name="Сосны")
        self.product = Product.objects.create(category=self.category, name="Сосна крымская")
        self.variant = ProductVariant.objects.create(
            product=self.product, size="1,5 м", price=Decimal("3900.00")
        )
        self.variant2 = ProductVariant.objects.create(
            product=self.product, size="2 м", price=Decimal("4900.00")
        )

    def make_order(self, lines=None, promo_code=None, **contact):
        data = {**CONTACT, **contact}
        return create_order(
            lines=lines if lines is not None else [(self.variant.pk, 2)],
            promo_code=promo_code,
            **data,
        )

    def test_order_created_with_snapshots_and_default_status(self):
        order = self.make_order()
        self.assertEqual(order.status, Order.STATUS_PROCESSING)
        self.assertEqual(order.name, "Мария")
        self.assertEqual(order.phone, CONTACT["phone"])
        self.assertEqual(order.address, CONTACT["address"])
        self.assertEqual(order.subtotal, Decimal("7800.00"))
        self.assertEqual(order.discount, Decimal("0.00"))
        self.assertEqual(order.total, Decimal("7800.00"))

        item = order.items.get()
        self.assertEqual(item.product_name, "Сосна крымская")
        self.assertEqual(item.variant_size, "1,5 м")
        self.assertEqual(item.unit_price, Decimal("3900.00"))
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.total_price, Decimal("7800.00"))
        # Позиции связаны с каталогом для служебной навигации.
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.variant, self.variant)

    def test_order_number_format(self):
        order = self.make_order()
        self.assertTrue(order.number.startswith(f"ЁД-{timezone.now().year}-"))
        self.assertEqual(order.number, build_order_number(order.pk, timezone.now().year))
        self.assertTrue(Order.objects.filter(number=order.number).exists())

    def test_customer_created_and_linked(self):
        order = self.make_order()
        self.assertIsNotNone(order.customer)
        self.assertEqual(order.customer.name, "Мария")
        self.assertEqual(order.customer.phone_normalized, "79181234567")

    def test_repeat_order_links_to_same_customer_by_phone(self):
        first = self.make_order()
        second = self.make_order(lines=[(self.variant2.pk, 1)], name="Машенька")
        self.assertEqual(first.customer, second.customer)
        self.assertEqual(Customer.objects.count(), 1)

    def test_ambiguous_phone_creates_separate_customer(self):
        # Два разных покупателя с одинаковым нормализованным телефоном:
        # автоматическое объединение запрещено, создаём отдельную запись.
        Customer.objects.create(name="Иван", phone="+7 (918) 123-45-67")
        Customer.objects.create(name="Игорь", phone="8 (918) 123-45-67")
        order = self.make_order()
        self.assertEqual(Customer.objects.count(), 3)
        self.assertNotEqual(order.customer.phone_normalized, "")
        self.assertIsNone(find_customer_by_phone(CONTACT["phone"]))

    def test_promo_applied_and_snapshotted(self):
        promo = make_promo(code="ЁЛКА10", discount_value=Decimal("10"))
        order = self.make_order(
            lines=[(self.variant.pk, 1)], promo_code=promo.code
        )
        self.assertEqual(order.subtotal, Decimal("3900.00"))
        self.assertEqual(order.discount, Decimal("390.00"))
        self.assertEqual(order.total, Decimal("3510.00"))
        self.assertEqual(order.promo_code, "ЁЛКА10")
        self.assertEqual(order.promo_discount_type, PromoCode.DISCOUNT_PERCENT)
        self.assertEqual(order.promo_discount_value, Decimal("10"))

    def test_expired_promo_gives_no_discount_but_order_created(self):
        promo = make_promo(code="OLD", ends_at=NOW - timedelta(days=1))
        order = self.make_order(
            lines=[(self.variant.pk, 1)], promo_code=promo.code
        )
        self.assertEqual(order.discount, Decimal("0.00"))
        self.assertEqual(order.total, Decimal("3900.00"))
        self.assertEqual(order.promo_code, "")

    def test_unavailable_variant_skipped(self):
        self.variant.is_active = False
        self.variant.save()
        order = self.make_order(
            lines=[(self.variant.pk, 1), (self.variant2.pk, 1)]
        )
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.subtotal, Decimal("4900.00"))

    def test_empty_or_fully_unavailable_cart_rejected(self):
        with self.assertRaises(CheckoutError):
            self.make_order(lines=[])
        self.variant.is_active = False
        self.variant.save()
        self.variant2.is_active = False
        self.variant2.save()
        with self.assertRaises(CheckoutError):
            self.make_order(lines=[(self.variant.pk, 1), (self.variant2.pk, 1)])
        self.assertEqual(Order.objects.count(), 0)

    def test_quantity_clamped_to_stock_at_checkout(self):
        self.variant.stock = 3
        self.variant.save()
        order = self.make_order(lines=[(self.variant.pk, 10)])
        item = order.items.get()
        self.assertEqual(item.quantity, 3)
        self.assertEqual(order.total, Decimal("11700.00"))

    def test_catalog_change_does_not_rewrite_old_order(self):
        order = self.make_order()
        self.product.name = "Сосна новая"
        self.product.save()
        self.variant.price = Decimal("9999.00")
        self.variant.save()
        self.variant.delete()  # удаление варианта не должно удалить позицию

        order.refresh_from_db()
        item = order.items.get()
        self.assertEqual(item.product_name, "Сосна крымская")
        self.assertEqual(item.unit_price, Decimal("3900.00"))
        self.assertEqual(item.total_price, Decimal("7800.00"))
        self.assertEqual(order.total, Decimal("7800.00"))
        self.assertIsNone(item.variant)


class CheckoutViewTests(TestCase):
    """HTTP-сценарии оформления: форма, ошибки, повторы, подтверждение."""

    def setUp(self):
        self.category = Category.objects.create(name="Сосны")
        self.product = Product.objects.create(category=self.category, name="Сосна крымская")
        self.variant = ProductVariant.objects.create(
            product=self.product, size="1,5 м", price=Decimal("3900.00")
        )

    def add_to_session_cart(self, variant=None, quantity=2):
        session = self.client.session
        session["cart"] = {str((variant or self.variant).pk): quantity}
        session.save()

    def get_checkout_token(self):
        return self.client.session.get("checkout_token")

    def open_checkout(self):
        """GET формы — обязательный шаг: он выдаёт checkout-token."""
        return self.client.get(reverse("orders:checkout"))

    def post_checkout(self, data=None):
        payload = {
            "ct": self.get_checkout_token() or "",
            "name": "Мария",
            "phone": "+7 (918) 123-45-67",
            "email": "",
            "address": "ул. Таганрогская, 140/4, кв. 12",
            "note": "После 18:00",
        }
        payload.update(data or {})
        return self.client.post(reverse("orders:checkout"), data=payload)

    def test_checkout_page_shows_form_and_summary(self):
        self.add_to_session_cart()
        response = self.open_checkout()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Оформление заказа")
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="phone"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="address"')
        self.assertContains(response, 'name="note"')
        # Обязательные поля помечены звёздочкой, у полей есть текст-помощник.
        self.assertContains(response, 'aria-hidden="true">*</span>')
        self.assertContains(response, "Позвоним, чтобы подтвердить заказ")
        self.assertContains(response, "Сосна крымская")
        self.assertContains(response, "Заказать")

    def test_checkout_redirects_when_cart_empty(self):
        response = self.open_checkout()
        self.assertRedirects(response, reverse("cart:detail"))

    def test_successful_checkout_creates_order_and_clears_cart(self):
        self.add_to_session_cart()
        self.open_checkout()
        response = self.post_checkout()
        self.assertRedirects(response, reverse("orders:confirmation"))

        order = Order.objects.get()
        self.assertEqual(order.items.get().quantity, 2)
        self.assertEqual(order.total, Decimal("7800.00"))
        self.assertEqual(order.note, "После 18:00")
        self.assertEqual(self.client.session.get("cart"), None)

        # Подтверждение: номер заказа, телефон и кнопка «Скачать».
        response = self.client.get(reverse("orders:confirmation"))
        self.assertContains(response, order.number)
        self.assertContains(response, "Заказ оформлен")
        self.assertContains(response, "+7 (918) 584-34-34")
        self.assertContains(response, "Скачать")
        self.assertContains(response, "скриншот")
        self.assertContains(response, "После 18:00")

    def test_checkout_with_promo(self):
        promo = make_promo(code="ЁЛКА10", discount_value=Decimal("10"))
        self.add_to_session_cart()
        session = self.client.session
        session["cart_promo"] = promo.code
        session.save()
        self.open_checkout()
        self.post_checkout()
        order = Order.objects.get()
        self.assertEqual(order.discount, Decimal("780.00"))
        self.assertEqual(order.total, Decimal("7020.00"))
        response = self.client.get(reverse("orders:confirmation"))
        self.assertContains(response, "ЁЛКА10")

    def test_invalid_form_preserves_data_and_creates_nothing(self):
        self.add_to_session_cart()
        self.open_checkout()
        response = self.post_checkout(
            data={"name": "", "phone": "123", "email": "не-email"}
        )
        self.assertEqual(response.status_code, 200)
        # Поля с ошибками выделены и под ними есть пояснения.
        self.assertContains(response, "input-error")
        self.assertContains(response, "укажите имя")
        self.assertContains(response, "в номере ошибка")
        # Введённые ранее данные не исчезли.
        self.assertContains(response, CONTACT["address"])
        self.assertContains(response, "не-email")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)

    def test_post_with_empty_cart_creates_nothing(self):
        self.open_checkout()
        # Корзину специально оставляем пустой.
        response = self.post_checkout()
        self.assertRedirects(response, reverse("cart:detail"))
        self.assertEqual(Order.objects.count(), 0)

    def test_post_without_token_rejected(self):
        self.add_to_session_cart()
        response = self.post_checkout(data={"ct": "чужой-токен"})
        self.assertRedirects(response, reverse("orders:checkout"))
        # Оформление не произошло: токен не совпал.
        self.assertEqual(Order.objects.count(), 0)

    def test_repeat_submit_after_success_redirects_without_new_order(self):
        self.add_to_session_cart()
        self.open_checkout()
        self.post_checkout()
        # Тот же POST повторно: корзина уже пуста, токен сгорел.
        response = self.post_checkout()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)

    def test_confirmation_closed_for_other_sessions(self):
        self.add_to_session_cart()
        self.open_checkout()
        self.post_checkout()

        # Другая сессия не видит чужое подтверждение, даже зная ID заказа:
        # доступ живёт только в сессии оформления и только к последнему заказу.
        other = Client()
        response = other.get(reverse("orders:confirmation"))
        self.assertRedirects(response, reverse("shop:home"))


class OrderAdminTests(TestCase):
    """Админка заказов: доступ staff, фильтры и поиск по снимку заказа."""

    def setUp(self):
        self.category = Category.objects.create(name="Сосны")
        self.product = Product.objects.create(category=self.category, name="Сосна крымская")
        self.variant = ProductVariant.objects.create(
            product=self.product, size="1,5 м", price=Decimal("3900.00")
        )
        self.staff = User.objects.create_user(
            username="manager", password="pass", is_staff=True, is_superuser=True
        )
        self.client.force_login(self.staff)
        self.order = create_order(
            lines=[(self.variant.pk, 1)], promo_code=None, **CONTACT
        )

    def test_changelist_available_with_filters(self):
        response = self.client.get(reverse("admin:orders_order_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.number)

    def test_search_by_number_name_and_address(self):
        for query in (self.order.number, "Мария", "Таганрогская"):
            response = self.client.get(
                reverse("admin:orders_order_changelist"), {"q": query}
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.order.number)

    def test_status_filter(self):
        response = self.client.get(
            reverse("admin:orders_order_changelist"),
            {"status__exact": Order.STATUS_PROCESSING},
        )
        self.assertContains(response, self.order.number)
        response = self.client.get(
            reverse("admin:orders_order_changelist"),
            {"status__exact": Order.STATUS_COMPLETED},
        )
        self.assertNotContains(response, self.order.number)

    def test_anonymous_has_no_access(self):
        anonymous = Client()
        response = anonymous.get(reverse("admin:orders_order_changelist"))
        self.assertEqual(response.status_code, 302)

    def test_order_items_inline_and_readonly_snapshot(self):
        response = self.client.get(
            reverse("admin:orders_order_change", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сосна крымская")
        self.assertContains(response, "1,5 м")


# --- Этап 6: почтовая очередь -------------------------------------------------

MANAGER_EMAIL = "contracts-2025@mail.ru"


def setup_catalog(cls):
    cls.category = Category.objects.create(name="Сосны")
    cls.product = Product.objects.create(category=cls.category, name="Сосна крымская")
    cls.variant = ProductVariant.objects.create(
        product=cls.product, size="1,5 м", price=Decimal("3900.00")
    )


def setup_manager_email():
    solo = ShopSettings.get_solo()
    solo.manager_email = MANAGER_EMAIL
    solo.save()


class OrderEmailQueueTests(TestCase):
    """Постановка писем в очередь в одной транзакции с заказом."""

    def setUp(self):
        setup_catalog(self)
        setup_manager_email()

    def make_order(self, email="maria@example.com", promo_code=None, note=""):
        return create_order(
            lines=[(self.variant.pk, 1)],
            promo_code=promo_code,
            **{**CONTACT, "email": email, "note": note},
        )

    def test_two_emails_queued_for_customer_and_manager(self):
        order = self.make_order()
        self.assertEqual(OutgoingEmail.objects.count(), 2)
        customer = OutgoingEmail.objects.get(kind=OutgoingEmail.KIND_CUSTOMER)
        manager = OutgoingEmail.objects.get(kind=OutgoingEmail.KIND_MANAGER)
        self.assertEqual(customer.to, "maria@example.com")
        self.assertEqual(manager.to, MANAGER_EMAIL)
        self.assertEqual(customer.order_number, order.number)
        self.assertEqual(customer.order, order)
        # Свежие записи готовы к отправке.
        self.assertEqual(customer.status, OutgoingEmail.STATUS_PENDING)
        self.assertEqual(customer.attempts, 0)
        self.assertIsNone(customer.next_attempt_at)
        self.assertNotEqual(customer.key, manager.key)

    def test_email_bodies_contain_full_order_info(self):
        order = self.make_order(note="После 18:00")
        customer = OutgoingEmail.objects.get(kind=OutgoingEmail.KIND_CUSTOMER)
        for body in (customer.body_text, customer.body_html):
            for fragment in (
                order.number,
                "Сосна крымская",
                "1,5 м",
                "3900",
                CONTACT["address"],
                CONTACT["phone"],
                "После 18:00",
            ):
                self.assertIn(fragment, body)
        self.assertIn(order.number, customer.subject)
        manager = OutgoingEmail.objects.get(kind=OutgoingEmail.KIND_MANAGER)
        self.assertIn("Новый заказ", manager.subject)
        self.assertIn(order.number, manager.body_text)

    def test_promo_mentioned_in_email(self):
        promo = make_promo(code="ЁЛКА10", discount_value=Decimal("10"))
        self.make_order(promo_code=promo.code)
        customer = OutgoingEmail.objects.get(kind=OutgoingEmail.KIND_CUSTOMER)
        self.assertIn("ЁЛКА10", customer.body_text)
        self.assertIn("390", customer.body_text)  # скидка 10% от 3900

    def test_customer_email_skipped_without_email(self):
        self.make_order(email="")
        self.assertEqual(OutgoingEmail.objects.count(), 1)
        self.assertEqual(
            OutgoingEmail.objects.get().kind, OutgoingEmail.KIND_MANAGER
        )

    def test_manager_email_skipped_without_settings(self):
        solo = ShopSettings.get_solo()
        solo.manager_email = ""
        solo.save()
        self.make_order()
        self.assertEqual(OutgoingEmail.objects.count(), 1)
        self.assertEqual(
            OutgoingEmail.objects.get().kind, OutgoingEmail.KIND_CUSTOMER
        )

    def test_queue_idempotent_by_key(self):
        order = self.make_order()
        queue_order_emails(order)
        self.assertEqual(OutgoingEmail.objects.count(), 2)

    def test_queue_rolls_back_with_order(self):
        # Ошибка постановки в очередь откатывает и заказ, и письма:
        # нет заказа без писем и писем без заказа.
        with mock.patch(
            "orders.services.queue_order_emails", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self.make_order()
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OutgoingEmail.objects.count(), 0)


class SendOrderEmailsCommandTests(TestCase):
    """Обработчик очереди: отправка, повторные попытки, отказ, партии."""

    def setUp(self):
        setup_catalog(self)
        setup_manager_email()

    def make_order(self, email="maria@example.com"):
        return create_order(
            lines=[(self.variant.pk, 1)],
            promo_code=None,
            **{**CONTACT, "email": email},
        )

    def run_command(self, **options):
        """Запуск команды с подменой SMTP-отправки; возвращает mock send()."""
        patcher = mock.patch("orders.emails.EmailMultiAlternatives.send")
        send_mock = patcher.start()
        self.addCleanup(patcher.stop)
        call_command("send_order_emails", **options)
        return send_mock

    def make_pending_email(self, key="test:pending", **kwargs):
        defaults = {
            "order": None,
            "order_number": "ЁД-2026-999999",
            "kind": OutgoingEmail.KIND_CUSTOMER,
            "key": key,
            "to": "x@example.com",
            "subject": "Тема",
            "body_text": "текст",
        }
        defaults.update(kwargs)
        return OutgoingEmail.objects.create(**defaults)

    def test_sends_queued_emails_and_marks_sent(self):
        self.make_order()
        send_mock = self.run_command()
        self.assertEqual(send_mock.call_count, 2)
        for m in OutgoingEmail.objects.all():
            self.assertEqual(m.status, OutgoingEmail.STATUS_SENT)
            self.assertIsNotNone(m.sent_at)
            self.assertEqual(m.attempts, 1)
            self.assertEqual(m.last_error, "")
        # Повторный запуск не шлёт уже отправленные письма.
        send_mock = self.run_command()
        send_mock.assert_not_called()

    def test_command_logs_result(self):
        self.make_order()
        with self.assertLogs("orders.mail", level="INFO") as cm:
            self.run_command()
        self.assertTrue(any("Отправлено письмо" in m for m in cm.output))

    def test_batch_limit(self):
        self.make_order(email="a@example.com")
        self.make_order(email="b@example.com")
        send_mock = self.run_command(batch=3)
        self.assertEqual(send_mock.call_count, 3)
        self.assertEqual(
            OutgoingEmail.objects.filter(status=OutgoingEmail.STATUS_SENT).count(), 3
        )
        self.assertEqual(
            OutgoingEmail.objects.filter(status=OutgoingEmail.STATUS_PENDING).count(),
            1,
        )

    def test_temporary_error_schedules_retry(self):
        m = self.make_pending_email()
        with mock.patch(
            "orders.emails.EmailMultiAlternatives.send",
            side_effect=Exception("SMTP: connection refused"),
        ):
            call_command("send_order_emails")
        m.refresh_from_db()
        self.assertEqual(m.status, OutgoingEmail.STATUS_PENDING)
        self.assertEqual(m.attempts, 1)
        self.assertGreater(m.next_attempt_at, timezone.now())
        self.assertIn("connection refused", m.last_error)

    def test_future_retry_not_taken_yet(self):
        m = self.make_pending_email(
            key="test:future",
            next_attempt_at=timezone.now() + timedelta(hours=1),
        )
        send_mock = self.run_command()
        send_mock.assert_not_called()
        m.refresh_from_db()
        self.assertEqual(m.status, OutgoingEmail.STATUS_PENDING)

    def test_permanent_error_fails_immediately(self):
        m = self.make_pending_email(key="test:permanent")
        with mock.patch(
            "orders.emails.EmailMultiAlternatives.send",
            side_effect=smtplib.SMTPAuthenticationError(535, b"auth failed"),
        ):
            call_command("send_order_emails")
        m.refresh_from_db()
        self.assertEqual(m.status, OutgoingEmail.STATUS_FAILED)
        self.assertEqual(m.attempts, 1)
        self.assertIsNone(m.next_attempt_at)

    def test_attempts_exhausted_marks_failed(self):
        m = self.make_pending_email(key="test:exhausted", attempts=MAX_ATTEMPTS - 1)
        with mock.patch(
            "orders.emails.EmailMultiAlternatives.send",
            side_effect=Exception("SMTP: timeout"),
        ):
            call_command("send_order_emails")
        m.refresh_from_db()
        self.assertEqual(m.status, OutgoingEmail.STATUS_FAILED)
        self.assertEqual(m.attempts, MAX_ATTEMPTS)

    def test_stale_sending_reclaimed(self):
        # Письмо зависло в sending (обработчик упал): возвращаем и шлём.
        self.make_order()
        OutgoingEmail.objects.update(
            status=OutgoingEmail.STATUS_SENDING,
            updated_at=timezone.now() - timedelta(minutes=30),
        )
        send_mock = self.run_command()
        self.assertEqual(send_mock.call_count, 2)
        self.assertEqual(
            OutgoingEmail.objects.filter(status=OutgoingEmail.STATUS_SENT).count(), 2
        )

    def test_sends_via_configured_mailer(self):
        # Сквозной тест через реальный тестовый backend (locmem):
        # письма уходят с темами и HTML-альтернативой.
        self.make_order()
        with override_settings(
            MAILERS={
                "default": {
                    "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
                }
            }
        ):
            call_command("send_order_emails")
        self.assertEqual(len(mail.outbox), 2)
        for message in mail.outbox:
            self.assertIn("ЁД-", message.subject)
            self.assertEqual(message.from_email, settings.DEFAULT_FROM_EMAIL)
            self.assertTrue(
                any(mime == "text/html" for _, mime in message.alternatives)
            )


class OutgoingEmailAdminTests(TestCase):
    """Админка почтовой очереди и настроек магазина."""

    def setUp(self):
        setup_catalog(self)
        setup_manager_email()
        self.staff = User.objects.create_user(
            username="manager", password="pass", is_staff=True, is_superuser=True
        )
        self.client.force_login(self.staff)
        self.order = create_order(
            lines=[(self.variant.pk, 1)],
            promo_code=None,
            **{**CONTACT, "email": "maria@example.com"},
        )
        self.email = OutgoingEmail.objects.get(kind=OutgoingEmail.KIND_CUSTOMER)

    def test_changelist_renders_with_filters(self):
        response = self.client.get(reverse("admin:orders_outgoingemail_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.email.to)
        response = self.client.get(
            reverse("admin:orders_outgoingemail_changelist"),
            {"status__exact": OutgoingEmail.STATUS_PENDING},
        )
        self.assertContains(response, self.email.to)

    def test_requeue_action_resets_failed_email(self):
        self.email.status = OutgoingEmail.STATUS_FAILED
        self.email.attempts = MAX_ATTEMPTS
        self.email.save()
        response = self.client.post(
            reverse("admin:orders_outgoingemail_changelist"),
            {"action": "requeue", "_selected_action": [self.email.pk]},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertEqual(self.email.status, OutgoingEmail.STATUS_PENDING)
        self.assertEqual(self.email.attempts, 0)

    def test_order_change_page_shows_email_inline(self):
        response = self.client.get(
            reverse("admin:orders_order_change", args=[self.order.pk])
        )
        self.assertContains(response, self.email.to)
        self.assertContains(response, "Исходящие письма")

    def test_shop_settings_admin_page(self):
        # Настройки магазина (email менеджера) доступны в админке.
        response = self.client.get(reverse("admin:orders_shopsettings_changelist"))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(
            reverse("admin:orders_shopsettings_change", args=[1])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, MANAGER_EMAIL)


class CertifiSmtpBackendTests(TestCase):
    """SMTP-бэкенд с явным CA-набором: сборка mailer'а и SSL-контекста."""

    def test_mailer_builds_ssl_context_with_ca_bundle(self):
        import certifi

        from django.core.mail import mailers

        with override_settings(
            MAILERS={
                "default": {
                    "BACKEND": "config.mail_backends.CertifiSMTPEmailBackend",
                    "OPTIONS": {
                        "host": "smtp.example.com",
                        "cafile": certifi.where(),
                    },
                }
            }
        ):
            connection = mailers.create_connection("default")
        self.assertIsNotNone(connection.ssl_context)

    def test_mailer_without_cafile_matches_default_behavior(self):
        from django.core.mail import mailers

        with override_settings(
            MAILERS={
                "default": {
                    "BACKEND": "config.mail_backends.CertifiSMTPEmailBackend",
                    "OPTIONS": {"host": "smtp.example.com"},
                }
            }
        ):
            connection = mailers.create_connection("default")
        self.assertIsNotNone(connection.ssl_context)


# --- Этап 7: staff-страницы менеджера и администратора -------------------------


def make_staff_user(username, *, manager=False, superuser=False):
    """Тестовый сотрудник. manager=True — в группу «Менеджер»."""
    user = User.objects.create_user(username=username, password="pass", is_staff=True)
    if manager:
        call_command("ensure_manager_group")
        user.groups.add(Group.objects.get(name="Менеджер"))
    if superuser:
        user.is_superuser = True
        user.save()
    return user


def bulk_orders(count, *, base_minutes=0, **kwargs):
    """Набор заказов напрямую в БД (быстро): от самых новых к старым."""
    defaults = dict(
        name="Покупатель",
        phone="+7 (900) 000-00-00",
        address="ул. Тестовая, 1",
        subtotal=Decimal("100.00"),
        discount=Decimal("0.00"),
        total=Decimal("100.00"),
    )
    defaults.update(kwargs)
    now = timezone.now() - timedelta(minutes=base_minutes)
    orders = [
        Order(
            number=f"ЁД-2026-{100000 + i:06d}",
            created_at=now - timedelta(minutes=i),
            **defaults,
        )
        for i in range(count)
    ]
    Order.objects.bulk_create(orders)
    return orders


class EnsureManagerGroupCommandTests(TestCase):
    """Группа «Менеджер»: состав прав и идемпотентность команды."""

    def test_group_created_with_expected_permissions(self):
        call_command("ensure_manager_group")
        group = Group.objects.get(name="Менеджер")
        codenames = set(group.permissions.values_list("codename", flat=True))
        self.assertIn("view_order", codenames)
        self.assertIn("change_order", codenames)
        self.assertIn("view_customer", codenames)
        self.assertIn("view_promocode", codenames)

    def test_no_dangerous_permissions(self):
        call_command("ensure_manager_group")
        group = Group.objects.get(name="Менеджер")
        codenames = set(group.permissions.values_list("codename", flat=True))
        # Удаление заказов, критичные настройки и пользователи — только админу.
        for forbidden in (
            "delete_order",
            "add_order",
            "delete_customer",
            "view_shopsettings",
            "change_shopsettings",
            "view_outgoingemail",
            "add_user",
            "change_user",
            "delete_user",
        ):
            self.assertNotIn(forbidden, codenames)

    def test_command_is_idempotent(self):
        call_command("ensure_manager_group")
        first = list(
            Group.objects.get(name="Менеджер")
            .permissions.values_list("pk", flat=True)
        )
        call_command("ensure_manager_group")
        second = list(
            Group.objects.get(name="Менеджер")
            .permissions.values_list("pk", flat=True)
        )
        self.assertEqual(sorted(first), sorted(second))

    def test_manager_can_view_and_change_orders(self):
        user = make_staff_user("manager", manager=True)
        self.assertTrue(user.has_perm("orders.view_order"))
        self.assertTrue(user.has_perm("orders.change_order"))
        self.assertFalse(user.has_perm("orders.delete_order"))
        self.assertFalse(user.has_perm("orders.view_shopsettings"))


class StaffAccessTests(TestCase):
    """Доступ к staff-страницам: аноним, обычный пользователь, менеджер, админ."""

    @classmethod
    def setUpTestData(cls):
        setup_catalog(cls)
        cls.order = create_order(
            lines=[(cls.variant.pk, 1)], promo_code=None, **CONTACT
        )
        cls.manager = make_staff_user("manager", manager=True)
        cls.admin = make_staff_user("admin7", superuser=True)
        cls.regular = User.objects.create_user(username="regular", password="pass")

    def test_anonymous_redirected_to_login(self):
        for url in ("orders:staff_orders", "orders:staff_customers"):
            with self.subTest(url=url):
                response = self.client.get(reverse(url))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_login_page_available(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вход для сотрудников")

    def test_regular_user_forbidden(self):
        self.client.force_login(self.regular)
        for url in ("orders:staff_orders", "orders:staff_customers"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(reverse(url)).status_code, 403)

    def test_staff_without_permissions_forbidden(self):
        staff_no_perms = User.objects.create_user(
            username="helper", password="pass", is_staff=True
        )
        self.client.force_login(staff_no_perms)
        self.assertEqual(
            self.client.get(reverse("orders:staff_orders")).status_code, 403
        )

    def test_manager_has_access(self):
        self.client.force_login(self.manager)
        for url in ("orders:staff_orders", "orders:staff_customers"):
            with self.subTest(url=url):
                response = self.client.get(reverse(url))
                self.assertEqual(response.status_code, 200)

    def test_admin_has_access(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("orders:staff_orders")).status_code, 200
        )

    def test_manager_admin_access_limited(self):
        """Менеджер заходит в админку, но не в пользователей и настройки."""
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse("admin:index")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("admin:orders_order_changelist")).status_code,
            200,
        )
        # Управление пользователями — только администратору.
        self.assertEqual(
            self.client.get(reverse("admin:auth_user_changelist")).status_code,
            403,
        )
        # Критичные настройки магазина — только администратору.
        self.assertEqual(
            self.client.get(reverse("admin:orders_shopsettings_changelist")).status_code,
            403,
        )

    def test_manager_cannot_delete_order(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("orders:staff_order_delete", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())


class StaffOrderFilterTests(TestCase):
    """Сервис фильтров заказов: статус, дата, категория, промокод, поиск."""

    @classmethod
    def setUpTestData(cls):
        setup_catalog(cls)
        cls.category2 = Category.objects.create(name="Подставки")
        cls.product2 = Product.objects.create(
            category=cls.category2, name="Подставка кованая"
        )
        cls.variant2 = ProductVariant.objects.create(
            product=cls.product2, size="—", price=Decimal("900.00")
        )
        cls.promo = make_promo(code="ЁЛКА10")
        cls.order_promo = create_order(
            lines=[(cls.variant.pk, 1)], promo_code=cls.promo.code, **CONTACT
        )
        cls.order_plain = create_order(
            lines=[(cls.variant2.pk, 1)],
            promo_code=None,
            name="Ольга",
            phone="+7 (928) 555-13-13",
            email="",
            address="пр. Михаила Нагибина, 5",
            note="",
        )

    def test_newest_first(self):
        orders, _ = staff_services.filter_orders(staff_services.OrderFilters())
        self.assertGreaterEqual(
            orders[0].created_at, orders[-1].created_at
        )

    def test_filter_by_status(self):
        self.order_plain.status = Order.STATUS_COMPLETED
        self.order_plain.save(update_fields=["status"])
        orders, _ = staff_services.filter_orders(
            staff_services.OrderFilters(status=Order.STATUS_COMPLETED)
        )
        self.assertEqual([o.pk for o in orders], [self.order_plain.pk])

    def test_filter_by_date_range(self):
        today = timezone.localdate()
        orders, _ = staff_services.filter_orders(
            staff_services.OrderFilters(date_from=today, date_to=today)
        )
        self.assertEqual(len(orders), 2)
        orders, _ = staff_services.filter_orders(
            staff_services.OrderFilters(date_to=today - timedelta(days=1))
        )
        self.assertEqual(orders, [])

    def test_filter_by_category_matches_any_position(self):
        # Заказ с товарами двух категорий виден при фильтре по любой из них.
        combo = create_order(
            lines=[(self.variant.pk, 1), (self.variant2.pk, 1)],
            promo_code=None,
            name="Дуэт",
            phone="+7 (900) 000-00-01",
            email="",
            address="ул. Комбо, 1",
            note="",
        )
        by_first, _ = staff_services.filter_orders(
            staff_services.OrderFilters(category_id=self.category.pk)
        )
        by_second, _ = staff_services.filter_orders(
            staff_services.OrderFilters(category_id=self.category2.pk)
        )
        self.assertIn(combo.pk, [o.pk for o in by_first])
        self.assertIn(combo.pk, [o.pk for o in by_second])
        self.assertNotIn(self.order_promo.pk, [o.pk for o in by_second])

    def test_filter_by_promo_presence(self):
        with_promo, _ = staff_services.filter_orders(
            staff_services.OrderFilters(promo="yes")
        )
        without_promo, _ = staff_services.filter_orders(
            staff_services.OrderFilters(promo="no")
        )
        self.assertEqual([o.pk for o in with_promo], [self.order_promo.pk])
        self.assertNotIn(self.order_promo.pk, [o.pk for o in without_promo])

    def test_search_is_case_insensitive_cyrillic(self):
        # SQLite LIKE сворачивает регистр только ASCII: проверяем кириллицу.
        for needle in ("мАрИя", "мария", "МАРИЯ"):
            with self.subTest(needle=needle):
                orders, _ = staff_services.filter_orders(
                    staff_services.OrderFilters(search=needle)
                )
                self.assertIn(self.order_promo.pk, [o.pk for o in orders])

    def test_search_by_product_and_promo_and_address(self):
        by_product, _ = staff_services.filter_orders(
            staff_services.OrderFilters(search="сосна")
        )
        self.assertIn(self.order_promo.pk, [o.pk for o in by_product])
        by_promo, _ = staff_services.filter_orders(
            staff_services.OrderFilters(search="ёлка10")
        )
        self.assertEqual([o.pk for o in by_promo], [self.order_promo.pk])
        by_address, _ = staff_services.filter_orders(
            staff_services.OrderFilters(search="нАгибинА")
        )
        self.assertEqual([o.pk for o in by_address], [self.order_plain.pk])

    def test_default_limit_and_lifting(self):
        bulk_orders(105, name="Массовый")
        filters = staff_services.OrderFilters()
        orders, total = staff_services.filter_orders(filters)
        self.assertEqual(len(orders), staff_services.DEFAULT_LIMIT)
        self.assertEqual(total, 107)
        stats = staff_services.summarize_orders(orders, total, filters)
        self.assertTrue(stats.limited)

        # Любой фильтр/поиск снимает ограничение: видны все подходящие.
        lifted, total_lifted = staff_services.filter_orders(
            staff_services.OrderFilters(search="массовый")
        )
        self.assertEqual(len(lifted), 105)
        self.assertEqual(total_lifted, 105)
        stats = staff_services.summarize_orders(
            lifted, total_lifted, staff_services.OrderFilters(search="массовый")
        )
        self.assertFalse(stats.limited)

    def test_stats_sums_visible_orders(self):
        orders, total = staff_services.filter_orders(staff_services.OrderFilters())
        stats = staff_services.summarize_orders(
            orders, total, staff_services.OrderFilters()
        )
        expected = self.order_promo.total + self.order_plain.total
        self.assertEqual(stats.shown, 2)
        self.assertEqual(stats.total_sum, expected)

    def test_paginate(self):
        items = list(range(1, 121))
        page = staff_services.paginate(items, "2", 50)
        self.assertEqual(page.number, 2)
        self.assertEqual(page.num_pages, 3)
        self.assertEqual(len(page.items), 50)
        self.assertTrue(page.has_previous)
        self.assertTrue(page.has_next)
        # Некорректные номера страниц не падают.
        self.assertEqual(staff_services.paginate(items, "abc", 50).number, 1)
        self.assertEqual(staff_services.paginate(items, "99", 50).number, 3)


class StaffOrdersViewTests(TestCase):
    """Staff-страница заказов: список, статус, редактирование, удаление, экспорт."""

    @classmethod
    def setUpTestData(cls):
        setup_catalog(cls)
        cls.order = create_order(
            lines=[(cls.variant.pk, 2)],
            promo_code=None,
            **{**CONTACT, "email": "maria@example.com"},
        )
        cls.manager = make_staff_user("manager", manager=True)
        cls.admin = make_staff_user("admin7", superuser=True)

    def test_list_renders_order_and_stats(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_orders"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.number)
        self.assertContains(response, "Мария")
        self.assertContains(response, "Сосна крымская")
        self.assertContains(response, "Найдено заказов: 1")
        self.assertContains(response, "7 800 руб.")
        # Кнопки, доступные администратору: просмотр, редактирование, удаление.
        self.assertContains(response, "Экспорт в Excel")

    def test_pagination_50_per_page(self):
        bulk_orders(60, name="Массовый")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_orders"))
        self.assertContains(response, "Страница 1 из 2")
        response = self.client.get(reverse("orders:staff_orders"), {"page": 2})
        self.assertEqual(response.status_code, 200)

    def test_limit_warning_shown_and_hidden(self):
        bulk_orders(105)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_orders"))
        self.assertContains(response, "Показаны последние 100 заказов")
        # Предупреждение исчезает, когда лимит снят поиском.
        response = self.client.get(
            reverse("orders:staff_orders"), {"search": "массовый"}
        )
        self.assertNotContains(response, "Показаны последние 100")

    def test_export_url_keeps_filters(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("orders:staff_orders"), {"status": "processing"}
        )
        self.assertContains(response, "status=processing")

    def test_status_change_from_list(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("orders:staff_order_status", args=[self.order.pk]),
            {"status": Order.STATUS_COMPLETED},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Trigger"], "staff:reload")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_COMPLETED)

    def test_status_change_rejects_unknown_value(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("orders:staff_order_status", args=[self.order.pk]),
            {"status": "hacked"},
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PROCESSING)

    def test_edit_get_returns_form_partial(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("orders:staff_order_edit", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Редактирование заказа")
        self.assertContains(response, "Мария")

    def test_edit_post_updates_contacts_and_status(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("orders:staff_order_edit", args=[self.order.pk]),
            {
                "name": "Мария Иванова",
                "phone": "+7 (918) 123-45-67",
                "email": "",
                "address": "ул. Таганрогская, 140/4, кв. 13",
                "note": "Позвонить за час",
                "status": Order.STATUS_COMPLETED,
            },
        )
        self.assertEqual(response.status_code, 204)
        self.order.refresh_from_db()
        self.assertEqual(self.order.name, "Мария Иванова")
        self.assertEqual(self.order.address, "ул. Таганрогская, 140/4, кв. 13")
        self.assertEqual(self.order.status, Order.STATUS_COMPLETED)

    def test_edit_post_keeps_money_snapshot_immutable(self):
        """Деньги и позиции — исторический снимок: подсунуть их в POST нельзя."""
        self.client.force_login(self.manager)
        self.client.post(
            reverse("orders:staff_order_edit", args=[self.order.pk]),
            {
                "name": "Мария",
                "phone": "+7 (918) 123-45-67",
                "email": "",
                "address": "ул. Таганрогская, 140/4, кв. 12",
                "note": "",
                "status": "processing",
                "total": "1.00",
                "subtotal": "1.00",
            },
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.total, Decimal("7800.00"))

    def test_edit_post_invalid_returns_422(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("orders:staff_order_edit", args=[self.order.pk]),
            {
                "name": "",
                "phone": "123",
                "email": "",
                "address": "",
                "note": "",
                "status": "processing",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.order.refresh_from_db()
        self.assertEqual(self.order.name, "Мария")

    def test_delete_removes_order_and_keeps_emails(self):
        emails_before = OutgoingEmail.objects.count()
        self.assertGreater(emails_before, 0)
        self.client.force_login(self.admin)
        next_url = reverse("orders:staff_orders") + "?status=processing"
        response = self.client.post(
            reverse("orders:staff_order_delete", args=[self.order.pk]),
            {"next": next_url},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, next_url)
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())
        self.assertEqual(OrderItem.objects.count(), 0)
        # Записи писем остаются (снимок номера, связь SET_NULL).
        self.assertEqual(OutgoingEmail.objects.count(), emails_before)

    def test_orders_export_returns_xlsx(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_orders_export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        wb = load_workbook(io.BytesIO(response.content))
        ws = wb["Заказы"]
        self.assertEqual(ws["A1"].value, "Номер")
        self.assertEqual(ws["A2"].value, self.order.number)

    def test_order_export_single(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("orders:staff_order_export", args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(io.BytesIO(response.content))
        ws = wb["Заказ"]
        self.assertEqual(ws["A1"].value, "Номер заказа")
        self.assertEqual(ws["B1"].value, self.order.number)


class StaffCustomerServiceTests(TestCase):
    """Клиентская база: строки со сводкой, поиск, лимит."""

    @classmethod
    def setUpTestData(cls):
        setup_catalog(cls)
        cls.order = create_order(
            lines=[(cls.variant.pk, 1)],
            promo_code=None,
            **{**CONTACT, "email": "maria@example.com"},
        )

    def test_row_contains_contacts_addresses_and_totals(self):
        rows, total = staff_services.get_customer_rows()
        self.assertEqual(total, 1)
        row = rows[0]
        self.assertEqual(row.customer.name, "Мария")
        self.assertEqual(row.orders_count, 1)
        self.assertEqual(row.total_spent, Decimal("3900.00"))
        self.assertEqual(row.addresses, [CONTACT["address"]])

    def test_search_by_phone_and_address_case_insensitive(self):
        by_phone, _ = staff_services.get_customer_rows("918) 123")
        self.assertEqual(len(by_phone), 1)
        by_address, _ = staff_services.get_customer_rows("тАгАнрогскАя")
        self.assertEqual(len(by_address), 1)
        none_found, _ = staff_services.get_customer_rows("никого")
        self.assertEqual(none_found, [])

    def test_default_limit_and_lifting_by_search(self):
        customers = [
            Customer(name=f"Гость {i}", phone=f"+7 (900) 111-22-{i % 100:02d}")
            for i in range(105)
        ]
        Customer.objects.bulk_create(customers)
        rows, total = staff_services.get_customer_rows()
        self.assertEqual(len(rows), staff_services.DEFAULT_LIMIT)
        self.assertEqual(total, 106)
        stats = staff_services.summarize_customers(rows, total, "")
        self.assertTrue(stats.limited)
        found, total_found = staff_services.get_customer_rows("гость 42")
        self.assertEqual(total_found, 1)
        self.assertFalse(
            staff_services.summarize_customers(found, total_found, "гость 42").limited
        )


class StaffCustomersViewTests(TestCase):
    """Страница клиентской базы: список, экспорт отфильтрованного и всего."""

    @classmethod
    def setUpTestData(cls):
        setup_catalog(cls)
        cls.order = create_order(
            lines=[(cls.variant.pk, 1)], promo_code=None, **CONTACT
        )
        cls.admin = make_staff_user("admin7", superuser=True)

    def test_list_renders_customer(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_customers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Мария")
        self.assertContains(response, CONTACT["address"])
        self.assertContains(response, "Экспорт всей базы")

    def test_filtered_export_returns_xlsx(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_customers_export"))
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(io.BytesIO(response.content))
        ws = wb["Клиенты"]
        self.assertEqual(ws["A1"].value, "Имя")
        self.assertEqual(ws["A2"].value, "Мария")

    def test_export_all_ignores_limit(self):
        customers = [
            Customer(name=f"Гость {i}", phone=f"+7 (900) 111-22-{i % 100:02d}")
            for i in range(105)
        ]
        Customer.objects.bulk_create(customers)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_customers_export_all"))
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(io.BytesIO(response.content))
        # шапка + Мария из setUpTestData + 105 гостей
        self.assertEqual(wb["Клиенты"].max_row, 107)

    def test_limit_warning(self):
        customers = [
            Customer(name=f"Гость {i}", phone=f"+7 (900) 111-22-{i % 100:02d}")
            for i in range(105)
        ]
        Customer.objects.bulk_create(customers)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("orders:staff_customers"))
        self.assertContains(response, "Показаны последние 100 покупателей")
        response = self.client.get(reverse("orders:staff_customers"), {"q": "мария"})
        self.assertNotContains(response, "Показаны последние 100")


class AdminExcelExportTests(TestCase):
    """Экспорт в Excel прямо из Django Admin."""

    @classmethod
    def setUpTestData(cls):
        setup_catalog(cls)
        cls.order = create_order(
            lines=[(cls.variant.pk, 1)], promo_code=None, **CONTACT
        )
        cls.admin = make_staff_user("admin7", superuser=True)

    def _run_action(self, url_name, modeladmin_url):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse(url_name),
            {"action": "export_excel", "_selected_action": [self.order.pk]},
            follow=True,
        )

    def test_orders_export_action(self):
        response = self._run_action(
            "admin:orders_order_changelist", "orders_order"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        wb = load_workbook(io.BytesIO(response.content))
        self.assertEqual(wb["Заказы"]["A2"].value, self.order.number)

    def test_customers_export_action(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:orders_customer_changelist"),
            {"action": "export_excel", "_selected_action": [self.order.customer.pk]},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(io.BytesIO(response.content))
        self.assertEqual(wb["Клиенты"]["A2"].value, "Мария")


class HeaderAuthIconsTests(TestCase):
    """Иконки шапки: вход для анонима, меню/админка/выход для авторизованных."""

    @classmethod
    def setUpTestData(cls):
        cls.manager = make_staff_user("manager", manager=True)

    def test_anonymous_sees_login_icon_only(self):
        response = self.client.get(reverse("shop:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Войти"')
        self.assertNotContains(response, 'aria-label="Открыть меню"')
        self.assertNotContains(response, 'aria-label="Выйти"')

    def test_authenticated_sees_menu_admin_logout(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("shop:home"))
        self.assertContains(response, 'aria-label="Открыть меню"')
        self.assertContains(response, 'aria-label="Администрирование"')
        self.assertContains(response, 'aria-label="Выйти"')
        # В меню есть ссылки на staff-страницы.
        self.assertContains(response, reverse("orders:staff_orders"))
        self.assertContains(response, reverse("orders:staff_customers"))
