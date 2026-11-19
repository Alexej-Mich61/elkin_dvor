"""Общие контакты магазина — доступны в шапке, подвале и на главной всех страниц.

SHOP_CONTACTS — единый источник контактов: context processor отдаёт его
шаблонам, а письма (orders/emails.py) используют те же значения.
"""

SHOP_CONTACTS = {
    "SHOP_NAME": "Ёлкин двор",
    "SHOP_PHONE_DISPLAY": "+7 (918) 584-34-34",
    "SHOP_PHONE_TEL": "+79185843434",
    # TODO: заменить на реальный адрес Telegram-канала или бота магазина.
    "SHOP_TELEGRAM_URL": "https://t.me/elkin_dvor",
    # TODO: заменить заглушку на реальный код профиля MAX.
    "SHOP_MAX_URL": "https://max.ru/u/ваш-код-профиля",
    "SHOP_ADDRESS": "г. Ростов-на-Дону, ул. Таганрогская, 140/4",
}


def contacts(request):
    return dict(SHOP_CONTACTS)
