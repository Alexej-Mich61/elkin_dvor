"""Построение Excel-файлов для staff-страниц и админки (этап 7).

Используется openpyxl (добавлен в requirements.txt). Фирменные цвета —
как в styles.css: сосновый зелёный шапки таблиц, тёплый сливочный фон.
Даты пишем строками в формате ДД.ММ.ГГГГ ЧЧ:ММ — так файл одинаково
читается в любом Excel/LibreCalc и не зависит от часовых поясов.

Единая точка сборки файлов: staff-страницы и admin actions вызывают
одни и те же функции.
"""
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .staff_services import CustomerRow

# Фирменная палитра (theme/static_src/src/styles.css).
PINE = "0D3B26"
CREAM = "F6F2E9"
BORDER_COLOR = "CCC2A8"
MONEY_FORMAT = "#,##0.00"

_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_FILL = PatternFill("solid", fgColor=PINE)
_BODY_FONT = Font(size=11)
_THIN = Side(style="thin", color=BORDER_COLOR)
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(vertical="top", wrap_text=True)
_TOP = Alignment(vertical="top")


def _fmt_datetime(value) -> str:
    """Дата/время по-московски строкой: «09.11.2026 14:30»."""
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _money(value) -> float:
    """Decimal -> float для openpyxl (деньги, 2 знака)."""
    return float(value)


def _sheet(wb: Workbook, title: str, headers: list[str], widths: list[int]):
    """Лист с оформленной шапкой и ширинами колонок."""
    ws = wb.active
    ws.title = title
    for col, (header, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    return ws


def _data_cell(ws, row: int, col: int, value, money: bool = False, wrap: bool = False):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = _BODY_FONT
    cell.border = _BORDER
    cell.alignment = _WRAP if wrap else _TOP
    if money:
        cell.number_format = MONEY_FORMAT
    return cell


def _positions_text(order) -> str:
    """Позиции заказа одной строкой: «Сосна (1,5 м) × 2; Подставка (—) × 1»."""
    return "; ".join(
        f"{item.product_name} ({item.variant_size}) × {item.quantity}"
        for item in order.items.all()
    )


# --- Файлы --------------------------------------------------------------------

def orders_workbook(orders: list) -> Workbook:
    """Список заказов: одна строка — один заказ."""
    wb = Workbook()
    headers = [
        "Номер", "Создан", "Статус", "Имя", "Телефон", "Email",
        "Адрес доставки", "Позиции", "Подытог, руб.", "Скидка, руб.",
        "Промокод", "Итог, руб.", "Примечание",
    ]
    widths = [16, 16, 12, 18, 16, 22, 34, 46, 13, 12, 12, 13, 30]
    ws = _sheet(wb, "Заказы", headers, widths)
    for row, order in enumerate(orders, start=2):
        values = [
            order.number,
            _fmt_datetime(order.created_at),
            order.get_status_display(),
            order.name,
            order.phone,
            order.email,
            order.address,
            _positions_text(order),
            _money(order.subtotal),
            _money(order.discount),
            order.promo_code,
            _money(order.total),
            order.note,
        ]
        for col, value in enumerate(values, start=1):
            _data_cell(
                ws, row, col, value,
                money=col in (9, 10, 12),
                wrap=col in (7, 8, 13),
            )
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(orders) + 1)}"
    return wb


def order_workbook(order) -> Workbook:
    """Один заказ: сведения сверху, позиции таблицей, итоги снизу."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Заказ"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60

    info = [
        ("Номер заказа", order.number),
        ("Создан", _fmt_datetime(order.created_at)),
        ("Статус", order.get_status_display()),
        ("Имя", order.name),
        ("Телефон", order.phone),
        ("Email", order.email),
        ("Адрес доставки", order.address),
        ("Примечание", order.note),
    ]
    row = 1
    for label, value in info:
        label_cell = ws.cell(row=row, column=1, value=label)
        label_cell.font = Font(bold=True, size=11)
        label_cell.fill = PatternFill("solid", fgColor=CREAM)
        label_cell.border = _BORDER
        label_cell.alignment = _TOP
        _data_cell(ws, row, 2, value, wrap=True)
        row += 1

    row += 1  # пустая строка перед позициями
    headers = ["Товар", "Размер", "Цена, руб.", "Количество", "Сумма, руб."]
    widths = [40, 14, 13, 12, 14]
    for col, (header, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=row, column=col, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
    # Позиции могут быть шире блока сведений — ширины выставляем максимум.
    for col, width in enumerate(widths, start=1):
        letter = get_column_letter(col)
        current = ws.column_dimensions[letter].width or 0
        ws.column_dimensions[letter].width = max(current, width)
    row += 1
    for item in order.items.all():
        _data_cell(ws, row, 1, item.product_name, wrap=True)
        _data_cell(ws, row, 2, item.variant_size)
        _data_cell(ws, row, 3, _money(item.unit_price), money=True)
        _data_cell(ws, row, 4, item.quantity)
        _data_cell(ws, row, 5, _money(item.total_price), money=True)
        row += 1

    totals = [
        ("Подытог", order.subtotal),
        ("Скидка", order.discount),
        ("Промокод", order.promo_code),
        ("Итог", order.total),
    ]
    row += 1
    for label, value in totals:
        label_cell = ws.cell(row=row, column=4, value=label)
        label_cell.font = Font(bold=True, size=11)
        label_cell.border = _BORDER
        money = isinstance(value, (int, float)) or hasattr(value, "quantize")
        _data_cell(ws, row, 5, _money(value) if money else value, money=money)
        row += 1
    return wb


def customers_workbook(rows: list[CustomerRow]) -> Workbook:
    """Клиентская база: покупатель, контакты, адреса из заказов, статистика."""
    wb = Workbook()
    headers = [
        "Имя", "Телефон", "Email", "Адреса доставки", "Заказов",
        "Сумма заказов, руб.", "Последний заказ", "В базе с", "Служебная заметка",
    ]
    widths = [20, 18, 24, 46, 9, 17, 16, 14, 30]
    ws = _sheet(wb, "Клиенты", headers, widths)
    for row_num, row in enumerate(rows, start=2):
        values = [
            row.customer.name,
            row.customer.phone,
            row.customer.email,
            "; ".join(row.addresses),
            row.orders_count,
            _money(row.total_spent),
            _fmt_datetime(row.last_order_at),
            _fmt_datetime(row.customer.created_at)[:10],
            row.customer.note,
        ]
        for col, value in enumerate(values, start=1):
            _data_cell(
                ws, row_num, col, value,
                money=col == 6,
                wrap=col in (4, 9),
            )
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"
    return wb


def excel_response(wb: Workbook, filename: str) -> HttpResponse:
    """HttpResponse с готовым файлом; кириллица в имени — через filename*."""
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    quoted = quote(filename)
    response["Content-Disposition"] = (
        f"attachment; filename=export.xlsx; filename*=UTF-8''{quoted}"
    )
    wb.save(response)
    return response


def export_filename(prefix: str) -> str:
    """Имя файла вида «заказы_20261109_1430.xlsx»."""
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    return f"{prefix}_{stamp}.xlsx"
