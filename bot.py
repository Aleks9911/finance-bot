import os, json, re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set!")
    exit(1)

USD_RATE = 3.0
DATA_FILE = "finance_bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"transactions": [], "shopping": [], "period_start": None}

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
    return {"type": "Доход" if is_income else "Расход", "amount": amount, "shop": shop, "description": msg.strip(",.").strip()}

CATS = {
    "Продукты": "хлеб молоко мясо овощи фрукты продукты еда магнит пятёрочка".split(),
    "Транспорт": "бензин топливо такси метро автобус проезд азс".split(),
    "Жильё/Коммуналка": "квартплата свет вода газ аренда жильё".split(),
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

async def start(update, context):
    await update.message.reply_text(
        "Привет! Я твой финансовый помощник.\n\n"
        "Расходы: «хлеб 55 магнит»\n"
        "Доходы: «зарплата 2832»\n"
        "Список покупок: «купить: хлеб яйца»\n"
        "Команды: сводка, бюджет, список, купил, /export, начать месяц")

async def handle_message(update, context):
    text = update.message.text.strip()

    # ---- Shopping: "купить: ..." ----
    if text.lower().startswith("купить:"):
        items = [i.strip() for i in text[7:].split() if i.strip()]
        if not items:
            await update.message.reply_text("Что купить? Пример: «купить: хлеб яйца»")
            return
        data = load_data()
        existing = data.get("shopping", [])
        for item in items:
            if item not in existing:
                existing.append(item)
        data["shopping"] = existing
        save_data(data)
        await update.message.reply_text(f"✅ Добавил: {', '.join(items)}")
        return

    # ---- Shopping: "купил ..." ----
    if text.lower().startswith("купил"):
        item = text[6:].strip().lower()
        data = load_data()
        shopping = data.get("shopping", [])
        if item == "всё":
            data["shopping"] = []
            save_data(data)
            await update.message.reply_text("✅ Всё куплено! Список пуст.")
            return
        if item in [i.lower() for i in shopping]:
            shopping = [i for i in shopping if i.lower() != item]
            data["shopping"] = shopping
            save_data(data)
            if shopping:
                await update.message.reply_text(f"✅ Вычеркнул: {item}\n🛒 Осталось: {', '.join(shopping)}")
            else:
                await update.message.reply_text("✅ Вычеркнул. Список пуст!")
        else:
            await update.message.reply_text(f"«{item}» нет в списке. Вот список: {', '.join(shopping) if shopping else 'пуст'}")
        return

    # ---- "список" ----
    if text.lower() == "список":
        data = load_data()
        shopping = data.get("shopping", [])
        if not shopping:
            await update.message.reply_text("🛒 Список покупок пуст.\nДобавь: «купить: хлеб яйца»")
        else:
            items = "\n".join(f"□ {i}" for i in shopping)
            await update.message.reply_text(f"🛒 Список покупок:\n{items}")
        return

    # ---- "бюджет" ----
    if text.lower() == "бюджет":
        data = load_data()
        period_start = data.get("period_start")
        txns = data["transactions"]
        if period_start:
            period_txns = [t for t in txns if t.get("date", "").startswith(period_start[:7])]
        else:
            period_txns = txns
        inc = sum(t.get("amount", 0) for t in period_txns if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in period_txns if t.get("type") == "Расход")
        cats = {}
        for t in period_txns:
            if t.get("type") == "Расход":
                cats[t.get("category", "Прочее")] = cats.get(t.get("category", "Прочее"), 0) + t.get("amount", 0)
        msg = f"📊 Бюджет{' с ' + period_start if period_start else ''}:\n💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN\n"
        if cats:
            msg += "\nПо категориям:\n"
            for c, s in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                msg += f"  {c}: {s:.2f} BYN\n"
        await update.message.reply_text(msg)
        return

    # ---- "сводка" / "баланс" / "итоги" ----
    if text.lower() in ("сводка", "баланс", "итоги"):
        data = load_data()
        inc = sum(t.get("amount", 0) for t in data["transactions"] if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in data["transactions"] if t.get("type") == "Расход")
        await update.message.reply_text(f"💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN")
        return

    # ---- "начать месяц" ----
    if text.lower() == "начать месяц":
        data = load_data()
        data["period_start"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        data["transactions"] = []
        data["shopping"] = []
        save_data(data)
        await update.message.reply_text("✅ Новый отчётный период начат! Все данные обнулены.")
        return

    # ---- Regular expense/income ----
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
    await update.message.reply_text(f"✅ Записано!\n{parsed['type']}: {cat}\n{byn:.2f} BYN / {usd:.2f} USD\nБаланс: {inc - exp:.2f} BYN")

async def export_command(update, context):
    data = load_data()
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    await update.message.reply_document(
        document=json_str.encode("utf-8"),
        filename="finance_data.json",
        caption="📄 Экспорт данных. Сохрани файл и пришли мне на почту / скинь в чат."
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
