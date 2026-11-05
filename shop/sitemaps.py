from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Product


class CategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Category.objects.filter(is_active=True)

    def location(self, item):
        return reverse("shop:category", kwargs={"category_slug": item.slug})


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.9

    def items(self):
        return Product.objects.filter(
            is_active=True, category__is_active=True
        ).order_by("pk")

    def lastmod(self, item):
        return item.updated_at

    def location(self, item):
        return reverse(
            "shop:product",
            kwargs={"category_slug": item.category.slug, "product_slug": item.slug},
        )
