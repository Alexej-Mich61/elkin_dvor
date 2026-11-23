from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Category, Product, ProductImage, ProductVariant


class CatalogTestCase(TestCase):
    """Базовый набор данных: категория и товар для тестов ограничений."""

    def setUp(self):
        self.category = Category.objects.create(name="Сосны")
        self.product = Product.objects.create(
            category=self.category, name="Сосна голубая"
        )


class CategoryModelTests(CatalogTestCase):
    def test_slug_created_from_russian_name(self):
        # slugify с allow_unicode сохраняет кириллицу в slug.
        self.assertEqual(self.category.slug, "сосны")

    def test_slug_uniqueness_with_suffix(self):
        # Второй slug с тем же названием получает числовой суффикс.
        duplicate = Category.objects.create(name="Сосны")
        self.assertEqual(duplicate.slug, "сосны-2")

    def test_manual_slug_not_overwritten(self):
        category = Category.objects.create(name="Ели", slug="el-custom")
        self.assertEqual(category.slug, "el-custom")

    def test_empty_slug_source_raises_validation_error(self):
        # Из названия без букв и цифр slug не построить — ждём ошибку.
        with self.assertRaises(ValidationError):
            Category.objects.create(name="!!!")


class ProductModelTests(CatalogTestCase):
    def test_slug_created_from_name(self):
        self.assertEqual(self.product.slug, "сосна-голубая")

    def test_category_protects_products_on_delete(self):
        # PROTECT: категорию с товарами нельзя удалить (IntegrityError).
        with self.assertRaises(IntegrityError):
            self.category.delete()

    def test_self_recommendation_forbidden(self):
        self.product.related_products.add(self.product)
        with self.assertRaises(ValidationError):
            self.product.full_clean()

    def test_recommendations_are_asymmetric(self):
        stand = Product.objects.create(category=self.category, name="Подставка")

        self.product.related_products.add(stand)

        # Прямая рекомендация есть...
        self.assertIn(stand, self.product.related_products.all())
        # ...а обратная не появляется автоматически.
        self.assertNotIn(self.product, stand.related_products.all())
        # Но обратный related_name позволяет найти «кому рекомендуют этот товар».
        self.assertIn(self.product, stand.recommended_for.all())


class ProductVariantModelTests(CatalogTestCase):
    def test_product_size_pair_unique(self):
        ProductVariant.objects.create(
            product=self.product, size="1,5 м", price=Decimal("3500.00")
        )
        with self.assertRaises(IntegrityError):
            ProductVariant.objects.create(
                product=self.product, size="1,5 м", price=Decimal("4000.00")
            )

    def test_size_trimmed_on_save(self):
        variant = ProductVariant.objects.create(
            product=self.product, size="  1,5 м  ", price=Decimal("3500.00")
        )
        self.assertEqual(variant.size, "1,5 м")

    def test_negative_price_rejected_by_validator(self):
        variant = ProductVariant(
            product=self.product, size="1,5 м", price=Decimal("-1.00")
        )
        with self.assertRaises(ValidationError):
            variant.full_clean()

    def test_negative_price_rejected_by_database(self):
        # Обходим валидаторы и сохраняем напрямую — constraint в БД
        # всё равно не даст записать отрицательную цену.
        with self.assertRaises(IntegrityError):
            ProductVariant.objects.create(
                product=self.product, size="1,5 м", price=Decimal("-1.00")
            )

    def test_negative_stock_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            ProductVariant.objects.create(
                product=self.product, size="1,5 м", price=Decimal("0.00"), stock=-1
            )


class ProductImageModelTests(CatalogTestCase):
    def test_only_one_main_image_per_product(self):
        ProductImage.objects.create(
            product=self.product, image="a.jpg", is_main=True
        )
        second_main = ProductImage(product=self.product, image="b.jpg", is_main=True)

        # Мягкая проверка на уровне модели даёт понятную ошибку в админке.
        with self.assertRaises(ValidationError):
            second_main.full_clean(exclude=["image"])
        # Без clean() constraint в БД всё равно не пропустит запись.
        with self.assertRaises(IntegrityError):
            second_main.save()

    def test_main_image_sorted_first(self):
        # Записываем основное изображение последним — в выборке оно первое.
        ProductImage.objects.create(product=self.product, image="a.jpg")
        main = ProductImage.objects.create(
            product=self.product, image="b.jpg", is_main=True
        )

        first = ProductImage.objects.filter(product=self.product).first()
        self.assertEqual(first.pk, main.pk)


class PublicCatalogTests(TestCase):
    """Публичные страницы показывают только активные записи и отдают SEO-основу."""

    def setUp(self):
        self.category = Category.objects.create(name="Сосны")
        self.product = Product.objects.create(
            category=self.category, name="Сосна обыкновенная", description="Пушистая"
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, size="1,5 м", price=Decimal("3900.00")
        )
        ProductVariant.objects.create(
            product=self.product, size="2,5 м", price=Decimal("4900.00")
        )

    def test_home_shows_active_product(self):
        response = self.client.get(reverse("shop:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сосна обыкновенная")
        self.assertContains(response, "3 900–4 900 руб.")

    def test_home_catalog_tabs_with_first_category_default(self):
        Category.objects.create(name="Ели")
        response = self.client.get(reverse("shop:home"))

        # Вкладки категорий — кнопки с role="tab"...
        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, 'role="tab"')
        # ...первая по счёту категория выбрана по умолчанию (activeTab в Alpine)...
        self.assertContains(response, "activeTab: 'сосны'")
        # ...и ссылка на страницу категории остаётся доступной.
        self.assertContains(response, 'Все товары категории «Сосны»')

    def test_home_hides_inactive_records(self):
        # Неактивные товар, категория и вариант не должны попасть на главную.
        Category.objects.create(name="Скрытые", is_active=False)
        Product.objects.create(
            category=self.category, name="Сосна невидимка", is_active=False
        )
        ProductVariant.objects.create(
            product=self.product, size="0,5 м", price=Decimal("500.00"), is_active=False
        )

        response = self.client.get(reverse("shop:home"))

        self.assertNotContains(response, "Скрытые")
        self.assertNotContains(response, "Сосна невидимка")
        self.assertNotContains(response, "0,5 м")

    def test_product_without_active_variant_hidden(self):
        lonely = Product.objects.create(category=self.category, name="Без вариантов")
        ProductVariant.objects.create(
            product=lonely, size="1 м", price=Decimal("100.00"), is_active=False
        )

        response = self.client.get(reverse("shop:home"))

        self.assertNotContains(response, "Без вариантов")

    def test_addon_category_products_in_addons_section(self):
        addons = Category.objects.create(name="Подставки", is_addon=True)
        stand = Product.objects.create(category=addons, name="Подставка малая")
        ProductVariant.objects.create(
            product=stand, size="до 2 м", price=Decimal("1500.00")
        )

        response = self.client.get(reverse("shop:home"))

        self.assertContains(response, "популярные дополнения")
        self.assertContains(response, "Подставка малая")

    def test_category_page_by_slug(self):
        response = self.client.get(
            reverse("shop:category", kwargs={"category_slug": self.category.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сосна обыкновенная")
        self.assertContains(response, '<h1', html=False)

    def test_inactive_category_not_public(self):
        hidden = Category.objects.create(name="Архив", is_active=False)
        response = self.client.get(
            reverse("shop:category", kwargs={"category_slug": hidden.slug})
        )
        self.assertEqual(response.status_code, 404)

    def test_product_page_by_slugs(self):
        response = self.client.get(
            reverse(
                "shop:product",
                kwargs={
                    "category_slug": self.category.slug,
                    "product_slug": self.product.slug,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сосна обыкновенная")
        self.assertContains(response, "3 900 руб.")
        self.assertContains(response, 'application/ld+json')

    def test_inactive_product_not_public(self):
        hidden = Product.objects.create(
            category=self.category, name="Сосна скрытая", is_active=False
        )
        response = self.client.get(
            reverse(
                "shop:product",
                kwargs={
                    "category_slug": self.category.slug,
                    "product_slug": hidden.slug,
                },
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_variant_price_returns_server_price(self):
        url = reverse(
            "shop:variant_price",
            kwargs={
                "category_slug": self.category.slug,
                "product_slug": self.product.slug,
            },
        )
        response = self.client.get(url, {"variant": self.variant.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3 900 руб.")

    def test_variant_price_rejects_inactive_variant(self):
        self.variant.is_active = False
        self.variant.save()
        url = reverse(
            "shop:variant_price",
            kwargs={
                "category_slug": self.category.slug,
                "product_slug": self.product.slug,
            },
        )
        response = self.client.get(url, {"variant": self.variant.pk})
        self.assertEqual(response.status_code, 404)

    def test_related_products_only_active(self):
        stand = Product.objects.create(category=self.category, name="Подставка")
        ProductVariant.objects.create(
            product=stand, size="до 3 м", price=Decimal("1500.00")
        )
        self.product.related_products.add(stand)
        hidden = Product.objects.create(
            category=self.category, name="Скрытая подставка", is_active=False
        )
        self.product.related_products.add(hidden)

        response = self.client.get(
            reverse(
                "shop:product",
                kwargs={
                    "category_slug": self.category.slug,
                    "product_slug": self.product.slug,
                },
            )
        )

        self.assertContains(response, "Подставка")
        self.assertNotContains(response, "Скрытая подставка")

    def test_sitemap_and_robots(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        # URL в sitemap отдаются в percent-encoding.
        self.assertContains(response, "/catalog/")

        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sitemap:")
        self.assertContains(response, "/admin/", html=False)


class LegalPagesTests(TestCase):
    """Юридические страницы: уведомление о cookies (ФЗ-152/420) и политики."""

    def test_privacy_page_public(self):
        response = self.client.get(reverse("shop:privacy"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Политика конфиденциальности")
        self.assertContains(response, "cookies")

    def test_personal_data_page_public(self):
        response = self.client.get(reverse("shop:personal_data"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Политика обработки персональных данных")
        # Ключевое требование: трансграничная передача не осуществляется.
        self.assertContains(response, "Трансграничная передача не осуществляется")

    def test_home_contains_cookie_banner(self):
        response = self.client.get(reverse("shop:home"))

        # Баннер подключён в base.html и показывается до выбора пользователя...
        self.assertContains(response, 'id="cookie-banner"')
        # ...обе кнопки одинакового размера (btn без size-модификаторов)...
        self.assertContains(response, "Принять")
        self.assertContains(response, "Отказаться")
        # ...и в тексте есть ссылка на политику конфиденциальности.
        self.assertContains(response, reverse("shop:privacy"))

    def test_yandex_metrika_wired_behind_consent(self):
        # Счётчик Яндекс Метрики встроен в механизм согласия: его код есть
        # на странице (внутри loadAnalytics), но выполняется он только после
        # «Принять» — до согласия запросов к mc.yandex.ru быть не должно.
        response = self.client.get(reverse("shop:home"))
        self.assertContains(response, "mc.yandex.ru/metrika/tag.js?id=114602242")
        self.assertContains(response, "ym(114602242, 'init'")
        # Двойной вызов подряд не должен повторно инициализировать счётчик.
        self.assertContains(response, "analyticsLoaded")


class ErrorPagesTests(TestCase):
    """Страницы ошибок подхватываются в production-режиме (DEBUG=False)."""

    @override_settings(DEBUG=False)
    def test_custom_404_page(self):
        # В production несуществующий URL отдаёт наш 404.html, а не technical 404.
        response = self.client.get("/такой-страницы-нет/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Такой страницы нет", status_code=404)
        self.assertContains(response, reverse("shop:home"), status_code=404)

    def test_error_templates_render(self):
        # Все шаблоны ошибок собираются; 500.html автономен и рендерится
        # без запроса и контекст-процессоров.
        for template_name in ("404.html", "403.html", "500.html"):
            html = render_to_string(template_name)
            self.assertIn("Ёлкин двор", html)
