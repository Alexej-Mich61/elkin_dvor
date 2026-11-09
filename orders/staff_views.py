"""Staff-страницы менеджера и администратора (этап 7).

Views тонкие: фильтры/поиск/статистика/пагинация — orders.staff_services,
Excel-файлы — orders.exports. Здесь — только HTTP: разбор запроса, вызов
сервисов, выбор шаблона (полный или HTMX-partial), редиректы и статусы.

Доступ: авторизованный + is_staff + соответствующее разрешение модели.
Группа «Менеджер» наполняется командой ensure_manager_group (см. AGENTS.md).
"""
import functools

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import OrderEditForm, OrderFilterForm
from .models import Customer, Order
from . import exports, staff_services

# Имя HTMX-события: страница слушает его и перезагружает список —
# так после правки/удаления/смены статуса остаются актуальными и фильтры,
# и статистика, и сама строка (например, ушла из выборки по статусу).
HX_TRIGGER_RELOAD = "staff:reload"


def staff_permission_required(perm):
    """Декоратор доступа: авторизован + is_staff + разрешение perm."""

    def decorator(view):
        @login_required
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_staff:
                raise PermissionDenied
            if not request.user.has_perm(perm):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def _query_without_page(request) -> str:
    """Текущий querystring без параметра page (для ссылок пагинации/экспорта)."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _filters_from_form(form: OrderFilterForm) -> staff_services.OrderFilters:
    """Очищенные данные формы -> объект фильтра для сервиса."""
    cd = form.cleaned_data
    return staff_services.OrderFilters(
        date_from=cd["date_from"],
        date_to=cd["date_to"],
        status=cd["status"] or "",
        category_id=cd["category"].pk if cd["category"] else None,
        promo=cd["promo"] or "",
        search=(cd["search"] or "").strip(),
    )


def _reload_response() -> HttpResponse:
    """Ответ HTMX: ничего не свопать, только событие перезагрузки списка."""
    response = HttpResponse(status=204)
    response["HX-Trigger"] = HX_TRIGGER_RELOAD
    return response


# --- Заказы -------------------------------------------------------------------

@staff_permission_required("orders.view_order")
def orders_list(request):
    """Список заказов: фильтры, статистика, пагинация, модальные окна."""
    form = OrderFilterForm(request.GET or None)
    filters = staff_services.OrderFilters()
    if form.is_valid():
        filters = _filters_from_form(form)

    orders, total_found = staff_services.filter_orders(filters)
    stats = staff_services.summarize_orders(orders, total_found, filters)
    page = staff_services.paginate(
        orders, request.GET.get("page"), staff_services.ORDERS_PER_PAGE
    )

    query = _query_without_page(request)
    export_url = reverse("orders:staff_orders_export")
    if query:
        export_url = f"{export_url}?{query}"

    return render(
        request,
        "orders/staff/orders_list.html",
        {
            "filter_form": form,
            "page": page,
            "stats": stats,
            "status_choices": Order.STATUS_CHOICES,
            "export_url": export_url,
            "query": query,
        },
    )


@staff_permission_required("orders.view_order")
def order_detail(request, pk: int):
    """Контент модального окна «Просмотр» (HTMX-фрагмент, без редактирования)."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items"), pk=pk
    )
    return render(
        request,
        "orders/staff/partials/order_detail.html",
        {"order": order},
    )


@staff_permission_required("orders.change_order")
def order_edit(request, pk: int):
    """Модальное окно «Редактирование»: GET — форма, POST — сохранение.

    Успех — 204 + событие перезагрузки списка; ошибки валидации —
    фрагмент с формой и статусом 422 (swap разрешён в htmx-config)."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items"), pk=pk
    )
    if request.method == "POST":
        form = OrderEditForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            return _reload_response()
        status = 422
    else:
        form = OrderEditForm(instance=order)
        status = 200
    return render(
        request,
        "orders/staff/partials/order_form.html",
        {"form": form, "order": order},
        status=status,
    )


@staff_permission_required("orders.change_order")
@require_POST
def order_status(request, pk: int):
    """Быстрая смена статуса прямо в списке (select с hx-post)."""
    order = get_object_or_404(Order, pk=pk)
    status = request.POST.get("status", "")
    if status not in dict(Order.STATUS_CHOICES):
        return HttpResponse(status=400)
    order.status = status
    order.save(update_fields=["status", "updated_at"])
    return _reload_response()


@staff_permission_required("orders.delete_order")
@require_POST
def order_delete(request, pk: int):
    """Удаление заказа из списка (с окном-подтверждением). Обычный POST:
    после удаления — возврат на список, фильтры берём из скрытого next."""
    order = get_object_or_404(Order, pk=pk)
    order.delete()
    next_url = request.POST.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("orders:staff_orders")


@staff_permission_required("orders.view_order")
def orders_export(request):
    """Excel со списком заказов: ровно тот набор, что виден на экране
    (с фильтрами/поиском; без них — последние 100)."""
    form = OrderFilterForm(request.GET or None)
    filters = _filters_from_form(form) if form.is_valid() else staff_services.OrderFilters()
    orders, _ = staff_services.filter_orders(filters)
    wb = exports.orders_workbook(orders)
    return exports.excel_response(wb, exports.export_filename("заказы"))


@staff_permission_required("orders.view_order")
def order_export(request, pk: int):
    """Excel с подробными сведениями об одном заказе (кнопка в окне просмотра)."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items"), pk=pk
    )
    wb = exports.order_workbook(order)
    safe_number = order.number.replace("/", "-")
    return exports.excel_response(wb, f"заказ_{safe_number}.xlsx")


# --- Клиентская база -----------------------------------------------------------

@staff_permission_required("orders.view_customer")
def customers_list(request):
    """Список покупателей: контакты, адреса из заказов, статистика, поиск."""
    search = (request.GET.get("q") or "").strip()[:100]

    rows, total_found = staff_services.get_customer_rows(search)
    stats = staff_services.summarize_customers(rows, total_found, search)
    page = staff_services.paginate(
        rows, request.GET.get("page"), staff_services.CUSTOMERS_PER_PAGE
    )

    query = _query_without_page(request)
    export_url = reverse("orders:staff_customers_export")
    if query:
        export_url = f"{export_url}?{query}"

    return render(
        request,
        "orders/staff/customers_list.html",
        {
            "page": page,
            "stats": stats,
            "search": search,
            "export_url": export_url,
            "export_all_url": reverse("orders:staff_customers_export_all"),
            "query": query,
        },
    )


@staff_permission_required("orders.view_customer")
def customers_export(request):
    """Excel с отфильтрованным набором покупателей (как на экране)."""
    search = (request.GET.get("q") or "").strip()[:100]
    rows, _ = staff_services.get_customer_rows(search)
    wb = exports.customers_workbook(rows)
    return exports.excel_response(wb, exports.export_filename("клиенты"))


@staff_permission_required("orders.view_customer")
def customers_export_all(request):
    """Excel со всей клиентской базой — без фильтров и без лимита."""
    rows = staff_services.build_customer_rows(Customer.objects.all())
    wb = exports.customers_workbook(rows)
    return exports.excel_response(wb, exports.export_filename("клиенты_все"))
