from django.contrib import admin

from .models import PromoCode, format_amount


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
