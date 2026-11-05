from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from shop.sitemaps import CategorySitemap, ProductSitemap

sitemaps = {
    "categories": CategorySitemap,
    "products": ProductSitemap,
}

urlpatterns = [
    path("admin/", admin.site.urls),
    # Главная и публичный каталог магазина
    path("", include("shop.urls")),
    # SEO: карта сайта и правила для роботов
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path(
        "robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
        name="robots",
    ),
]

if settings.DEBUG:
    # URL для автообновления браузера (только для разработки!)
    urlpatterns += [path("__reload__/", include("django_browser_reload.urls"))]
    # Раздача загруженных медиа через Django (только для разработки!)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
