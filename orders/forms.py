"""Форма оформления заказа (этап 5).

Обязательны только имя, телефон и адрес доставки; email и примечание
необязательны. Телефон нормализуется для поиска покупателя; в заказ
попадает введённый пользователем вид. Цены и суммы форма не принимает —
они пересчитываются сервером при создании заказа.
"""
from django import forms

from shop.models import Category

from .models import (
    ADDRESS_MAX_LENGTH,
    CONTACT_NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    Order,
    normalize_phone,
)

NOTE_MAX_LENGTH = 1000

# Диапазон допустимой длины нормализованного телефона: +7 XXX XXX-XX-XX — 11 цифр,
# без кода страны — 10; запас сверху на редкие форматы.
PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15


class CheckoutForm(forms.Form):
    """Контакты и адрес доставки. Поля с ошибками выделяются в шаблоне,
    введённые данные Django возвращает в form.data без потерь."""

    name = forms.CharField(
        label="Имя",
        min_length=2,
        max_length=CONTACT_NAME_MAX_LENGTH,
        help_text="Как к вам обращаться — например, Мария.",
        error_messages={
            "required": "Пожалуйста, укажите имя.",
            "min_length": "Имя слишком короткое — уточните, пожалуйста.",
        },
    )
    phone = forms.CharField(
        label="Телефон",
        max_length=PHONE_MAX_LENGTH,
        help_text="Позвоним, чтобы подтвердить заказ и доставку. "
        "Например: +7 (918) 123-45-67.",
        error_messages={"required": "Пожалуйста, укажите телефон для связи."},
    )
    email = forms.EmailField(
        label="Email",
        required=False,
        max_length=254,
        help_text="Необязательно: пришлём подтверждение заказа.",
        error_messages={"invalid": "Похоже, в адресе опечатка — проверьте, пожалуйста."},
    )
    address = forms.CharField(
        label="Адрес доставки",
        min_length=5,
        max_length=ADDRESS_MAX_LENGTH,
        help_text="Улица, дом, квартира или офис, этаж, код домофона.",
        error_messages={
            "required": "Пожалуйста, укажите адрес доставки.",
            "min_length": "Адрес слишком короткий — добавьте улицу и дом.",
        },
    )
    note = forms.CharField(
        label="Примечание к заказу",
        required=False,
        max_length=NOTE_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Необязательно: удобное время доставки, пожелания к виду ёлки.",
    )

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        digits = normalize_phone(phone)
        if not (PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS):
            raise forms.ValidationError(
                "Похоже, в номере ошибка: нужно от 10 до 15 цифр. "
                "Проверьте, пожалуйста."
            )
        return phone

    def clean_email(self):
        # Пустой email — нормально (необязательное поле), нормализуем непустой.
        email = self.cleaned_data["email"].strip().lower()
        return email


# --- Staff-страницы менеджера (этап 7) ----------------------------------------

PROMO_FILTER_CHOICES = (
    ("", "Все заказы"),
    ("yes", "С промокодом"),
    ("no", "Без промокода"),
)


class OrderFilterForm(forms.Form):
    """Фильтр списка заказов на staff-странице. Параметры — только чтение,
    данные заказов не меняет; разбор очищенных значений — staff_services."""

    date_from = forms.DateField(
        label="Дата с",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label="Дата по",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    status = forms.ChoiceField(
        label="Статус",
        required=False,
        choices=[("", "Все статусы")] + list(Order.STATUS_CHOICES),
    )
    category = forms.ModelChoiceField(
        label="Категория товара",
        required=False,
        queryset=Category.objects.none(),  # заполняем в __init__ (см. ниже)
        empty_label="Все категории",
    )
    promo = forms.ChoiceField(
        label="Промокод",
        required=False,
        choices=PROMO_FILTER_CHOICES,
    )
    search = forms.CharField(label="Поиск", required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by(
            "sort_order", "name"
        )


class OrderEditForm(forms.ModelForm):
    """Редактирование заказа менеджером (модальное окно на staff-странице).

    Доступны контактный снимок и статус — их правка — служебная
    необходимость (опечатки в адресе/телефоне, ручной перевод статуса).
    Деньги и позиции — исторический снимок: не редактируются никогда
    (см. docs/architecture.md §6), в форме показываются только для чтения.
    """

    class Meta:
        model = Order
        fields = ["name", "phone", "email", "address", "note", "status"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        digits = normalize_phone(phone)
        if not (PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS):
            raise forms.ValidationError(
                "Похоже, в номере ошибка: нужно от 10 до 15 цифр. "
                "Проверьте, пожалуйста."
            )
        return phone

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()
