"""Промокоды. Модели заказов и покупателей появятся на этапе 5.

Код промокода — только цифры и буквы (латиница или кириллица), без
спецсимволов. В хранилище код всегда нормализован: обрезанные пробелы
и верхний регистр, поэтому «ёлка2026» и « ЁЛКА2026 » — один код.
См. docs/architecture.md §7.
"""
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

# Допустимые символы кода: цифры + буквы обоих алфавитов (в верхнем регистре).
PROMO_CODE_PATTERN = re.compile(r"^[0-9A-ZА-ЯЁ]+$")
PROMO_CODE_MAX_LENGTH = 40


def normalize_promo_code(value):
    """Единая нормализация кода: trim + верхний регистр."""
    return value.strip().upper()


def format_amount(value):
    """Сумма для сообщений: 1000 -> «1000», 999.50 -> «999,50»."""
    amount = Decimal(value).quantize(Decimal("0.01"))
    if amount == amount.to_integral_value():
        return str(int(amount))
    return f"{amount:.2f}".replace(".", ",")


class PromoCode(models.Model):
    """Скидочный промокод с периодом действия и необязательной минимальной суммой."""

    DISCOUNT_PERCENT = "percent"
    DISCOUNT_FIXED = "fixed"
    DISCOUNT_TYPE_CHOICES = (
        (DISCOUNT_PERCENT, "Скидка в процентах от суммы заказа"),
        (DISCOUNT_FIXED, "Фиксированная сумма скидки"),
    )

    code = models.CharField(
        "Код",
        max_length=PROMO_CODE_MAX_LENGTH,
        unique=True,
        help_text="Только цифры и буквы (русские или латинские), без пробелов "
        "и спецсимволов. Регистр не важен: «Ёлка2026» и «ЁЛКА2026» — один код.",
    )
    is_active = models.BooleanField(
        "Активен",
        default=True,
        db_index=True,
        help_text="Неактивный промокод не применяется, даже если срок действия не истёк.",
    )
    discount_type = models.CharField(
        "Тип скидки",
        max_length=10,
        choices=DISCOUNT_TYPE_CHOICES,
        default=DISCOUNT_PERCENT,
    )
    discount_value = models.DecimalField(
        "Величина скидки",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Проценты (1–100) для процентной скидки или сумма в рублях "
        "для фиксированной. Фиксированная скидка не может сделать итог отрицательным.",
    )
    min_order_total = models.DecimalField(
        "Минимальная сумма заказа",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Промокод применяется, только если подытог заказа не ниже этой суммы. "
        "Пусто — без ограничения.",
    )
    starts_at = models.DateTimeField(
        "Начало действия",
        null=True,
        blank=True,
        help_text="Пусто — действует сразу.",
    )
    ends_at = models.DateTimeField(
        "Конец действия",
        null=True,
        blank=True,
        help_text="Пусто — действует бессрочно.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "Промокод"
        verbose_name_plural = "Промокоды"
        constraints = [
            # Скидка всегда положительна.
            models.CheckConstraint(
                condition=models.Q(discount_value__gt=0),
                name="promo_discount_value_positive",
            ),
            # Процентная скидка не может превышать 100.
            models.CheckConstraint(
                condition=models.Q(discount_type="fixed")
                | models.Q(discount_value__lte=100),
                name="promo_percent_not_over_100",
            ),
            # Минимальная сумма неотрицательна, если задана.
            models.CheckConstraint(
                condition=models.Q(min_order_total__isnull=True)
                | models.Q(min_order_total__gte=0),
                name="promo_min_order_total_nonnegative",
            ),
            # Если обе границы заданы, конец должен быть позже начала.
            models.CheckConstraint(
                condition=models.Q(starts_at__isnull=True)
                | models.Q(ends_at__isnull=True)
                | models.Q(ends_at__gt=models.F("starts_at")),
                name="promo_period_consistent",
            ),
        ]

    def save(self, *args, **kwargs):
        # Нормализуем код, чтобы дубли в разном регистре не проскакивали.
        if self.code:
            self.code = normalize_promo_code(self.code)
        super().save(*args, **kwargs)

    def clean(self):
        """Проверяем формат кода и согласованность полей до обращения к БД."""
        super().clean()

        if self.code:
            self.code = normalize_promo_code(self.code)
            if not PROMO_CODE_PATTERN.fullmatch(self.code):
                raise ValidationError(
                    {
                        "code": "Код может состоять только из цифр и букв "
                        "(русских или латинских)."
                    }
                )

        if (
            self.discount_type == self.DISCOUNT_PERCENT
            and self.discount_value is not None
            and self.discount_value > 100
        ):
            raise ValidationError(
                {"discount_value": "Процентная скидка не может быть больше 100%."}
            )

        if (
            self.starts_at
            and self.ends_at
            and self.ends_at <= self.starts_at
        ):
            raise ValidationError(
                {"ends_at": "Конец действия должен быть позже начала."}
            )

    def validate_for(self, subtotal, now=None):
        """Проверяет применимость к заказу. Возвращает текст ошибки или None.

        Проверка повторяется при каждом пересчёте корзины и при оформлении
        заказа — скидку нельзя «зашить» один раз на стороне клиента.
        """
        now = now or timezone.now()

        if not self.is_active:
            return "Этот промокод не действует."
        if self.starts_at and now < self.starts_at:
            return "Промокод ещё не начал действовать."
        if self.ends_at and now > self.ends_at:
            return "Срок действия промокода истёк."
        if (
            self.min_order_total is not None
            and subtotal < self.min_order_total
        ):
            return (
                f"Промокод действует при заказе от "
                f"{format_amount(self.min_order_total)} руб."
            )
        return None

    def __str__(self):
        return self.code
