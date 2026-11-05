"""Разовое наполнение демо-каталога для ручной проверки этапа 2 (запускать вручную).

Создаёт товары с вариантами и изображениями-заглушками, чтобы главная
выглядела как в дизайне (несколько карточек в ряд). Повторный запуск
не дублирует записи: проверяет товар по имени.
"""
from decimal import Decimal

from shop.models import Category, Product, ProductImage, ProductVariant


def get_or_make_product(category, name, description):
    product, created = Product.objects.get_or_create(
        category=category,
        name=name,
        defaults={"description": description},
    )
    return product, created


def add_variant(product, size, price):
    variant, created = ProductVariant.objects.get_or_create(
        product=product,
        size=size,
        defaults={"price": Decimal(price)},
    )
    return created


def add_image(product, filename, alt):
    if product.images.exists():
        return False
    ProductImage.objects.create(
        product=product, image=f"products/images/{filename}", alt=alt, is_main=True
    )
    return True


eli = Category.objects.get(slug="ели")
sosny = Category.objects.get(slug="сосны")
pikhta = Category.objects.get_or_create(
    name="Пихты", defaults={"sort_order": 30}
)[0]
addons = Category.objects.get(slug="подставки-и-украшения")

catalog = [
    (
        eli,
        "Ель отборная",
        "Ель уральская отборная из питомника",
        [("до 1,5 метров", "2500.00"), ("от 1,5 до 2-х метров", "4000.00")],
        ("el-1.jpg", "Ель отборная — общий вид"),
    ),
    (
        eli,
        "Ель премиум",
        "Ель уральская отборная из питомника",
        [("от 1,5 до 2-х метров", "3000.00"), ("от 2-х метров", "7000.00")],
        ("el-1.jpg", "Ель премиум — общий вид"),
    ),
    (
        sosny,
        "Сосна крымская",
        "Сосна крымская отборная",
        [("до 1,5 метров", "2500.00"), ("от 1,5 до 2-х метров", "3500.00")],
        ("sosna-1.jpg", "Сосна крымская — общий вид"),
    ),
    (
        pikhta,
        "Пихта сибирская",
        "Пихта сибирская отборная из питомника",
        [("до 1,5 метров", "2800.00"), ("от 1,5 до 2-х метров", "4200.00")],
        ("sosna-2.jpg", "Пихта сибирская — общий вид"),
    ),
    (
        addons,
        "Подставка большая",
        "Пластиковая подставка для новогоднего дерева с ёмкостью для воды. Для дерева от 2 метров",
        [("универсальная", "2500.00")],
        ("podstavka-1.jpg", "Подставка большая для ёлки"),
    ),
    (
        addons,
        "Икебана из крымской сосны",
        "Изделие ручной работы из крымской сосны",
        [("от 0,8 до 1,5 метров", "1600.00")],
        ("sosna-2.jpg", "Икебана из крымской сосны"),
    ),
]

for category, name, description, variants, (filename, alt) in catalog:
    product, created = get_or_make_product(category, name, description)
    for size, price in variants:
        add_variant(product, size, price)
    add_image(product, filename, alt)
    print(("создан" if created else "уже есть") + ":", product.name)

print("готово")
