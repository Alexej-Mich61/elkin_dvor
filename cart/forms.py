"""Формы корзины: проверка входных данных перед изменением сессии."""
from django import forms

from shop.models import ProductVariant

from .services import MAX_LINE_QUANTITY


class AddToCartForm(forms.Form):
    """Валидация добавления в корзину.

    Форма не принимает цены: на сервере известны только ID варианта
    и количество, всё остальное берётся из актуального каталога."""

    variant_id = forms.IntegerField(min_value=1)
    quantity = forms.IntegerField(min_value=1, max_value=MAX_LINE_QUANTITY)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Найденный вариант переиспользует view, чтобы не ходить в БД дважды.
        self.variant = None

    def clean_variant_id(self):
        variant_id = self.cleaned_data["variant_id"]
        try:
            self.variant = ProductVariant.objects.select_related(
                "product__category"
            ).get(pk=variant_id)
        except ProductVariant.DoesNotExist:
            raise forms.ValidationError("Такого товара нет в каталоге.")

        variant = self.variant
        if not (
            variant.is_active
            and variant.product.is_active
            and variant.product.category.is_active
        ):
            raise forms.ValidationError("Этот товар сейчас недоступен для заказа.")
        return variant_id
