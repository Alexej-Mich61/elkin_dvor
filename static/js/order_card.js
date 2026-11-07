/* Карточка заказа: кнопка «Скачать» на странице подтверждения рисует
   изображение с данными заказа через canvas и скачивает его как PNG.
   Данные берутся из <script type="application/json" id="order-card-data">,
   повторных запросов к серверу нет. */
(function () {
    "use strict";

    var dataNode = document.getElementById("order-card-data");
    var button = document.getElementById("download-order-card");
    if (!dataNode || !button) {
        return;
    }

    var data;
    try {
        data = JSON.parse(dataNode.textContent);
    } catch (e) {
        button.disabled = true;
        return;
    }

    // Фирменная палитра (theme/static_src/src/styles.css).
    var PINE = "#0d3b26";
    var CREAM = "#f6f2e9";
    var CRIMSON = "#b3122e";
    var INK = "#201d1a";
    var MUTED = "#6b6257";

    var FONT = '"Nunito", "Segoe UI", system-ui, sans-serif';
    var W = 1080;
    var MARGIN = 64;
    var CONTENT_W = W - MARGIN * 2;

    function formatMoney(value) {
        var amount = Number(value);
        if (!isFinite(amount)) {
            return String(value);
        }
        var fixed = amount.toFixed(2);
        var hasCents = fixed.slice(-2) !== "00";
        var text = hasCents ? fixed : String(Math.round(amount));
        // Разбиваем целую часть тонкими пробелами, копейки через запятую.
        var parts = text.split(".");
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
        return hasCents ? parts.join(",") : parts[0];
    }

    // Перенос строки по словам с ограничением ширины (ctx.measureText).
    function wrapText(ctx, text, maxWidth) {
        var words = String(text).split(/\s+/);
        var lines = [];
        var line = "";
        words.forEach(function (word) {
            var candidate = line ? line + " " + word : word;
            if (ctx.measureText(candidate).width <= maxWidth) {
                line = candidate;
            } else {
                if (line) {
                    lines.push(line);
                }
                line = word;
            }
        });
        if (line) {
            lines.push(line);
        }
        return lines.length ? lines : [""];
    }

    function roundRect(ctx, x, y, width, height, radius) {
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.arcTo(x + width, y, x + width, y + height, radius);
        ctx.arcTo(x + width, y + height, x, y + height, radius);
        ctx.arcTo(x, y + height, x, y, radius);
        ctx.arcTo(x, y, x + width, y, radius);
        ctx.closePath();
    }

    // Геометрия карточки: константы дублируют шаги draw(), чтобы высота
    // холста всегда вмещала весь контент включая переносы и скидку.
    var ITEMS_START_Y = 340;
    var ROW_GAP = 28;
    var DIVIDER_OFFSET = 8 + 56;          /* отступ + линия перед итогами */
    var TOTALS_HEIGHT = 52 + 62;          /* «Итого» + «Оплата при получении» */
    var DISCOUNT_HEIGHT = 48 + 56;        /* строки подытога и скидки */
    var RECEIVER_HEIGHT = 42;             /* имя и телефон получателя */
    var ADDRESS_LINE_HEIGHT = 38;         /* строка адреса с переносом */
    var FOOTER_OFFSET = 6 + 76;           /* отступ + плашка с телефоном */

    // Высота карточки считается до отрисовки: позиции с переносами + итоги
    // + контакты доставки + подвал.
    function measureHeight(ctx, rowHeights, hasDiscount) {
        var addressLines = wrapText(ctx, data.address || "", CONTENT_W).length;
        var height = ITEMS_START_Y;
        rowHeights.forEach(function (h) {
            height += h + ROW_GAP;
        });
        height += DIVIDER_OFFSET;
        if (hasDiscount) {
            height += DISCOUNT_HEIGHT;
        }
        height += TOTALS_HEIGHT;
        height += RECEIVER_HEIGHT;
        height += addressLines * ADDRESS_LINE_HEIGHT;
        height += FOOTER_OFFSET;
        return height + MARGIN;
    }

    function draw() {
        var canvas = document.createElement("canvas");
        var ctx = canvas.getContext("2d");
        if (!ctx) {
            return null;
        }

        ctx.font = "600 34px " + FONT;

        // Высоты строк позиций (перенос названия).
        var rows = (data.items || []).map(function (item) {
            var title = item.name + " · " + item.size + " × " + item.quantity;
            var titleLines = wrapText(ctx, title, CONTENT_W - 260);
            return {
                titleLines: titleLines,
                total: formatMoney(item.total_price) + " руб.",
                height: Math.max(titleLines.length * 44, 44)
            };
        });

        canvas.width = W;
        canvas.height = measureHeight(
            ctx,
            rows.map(function (r) { return r.height; }),
            (Number(data.discount) || 0) > 0
        );

        // Фон.
        ctx.fillStyle = CREAM;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Шапка: тёмно-зелёная плашка.
        ctx.fillStyle = PINE;
        ctx.fillRect(0, 0, W, 190);
        ctx.textBaseline = "alphabetic";

        ctx.fillStyle = "#ffffff";
        ctx.font = "800 30px " + FONT;
        ctx.fillText(data.shop || "Ёлкин двор", MARGIN, 66);

        ctx.font = "900 64px " + FONT;
        ctx.fillText("Заказ оформлен", MARGIN, 140);

        // Номер заказа и дата.
        ctx.fillStyle = CRIMSON;
        ctx.font = "900 48px " + FONT;
        ctx.fillText("№ " + data.number, MARGIN, 268);

        ctx.fillStyle = MUTED;
        ctx.font = "600 30px " + FONT;
        var dateWidth = ctx.measureText(data.date).width;
        ctx.fillText(data.date, W - MARGIN - dateWidth, 268);

        // Позиции.
        var y = 340;
        rows.forEach(function (row) {
            ctx.fillStyle = INK;
            ctx.font = "700 34px " + FONT;
            row.titleLines.forEach(function (line, index) {
                ctx.fillText(line, MARGIN, y + index * 44);
            });
            ctx.font = "800 34px " + FONT;
            var totalWidth = ctx.measureText(row.total).width;
            ctx.fillText(row.total, W - MARGIN - totalWidth, y);
            y += row.height + 28;
        });

        // Разделитель перед итогами.
        y += 8;
        ctx.strokeStyle = "#ddd2b8";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(MARGIN, y);
        ctx.lineTo(W - MARGIN, y);
        ctx.stroke();
        y += 56;

        // Итоги.
        ctx.font = "600 32px " + FONT;
        var discount = Number(data.discount) || 0;
        if (discount > 0) {
            ctx.fillStyle = MUTED;
            ctx.fillText("Товары", MARGIN, y);
            var subtotal = formatMoney(data.subtotal) + " руб.";
            ctx.fillText(subtotal, W - MARGIN - ctx.measureText(subtotal).width, y);
            y += 48;

            ctx.fillStyle = "#15803d";
            var promoLabel = data.promo_code
                ? "Скидка по промокоду " + data.promo_code
                : "Скидка";
            ctx.fillText(promoLabel, MARGIN, y);
            var discountText = "−" + formatMoney(data.discount) + " руб.";
            ctx.fillText(discountText, W - MARGIN - ctx.measureText(discountText).width, y);
            y += 56;
        }

        ctx.fillStyle = INK;
        ctx.font = "900 46px " + FONT;
        ctx.fillText("Итого", MARGIN, y);
        var total = formatMoney(data.total) + " руб.";
        ctx.fillText(total, W - MARGIN - ctx.measureText(total).width, y);
        y += 52;

        ctx.fillStyle = MUTED;
        ctx.font = "600 28px " + FONT;
        ctx.fillText("Оплата наличными при получении", MARGIN, y);
        y += 62;

        // Контакты получателя.
        ctx.fillStyle = INK;
        ctx.font = "700 30px " + FONT;
        var receiver = (data.name || "") + " · " + (data.phone || "");
        ctx.fillText(receiver, MARGIN, y);
        y += 42;
        ctx.fillStyle = MUTED;
        ctx.font = "600 28px " + FONT;
        wrapText(ctx, data.address || "", CONTENT_W).forEach(function (line) {
            ctx.fillText(line, MARGIN, y);
            y += 38;
        });

        // Подвал: телефон магазина.
        y += 6;
        ctx.fillStyle = PINE;
        roundRect(ctx, MARGIN, y, CONTENT_W, 76, 20);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.font = "800 30px " + FONT;
        var footer = (data.shop || "Ёлкин двор") + " · " + (data.shop_phone || "");
        var footerWidth = ctx.measureText(footer).width;
        ctx.fillText(footer, MARGIN + (CONTENT_W - footerWidth) / 2, y + 50);

        return canvas;
    }

    button.addEventListener("click", function () {
        var canvas = draw();
        if (!canvas) {
            return;
        }
        canvas.toBlob(function (blob) {
            if (!blob) {
                return;
            }
            var url = URL.createObjectURL(blob);
            var link = document.createElement("a");
            link.href = url;
            link.download = "zakaz-" + (data.number || "order") + ".png";
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        }, "image/png");
    });
})();
