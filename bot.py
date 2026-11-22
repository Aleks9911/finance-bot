import os, json, re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set. Add it in Railway Variables!")
    exit(1)

USD_RATE = 3.0
DATA_FILE = "finance_bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"transactions": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_message(msg):
    msg = msg.strip()
    is_income = msg.lower().startswith(("доход", "зарплата", "получил", "аванс"))
    if is_income:
        msg = re.sub(r"^(доход|зарплата|получил|аванс)\s*", "", msg, flags=re.I)
    m = re.search(r"(\d[\d\s]*)(?:р|руб|₽|\$)?", msg)
    amount = 0
    if m:
        amount = float(m.group(1).replace(" ", ""))
        msg = msg.replace(m.group(0), "")
    s = re.search(r"(?:в|из|на)\s+([\w\- ]{2,30})", msg)
    shop = s.group(1).strip() if s else ""
    if s:
        msg = msg.replace(s.group(0), "")
    return {"type": "Доход" if is_income else "Расход", "amount": amount, "shop": shop, "description": msg.strip(",.").strip()}

CATS = {
    "Продукты": "хлеб молоко мясо овощи фрукты продукты еда магнит пятёрочка".split(),
    "Транспорт": "бензин топливо такси метро автобус проезд азс".split(),
    "Жильё/Коммуналка": "квартплата свет вода газ аренда жильё коммуналка".split(),
    "Здоровье": "аптека лекарства врач косметолог массаж".split(),
    "Развлечения": "кино кафе ресторан кофе подписка".split(),
    "Кредиты": "кредит рассрочка".split(),
}

def find_category(text):
    tl = text.lower()
    best, score = "Прочее", 0
    for cat, kws in CATS.items():
        for kw in kws:
            if kw in tl and len(kw) > score:
                best, score = cat, len(kw)
    return best

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я твой финансовый помощник.\n"
        "Пиши расходы: «хлеб 55 магнит»\n"
        "Команды: «сводка», «баланс»"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ("сводка", "баланс", "итоги"):
        data = load_data()
        inc = sum(t.get("amount", 0) for t in data["transactions"] if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in data["transactions"] if t.get("type") == "Расход")
        await update.message.reply_text(
            f"💰 Доходы: {inc:.2f} BYN\n"
            f"💸 Расходы: {exp:.2f} BYN\n"
            f"📊 Баланс: {inc - exp:.2f} BYN"
        )
        return

    parsed = parse_message(text)
    if parsed["amount"] == 0:
        await update.message.reply_text("Не понял сумму. Пример: «хлеб 55»")
        return

    cat = find_category(text)
    byn = parsed["amount"]
    usd = round(byn / USD_RATE, 2)

    data = load_data()
    data["transactions"].append({
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "type": parsed["type"],
        "category": cat,
        "amount": byn,
        "usd": usd,
        "shop": parsed["shop"],
        "description": parsed["description"],
    })
    save_data(data)

    inc = sum(t.get("amount", 0) for t in data["transactions"] if t.get("type") == "Доход")
    exp = sum(t.get("amount", 0) for t in data["transactions"] if t.get("type") == "Расход")
    await update.message.reply_text(
        f"✅ Записано!\n"
        f"{parsed['type']}: {cat}\n"
        f"{byn:.2f} BYN / {usd:.2f} USD\n"
        f"Баланс: {inc - exp:.2f} BYN"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
