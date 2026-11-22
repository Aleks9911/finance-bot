import os, json, re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

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

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💰 Сводка", callback_data="summary"),
         InlineKeyboardButton("📊 Бюджет", callback_data="budget")],
        [InlineKeyboardButton("🛒 Список покупок", callback_data="shopping"),
         InlineKeyboardButton("📤 Экспорт", callback_data="export")],
        [InlineKeyboardButton("📈 Отчёт за неделю", callback_data="report"),
         InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📌 Меню:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_data()
    user = get_user_data(data, user_id)

    if query.data == "summary":
        inc = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Расход")
        await query.message.reply_text(f"💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN")

    elif query.data == "budget":
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
        await query.message.reply_text(msg)

    elif query.data == "shopping":
        shopping = data.get("shopping", [])
        if not shopping:
            await query.message.reply_text("🛒 Список покупок пуст.\nДобавь: «купить хлеб молоко»")
        else:
            items = "\n".join(f"□ {i}" for i in shopping)
            await query.message.reply_text(f"🛒 Общий список покупок:\n{items}")

    elif query.data == "export":
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
        await query.message.reply_document(
            document=json_str.encode("utf-8"),
            filename="finance_export.json",
            caption="📄 Экспорт: расходы по пользователям + список покупок."
        )

    elif query.data == "report":
        txns = user["transactions"]
        now = datetime.now()
        week_ago = now.strftime("%d.%m.%Y")
        week_txns = [t for t in txns if t.get("date", "").startswith(now.strftime("%d.%m.%Y")[:7])]
        inc = sum(t.get("amount", 0) for t in week_txns if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in week_txns if t.get("type") == "Расход")
        cats = {}
        for t in week_txns:
            if t.get("type") == "Расход":
                cats[t.get("category", "Прочее")] = cats.get(t.get("category", "Прочее"), 0) + t.get("amount", 0)
        msg = f"📈 Отчёт за период:\n💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN\n"
        if cats:
            msg += "\nПо категориям:\n"
            for c, s in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                pct = (s / exp * 100) if exp > 0 else 0
                msg += f"  {c}: {s:.2f} BYN ({pct:.0f}%)\n"
        msg += f"\n💡 Топливо: {cats.get('Транспорт', 0):.2f} BYN"
        if exp > 0:
            daily = exp / max(len(week_txns), 1)
            msg += f"\n📉 Средний чек: {daily:.2f} BYN"
        await query.message.reply_text(msg)

    elif query.data == "help":
        await query.message.reply_text(
            "📖 Команды:\n\n"
            "Расходы: «хлеб 55 магнит»\n"
            "Доходы: «зарплата 2832»\n"
            "Список: «купить хлеб» / «список» / «купил хлеб»\n"
            "«сводка» / «бюджет» / «начать месяц»\n"
            "«/menu» — меню кнопок\n"
            "«/export» — скачать данные"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я финансовый помощник.\n\n"
        "Пиши расходы: «хлеб 55 магнит»\n"
        "Или нажми /menu для меню кнопок"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    data = load_data()

    if text.lower().startswith("купить"):
        items_raw = text[6:].strip()
        if items_raw.startswith(":"):
            items_raw = items_raw[1:].strip()
        items = [i.strip(",.") for i in items_raw.split() if i.strip(",.")]
        if not items:
            await update.message.reply_text("Что купить? Пример: «купить хлеб молоко»")
            return
        shopping = data.get("shopping", [])
        added = []
        for item in items:
            if item.lower() not in [i.lower() for i in shopping]:
                shopping.append(item)
                added.append(item)
        data["shopping"] = shopping
        save_data(data)
        if added:
            await update.message.reply_text(f"✅ Добавил: {', '.join(added)}")
        else:
            await update.message.reply_text("Это уже есть в списке!")
        return

    if text.lower().startswith("купил"):
        target = text[6:].strip().lower()
        shopping = data.get("shopping", [])
        if target == "всё":
            data["shopping"] = []
            save_data(data)
            await update.message.reply_text("✅ Всё куплено! Список пуст.")
            return
        found = None
        for item in shopping:
            if item.lower() == target:
                found = item
                break
        if found:
            shopping.remove(found)
            data["shopping"] = shopping
            save_data(data)
            reply = f"✅ Купил: {found}"
            if shopping:
                reply += f"\n🛒 Осталось: {', '.join(shopping)}"
            else:
                reply += "\nСписок пуст!"
            await update.message.reply_text(reply)
        else:
            await update.message.reply_text(f"«{target}» нет в списке.")
        return

    if text.lower() == "список":
        shopping = data.get("shopping", [])
        if not shopping:
            await update.message.reply_text("🛒 Список покупок пуст.\nДобавь: «купить хлеб молоко»")
        else:
            items = "\n".join(f"□ {i}" for i in shopping)
            await update.message.reply_text(f"🛒 Общий список покупок:\n{items}")
        return

    if text.lower() in ("сводка", "баланс", "итоги"):
        user = get_user_data(data, user_id)
        inc = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Доход")
        exp = sum(t.get("amount", 0) for t in user["transactions"] if t.get("type") == "Расход")
        await update.message.reply_text(f"💰 Доходы: {inc:.2f} BYN\n💸 Расходы: {exp:.2f} BYN\n📊 Баланс: {inc - exp:.2f} BYN")
        return

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

    if text.lower() == "начать месяц":
        user = get_user_data(data, user_id)
        user["period_start"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        user["transactions"] = []
        save_data(data)
        await update.message.reply_text("✅ Новый отчётный период начат! Твои данные обнулены.")
        return

    parsed = parse_message(text)
    if parsed["amount"] == 0:
        await update.message.reply_text("Не понял сумму. Пример: «хлеб 55»\nИли /menu")
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
    await update.message.reply_document(document=json_str.encode("utf-8"), filename="finance_export.json", caption="📄 Экспорт")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
