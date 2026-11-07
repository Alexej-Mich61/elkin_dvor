from decimal import Decimal

from orders.models import PromoCode

PromoCode.objects.all().delete()
promos = [
    dict(code="ЕЛКА10", discount_type="percent", discount_value=Decimal("10")),
    dict(code="НОВЫЙГОД500", discount_type="fixed", discount_value=Decimal("500")),
    dict(code="БОЛЬШОЙ3000", discount_type="fixed", discount_value=Decimal("3000"),
         min_order_total=Decimal("50000")),
]
for params in promos:
    obj, created = PromoCode.objects.get_or_create(code=params["code"], defaults=params)
    print(("created" if created else "exists "), repr(obj.code))
