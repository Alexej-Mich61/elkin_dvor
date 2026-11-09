"""Админка промокодов, заказов, покупателей и почтовой очереди.

Заказы: фильтр по статусу и дате, поиск по номеру, имени, телефону, email
и адресу. Контактный и денежный снимок заказа исторический — в админке
только для чтения; менять вручную можно только статус (выполнен/отменён).
Письма очереди — только для чтения; failed можно вернуть в очередь действием.
"""
from django.contrib import admin
from django.db.models import Count
from django.utils import timezone

from . import exports, staff_services
from .models import (
    Customer,
    Order,
    OrderItem,
    OutgoingEmail,
    PromoCode,
    ShopSettings,
    format_amount,
)


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    """Промокоды: код и скидка — поиском, активность и тип — фильтрами."""

    list_display = (
        "code",
        "discount_display",
        "is_active",
        "min_order_total",
        "starts_at",
        "ends_at",
        "updated_at",
    )
    list_filter = ("is_active", "discount_type")
    search_fields = ("code",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Скидка")
    def discount_display(self, obj):
        if obj.discount_type == PromoCode.DISCOUNT_PERCENT:
            return f"{format_amount(obj.discount_value)} %"
        return f"{format_amount(obj.discount_value)} руб."


class OrderItemInline(admin.TabularInline):
    """Позиции заказа — исторический снимок, в админке только для чтения."""

    model = OrderItem
    extra = 0
    can_delete = False
    fields = readonly_fields = (
        "product_name",
        "variant_size",
        "unit_price",
        "quantity",
        "total_price",
    )

    def has_add_permission(self, request, obj=None):
        return False


class OutgoingEmailInline(admin.TabularInline):
    """Письма очереди по заказу — для диагностики, только для чтения."""

    model = OutgoingEmail
    extra = 0
    can_delete = False
    fields = readonly_fields = (
        "kind",
        "to",
        "subject",
        "status",
        "attempts",
        "sent_at",
        "last_error",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Заказы: список с фильтрами и поиском; статус меняется вручную."""

    list_display = (
        "number",
        "created_at",
        "name",
        "phone",
        "total_display",
        "status",
    )
    list_filter = ("status", "created_at")
    search_fields = ("number", "name", "phone", "email", "address")
    list_editable = ("status",)
    inlines = (OrderItemInline, OutgoingEmailInline)
    actions = ("export_excel",)
    # Снимок оформления (контакты, адрес, деньги, промокод) — исторический:
    # после создания заказа не редактируется, только статус.
    readonly_fields = (
        "number",
        "customer",
        "name",
        "phone",
        "email",
        "address",
        "note",
        "subtotal",
        "discount",
        "total",
        "promo_code",
        "promo_discount_type",
        "promo_discount_value",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Сумма")
    def total_display(self, obj):
        return f"{format_amount(obj.total)} руб."

    @admin.action(description="Экспорт в Excel")
    def export_excel(self, request, queryset):
        """Те же колонки, что на staff-странице заказов."""
        orders = list(queryset.prefetch_related("items"))
        wb = exports.orders_workbook(orders)
        return exports.excel_response(wb, exports.export_filename("заказы"))


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Покупатели: поиск по имени, телефону и email; число заказов в списке."""

    list_display = ("name", "phone", "email", "orders_count", "created_at")
    search_fields = ("name", "phone", "phone_normalized", "email")
    readonly_fields = ("phone_normalized", "created_at", "updated_at")
    actions = ("export_excel",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_orders_count=Count("orders"))

    @admin.display(description="Заказов", ordering="_orders_count")
    def orders_count(self, obj):
        return obj._orders_count

    @admin.action(description="Экспорт в Excel")
    def export_excel(self, request, queryset):
        """Колонки как на staff-странице клиентской базы (контакты + адреса)."""
        rows = staff_services.build_customer_rows(queryset)
        wb = exports.customers_workbook(rows)
        return exports.excel_response(wb, exports.export_filename("клиенты"))


@admin.register(OutgoingEmail)
class OutgoingEmailAdmin(admin.ModelAdmin):
    """Исходящая почта: только для чтения; failed возвращается в очередь действием."""

    list_display = (
        "subject",
        "to",
        "order_number",
        "kind",
        "status",
        "attempts",
        "next_attempt_at",
        "sent_at",
        "created_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("to", "subject", "order_number")
    readonly_fields = (
        "order",
        "order_number",
        "kind",
        "key",
        "to",
        "subject",
        "body_text",
        "body_html",
        "status",
        "attempts",
        "next_attempt_at",
        "sent_at",
        "last_error",
        "created_at",
        "updated_at",
    )
    actions = ("requeue",)

    @admin.action(description="Вернуть выбранные письма в очередь")
    def requeue(self, request, queryset):
        """Сброс failed в pending: счётчик попыток с нуля, отправка при следующем запуске."""
        updated = queryset.filter(status=OutgoingEmail.STATUS_FAILED).update(
            status=OutgoingEmail.STATUS_PENDING,
            attempts=0,
            next_attempt_at=timezone.now(),
            last_error="",
            updated_at=timezone.now(),
        )
        self.message_user(request, f"В очередь возвращено писем: {updated}.")


@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    """Настройки магазина — одна запись; здесь задаётся email менеджера."""

    def has_add_permission(self, request):
        # Singleton: вторую запись создать нельзя.
        return not ShopSettings.objects.exists()
