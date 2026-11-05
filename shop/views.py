import json

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from .models import Category, Product, ProductImage, ProductVariant


def public_products_queryset():
    """Товары публичного каталога: активные товары активных категорий,
    у которых есть хотя бы один активный вариант. Сразу подгружаем
    изображения и активные варианты, чтобы не лезть в БД из шаблона."""
    active_variants = ProductVariant.objects.filter(is_active=True)
    return (
        Product.objects.filter(
            is_active=True,
            category__is_active=True,
            pk__in=ProductVariant.objects.filter(is_active=True).values("product_id"),
        )
        .select_related("category")
        .prefetch_related(
            Prefetch("variants", queryset=active_variants),
            "images",
        )
    )


def _categories_with_products(addon):
    """Активные категории (деревья или дополнения) вместе с активными товарами."""
    categories = (
        Category.objects.filter(is_active=True, is_addon=addon)
        .prefetch_related(Prefetch("products", queryset=public_products_queryset()))
        .order_by("sort_order", "name")
    )
    # Пустые категории не показываем: вкладки и секции должны вести к товарам.
    return [category for category in categories if category.products.all()]


def home(request):
    """Главная: баннер, преимущества, каталог по категориям, дополнения, контакты."""
    addon_products = []
    for category in _categories_with_products(addon=True):
        addon_products.extend(category.products.all())

    context = {
        "tree_categories": _categories_with_products(addon=False),
        "addon_products": addon_products,
    }
    return render(request, "home.html", context)


def category_detail(request, category_slug):
    """Страница категории: её активные товары с ценами."""
    category = get_object_or_404(Category, slug=category_slug, is_active=True)
    products = public_products_queryset().filter(category=category)

    context = {
        "category": category,
        "products": products,
    }
    return render(request, "shop/category.html", context)


def product_detail(request, category_slug, product_slug):
    """Карточка товара: галерея, описание, выбор активного варианта размера."""
    product = get_object_or_404(
        public_products_queryset(),
        slug=product_slug,
        category__slug=category_slug,
    )
    images = list(product.images.all())
    variants = list(product.variants.all())

    related_products = public_products_queryset().filter(
        pk__in=product.related_products.values("pk")
    )[:4]

    context = {
        "product": product,
        "images": images,
        "variants": variants,
        "default_variant": variants[0] if variants else None,
        "related_products": related_products,
        "product_jsonld": _product_jsonld(request, product, images, variants),
    }
    return render(request, "shop/product.html", context)


def variant_price(request, category_slug, product_slug):
    """HTMX-фрагмент: актуальная серверная цена выбранного варианта."""
    product = get_object_or_404(
        Product.objects.filter(is_active=True, category__is_active=True),
        slug=product_slug,
        category__slug=category_slug,
    )
    variant = get_object_or_404(
        product.variants.filter(is_active=True),
        pk=request.GET.get("variant"),
    )
    return render(request, "partials/variant_price.html", {"variant": variant})


def _product_jsonld(request, product, images, variants):
    """Структурированные данные Product/AggregateOffer для поисковиков."""
    if not variants:
        return None
    prices = [variant.price for variant in variants]
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "description": product.description or product.name,
        "category": product.category.name,
        "offers": {
            "@type": "AggregateOffer",
            "priceCurrency": "RUB",
            "lowPrice": str(min(prices)),
            "highPrice": str(max(prices)),
            "offerCount": len(variants),
            "availability": "https://schema.org/InStock",
        },
    }
    main_image = next((img for img in images if img.is_main), images[0] if images else None)
    if main_image:
        data["image"] = request.build_absolute_uri(main_image.image.url)
    return json.dumps(data, ensure_ascii=False)
