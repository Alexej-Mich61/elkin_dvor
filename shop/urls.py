from django.urls import path, register_converter
from django.views.generic import TemplateView

from . import views


class UnicodeSlugConverter:
    """Как стандартный slug-конвертер Django, но принимает кириллицу:
    slug'и проекта создаются с allow_unicode=True."""

    regex = r"[-\w]+"
    to_python = str
    to_url = str


register_converter(UnicodeSlugConverter, "uslug")

app_name = "shop"

urlpatterns = [
    path("", views.home, name="home"),
    path("catalog/<uslug:category_slug>/", views.category_detail, name="category"),
    path(
        "catalog/<uslug:category_slug>/<uslug:product_slug>/",
        views.product_detail,
        name="product",
    ),
    # HTMX-фрагмент с актуальной ценой выбранного варианта размера.
    path(
        "catalog/<uslug:category_slug>/<uslug:product_slug>/price/",
        views.variant_price,
        name="variant_price",
    ),
    # Политика конфиденциальности (ссылка из уведомления о cookies).
    path(
        "privacy/",
        TemplateView.as_view(template_name="shop/privacy.html"),
        name="privacy",
    ),
    # Политика обработки персональных данных (ссылка из формы заказа).
    path(
        "personal-data/",
        TemplateView.as_view(template_name="shop/personal_data.html"),
        name="personal_data",
    ),
]
