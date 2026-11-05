from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Product, ProductImage, ProductVariant


class ProductVariantInline(admin.TabularInline):
    """Варианты (размеры с ценами) редактируются прямо на странице товара."""

    model = ProductVariant
    extra = 1
    fields = ("size", "price", "stock", "sort_order", "is_active")


class ProductImageInline(admin.TabularInline):
    """Изображения товара с миниатюрой и признаком основного."""

    model = ProductImage
    extra = 1
    fields = ("image", "image_preview", "alt", "sort_order", "is_main")
    readonly_fields = ("image_preview",)

    @admin.display(description="Превью")
    def image_preview(self, obj):
        # Миниатюра появляется только после первого сохранения записи:
        # до этого у загруженного файла ещё нет URL.
        if obj.pk and obj.image:
            return format_html(
                '<img src="{}" style="max-height: 48px;" />', obj.image.url
            )
        return "—"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Админка категорий: порядок и активность правятся прямо из списка."""

    list_display = ("name", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "slug")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Админка товаров: варианты и изображения — инлайнами, рекомендации —
    удобным двухколоночным виджетом. Проверка «товар не рекомендует сам себя»
    срабатывает через Product.clean() автоматически."""

    list_display = ("name", "category", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "slug", "category__name")
    filter_horizontal = ("related_products",)
    inlines = (ProductVariantInline, ProductImageInline)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Отдельный список вариантов: удобно проверять цены и остатки."""

    list_display = ("product", "size", "price", "stock", "sort_order", "is_active")
    list_editable = ("price", "stock", "sort_order", "is_active")
    list_filter = ("is_active", "product__category")
    search_fields = ("product__name", "size")


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    """Отдельный список изображений с миниатюрами."""

    list_display = ("product", "image_preview", "alt", "sort_order", "is_main")
    list_filter = ("is_main",)
    search_fields = ("product__name", "alt")

    @admin.display(description="Превью")
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 48px;" />', obj.image.url
            )
        return "—"
