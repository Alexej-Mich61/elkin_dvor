"""Общие контакты магазина — доступны в шапке, подвале и на главной всех страниц."""


def contacts(request):
    return {
        "SHOP_NAME": "Ёлкин двор",
        "SHOP_PHONE_DISPLAY": "+7 (918) 584-34-34",
        "SHOP_PHONE_TEL": "+79185843434",
        # TODO: заменить на реальный адрес Telegram-канала или бота магазина.
        "SHOP_TELEGRAM_URL": "https://t.me/elkin_dvor",
        "SHOP_WHATSAPP_URL": "https://wa.me/79185843434",
        "SHOP_ADDRESS": "г. Ростов-на-Дону, ул. Таганрогская, 140/4",
    }
