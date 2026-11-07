"""Формы корзины: проверка входных данных перед изменением сессии."""
from django import forms

from orders.models import PROMO_CODE_MAX_LENGTH, PROMO_CODE_PATTERN, normalize_promo_code
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


class PromoCodeForm(forms.Form):
    """Валидация введённого промокода: формат и длина кода.

    Существование, активность, сроки и минимальная сумма проверяются
    сервисом корзины через единый расчёт — там же, где считается скидка."""

    code = forms.CharField(
        label="Промокод",
        max_length=PROMO_CODE_MAX_LENGTH,
        error_messages={"required": "Введите промокод."},
    )

    def clean_code(self):
        code = normalize_promo_code(self.cleaned_data["code"])
        if not PROMO_CODE_PATTERN.fullmatch(code):
            raise forms.ValidationError(
                "Код может состоять только из цифр и букв (русских или латинских)."
            )
        return code
