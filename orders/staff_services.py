"""Сервисы staff-страниц менеджера (этап 7).

Здесь вся логика фильтров, поиска, статистики и пагинации для страниц
«Заказы» и «Клиентская база» — views остаются тонкими. Экспорт в Excel —
в orders.exports.

Особенности:
- поиск регистронезависимый, включая кириллицу: SQLite LIKE (icontains)
  сворачивает регистр только для ASCII, поэтому фильтрация по тексту
  выполняется в Python через str.casefold();
- по умолчанию показываются последние DEFAULT_LIMIT записей; как только
  применён любой фильтр или поиск, ограничение снимается и показываются
  все подходящие записи;
- статистика (число записей и сумма) считается по тому же набору,
  который виден на экране.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from math import ceil

from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from .models import Customer, Order

ORDERS_PER_PAGE = 50
CUSTOMERS_PER_PAGE = 50
# Потолок «последних N записей» без фильтров — снимается фильтром/поиском.
DEFAULT_LIMIT = 100


# --- Заказы ------------------------------------------------------------------

@dataclass
class OrderFilters:
    """Разобранные и провалидированные параметры фильтра списка заказов."""

    date_from: date | None = None
    date_to: date | None = None
    status: str = ""
    category_id: int | None = None
    promo: str = ""  # "" — все, "yes" — с промокодом, "no" — без промокода
    search: str = ""

    @property
    def is_active(self):
        """Применён ли хоть один фильтр/поиск (снимает лимит в 100 записей)."""
        return bool(
            self.date_from
            or self.date_to
            or self.status
            or self.category_id
            or self.promo
            or self.search
        )


def _order_matches_search(order: Order, needle: str) -> bool:
    """Регистронезависимое вхождение needle в имя/адрес/промокод/товары заказа."""
    n = needle.casefold()
    if (
        n in order.name.casefold()
        or n in order.address.casefold()
        or n in order.promo_code.casefold()
    ):
        return True
    return any(n in item.product_name.casefold() for item in order.items.all())


def filter_orders(filters: OrderFilters) -> tuple[list[Order], int]:
    """Возвращает (заказы от новых к старым, всего найдено без лимита).

    Без фильтров/поиска возвращает не более последних DEFAULT_LIMIT заказов
    (второе число при этом — общее число заказов в базе, для предупреждения).
    """
    qs = Order.objects.prefetch_related("items")
    if filters.date_from:
        qs = qs.filter(created_at__gte=_day_start(filters.date_from))
    if filters.date_to:
        qs = qs.filter(created_at__lte=_day_end(filters.date_to))
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.category_id:
        # Заказ попадает в выборку, если хотя бы одна позиция относится
        # к выбранной категории (остальные позиции заказа не важны).
        qs = qs.filter(items__product__category_id=filters.category_id).distinct()
    if filters.promo == "yes":
        qs = qs.exclude(promo_code="")
    elif filters.promo == "no":
        qs = qs.filter(promo_code="")

    orders = list(qs.order_by("-created_at", "-pk"))
    if filters.search:
        orders = [o for o in orders if _order_matches_search(o, filters.search)]

    total_found = len(orders)
    if not filters.is_active and total_found > DEFAULT_LIMIT:
        orders = orders[:DEFAULT_LIMIT]
    return orders, total_found


@dataclass
class ListStats:
    """Статистика над списком: сколько показано/найдено и общая сумма."""

    shown: int
    total_found: int
    total_sum: Decimal
    limited: bool = False
    orders_count: int = 0


def summarize_orders(orders: list[Order], total_found: int, filters: OrderFilters) -> ListStats:
    """Статистика по видимому набору: число записей и сумма итогов."""
    return ListStats(
        shown=len(orders),
        total_found=total_found,
        total_sum=sum((order.total for order in orders), Decimal("0.00")),
        limited=not filters.is_active and total_found > len(orders),
    )


# --- Клиентская база ----------------------------------------------------------

@dataclass
class CustomerRow:
    """Строка списка клиентской базы: покупатель + сводка по его заказам."""

    customer: Customer
    orders_count: int
    total_spent: Decimal
    last_order_at: datetime | None
    addresses: list[str] = field(default_factory=list)


def _build_customer_row(customer: Customer) -> CustomerRow:
    # Заказы предзагружены (см. _customers_prefetch), от новых к старым.
    orders = list(customer.orders.all())
    addresses: list[str] = []
    for order in orders:
        if order.address and order.address not in addresses:
            addresses.append(order.address)
    return CustomerRow(
        customer=customer,
        orders_count=len(orders),
        total_spent=sum((order.total for order in orders), Decimal("0.00")),
        last_order_at=orders[0].created_at if orders else None,
        addresses=addresses,
    )


def _customers_prefetch() -> Prefetch:
    return Prefetch(
        "orders",
        queryset=Order.objects.order_by("-created_at", "-pk"),
    )


def _customer_matches_search(row: CustomerRow, needle: str) -> bool:
    """Поиск по имени, контактам и адресам заказов (регистронезависимо)."""
    n = needle.casefold()
    customer = row.customer
    if (
        n in customer.name.casefold()
        or n in customer.email.casefold()
        or n in customer.phone.casefold()
        or n in customer.phone_normalized.casefold()
    ):
        return True
    return any(n in address.casefold() for address in row.addresses)


def get_customer_rows(search: str = "") -> tuple[list[CustomerRow], int]:
    """Строки клиентской базы: последние DEFAULT_LIMIT, пока нет поиска.

    Возвращает (строки, всего найдено без лимита).
    """
    qs = Customer.objects.prefetch_related(_customers_prefetch())
    rows = [_build_customer_row(c) for c in qs]
    if search:
        rows = [row for row in rows if _customer_matches_search(row, search)]

    total_found = len(rows)
    if not search and total_found > DEFAULT_LIMIT:
        rows = rows[:DEFAULT_LIMIT]
    return rows, total_found


def summarize_customers(rows: list[CustomerRow], total_found: int, search: str) -> ListStats:
    """Статистика по видимому набору покупателей (сумма — по их заказам)."""
    return ListStats(
        shown=len(rows),
        total_found=total_found,
        total_sum=sum((row.total_spent for row in rows), Decimal("0.00")),
        limited=not search and total_found > len(rows),
        orders_count=sum(row.orders_count for row in rows),
    )


def build_customer_rows(customers) -> list[CustomerRow]:
    """Строки для экспорта/админки из произвольного набора покупателей."""
    if isinstance(customers, QuerySet):
        customers = customers.prefetch_related(_customers_prefetch())
    return [_build_customer_row(c) for c in customers]


# --- Пагинация ----------------------------------------------------------------

@dataclass
class SimplePage:
    """Одна страница списка: элементы и номера страниц."""

    items: list
    number: int
    num_pages: int

    @property
    def has_previous(self):
        return self.number > 1

    @property
    def has_next(self):
        return self.number < self.num_pages

    @property
    def previous_page_number(self):
        return self.number - 1

    @property
    def next_page_number(self):
        return self.number + 1


def paginate(items: list, page_number, per_page: int) -> SimplePage:
    """Режем список на страницы; некорректный номер — первая/последняя."""
    num_pages = max(1, ceil(len(items) / per_page))
    try:
        number = int(page_number)
    except (TypeError, ValueError):
        number = 1
    number = min(max(number, 1), num_pages)
    start = (number - 1) * per_page
    return SimplePage(
        items=items[start : start + per_page],
        number=number,
        num_pages=num_pages,
    )


# --- Даты ---------------------------------------------------------------------

def _day_start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def _day_end(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.max))
