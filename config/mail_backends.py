"""SMTP-бэкенд с явным набором корневых CA (этап 6).

Некоторые SMTP-серверы (например, smtp.mail.ru) используют сертификатные
цепочки, корни которых отсутствуют в системном хранилище Windows:
ssl.create_default_context() тогда падает с CERTIFICATE_VERIFY_FAILED
(«unable to get local issuer certificate»). Здесь контекст верификации
строится по CA-набору certifi (Mozilla bundle, уже в requirements) или
по собственному файлу из EMAIL_CA_FILE.
"""
import ssl

from django.core.mail.backends.smtp import EmailBackend
from django.utils.functional import cached_property


class CertifiSMTPEmailBackend(EmailBackend):
    """Стандартный SMTP-бэкенд, но верификация TLS идёт по заданному CA-файлу.

    Опция cafile необязательна: без неё поведение совпадает со стандартным
    бэкендом (ssl.create_default_context)."""

    def __init__(self, *args, cafile=None, **kwargs):
        self.cafile = cafile
        super().__init__(*args, **kwargs)

    @cached_property
    def ssl_context(self):
        if self.ssl_certfile or self.ssl_keyfile:
            return super().ssl_context
        if self.cafile:
            return ssl.create_default_context(cafile=self.cafile)
        return ssl.create_default_context()
