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
    return {"users": {}, "shopping": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_data(data, user_id):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {"transactions": [], "period_start": None}
    return data["users"][uid]

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я общий финансовый помощник.\n\n"
        "Расходы: «хлеб 55 магнит»\n"
        "Доходы: «зарплата 2832»\n"
        "Список покупок (общий): «купить хлеб молоко»\n"
        "Команды: сводка, бюджет, список, купил, /export, начать месяц")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    data = load_data()

    # ---- Shopping: starts with "купить" ----
    if text.lower().startswith("купить"):
        items_raw = text[6:].strip()
        # Allow colon after "купить"
        if items_raw.startswith(":"):
            items_raw = items_raw[1:].strip()
        # Split by whitespace and remove empty + strip commas
        items = [i.strip(",.") for i in items_raw.split() if i.strip(",.")]
        if not items:
            await update.message.reply_text("Что купить? Пример: «купить хлеб молоко»")
            return
        shopping = data.get("shopping", [])
        added = []
        for item in items:
            item_lower = item.lower()
            if item_lower not in [i.lower() for i in shopping]:
                shopping.append(item)
                added.append(item)
        data["shopping"] = shopping
        save_data(data)
        if added:
            await update.message.reply_text(f"✅ Добавил: {', '.join(added)}")
        else:
            await update.message.reply_text("Это уже есть в списке!")
        return

    # ---- Shopping: "купил ..." ----
    if text.lower().startswith("купил"):
        target = text[6:].strip().lower()
        shopping = data.get("shopping", [])
        if target in ("всё", "все"):
            data["shopping"] = []
            save_data(data)
            await update.message.reply_text("✅ Всё куплено! Список пуст.")
            return
        # Match and remove (case insensitive)
        found = None
        for item in shopping:
            if item.lower() == target:
                found = item
                break
        if found:
            shopping.remove(found)
            data["shopping"] = shopping
            save_data(data)
            if shopping:
                await update.message.reply_text(f"✅ Купил: {found}\n🛒 Осталось: {', '.join(shopping)}")
            else:
                await update.message.reply_text(f"✅ Купил: {found}. Список пуст!")
        else:
            await update.message.reply_text(f"«{target}» нет в списке.")
        return

    # ---- "список" ----
    if text.lower() == "список":
        shopping = data.get("shopping", [])
        if not shopping:
            await update.message.reply_text("🛒 Список покупок пуст.\nДобавь: «купить хлеб молоко»")
        else:
            items = "\n".join(f"□ {i}" for i in shopping)
            await update.message.reply_text(f"🛒 Общий список покупок:\n{items}")
        return

    # ---- "сводка" / "баланс" / "итоги" ----
    if text.lower() in ("сводка", "баланс", "итоги"):
        user = get_user_data(data, user_id)
        inc = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Расход")
        await update.message.reply_text(f"💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN")
        return

    # ---- "бюджет" ----
    if text.lower() == "бюджет":
        user = get_user_data(data, user_id)
        ps = user.get("period_start")
        txns = user["transactions"]
        if ps:
            txns = [t for t in txns if t.get("date", "").startswith(ps[:7])]
        inc = sum(t.get("amount", 0) for t in txns if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in txns if t.get("type") == "Расход")
        cats = {}
        for t in txns:
            if t.get("type") == "Расход":
                cats[t.get("category", "Прочее")] = cats.get(t.get("category", "Прочее"), 0) + t.get("amount", 0)
        msg = f"📊 Бюджет{' с ' + ps if ps else ' (за всё время)'}:\n💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN\n"
        if cats:
            msg += "\nПо категориям:\n"
            for c, s in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                msg += f"  {c}: {s:.2f} BYN\n"
        await update.message.reply_text(msg)
        return

    # ---- "начать месяц" ----
    if text.lower() == "начать месяц":
        user = get_user_data(data, user_id)
        user["period_start"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        user["transactions"] = []
        save_data(data)
        await update.message.reply_text("✅ Новый отчётный период начат! Твои данные обнулены.")
        return

    # ---- Regular expense/income ----
    parsed = parse_message(text)
    if parsed["amount"] == 0:
        await update.message.reply_text("Не понял сумму. Пример: «хлеб 55»")
        return
    cat = find_category(text)
    byn = parsed["amount"]
    usd = round(byn / USD_RATE, 2)
    user = get_user_data(data, user_id)
    user["transactions"].append({
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "type": parsed["type"],
        "category": cat,
        "amount": byn,
        "usd": usd,
        "shop": parsed["shop"],
        "description": parsed["description"],
    })
    save_data(data)
    inc = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Доход")
    exp = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Расход")
    await update.message.reply_text(f"✅ Записано!\n{parsed['type']}: {cat}\n{byn:.2f} BYN / {usd:.2f} USD\nБаланс: {inc - exp:.2f} BYN")

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    users_info = {}
    all_txns = []
    for uid, uinfo in data.get("users", {}).items():
        uname = f"User {uid}"
        all_txns.extend({"user": uname, **t} for t in uinfo.get("transactions", []))
    
    export = {
        "export_date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "shopping_list": data.get("shopping", []),
        "transactions_by_user": {uid: uinfo.get("transactions", []) for uid, uinfo in data.get("users", {}).items()},
        "all_transactions": all_txns,
    }
    json_str = json.dumps(export, ensure_ascii=False, indent=2)
    await update.message.reply_document(
        document=json_str.encode("utf-8"),
        filename="finance_export.json",
        caption="📄 Экспорт: расходы по пользователям + общий список покупок."
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
