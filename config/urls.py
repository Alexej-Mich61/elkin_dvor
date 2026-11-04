from django.urls import path, include  # <--- Добавить include
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='base.html'), name='home'),

    # URL для автообновления браузера (только для разработки!)
    path("__reload__/", include("django_browser_reload.urls")),
]