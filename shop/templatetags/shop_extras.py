from decimal import Decimal

from django import template

register = template.Library()


def format_number(value):
    """Число по-русски без единицы: 3400 -> «3 400», 1490.5 -> «1 490,50»."""
    if value is None:
        return ""
    amount = Decimal(value).quantize(Decimal("0.01"))
    if amount == amount.to_integral_value():
        return f"{int(amount):,}".replace(",", " ")
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


@register.filter(name="price")
def price_filter(value):
    """Цена с единицей: «3 400 руб.»."""
    if value is None:
        return ""
    return f"{format_number(value)} руб."


@register.simple_tag
def product_price_range(product):
    """Диапазон цен активных вариантов: «3 400 руб.» или «2 900–4 900 руб.»."""
    prices = [variant.price for variant in product.variants.all() if variant.is_active]
    if not prices:
        return "Цена по запросу"
    low, high = min(prices), max(prices)
    if low == high:
        return f"{format_number(low)} руб."
    return f"{format_number(low)}–{format_number(high)} руб."


@register.simple_tag
def product_sizes(product):
    """Размеры активных вариантов одной строкой через точку."""
    return " · ".join(
        variant.size for variant in product.variants.all() if variant.is_active
    )


@register.simple_tag
def main_image(product):
    """Основное изображение товара (первое по сортировке модели)."""
    return product.images.all().first()
