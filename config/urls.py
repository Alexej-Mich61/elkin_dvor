from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
]

if settings.DEBUG:
    # URL для автообновления браузера (только для разработки!)
    urlpatterns += [path("__reload__/", include("django_browser_reload.urls"))]
    # Раздача загруженных медиа через Django (только для разработки!)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
