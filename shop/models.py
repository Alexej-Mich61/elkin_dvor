from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify


def build_unique_slug(instance, source):
    """Создаёт уникальный slug, в том числе для русских названий."""
    max_length = instance._meta.get_field("slug").max_length
    base_slug = slugify(source, allow_unicode=True)[:max_length].strip("-")

    if not base_slug:
        raise ValidationError(
            "Не удалось создать slug из названия. Укажите slug вручную."
        )

    queryset = instance.__class__.objects.all()

    # При редактировании исключаем саму запись из проверки уникальности,
    # чтобы slug записи не конфликтовал сам с собой.
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    slug = base_slug
    counter = 2

    # При совпадении добавляем числовой суффикс: name, name-2, name-3 и т.д.
    while queryset.filter(slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base_slug[:max_length - len(suffix)]}{suffix}"
        counter += 1

    return slug


class Category(models.Model):
    """Категория каталога: сосны, ели, пихты, подставки, украшения и т.п."""

    name = models.CharField(
        "Название",
        max_length=120,
    )
    slug = models.SlugField(
        "URL-имя",
        max_length=120,
        unique=True,
        allow_unicode=True,
        blank=True,
        help_text="Если оставить пустым, будет создано из названия.",
    )
    description = models.TextField(
        "Описание",
        blank=True,
    )
    sort_order = models.PositiveIntegerField(
        "Порядок отображения",
        default=0,
    )
    is_active = models.BooleanField(
        "Показывать на сайте",
        default=True,
        db_index=True,
    )
    # Отличает обычные категории деревьев (сосны, ёлки, пихты) от дополнительных
    # товаров (подставки, украшения), которые выводятся отдельной секцией на главной.
    is_addon = models.BooleanField(
        "Дополнительные товары",
        default=False,
        help_text="Показывать товары категории в секции «Популярные дополнения» на главной странице.",
    )
    seo_title = models.CharField(
        "SEO title",
        max_length=160,
        blank=True,
    )
    seo_description = models.CharField(
        "SEO description",
        max_length=300,
        blank=True,
    )

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def save(self, *args, **kwargs):
        # Пустой slug заполняем автоматически из названия.
        if not self.slug:
            self.slug = build_unique_slug(self, self.name)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    """Товар каталога. Покупается не напрямую, а через варианты (ProductVariant)."""

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Категория",
    )
    name = models.CharField(
        "Название",
        max_length=120,
    )
    slug = models.SlugField(
        "URL-имя",
        max_length=120,
        unique=True,
        allow_unicode=True,
        blank=True,
        help_text="Если оставить пустым, будет создано из названия.",
    )
    description = models.TextField(
        "Описание",
        blank=True,
    )
    # Несимметричные рекомендации: «ёлка -> подставка» не создаёт обратную связь.
    # Рекомендация товара самим собой запрещена в clean().
    related_products = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="recommended_for",
        verbose_name="Рекомендуемые товары",
    )
    sort_order = models.PositiveIntegerField(
        "Порядок отображения",
        default=0,
    )
    is_active = models.BooleanField(
        "Показывать на сайте",
        default=True,
        db_index=True,
    )
    seo_title = models.CharField(
        "SEO title",
        max_length=160,
        blank=True,
    )
    seo_description = models.CharField(
        "SEO description",
        max_length=300,
        blank=True,
    )
    created_at = models.DateTimeField(
        "Создан",
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        "Обновлён",
        auto_now=True,
    )

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    def clean(self):
        """Проверяем бизнес-правило: товар не может рекомендовать сам себя."""
        super().clean()

        if self.pk and self.related_products.filter(pk=self.pk).exists():
            raise ValidationError(
                {"related_products": "Товар не может рекомендовать сам себя."}
            )

    def save(self, *args, **kwargs):
        # Пустой slug заполняем автоматически из названия.
        if not self.slug:
            self.slug = build_unique_slug(self, self.name)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """Конкретный размер товара с собственной ценой и остатком."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name="Товар",
    )
    size = models.CharField(
        "Размер",
        max_length=80,
        help_text='Например: «от 1,5 м до 2,0 м».',
    )
    price = models.DecimalField(
        "Цена",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    stock = models.PositiveIntegerField(
        "Доступное количество",
        default=0,
    )
    sort_order = models.PositiveIntegerField(
        "Порядок отображения",
        default=0,
    )
    is_active = models.BooleanField(
        "Доступен для заказа",
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ("sort_order", "size", "id")
        verbose_name = "Вариант товара"
        verbose_name_plural = "Варианты товаров"
        constraints = [
            # Один и тот же размер не может дублироваться у одного товара.
            models.UniqueConstraint(
                fields=("product", "size"),
                name="unique_size_per_product",
            ),
            # Защита от отрицательных цен и остатков на уровне базы.
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="product_variant_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(stock__gte=0),
                name="product_variant_stock_nonnegative",
            ),
        ]

    def save(self, *args, **kwargs):
        # Нормализуем размер, чтобы «1,5 м» и « 1,5 м » не считались разными.
        self.size = self.size.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} — {self.size}"


class ProductImage(models.Model):
    """Изображение товара. Основное (is_main) показывается первым в галерее."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="Товар",
    )
    image = models.ImageField(
        "Изображение",
        upload_to="products/images/",
    )
    alt = models.CharField(
        "Alt-текст",
        max_length=160,
        blank=True,
        help_text="Краткое описание изображения для SEO и доступности.",
    )
    sort_order = models.PositiveIntegerField(
        "Порядок отображения",
        default=0,
    )
    is_main = models.BooleanField(
        "Основное изображение",
        default=False,
    )

    class Meta:
        # Основное изображение всегда будет первым в галерее.
        ordering = ("-is_main", "sort_order", "id")
        verbose_name = "Изображение товара"
        verbose_name_plural = "Изображения товаров"
        constraints = [
            # У товара может быть только одно основное изображение.
            models.UniqueConstraint(
                fields=("product",),
                condition=models.Q(is_main=True),
                name="unique_main_image_per_product",
            ),
        ]

    def clean(self):
        """Мягкая проверка до обращения к БД: не даём назначить второе
        основное изображение, чтобы администратор увидел понятную ошибку,
        а не сырое исключение уникальности из базы."""
        super().clean()

        if self.is_main and self.product_id:
            other_mains = ProductImage.objects.filter(
                product_id=self.product_id, is_main=True
            )
            if self.pk:
                other_mains = other_mains.exclude(pk=self.pk)

            if other_mains.exists():
                raise ValidationError(
                    {"is_main": "У товара уже есть основное изображение."}
                )

    def __str__(self):
        return f"Изображение товара «{self.product.name}»"
