from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

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
