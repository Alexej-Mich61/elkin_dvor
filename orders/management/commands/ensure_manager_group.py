"""Создание (или синхронизация) группы «Менеджер» с курируемым набором прав.

Этап 7. Команда идемпотентна: можно запускать повторно — набор прав
приведётся к заданному. Пользователям, входящим в группу, права не
сужаются и не расширяются вручную через эту команду — она управляет
только составом группы.

Права менеджера (см. docs/architecture.md §13):
- заказы: просмотр и изменение (статус, контакты — через staff-форму);
- покупатели: просмотр, изменение, добавление;
- промокоды и каталог — только просмотр (контекст для работы с заказами).

Чего у менеджера НЕТ: удаление заказов, ShopSettings (критичные настройки),
исходящая почта, управление пользователями, admin (сайты/журналы) —
всё это доступно только администратору (суперпользователю).

Замечание про is_staff: флаг is_staff ставится на самом пользователе
(в админке при создании/редактировании), команда его не трогает.
"""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

GROUP_NAME = "Менеджер"

# (app_label, codename) разрешений группы. Только явный список —
# никаких широких granted по префиксу.
MANAGER_PERMISSIONS = [
    ("orders", "view_order"),
    ("orders", "change_order"),
    ("orders", "view_orderitem"),
    ("orders", "add_customer"),
    ("orders", "view_customer"),
    ("orders", "change_customer"),
    ("orders", "view_promocode"),
    ("shop", "view_category"),
    ("shop", "view_product"),
    ("shop", "view_productvariant"),
    ("shop", "view_productimage"),
]


class Command(BaseCommand):
    help = (
        "Создаёт группу «Менеджер» с правами на работу с заказами и "
        "покупателями (без доступа к критичным настройкам). Идемпотентна."
    )

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name=GROUP_NAME)

        permissions = []
        missing = []
        for app_label, codename in MANAGER_PERMISSIONS:
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename
            ).first()
            if perm is None:
                missing.append(f"{app_label}.{codename}")
            else:
                permissions.append(perm)

        group.permissions.set(permissions)

        if missing:
            self.stderr.write(
                self.style.WARNING(
                    "Не найдены разрешения (миграции не применены?): "
                    + ", ".join(missing)
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Группа «{GROUP_NAME}»: {len(permissions)} прав. "
                "Не забудьте включить пользователю is_staff при создании менеджера."
            )
        )
