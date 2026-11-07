from decimal import Decimal

from django.contrib.sessions.backends.base import SessionBase
from django.test import TestCase
from django.urls import reverse

from shop.models import Category, Product, ProductVariant

from .services import MAX_LINE_QUANTITY, Cart

HX = "true"  # Заголовок HX-Request для HTMX-запросов


class CartTestCase(TestCase):
    """Базовый набор: категория, товар и активный вариант."""

    def setUp(self):
        self.category = Category.objects.create(name="Сосны")
        self.product = Product.objects.create(category=self.category, name="Сосна крымская")
        self.variant = ProductVariant.objects.create(
            product=self.product, size="1,5 м", price=Decimal("3900.00")
        )

    def make_cart(self, data=None):
        session = SessionBase()
        if data is not None:
            session["cart"] = data
        return Cart(session)


class CartServiceTests(CartTestCase):
    """Операции корзины и серверный пересчёт сумм."""

    def test_add_merges_quantities(self):
        cart = self.make_cart()
        cart.add(self.variant, 2)
        total = cart.add(self.variant, 3)
        self.assertEqual(total, 5)
        self.assertEqual(cart.items, {self.variant.pk: 5})
        self.assertEqual(cart.count(), 5)

    def test_add_clamps_to_max_when_stock_untracked(self):
        # stock=0 — остаток не учитывается, действует общий потолок.
        cart = self.make_cart()
        total = cart.add(self.variant, MAX_LINE_QUANTITY + 50)
        self.assertEqual(total, MAX_LINE_QUANTITY)

    def test_add_clamps_to_stock(self):
        self.variant.stock = 3
        self.variant.save()
        cart = self.make_cart()
        total = cart.add(self.variant, 10)
        self.assertEqual(total, 3)

    def test_set_quantity_zero_removes_line(self):
        cart = self.make_cart()
        cart.add(self.variant)
        cart.set_quantity(self.variant.pk, 0)
        self.assertEqual(cart.items, {})
        # Пустая корзина не оставляет записи в сессии.
        self.assertNotIn("cart", cart.session)

    def test_remove_unknown_line_returns_false(self):
        cart = self.make_cart()
        self.assertFalse(cart.remove(999))

    def test_clear_empties_cart(self):
        cart = self.make_cart()
        cart.add(self.variant, 2)
        cart.clear()
        self.assertEqual(cart.count(), 0)
        self.assertEqual(cart.contents().lines, [])

    def test_tampered_session_entries_are_ignored(self):
        cart = self.make_cart(
            {"abc": "x", "-1": 5, "7": 0, "8": 2, "9": "много", "10": 4}
        )
        self.assertEqual(cart.items, {8: 2, 10: 4})

    def test_subtotal_recalculated_from_current_price(self):
        # Цену меняют после добавления — сумма считается по новой цене.
        cart = self.make_cart()
        cart.add(self.variant, 2)
        self.variant.price = Decimal("4900.00")
        self.variant.save()
        contents = cart.contents()
        self.assertEqual(contents.subtotal, Decimal("9800.00"))
        self.assertEqual(contents.total_items, 2)

    def test_inactive_variant_marked_unavailable_and_excluded(self):
        cart = self.make_cart()
        cart.add(self.variant, 2)
        self.variant.is_active = False
        self.variant.save()

        contents = cart.contents()
        self.assertTrue(contents.has_unavailable)
        self.assertEqual(contents.subtotal, Decimal("0"))
        self.assertEqual(contents.total_items, 2)  # позиция остаётся видимой

    def test_deleted_variant_kept_as_unavailable_line(self):
        cart = self.make_cart()
        cart.add(self.variant)
        variant_id = self.variant.pk
        self.variant.delete()

        contents = cart.contents()
        self.assertTrue(contents.has_unavailable)
        self.assertIsNone(contents.lines[0].variant)
        self.assertEqual(contents.lines[0].variant_id, variant_id)

    def test_inactive_product_line_unavailable(self):
        cart = self.make_cart()
        cart.add(self.variant)
        self.product.is_active = False
        self.product.save()
        self.assertFalse(cart.contents().lines[0].is_available)

    def test_inactive_category_line_unavailable(self):
        cart = self.make_cart()
        cart.add(self.variant)
        self.category.is_active = False
        self.category.save()
        self.assertFalse(cart.contents().lines[0].is_available)


class AddToCartViewTests(CartTestCase):
    """Добавление через HTTP: обычный POST и HTMX."""

    def _post_add(self, data, htmx=False, variant=None):
        variant = variant or self.variant
        payload = {"variant_id": variant.pk, "quantity": 1, **data}
        headers = {"HTTP_HX_REQUEST": HX} if htmx else {}
        return self.client.post(reverse("cart:add"), payload, **headers)

    def test_add_without_htmx_redirects_to_cart(self):
        response = self._post_add({"quantity": 2})
        self.assertRedirects(response, reverse("cart:detail"))
        session = self.client.session
        self.assertEqual(session["cart"][str(self.variant.pk)], 2)

    def test_cart_persists_between_requests(self):
        self._post_add({"quantity": 2})
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "Сосна крымская")
        self.assertContains(response, "7 800 руб.")

    def test_add_htmx_returns_feedback_and_counter_oob(self):
        response = self._post_add({"quantity": 2}, htmx=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Добавлено")
        # Счётчик в шапке обновляется out-of-band.
        self.assertContains(response, 'id="cart-counter"')
        self.assertContains(response, 'hx-swap-oob="true"')
        self.assertContains(response, ">2</span>", html=False)

    def test_add_rejects_inactive_variant(self):
        self.variant.is_active = False
        self.variant.save()
        response = self._post_add({"quantity": 1}, htmx=True)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "недоступен", status_code=422)
        self.assertEqual(self.client.session.get("cart"), None)

    def test_add_rejects_inactive_product_variant(self):
        self.product.is_active = False
        self.product.save()
        response = self._post_add({"quantity": 1}, htmx=True)
        self.assertEqual(response.status_code, 422)

    def test_add_rejects_zero_quantity(self):
        response = self._post_add({"quantity": 0}, htmx=True)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.session.get("cart"), None)

    def test_add_rejects_excessive_quantity(self):
        response = self._post_add({"quantity": MAX_LINE_QUANTITY + 1}, htmx=True)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.session.get("cart"), None)

    def test_add_clamps_to_stock_with_notice(self):
        self.variant.stock = 3
        self.variant.save()
        response = self._post_add({"quantity": 10}, htmx=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 3)
        self.assertContains(response, "В наличии только 3 шт.")

    def test_repeated_add_clamps_to_stock(self):
        self.variant.stock = 4
        self.variant.save()
        self._post_add({"quantity": 3})
        response = self._post_add({"quantity": 3}, htmx=True)
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 4)

    def test_add_requires_post(self):
        response = self.client.get(reverse("cart:add"))
        self.assertRedirects(response, reverse("cart:detail"))


class CartMutationViewTests(CartTestCase):
    """Изменение количества, удаление и очистка."""

    def _seed_cart(self, quantity=2):
        session = self.client.session
        session["cart"] = {str(self.variant.pk): quantity}
        session.save()

    def test_update_quantity_via_stepper_value(self):
        # Кнопки «−»/«+» присылают value нажатой кнопки — как и обычный POST.
        self._seed_cart(2)
        response = self.client.post(
            reverse("cart:update", kwargs={"variant_id": self.variant.pk}),
            {"quantity": 5},
        )
        self.assertRedirects(response, reverse("cart:detail"))
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 5)

    def test_update_htmx_returns_cart_fragment(self):
        self._seed_cart(2)
        response = self.client.post(
            reverse("cart:update", kwargs={"variant_id": self.variant.pk}),
            {"quantity": 5},
            HTTP_HX_REQUEST=HX,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сосна крымская")
        self.assertContains(response, "19 500 руб.")
        # Счётчик в шапке обновляется out-of-band.
        self.assertContains(response, 'id="cart-counter"')
        self.assertContains(response, 'hx-swap-oob="true"')
        self.assertContains(response, ">5</span>", html=False)

    def test_update_zero_removes_line(self):
        self._seed_cart(2)
        self.client.post(
            reverse("cart:update", kwargs={"variant_id": self.variant.pk}),
            {"quantity": 0},
        )
        self.assertNotIn("cart", self.client.session)

    def test_update_non_numeric_keeps_cart_unchanged(self):
        self._seed_cart(2)
        self.client.post(
            reverse("cart:update", kwargs={"variant_id": self.variant.pk}),
            {"quantity": "abc"},
        )
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 2)

    def test_update_clamps_to_stock(self):
        self.variant.stock = 4
        self.variant.save()
        self._seed_cart(2)
        self.client.post(
            reverse("cart:update", kwargs={"variant_id": self.variant.pk}),
            {"quantity": 10},
        )
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 4)

    def test_update_missing_variant_drops_line(self):
        # Вариант удалили из каталога — позиция убирается, а не зависает.
        variant_id = self.variant.pk
        self._seed_cart(2)
        self.variant.delete()
        self.client.post(
            reverse("cart:update", kwargs={"variant_id": variant_id}),
            {"quantity": 3},
        )
        self.assertNotIn("cart", self.client.session)

    def test_remove_line(self):
        self._seed_cart()
        self.client.post(reverse("cart:remove", kwargs={"variant_id": self.variant.pk}))
        self.assertNotIn("cart", self.client.session)

    def test_remove_is_idempotent(self):
        self._seed_cart()
        url = reverse("cart:remove", kwargs={"variant_id": self.variant.pk})
        self.client.post(url)
        response = self.client.post(url, HTTP_HX_REQUEST=HX)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "пока пусто")

    def test_clear_cart(self):
        self._seed_cart()
        self.client.post(reverse("cart:clear"))
        self.assertNotIn("cart", self.client.session)

    def test_cart_page_shows_unavailable_notice(self):
        self._seed_cart()
        self.variant.is_active = False
        self.variant.save()

        response = self.client.get(reverse("cart:detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Снят с продажи")
        self.assertContains(response, "Итого:")
        self.assertContains(response, "0 руб.")

    def test_cart_page_noindex(self):
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(
            response, '<meta name="robots" content="noindex, nofollow">'
        )


class CartCounterTests(CartTestCase):
    """Счётчик корзины в шапке."""

    def test_counter_hidden_when_cart_empty(self):
        response = self.client.get(reverse("shop:home"))
        self.assertContains(response, 'id="cart-counter"')
        self.assertNotContains(response, "cart_badge", html=False)

    def test_counter_shows_quantity(self):
        self._seed_cart(3)
        response = self.client.get(reverse("shop:home"))
        self.assertContains(response, ">3</span>", html=False)

    def _seed_cart(self, quantity):
        session = self.client.session
        session["cart"] = {str(self.variant.pk): quantity}
        session.save()
