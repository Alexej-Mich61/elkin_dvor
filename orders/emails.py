"""Почтовая очередь: построение писем о заказе, их постановка в очередь
и отправка обработчиком (этап 6).

Жизненный цикл: create_order в одной транзакции создаёт заказ и две записи
OutgoingEmail (покупателю и менеджеру). SMTP в транзакции нет — отправляет
management-команда send_order_emails, которую периодически запускает
планировщик ОС (на Windows — send_emails.bat / Планировщик заданий).

Устойчивость к сбоям и параллельным запускам:
- захват письма атомарный (UPDATE с проверкой статуса) — два обработчика
  не возьмут одно письмо, отправка работает при нескольких воркерах;
- временная ошибка откладывает письмо на RETRY_DELAY, всего MAX_ATTEMPTS
  попыток; постоянная ошибка сразу переводит письмо в failed;
- письмо, зависшее в sending (обработчик умер mid-flight), возвращается
  в очередь после STALE_SENDING тишины — редкий повторный отсыл
  допустим, потеря письма — нет (см. docs/architecture.md §10).

Лог — logger «orders.mail»: консоль + logs/mail.log (настройка в settings).
Без секретов: логируем получателя, номер заказа и результат, не тело письма.
"""
import logging
import smtplib
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from shop.context_processors import SHOP_CONTACTS

from .models import OutgoingEmail, ShopSettings, format_amount

logger = logging.getLogger("orders.mail")

# Обработка одного запуска команды по умолчанию.
DEFAULT_BATCH_SIZE = 20
# Всего попыток отправки одного письма.
MAX_ATTEMPTS = 5
# Пауза перед повторной попыткой после временной ошибки.
RETRY_DELAY = timedelta(minutes=5)
# Через сколько письмо в «sending» считается зависшим и снова доступно.
STALE_SENDING = timedelta(minutes=15)

TEMPLATE_BY_KIND = {
    OutgoingEmail.KIND_CUSTOMER: (
        "orders/emails/order_customer_subject.txt",
        "orders/emails/order_customer.txt",
        "orders/emails/order_customer.html",
    ),
    OutgoingEmail.KIND_MANAGER: (
        "orders/emails/order_manager_subject.txt",
        "orders/emails/order_manager.txt",
        "orders/emails/order_manager.html",
    ),
}


def order_email_context(order):
    """Контекст шаблонов письма: заказ, позиции, суммы и контакты магазина."""
    items = [
        {
            "name": item.product_name,
            "size": item.variant_size,
            "quantity": item.quantity,
            "unit_price": format_amount(item.unit_price),
            "total_price": format_amount(item.total_price),
        }
        for item in order.items.all()
    ]
    return {
        "order": order,
        "items": items,
        "date": timezone.localtime(order.created_at).strftime("%d.%m.%Y %H:%M"),
        "subtotal": format_amount(order.subtotal),
        "discount": format_amount(order.discount),
        "total": format_amount(order.total),
        "shop_phone": SHOP_CONTACTS["SHOP_PHONE_DISPLAY"],
        "shop_phone_tel": SHOP_CONTACTS["SHOP_PHONE_TEL"],
        "shop_address": SHOP_CONTACTS["SHOP_ADDRESS"],
        "shop_name": SHOP_CONTACTS["SHOP_NAME"],
    }


def build_order_email(order, kind, recipient):
    """Собирает не сохранённую запись OutgoingEmail для заказа."""
    subject_template, text_template, html_template = TEMPLATE_BY_KIND[kind]
    context = order_email_context(order)
    return OutgoingEmail(
        order=order,
        order_number=order.number,
        kind=kind,
        key=f"order:{order.pk}:{kind}",
        to=recipient,
        subject=render_to_string(subject_template, context).strip(),
        body_text=render_to_string(text_template, context),
        body_html=render_to_string(html_template, context),
    )


def queue_order_emails(order):
    """Ставит письма покупателю и менеджеру в очередь. Вызывается внутри
    транзакции создания заказа: откат заказа уносит и записи писем.

    Письмо покупателю создаётся, только если email указан; письмо менеджеру —
    только если задан email менеджера в настройках магазина. Уже существующие
    ключи пропускаются — повторная постановка невозможна."""
    emails = []
    if order.email:
        emails.append(build_order_email(order, OutgoingEmail.KIND_CUSTOMER, order.email))
    manager_email = ShopSettings.get_solo().manager_email
    if manager_email:
        emails.append(
            build_order_email(order, OutgoingEmail.KIND_MANAGER, manager_email)
        )
    else:
        logger.warning(
            "Email менеджера не настроен (админка → Настройки магазина): "
            "письмо о заказе %s магазину не поставлено в очередь.",
            order.number,
        )

    existing_keys = set(
        OutgoingEmail.objects.filter(order=order).values_list("key", flat=True)
    )
    fresh = [mail for mail in emails if mail.key not in existing_keys]
    skipped = len(emails) - len(fresh)
    OutgoingEmail.objects.bulk_create(fresh)
    for mail in fresh:
        logger.info(
            "В очереди письмо «%s» для %s (заказ %s).",
            mail.subject,
            mail.to,
            order.number,
        )
    if skipped:
        logger.warning(
            "Пропущено %s писем для заказа %s: такие уже есть в очереди.",
            skipped,
            order.number,
        )
    return fresh


# --- Обработка очереди (management-команда send_order_emails) ---------------

def reclaim_stale_sending(now=None, stale_after=STALE_SENDING):
    """Возвращает в очередь письма, зависшие в статусе sending: обработчик
    мог упасть между фактической отправкой и записью статуса."""
    now = now or timezone.now()
    reclaimed = OutgoingEmail.objects.filter(
        status=OutgoingEmail.STATUS_SENDING, updated_at__lt=now - stale_after
    ).update(status=OutgoingEmail.STATUS_PENDING, updated_at=now)
    if reclaimed:
        logger.warning(
            "В очередь возвращено %s зависших писем (статус «отправляется» "
            "дольше %s мин).",
            reclaimed,
            int(stale_after.total_seconds() // 60),
        )
    return reclaimed


def claim_pending_emails(batch_size, now=None):
    """Атомарно переводит до batch_size готовых писем в sending и возвращает
    их. Каждая запись захватывается отдельным UPDATE с проверкой статуса,
    поэтому при одновременном запуске нескольких обработчиков письмо достаётся
    только одному (и на SQLite, и на PostgreSQL)."""
    now = now or timezone.now()
    candidates = (
        OutgoingEmail.objects.filter(status=OutgoingEmail.STATUS_PENDING)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .order_by("created_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    claimed_pks = []
    for pk in candidates:
        taken = OutgoingEmail.objects.filter(
            pk=pk, status=OutgoingEmail.STATUS_PENDING
        ).update(status=OutgoingEmail.STATUS_SENDING, updated_at=now)
        if taken:
            claimed_pks.append(pk)
    return list(
        OutgoingEmail.objects.filter(pk__in=claimed_pks).order_by("created_at")
    )


def _is_permanent_error(exc):
    """Ошибки, при которых повтор бессмысленен: отказ авторизации, неверный
    получатель, ответ SMTP 5xx. Остальное (сеть, таймауты, 4xx) — временно."""
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused)):
        return True
    if isinstance(exc, smtplib.SMTPResponseException):
        return exc.smtp_code >= 500
    return False


def send_outgoing_email(mail, now=None):
    """Отправляет одно письмо через настроенный mailer и обновляет его статус.

    Успех → sent; временная ошибка → pending с отложенной следующей попыткой;
    постоянная ошибка или исчерпание попыток → failed. Возвращает True,
    если письмо отправлено."""
    now = now or timezone.now()
    message = EmailMultiAlternatives(
        subject=mail.subject,
        body=mail.body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[mail.to],
    )
    if mail.body_html:
        message.attach_alternative(mail.body_html, "text/html")
    mail.attempts += 1
    try:
        message.send()
    except Exception as exc:
        mail.last_error = str(exc)[:2000]
        if _is_permanent_error(exc) or mail.attempts >= MAX_ATTEMPTS:
            mail.status = OutgoingEmail.STATUS_FAILED
            mail.next_attempt_at = None
            logger.error(
                "Письмо #%s (%s, заказ %s) для %s НЕ отправлено: %s",
                mail.pk,
                mail.get_kind_display(),
                mail.order_number,
                mail.to,
                mail.last_error,
            )
        else:
            mail.status = OutgoingEmail.STATUS_PENDING
            mail.next_attempt_at = now + RETRY_DELAY
            logger.warning(
                "Временная ошибка отправки письма #%s (%s, заказ %s) для %s: %s. "
                "Попытка %s из %s, следующая через %s мин.",
                mail.pk,
                mail.get_kind_display(),
                mail.order_number,
                mail.to,
                mail.last_error,
                mail.attempts,
                MAX_ATTEMPTS,
                int(RETRY_DELAY.total_seconds() // 60),
            )
    else:
        mail.status = OutgoingEmail.STATUS_SENT
        mail.sent_at = now
        mail.last_error = ""
        logger.info(
            "Отправлено письмо #%s (%s, заказ %s) для %s.",
            mail.pk,
            mail.get_kind_display(),
            mail.order_number,
            mail.to,
        )
    mail.save(
        update_fields=[
            "status",
            "attempts",
            "next_attempt_at",
            "sent_at",
            "last_error",
            "updated_at",
        ]
    )
    return mail.status == OutgoingEmail.STATUS_SENT


def pending_ready_count(now=None):
    """Сколько писем готово к отправке прямо сейчас (для сводки команды)."""
    now = now or timezone.now()
    return OutgoingEmail.objects.filter(
        status=OutgoingEmail.STATUS_PENDING
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)).count()
