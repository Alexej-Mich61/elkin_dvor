"""Сервис сессионной корзины.

В сессии хранятся только ID вариантов и количества ({variant_id: quantity})
и введённый промокод (строка-код). Цены, скидки и суммы не сохраняются:
содержимое корзины при каждом запросе строится заново по актуальным данным
каталога и промокодам через единый расчёт orders.services. Отдельная таблица
анонимных корзин в БД не используется — см. docs/architecture.md §4 и §8.

Здесь же живут все операции изменения корзины; views (views.py) отвечают
только за HTTP: формы, шаблоны, редиректы и выбор partial для HTMX.
"""
from dataclasses import dataclass
from decimal import Decimal

from orders.models import PROMO_CODE_PATTERN, PromoCode, normalize_promo_code
from orders.services import Totals, calculate_totals
from shop.models import ProductVariant

CART_SESSION_KEY = "cart"
# В сессии — только нормализованный код, не рассчитанная скидка.
CART_PROMO_SESSION_KEY = "cart_promo"

# Потолок количества одной позиции, когда складской учёт не ведётся
# (у варианта stock=0 — остаток не ограничен, доступность задаёт is_active).
MAX_LINE_QUANTITY = 100


def quantity_limit(variant):
    """Максимум варианта в корзине: фактический остаток, если он учитывается."""
    return variant.stock if variant.stock > 0 else MAX_LINE_QUANTITY


@dataclass
class CartLine:
    """Позиция корзины: вариант из БД + количество из сессии.

    variant равен None, если вариант удалили из каталога: такую позицию
    нельзя купить, но пользователь должен увидеть её и убрать сам.
    """

    variant: ProductVariant | None
    variant_id: int
    quantity: int
    is_available: bool

    @property
    def unit_price(self):
        return self.variant.price if self.is_available else Decimal("0")

    @property
    def total_price(self):
        return self.unit_price * self.quantity


@dataclass
class CartContents:
    """Актуальное представление корзины: позиции и суммы из текущего каталога.

    Суммы (подытог/скидка/итог) приходят из единого расчёта orders.services —
    корзина не дублирует денежную логику. Промокод с его статусом проверки
    доступен через promo/promo_error: невалидный сохранённый код не даёт
    скидку, но остаётся в сессии, чтобы пользователь видел причину."""
    lines: list[CartLine]
    totals: Totals

    @property
    def available_lines(self):
        return [line for line in self.lines if line.is_available]

    @property
    def has_unavailable(self):
        return any(not line.is_available for line in self.lines)

    @property
    def total_items(self):
        return sum(line.quantity for line in self.lines)

    @property
    def subtotal(self):
        return self.totals.subtotal

    @property
    def discount(self):
        return self.totals.discount

    @property
    def total(self):
        return self.totals.total

    @property
    def promo(self):
        return self.totals.promo

    @property
    def promo_applied(self):
        return self.totals.promo_applied

    @property
    def promo_error(self):
        return self.totals.promo_error


class Cart:
    """Корзина поверх request.session. Инкапсулирует формат хранения."""

    def __init__(self, session):
        self.session = session
        self._items = self._parse(session.get(CART_SESSION_KEY))

    @staticmethod
    def _parse(raw):
        """Разбирает сессионное содержимое и отсекает битые записи.

        Сессию можно править руками, поэтому формату доверять нельзя:
        оставляем только положительные целые ID и количества."""
        items = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                try:
                    variant_id, quantity = int(key), int(value)
                except (TypeError, ValueError):
                    continue
                if variant_id > 0 and quantity > 0:
                    items[variant_id] = quantity
        return items

    def _save(self):
        if self._items:
            self.session[CART_SESSION_KEY] = self._items
        else:
            # Пустой словарь не храним, чтобы сессия не разрасталась.
            self.session.pop(CART_SESSION_KEY, None)
        self.session.modified = True

    @property
    def items(self):
        """Копия содержимого {variant_id: quantity}."""
        return dict(self._items)

    def count(self):
        """Общее число товаров — для счётчика в шапке, без запросов к БД."""
        return sum(self._items.values())

    def add(self, variant, quantity=1):
        """Добавляет вариант, ограничивая суммарное количество остатком.

        Возвращает фактически установленное суммарное количество."""
        total = min(self._items.get(variant.pk, 0) + quantity, quantity_limit(variant))
        self._items[variant.pk] = total
        self._save()
        return total

    def set_quantity(self, variant_id, quantity):
        """Устанавливает количество; quantity <= 0 удаляет позицию."""
        if quantity <= 0:
            self._items.pop(variant_id, None)
        else:
            self._items[variant_id] = quantity
        self._save()

    def remove(self, variant_id):
        """Убирает позицию. Возвращает True, если позиция была в корзине."""
        existed = variant_id in self._items
        self._items.pop(variant_id, None)
        self._save()
        return existed

    def clear(self):
        self._items = {}
        self.session.pop(CART_PROMO_SESSION_KEY, None)
        self._save()

    # --- Промокод: в сессии только нормализованный код ---------------------

    @property
    def promo_code(self):
        """Нормализованный код из сессии или None (битые записи отсекаем)."""
        code = self.session.get(CART_PROMO_SESSION_KEY)
        if isinstance(code, str) and code.strip():
            return normalize_promo_code(code)
        return None

    def _load_promo(self):
        """Загружает промокод по коду из сессии; исчезнувший код игнорируется."""
        code = self.promo_code
        if code is None:
            return None
        return PromoCode.objects.filter(code=code).first()

    def apply_promo(self, raw_code):
        """Проверяет и сохраняет код в сессии.

        Возвращает (promo, error): при ошибке промокод в сессию не пишется.
        Бизнес-правила (активность, сроки, минимальная сумма) проверяются
        через единый расчёт по актуальному подытогу корзины."""
        code = normalize_promo_code(raw_code or "")
        if not PROMO_CODE_PATTERN.fullmatch(code):
            return None, "Код может состоять только из цифр и букв (русских или латинских)."
        promo = PromoCode.objects.filter(code=code).first()
        if promo is None:
            return None, "Такого промокода нет."

        totals = calculate_totals(self._available_line_pairs(), promo=promo)
        if totals.promo_error is not None:
            return None, totals.promo_error

        self.session[CART_PROMO_SESSION_KEY] = promo.code
        self.session.modified = True
        return promo, None

    def clear_promo(self):
        """Убирает промокод. Возвращает True, если код был в корзине."""
        existed = CART_PROMO_SESSION_KEY in self.session
        self.session.pop(CART_PROMO_SESSION_KEY, None)
        if existed:
            self.session.modified = True
        return existed

    def _available_line_pairs(self):
        """(цена, количество) доступных позиций — вход единого расчёта."""
        variants = {
            variant.pk: variant
            for variant in ProductVariant.objects.filter(
                pk__in=self._items.keys()
            ).select_related("product__category")
        }
        pairs = []
        for variant_id, quantity in self._items.items():
            variant = variants.get(variant_id)
            if (
                variant is not None
                and variant.is_active
                and variant.product.is_active
                and variant.product.category.is_active
            ):
                pairs.append((variant.price, quantity))
        return pairs

    def contents(self):
        """Строит актуальное представление: варианты загружаются из БД,
        неактивные или удалённые позиции помечаются недоступными; суммы и
        скидка считаются единым расчётом, промокод перепроверяется заново."""
        variants = {
            variant.pk: variant
            for variant in ProductVariant.objects.filter(
                pk__in=self._items.keys()
            ).select_related("product__category")
        }
        lines = []
        for variant_id, quantity in self._items.items():
            variant = variants.get(variant_id)
            is_available = (
                variant is not None
                and variant.is_active
                and variant.product.is_active
                and variant.product.category.is_active
            )
            lines.append(
                CartLine(
                    variant=variant,
                    variant_id=variant_id,
                    quantity=quantity,
                    is_available=is_available,
                )
            )
        # Стабильный порядок отображения независимо от порядка добавления.
        lines.sort(
            key=lambda line: (
                line.variant.product.name if line.variant else "",
                line.variant.size if line.variant else "",
            )
        )
        totals = calculate_totals(
            ((line.unit_price, line.quantity) for line in lines if line.is_available),
            promo=self._load_promo(),
        )
        return CartContents(lines=lines, totals=totals)
