"""Отправка ограниченной партии писем из почтовой очереди (этап 6).

Команда предназначена для периодического запуска планировщиком ОС
(Windows: send_emails.bat / Планировщик заданий; Linux: cron, например
«*/1 * * * * ... manage.py send_order_emails >> logs/mail_cron.log 2>&1»).

SMTP-вызовы выполняются вне транзакции создания заказа и без длинной
блокировки БД: письма атомарно захватываются в sending, отправляются по
одному, затем переводятся в sent либо возвращаются в pending со сдвигом
next_attempt_at (см. orders/emails.py и docs/architecture.md §10).
Параллельные запуски безопасны: одно письмо достаётся только одному
обработчику благодаря атомарному захвату UPDATE-ом с проверкой статуса.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.emails import (
    DEFAULT_BATCH_SIZE,
    claim_pending_emails,
    pending_ready_count,
    reclaim_stale_sending,
    send_outgoing_email,
)


class Command(BaseCommand):
    help = (
        "Отправляет до --batch готовых писем из очереди исходящей почты. "
        "Временные ошибки откладывают письмо на повтор, постоянные переводят "
        "его в failed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Максимум писем за один запуск (по умолчанию {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        # Письма, зависшие в sending после падения обработчика, снова в очереди.
        reclaim_stale_sending(now)
        claimed = claim_pending_emails(options["batch"], now)

        sent = retries = failed = 0
        for mail in claimed:
            send_outgoing_email(mail, now)
            if mail.status == mail.STATUS_SENT:
                sent += 1
            elif mail.status == mail.STATUS_PENDING:
                retries += 1
            else:
                failed += 1

        ready_left = pending_ready_count(now)
        summary = (
            f"Обработано писем: {len(claimed)} "
            f"(отправлено: {sent}, повтор позже: {retries}, отказ: {failed}); "
            f"готово к отправке ещё: {ready_left}."
        )
        self.stdout.write(summary)
