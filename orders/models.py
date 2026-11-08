"""Промокоды, покупатели и заказы.

Код промокода — только цифры и буквы (латиница или кириллица), без
спецсимволов. В хранилище код всегда нормализован: обрезанные пробелы
и верхний регистр, поэтому «ёлка2026» и « ЁЛКА2026 » — один код.
См. docs/architecture.md §6–7.

Заказ хранит исторический снимок контактов, адреса, цен и сумм:
изменение каталога или карточки покупателя старый заказ не переписывает.
Статусы заказа согласованы с владельцем: «выполняется» (ставится
автоматически при создании), «выполнен» и «отменён» — вручную в админке.
"""
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


# --- Нормализация контактов (этап 5) ---------------------------------------

def normalize_phone(value):
    """Нормализованный телефон для поиска покупателя: только цифры.

    Российская «8» приводится к «7», чтобы «8 (918) …» и «+7 (918) …»
    давали один ключ. Пустой ввод — пустая строка."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def normalize_email(value):
    """Нормализованный email: trim + нижний регистр. Пустой ввод — пустая строка."""
    return (value or "").strip().lower()

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


# --- Покупатели и заказы (этап 5) -------------------------------------------

PHONE_MAX_LENGTH = 32
CONTACT_NAME_MAX_LENGTH = 150
ADDRESS_MAX_LENGTH = 300


class Customer(models.Model):
    """Рабочая база контактов. Телефон и email не уникальны на уровне БД:
    контакт может быть общим, а неоднозначные совпадения нельзя объединять
    автоматически — см. docs/architecture.md §6."""

    name = models.CharField("Имя", max_length=CONTACT_NAME_MAX_LENGTH)
    phone = models.CharField("Телефон", max_length=PHONE_MAX_LENGTH)
    phone_normalized = models.CharField(
        "Нормализованный телефон",
        max_length=PHONE_MAX_LENGTH,
        db_index=True,
        editable=False,
        help_text="Ключ осторожного поиска покупателя: только цифры, "
        "российская «8» приведена к «7».",
    )
    email = models.EmailField("Email", max_length=254, blank=True)
    note = models.TextField("Служебная заметка", blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Покупатель"
        verbose_name_plural = "Покупатели"

    def save(self, *args, **kwargs):
        self.phone_normalized = normalize_phone(self.phone)
        if self.email:
            self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} · {self.phone}"


class Order(models.Model):
    """Заказ с историческим снимком контактов, адреса, цен и сумм.

    Снимок необходим даже при наличии Customer: карточка покупателя и
    каталог могут измениться, а данные конкретной доставки должны остаться
    прежними. См. docs/architecture.md §6."""

    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PROCESSING, "Выполняется"),
        (STATUS_COMPLETED, "Выполнен"),
        (STATUS_CANCELLED, "Отменён"),
    )

    number = models.CharField(
        "Номер заказа",
        max_length=32,
        unique=True,
        editable=False,
        help_text="Публичный номер вида «ЁД-2026-000125». Формируется "
        "автоматически и сам по себе не открывает доступ к заказу.",
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name="Покупатель",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
        help_text="Связь рабочая: при удалении карточки покупателя заказ сохраняется.",
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PROCESSING,
        db_index=True,
        help_text="«Выполняется» ставится автоматически при создании. "
        "«Выполнен» и «отменён» меняются вручную.",
    )

    # Снимок оформления: имя, телефон, email, адрес и примечание на момент заказа.
    name = models.CharField("Имя", max_length=CONTACT_NAME_MAX_LENGTH)
    phone = models.CharField("Телефон", max_length=PHONE_MAX_LENGTH)
    email = models.EmailField("Email", max_length=254, blank=True)
    address = models.CharField("Адрес доставки", max_length=ADDRESS_MAX_LENGTH)
    note = models.TextField("Примечание к заказу", blank=True)

    # Деньги: снимок единого расчёта orders.services.calculate_totals.
    subtotal = models.DecimalField("Подытог", max_digits=10, decimal_places=2)
    discount = models.DecimalField("Скидка", max_digits=10, decimal_places=2)
    total = models.DecimalField("Итог", max_digits=10, decimal_places=2)
    # Параметры применённого промокода — снимок, FK не нужен:
    # удаление промокода старые заказы не меняет.
    promo_code = models.CharField("Промокод", max_length=PROMO_CODE_MAX_LENGTH, blank=True)
    promo_discount_type = models.CharField(
        "Тип скидки промокода",
        max_length=10,
        choices=PromoCode.DISCOUNT_TYPE_CHOICES,
        blank=True,
    )
    promo_discount_value = models.DecimalField(
        "Величина скидки промокода",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0),
                name="order_subtotal_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(discount__gte=0),
                name="order_discount_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(total__gte=0),
                name="order_total_nonnegative",
            ),
        ]

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    """Позиция заказа: снимок названия, размера и цены на момент заказа.

    Ссылки на каталог служебные и необязательные: при удалении товара или
    варианта позиция сохраняется, при изменении цены не пересчитывается."""

    order = models.ForeignKey(
        Order, verbose_name="Заказ", on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        "shop.Product",
        verbose_name="Товар",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        editable=False,
    )
    variant = models.ForeignKey(
        "shop.ProductVariant",
        verbose_name="Вариант",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        editable=False,
    )
    product_name = models.CharField("Название", max_length=255)
    variant_size = models.CharField("Размер", max_length=80)
    unit_price = models.DecimalField("Цена за единицу", max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField("Количество")
    total_price = models.DecimalField("Сумма позиции", max_digits=10, decimal_places=2)

    class Meta:
        ordering = ("pk",)
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказов"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="order_item_unit_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_price__gte=0),
                name="order_item_total_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.product_name} ({self.variant_size}) × {self.quantity}"


def build_order_number(order_pk, year):
    """Публичный номер заказа: «ЁД-2026-000125». См. architecture.md §6."""
    return f"ЁД-{year}-{order_pk:06d}"


# --- Почтовая очередь (этап 6) -----------------------------------------------

EMAIL_MAX_LENGTH = 254
EMAIL_SUBJECT_MAX_LENGTH = 255
EMAIL_KEY_MAX_LENGTH = 80


class ShopSettings(models.Model):
    """Служебные настройки магазина. Хранится ровно одна запись (singleton);
    редактируется через админку. См. docs/architecture.md §10."""

    manager_email = models.EmailField(
        "Email менеджера",
        max_length=EMAIL_MAX_LENGTH,
        blank=True,
        help_text="Сюда уходит письмо о каждом новом заказе. Если пусто — "
        "письмо магазину не ставится в очередь (в логе будет предупреждение).",
    )
    updated_at = models.DateTimeField("Обновлены", auto_now=True)

    class Meta:
        verbose_name = "Настройки магазина"
        verbose_name_plural = "Настройки магазина"

    def save(self, *args, **kwargs):
        # Singleton: всегда одна и та же запись с pk=1.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        """Единственная запись настроек; создаётся при первом обращении."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Настройки магазина"


class OutgoingEmail(models.Model):
    """Одно исходящее письмо: поставлено в очередь вместе с заказом,
    отправляется отдельной командой вне транзакции заказа.

    Статусы: pending — ждёт отправки; sending — захвачено обработчиком;
    sent — отправлено; failed — попытки исчерпаны. Технический ключ
    защищает от повторной постановки того же письма. См. §10."""

    KIND_CUSTOMER = "customer"
    KIND_MANAGER = "manager"
    KIND_CHOICES = (
        (KIND_CUSTOMER, "Покупателю"),
        (KIND_MANAGER, "Менеджеру"),
    )

    STATUS_PENDING = "pending"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "В очереди"),
        (STATUS_SENDING, "Отправляется"),
        (STATUS_SENT, "Отправлено"),
        (STATUS_FAILED, "Ошибка"),
    )

    order = models.ForeignKey(
        Order,
        verbose_name="Заказ",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outgoing_emails",
        editable=False,
        help_text="Связь служебная: удаление заказа запись письма не стирает.",
    )
    # Снимок номера: письмо остаётся идентифицируемым даже после удаления заказа.
    order_number = models.CharField(
        "Номер заказа", max_length=32, editable=False, db_index=True
    )
    kind = models.CharField(
        "Тип", max_length=16, choices=KIND_CHOICES, editable=False
    )
    key = models.CharField(
        "Ключ идемпотентности",
        max_length=EMAIL_KEY_MAX_LENGTH,
        unique=True,
        editable=False,
        help_text="Технический ключ вида «order:12:customer»: не даёт поставить "
        "одно и то же письмо дважды.",
    )
    to = models.EmailField("Получатель", max_length=EMAIL_MAX_LENGTH)
    subject = models.CharField("Тема", max_length=EMAIL_SUBJECT_MAX_LENGTH)
    body_text = models.TextField("Текстовое тело")
    body_html = models.TextField("HTML-тело", blank=True)
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField("Попыток отправки", default=0)
    next_attempt_at = models.DateTimeField(
        "Следующая попытка",
        null=True,
        blank=True,
        db_index=True,
        help_text="Пусто — отправить при ближайшем запуске обработчика.",
    )
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)
    last_error = models.TextField("Последняя ошибка", blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Исходящее письмо"
        verbose_name_plural = "Исходящие письма"

    def __str__(self):
        return f"{self.subject} → {self.to}"
