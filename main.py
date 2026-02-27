import os
import re
import time
import random
import signal
import logging
import asyncio
import hashlib
from typing import Optional, Dict, Any, List

import aiohttp
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ira-finance-bot")


# =========================
# CONFIG from ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SCRIPT_URL = os.getenv("SCRIPT_URL", "").strip()
WIFE_TG_ID = int(os.getenv("WIFE_TG_ID", "0").strip() or 0)

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not SCRIPT_URL:
    raise RuntimeError("SCRIPT_URL is missing")
if not WIFE_TG_ID:
    raise RuntimeError("WIFE_TG_ID is missing")


def _default_webhook_path() -> str:
    h = hashlib.sha256(BOT_TOKEN.encode("utf-8")).hexdigest()
    return f"tg/{h[:24]}"


# =========================
# [+] Persistent HTTP session
# =========================
_http_session: Optional[aiohttp.ClientSession] = None


async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
        logger.info("HTTP session created")
    return _http_session


async def close_http_session() -> None:
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        logger.info("HTTP session closed")


# =========================
# [+] Month summary cache
# =========================
_month_cache: Dict[str, Any] = {}
CACHE_TTL = 60


def _invalidate_month_cache() -> None:
    _month_cache.clear()


# =========================
# Dictionaries
# =========================
EXPENSES: Dict[str, List[str]] = {
    "Дети": [
        "Кружки и секции", "Карманные деньги", "Медицинские расходы", "Детский сад",
        "Одежда", "Повседневные траты", "Игрушки", "Другое"
    ],
    "Задолженности": [
        "Кредитные карты", "Образовательный кредит", "Другие кредиты",
        "Налоги (федеральные)", "Налоги (муниципальные)", "Другое"
    ],
    "Образование": ["Плата за образование", "Учебная литература", "Уроки музыки", "Другое"],
    "Развлечения": [
        "Книги", "Концерты", "Игры", "Хобби", "Кино", "Музыка", "Отдых на природе",
        "Фотографии", "Спорт", "Театр", "Телевидение", "Другое"
    ],
    "Повседневные расходы": [
        "Продукты", "Рестораны и кафе", "Средства гигиены", "Одежда",
        "Химчистка", "Косметические средства", "Подписки", "Другое"
    ],
    "Подарки": ["Подарки", "Благотворительность", "Другое"],
    "Здоровье": [
        "Обследования врачей/стоматолога/окулиста", "Услуги специалистов",
        "Лекарства", "Скорая помощь", "Другое"
    ],
    "Дом": [
        "Аренда/ипотека", "Налог на недвижимость", "Мебель", "Сад", "Товары для дома",
        "Обслуживание", "Ремонт", "Переезд", "Другое"
    ],
    "Страхование": [
        "Страхование автомобиля", "Медицинская страховка",
        "Страхование недвижимости", "Страхование жизни", "Другое"
    ],
    "Домашние животные": ["Корм", "Ветеринар", "Игрушки", "Товары для животных", "Другое"],
    "Техника": ["Домены и хостинг", "Онлайн-сервисы", "Устройства", "Программное обеспечение", "Другое"],
    "Транспорт": [
        "Топливо", "Платежи за автомобиль", "Ремонт", "Регистрация/водительские права",
        "Запчасти", "Общественный транспорт", "Такси и каршеринг"
    ],
    "Путешествия": ["Авиабилеты", "Отели", "Питание", "Транспорт", "Развлечения", "Другое"],
    "Услуги ЖКХ": [
        "Телефон", "Телевидение", "Интернет", "Электричество",
        "Отопление/газ", "Вода", "Вывоз мусора", "Другое"
    ],
    "Красота": ["Маникюр", "Педикюр", "Парикмахер", "Убирание волос", "Массаж", "Другое"],
}

INCOME_CATEGORIES = [
    "Муж", "Государство", "% по вкладам", "Возвраты", "Подарки", "Случайные доходы", "Продажи"
]


# =========================
# Phrases
# =========================
PH_EXP_CAT = [
    "На что потратилась, Иришка? 🙂",
    "Куда сегодня ушли денежки, Иришка?",
    "Что оплатили? Давай выберем категорию.",
    "Окей, рассказывай — что за трата?",
    "Давай зафиксируем: какая категория?",
    "Выбирай, на что это было 🙂",
    "На что записываем расход?",
    "Что купила? 🙂",
    "Куда улетели денежки? 🙂",
]
PH_EXP_SUB = [
    "*{cat}*, а точнее?",
    "Понял(а). А внутри *{cat}* — что именно?",
    "Уточним: *{cat}* → какой пункт?",
    "Что конкретно в *{cat}*?",
    "Окей, а точнее в *{cat}*?",
    "Выбери подкатегорию, пожалуйста.",
    "Какая подкатегория подходит лучше всего?",
    "В *{cat}* какой раздел?",
    "Давай точнее в рамках *{cat}*.",
    "Что именно из *{cat}*?",
]
PH_AMOUNT_EXP = [
    "И сколько там?",
    "Какая сумма?",
    "На сколько вышло?",
    "Сколько списалось?",
    "Сколько запишем?",
    "Окей, цифру скажи 🙂",
    "Сколько это стоило?",
    "Давай сумму.",
    "Сколько получилось?",
    "Ммм, и сколько там?",
]
PH_COMMENT_EXP = [
    "Да норм, это недорого! Добавишь коммент?",
    "Коммент добавим или пропускаем?",
    "Хочешь уточнение для себя? (необязательно)",
    "Добавим короткий коммент? 🙂",
    "Если есть деталь — напиши, если нет — пропускай.",
    "Коммент оставим? (можно пропустить)",
    "Одной фразой что это было? (или пропусти)",
    "Есть что дописать? 🙂",
    "Добавишь пояснение? (не обязательно)",
    "Оставим заметку? (если хочешь)",
]
PH_SAVED_EXP = [
    "Всё понял, записал ✅",
    "Готово ✅ Зафиксировал.",
    "Записано ✅ Спасибо.",
    "Есть ✅ Сохранил.",
    "Сделано ✅",
    "Принял ✅ Добавил в таблицу.",
    "Угу ✅ Зафиксировал.",
    "Окей ✅ Записал.",
    "Отлично ✅ Внес.",
    "Готово ✅",
]
PH_INC_CAT = [
    "Опачки, денежки! И кто такой добрый?",
    "Ого! Доходик пришёл 🙂 От кого?",
    "Денежки пришли — записываем. Кто источник?",
    "Супер! Откуда поступление?",
    "Окей, выбери источник дохода 🙂",
    "Поступление! Кто молодец?",
    "Доход! Давай категорию.",
    "Ну красота 🙂 Кто отправитель?",
    "Денежки прилетели. Откуда?",
    "Кто сегодня пополнил копилочку? 🙂",
]
PH_AMOUNT_INC = [
    "Ммм, и сколько там?",
    "И сколько пришло?",
    "Какая сумма?",
    "Сколько запишем?",
    "На сколько пополнились?",
    "Окей, цифру скажи 🙂",
    "Сколько поступило?",
    "Давай сумму.",
    "Сколько получилось?",
    "Сколько там денежек?",
]
PH_COMMENT_INC = [
    "Нормально так! Коммент оставишь?",
    "Хочешь добавить коммент? (необязательно)",
    "Добавим уточнение? (можно пропустить)",
    "Коммент напишешь? 🙂",
    "Если есть деталь — напиши, если нет — пропускай.",
    "Оставим заметку?",
    "Одной фразой — что это было? (или пропусти)",
    "Добавишь пояснение?",
    "Коммент нужен?",
    "Есть что уточнить? 🙂",
]
PH_SAVED_INC = [
    "Красотка, всё записал ✅",
    "Готово ✅ Записал поступление.",
    "Есть ✅ Сохранил.",
    "Отлично ✅ Зафиксировал.",
    "Принял ✅",
    "Сделано ✅",
    "Записано ✅",
    "Окей ✅ Всё занёс.",
    "Угу ✅ В таблице.",
    "Красота ✅",
]

DENY_TEXT = "Извини, доступ только для Иришки 🙂"


# =========================
# Conversation states
# =========================
(
    ST_MENU,
    ST_ADD_CHOOSE_TYPE,
    ST_EXP_CATEGORY,
    ST_EXP_SUBCATEGORY,
    ST_AMOUNT,
    ST_COMMENT,
    ST_INC_CATEGORY,
    ST_ANALYSIS_KIND,
    ST_ANALYSIS_PERIOD,
    ST_SET_BALANCE,
    ST_EDIT_SELECT,
    ST_EDIT_FIELD,
    ST_EDIT_VALUE,
) = range(13)


# =========================
# Helpers
# =========================
async def delete_working_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    msg_id = context.user_data.get("working_message_id")
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.debug(f"Couldn't delete message {msg_id}: {e}")
    context.user_data["working_message_id"] = None


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == WIFE_TG_ID)


# =========================
# Keyboards
# =========================
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Внести транзакцию", callback_data="menu:add")],
        [InlineKeyboardButton("📝 Скорректировать записи", callback_data="menu:edit")],
        [InlineKeyboardButton("📊 Анализ", callback_data="menu:analysis")],
        [InlineKeyboardButton("💰 Установить баланс", callback_data="menu:set_balance")],
    ])


def kb_choose_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➖ Затраты", callback_data="type:expense")],
        [InlineKeyboardButton("➕ Доход", callback_data="type:income")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:menu")],
    ])


def kb_expense_categories() -> InlineKeyboardMarkup:
    cats = list(EXPENSES.keys())
    rows = []
    row = []
    for i, c in enumerate(cats):
        row.append(InlineKeyboardButton(c, callback_data=f"expcat:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:choose_type")])
    return InlineKeyboardMarkup(rows)


def kb_expense_subcategories(cat: str) -> InlineKeyboardMarkup:
    subs = EXPENSES.get(cat, [])
    rows = []
    row = []
    for i, s in enumerate(subs):
        row.append(InlineKeyboardButton(s, callback_data=f"expsub:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:exp_cat")])
    return InlineKeyboardMarkup(rows)


def kb_income_categories() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, c in enumerate(INCOME_CATEGORIES):
        row.append(InlineKeyboardButton(c, callback_data=f"inccat:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:choose_type")])
    return InlineKeyboardMarkup(rows)


def kb_skip_comment() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустить", callback_data="comment:skip")],
    ])


def kb_analysis_kind() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➖ Затраты", callback_data="akind:expense")],
        [InlineKeyboardButton("➕ Доходы", callback_data="akind:income")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:menu")],
    ])


def kb_analysis_period() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сегодня", callback_data="aperiod:today")],
        [InlineKeyboardButton("В этом месяце", callback_data="aperiod:month")],
        [InlineKeyboardButton("В этом году", callback_data="aperiod:year")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:analysis_kind")],
    ])


def kb_edit_list(transactions: List[Dict]) -> InlineKeyboardMarkup:
    rows = []
    for tx in transactions:
        row_id = tx["row_id"]
        date_str = tx["date"][:10]
        tx_type = tx["type"]
        emoji = "➖" if tx_type == "расход" else "➕"
        cat = tx["category"]
        amt = tx["amount"]
        label = f"{emoji} {date_str} | {cat} | {amt:,.0f} ₽".replace(",", " ")
        rows.append([InlineKeyboardButton(label, callback_data=f"edit_row:{row_id}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:menu")])
    return InlineKeyboardMarkup(rows)


def kb_edit_field() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Изменить сумму", callback_data="edit_field:amount")],
        [InlineKeyboardButton("💬 Изменить комментарий", callback_data="edit_field:comment")],
        [InlineKeyboardButton("🗑 Удалить запись", callback_data="edit_field:delete")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:edit_list")],
    ])


# =========================
# Amount parsing
# =========================
def parse_amount(text: str) -> Optional[float]:
    if not text:
        return None
    s0 = text.strip().lower()

    mult = 1.0
    s = re.sub(r"\s+", "", s0)
    if s.endswith("к") or s.endswith("k"):
        mult = 1000.0
        s = s[:-1]

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        dec_pos = max(last_comma, last_dot)
        int_part = re.sub(r"[.,]", "", s[:dec_pos])
        frac_part = re.sub(r"[.,]", "", s[dec_pos + 1:])
        s = f"{int_part}.{frac_part}"
    elif has_comma and not has_dot:
        s = s.replace(",", ".")

    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        val = float(s) * mult
        if val < 0:
            return None
        return round(val, 2)
    except Exception:
        return None


# =========================
# GAS API  [+] persistent session + logging
# =========================
async def gas_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["user_id"] = WIFE_TG_ID
    cmd = payload.get("cmd", "?")
    logger.info("GAS >> cmd=%s %s", cmd, {k: v for k, v in payload.items() if k != "user_id"})

    session = await get_http_session()
    async with session.post(SCRIPT_URL, json=payload) as resp:
        txt = await resp.text()
        logger.info("GAS << cmd=%s status=%s body=%.400s", cmd, resp.status, txt)
        try:
            data = await resp.json(content_type=None)
        except Exception:
            logger.error("GAS non-json response: %s", txt)
            raise RuntimeError("GAS вернул не-JSON ответ")
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "GAS error")
        return data["data"]


async def month_screen_text() -> str:
    # [+] cache
    now = time.monotonic()
    if _month_cache.get("ts") and now - _month_cache["ts"] < CACHE_TTL:
        s = _month_cache["data"]
    else:
        s = await gas_request({"cmd": "summary_month"})
        _month_cache["data"] = s
        _month_cache["ts"] = now

    month = s.get("month_label", "Текущий месяц")
    exp = s.get("expenses", 0)
    inc = s.get("incomes", 0)
    bal = s.get("balance", 0)
    init_bal = s.get("initial_balance", 0)
    curr_bal = s.get("current_balance", 0)

    return (
        f"<b>{month}</b>\n"
        f"💰 Начальный баланс: <b>{init_bal:,.2f}</b> ₽\n"
        f"➖ Расходы: <b>{exp:,.2f}</b> ₽\n"
        f"➕ Доходы: <b>{inc:,.2f}</b> ₽\n"
        f"🟰 За месяц: <b>{bal:,.2f}</b> ₽\n"
        f"💵 Текущий баланс: <b>{curr_bal:,.2f}</b> ₽"
    ).replace(",", " ")


# =========================
# Handlers  — КОД 1-В-1 С ОРИГИНАЛОМ, кроме save_and_finish_
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    context.user_data.clear()

    txt = await month_screen_text()
    await update.message.reply_text(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)

    return ST_MENU


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(DENY_TEXT)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if q.data == "menu:add":
        await q.edit_message_text("Окей 🙂 Что вносим?", reply_markup=kb_choose_type())
        context.user_data["working_message_id"] = q.message.message_id
        return ST_ADD_CHOOSE_TYPE

    if q.data == "menu:edit":
        result = await gas_request({"cmd": "get_recent_transactions", "limit": 5})
        transactions = result.get("transactions", [])

        if not transactions:
            await q.answer("Нет записей для редактирования", show_alert=True)
            return ST_MENU

        await q.edit_message_text(
            "<b>📝 Выбери запись для редактирования:</b>",
            reply_markup=kb_edit_list(transactions),
            parse_mode=ParseMode.HTML
        )
        context.user_data["working_message_id"] = q.message.message_id
        context.user_data["edit_transactions"] = transactions
        return ST_EDIT_SELECT

    if q.data == "menu:analysis":
        await q.edit_message_text("Что посмотрим?", reply_markup=kb_analysis_kind())
        context.user_data["working_message_id"] = q.message.message_id
        return ST_ANALYSIS_KIND

    if q.data == "menu:set_balance":
        await q.edit_message_text(
            "Какой у тебя сейчас баланс? 💰\n\n"
            "Напиши сумму (например: 50000 или 50к)",
            parse_mode=ParseMode.HTML
        )
        context.user_data["working_message_id"] = q.message.message_id
        return ST_SET_BALANCE

    return ST_MENU


async def back_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "back:menu":
        await delete_working_message(context, update.effective_chat.id)
        txt = await month_screen_text()
        await update.effective_chat.send_message(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
        return ST_MENU

    if q.data == "back:choose_type":
        await q.edit_message_text("Окей 🙂 Что вносим?", reply_markup=kb_choose_type())
        return ST_ADD_CHOOSE_TYPE

    if q.data == "back:exp_cat":
        await q.edit_message_text(random.choice(PH_EXP_CAT), reply_markup=kb_expense_categories())
        return ST_EXP_CATEGORY

    if q.data == "back:analysis_kind":
        await q.edit_message_text("Что посмотрим?", reply_markup=kb_analysis_kind())
        return ST_ANALYSIS_KIND

    if q.data == "back:edit_list":
        transactions = context.user_data.get("edit_transactions", [])
        await q.edit_message_text(
            "<b>📝 Выбери запись для редактирования:</b>",
            reply_markup=kb_edit_list(transactions),
            parse_mode=ParseMode.HTML
        )
        return ST_EDIT_SELECT

    return ST_MENU


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.pop("tx", None)
    context.user_data["tx"] = {}

    if q.data == "type:expense":
        await q.edit_message_text(random.choice(PH_EXP_CAT), reply_markup=kb_expense_categories())
        return ST_EXP_CATEGORY

    if q.data == "type:income":
        await q.edit_message_text(random.choice(PH_INC_CAT), reply_markup=kb_income_categories())
        return ST_INC_CATEGORY

    return ST_ADD_CHOOSE_TYPE


async def expense_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    cats = list(EXPENSES.keys())
    idx = int(q.data.split(":")[1])
    cat = cats[idx]

    tx = context.user_data.get("tx", {})
    tx["type"] = "расход"
    tx["category"] = cat
    context.user_data["tx"] = tx

    msg = random.choice(PH_EXP_SUB).format(cat=cat)
    await q.edit_message_text(msg, reply_markup=kb_expense_subcategories(cat), parse_mode=ParseMode.MARKDOWN)
    return ST_EXP_SUBCATEGORY


async def expense_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tx = context.user_data.get("tx", {})
    cat = tx.get("category", "")
    subs = EXPENSES.get(cat, [])
    idx = int(q.data.split(":")[1])
    sub = subs[idx] if 0 <= idx < len(subs) else ""

    tx["subcategory"] = sub
    context.user_data["tx"] = tx

    prompt = random.choice(PH_AMOUNT_EXP) + "\n\nПримеры: <code>2500</code>, <code>2 500</code>, <code>2.500</code>, <code>2500,50</code>, <code>2к</code>"
    await q.edit_message_text(prompt, parse_mode=ParseMode.HTML)
    return ST_AMOUNT


async def income_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    idx = int(q.data.split(":")[1])
    cat = INCOME_CATEGORIES[idx]

    tx = context.user_data.get("tx", {})
    tx["type"] = "доход"
    tx["category"] = cat
    tx["subcategory"] = ""
    context.user_data["tx"] = tx

    prompt = random.choice(PH_AMOUNT_INC) + "\n\nПримеры: <code>2500</code>, <code>2 500</code>, <code>2.500</code>, <code>2500,50</code>, <code>2к</code>"
    await q.edit_message_text(prompt, parse_mode=ParseMode.HTML)
    return ST_AMOUNT


async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    amt = parse_amount(update.message.text)

    try:
        await update.message.delete()
    except Exception:
        pass

    if amt is None:
        await delete_working_message(context, update.effective_chat.id)
        msg = await update.effective_chat.send_message(
            "Не понял сумму 🙈\nНапиши, пожалуйста, например: 2500 / 2 500 / 2500,50 / 2к"
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_AMOUNT

    tx = context.user_data.get("tx", {})
    tx["amount"] = amt
    context.user_data["tx"] = tx

    work_msg_id = context.user_data.get("working_message_id")
    if work_msg_id:
        try:
            text = random.choice(PH_COMMENT_EXP) if tx.get("type") == "расход" else random.choice(PH_COMMENT_INC)
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=work_msg_id,
                text=text,
                reply_markup=kb_skip_comment()
            )
        except Exception:
            pass

    return ST_COMMENT


async def comment_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tx = context.user_data.get("tx", {})
    tx["comment"] = ""
    context.user_data["tx"] = tx

    await save_and_finish_(update, context)
    return ST_MENU


async def comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    try:
        await update.message.delete()
    except Exception:
        pass

    tx = context.user_data.get("tx", {})
    tx["comment"] = (update.message.text or "").strip()
    context.user_data["tx"] = tx

    await save_and_finish_(update, context)
    return ST_MENU


async def save_and_finish_(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранить транзакцию.
    [+] UX: удаляем рабочее сообщение → показываем 'Записано' → удаляем через 2 сек → главный экран.
    """
    await delete_working_message(context, update.effective_chat.id)

    tx = context.user_data.get("tx", {})
    payload = {
        "cmd": "add",
        "type": tx.get("type"),
        "category": tx.get("category"),
        "subcategory": tx.get("subcategory", ""),
        "amount": tx.get("amount"),
        "comment": tx.get("comment", ""),
    }

    # [+] инвалидируем кэш перед записью
    _invalidate_month_cache()

    await gas_request(payload)

    if tx.get("type") == "расход":
        header = random.choice(PH_SAVED_EXP)
        detail = f"{tx.get('category')} → {tx.get('subcategory')} — {tx.get('amount'):,.2f} ₽".replace(",", " ")
    else:
        header = random.choice(PH_SAVED_INC)
        detail = f"{tx.get('category')} — {tx.get('amount'):,.2f} ₽".replace(",", " ")

    comment = tx.get("comment", "").strip()
    if comment:
        detail += f"\nКоммент: {comment}"

    # [+] Показываем "Записано", через 2 сек удаляем, потом главный экран
    confirm_msg = await update.effective_chat.send_message(f"{header}\n{detail}")
    await asyncio.sleep(2)
    try:
        await confirm_msg.delete()
    except Exception:
        pass

    txt_month = await month_screen_text()
    await update.effective_chat.send_message(
        txt_month,
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )


async def analysis_kind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "akind:expense":
        context.user_data["analysis_kind"] = "расход"
        await q.edit_message_text("Окей 🙂 За какой период?", reply_markup=kb_analysis_period())
        return ST_ANALYSIS_PERIOD

    if q.data == "akind:income":
        context.user_data["analysis_kind"] = "доход"
        await q.edit_message_text("Окей 🙂 За какой период?", reply_markup=kb_analysis_period())
        return ST_ANALYSIS_PERIOD

    return ST_ANALYSIS_KIND


async def analysis_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    period = q.data.split(":")[1]
    kind = context.user_data.get("analysis_kind", "расход")

    res = await gas_request({"cmd": "analysis", "kind": kind, "period": period})

    label_map = {"today": "Сегодня", "month": "В этом месяце", "year": "В этом году"}
    kind_label = "Затраты" if kind == "расход" else "Доходы"

    total = res.get("total", 0)
    text = f"<b>{kind_label}</b> — <b>{label_map.get(period, period)}</b>\nСумма: <b>{total:,.2f}</b> ₽"
    text = text.replace(",", " ")

    await delete_working_message(context, update.effective_chat.id)
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML)

    txt = await month_screen_text()
    await update.effective_chat.send_message(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)

    return ST_MENU


async def set_balance_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    try:
        await update.message.delete()
    except Exception:
        pass

    amt = parse_amount(update.message.text)
    if amt is None or amt < 0:
        await delete_working_message(context, update.effective_chat.id)
        msg = await update.effective_chat.send_message(
            "Не понял сумму 🙈\nНапиши, пожалуйста, например: 50000 / 50 000 / 50к"
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_SET_BALANCE

    # [+] инвалидируем кэш
    _invalidate_month_cache()

    await gas_request({"cmd": "set_balance", "amount": amt})

    await delete_working_message(context, update.effective_chat.id)
    await update.effective_chat.send_message(
        f"Отлично! ✅ Начальный баланс установлен: <b>{amt:,.2f}</b> ₽".replace(",", " "),
        parse_mode=ParseMode.HTML
    )

    txt = await month_screen_text()
    await update.effective_chat.send_message(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)

    return ST_MENU


# =========================
# Edit handlers
# =========================
async def edit_select_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    row_id = int(q.data.split(":")[1])

    transactions = context.user_data.get("edit_transactions", [])
    selected_tx = None
    for tx in transactions:
        if tx["row_id"] == row_id:
            selected_tx = tx
            break

    if not selected_tx:
        await q.answer("Ошибка: запись не найдена", show_alert=True)
        return ST_EDIT_SELECT

    context.user_data["selected_transaction"] = selected_tx

    tx_type = selected_tx["type"]
    emoji = "➖" if tx_type == "расход" else "➕"
    date_str = selected_tx["date"][:16]
    cat = selected_tx["category"]
    subcat = selected_tx.get("subcategory", "")
    amt = selected_tx["amount"]
    comment = selected_tx.get("comment", "")

    text = (
        f"<b>{emoji} {tx_type.capitalize()}</b>\n"
        f"📅 {date_str}\n"
        f"📂 {cat}"
    )
    if subcat:
        text += f" → {subcat}"
    text += f"\n💰 {amt:,.2f} ₽".replace(",", " ")
    if comment:
        text += f"\n💬 {comment}"

    text += "\n\n<b>Что хочешь изменить?</b>"

    await q.edit_message_text(text, reply_markup=kb_edit_field(), parse_mode=ParseMode.HTML)
    return ST_EDIT_FIELD


async def edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    field = q.data.split(":")[1]
    context.user_data["edit_field"] = field

    selected_tx = context.user_data.get("selected_transaction", {})

    if field == "delete":
        row_id = selected_tx["row_id"]
        _invalidate_month_cache()
        await gas_request({"cmd": "delete_transaction", "row_id": row_id})

        await delete_working_message(context, update.effective_chat.id)
        await update.effective_chat.send_message("✅ Запись удалена")

        txt = await month_screen_text()
        await update.effective_chat.send_message(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
        return ST_MENU

    elif field == "amount":
        current_amt = selected_tx.get("amount", 0)
        await q.edit_message_text(
            f"Текущая сумма: <b>{current_amt:,.2f}</b> ₽\n\n"
            f"Введи новую сумму:\n"
            f"(например: 2500 / 2 500 / 2к)".replace(",", " "),
            parse_mode=ParseMode.HTML
        )
        return ST_EDIT_VALUE

    elif field == "comment":
        current_comment = selected_tx.get("comment", "")
        text = "Текущий комментарий: "
        if current_comment:
            text += f"<i>{current_comment}</i>"
        else:
            text += "<i>(пусто)</i>"
        text += "\n\nВведи новый комментарий:"

        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        return ST_EDIT_VALUE

    return ST_EDIT_FIELD


async def edit_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    try:
        await update.message.delete()
    except Exception:
        pass

    field = context.user_data.get("edit_field")
    selected_tx = context.user_data.get("selected_transaction", {})
    row_id = selected_tx["row_id"]

    if field == "amount":
        amt = parse_amount(update.message.text)
        if amt is None or amt <= 0:
            await delete_working_message(context, update.effective_chat.id)
            msg = await update.effective_chat.send_message(
                "Не понял сумму 🙈\nНапиши, пожалуйста, например: 2500 / 2 500 / 2к"
            )
            context.user_data["working_message_id"] = msg.message_id
            return ST_EDIT_VALUE

        _invalidate_month_cache()
        await gas_request({"cmd": "update_transaction", "row_id": row_id, "field": "amount", "value": amt})

        await delete_working_message(context, update.effective_chat.id)
        await update.effective_chat.send_message(
            f"✅ Сумма изменена на <b>{amt:,.2f}</b> ₽".replace(",", " "),
            parse_mode=ParseMode.HTML
        )

    elif field == "comment":
        comment = (update.message.text or "").strip()
        await gas_request({"cmd": "update_transaction", "row_id": row_id, "field": "comment", "value": comment})

        await delete_working_message(context, update.effective_chat.id)
        await update.effective_chat.send_message("✅ Комментарий изменен")

    txt = await month_screen_text()
    await update.effective_chat.send_message(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)

    return ST_MENU


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return
    await update.message.reply_text(
        "Кнопки внизу 🙂\n"
        "• Внести транзакцию\n"
        "• Скорректировать записи\n"
        "• Анализ\n"
        "• Установить баланс"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error: %s", context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Ой, что-то пошло не так 🙈 Попробуем ещё раз?")
    except Exception:
        pass


def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ST_MENU: [
                CallbackQueryHandler(on_menu, pattern=r"^menu:"),
            ],
            ST_ADD_CHOOSE_TYPE: [
                CallbackQueryHandler(choose_type, pattern=r"^type:"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_EXP_CATEGORY: [
                CallbackQueryHandler(expense_category, pattern=r"^expcat:\d+$"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_EXP_SUBCATEGORY: [
                CallbackQueryHandler(expense_subcategory, pattern=r"^expsub:\d+$"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_INC_CATEGORY: [
                CallbackQueryHandler(income_category, pattern=r"^inccat:\d+$"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received),
            ],
            ST_COMMENT: [
                CallbackQueryHandler(comment_skip, pattern=r"^comment:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, comment_received),
            ],
            ST_ANALYSIS_KIND: [
                CallbackQueryHandler(analysis_kind, pattern=r"^akind:"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_ANALYSIS_PERIOD: [
                CallbackQueryHandler(analysis_period, pattern=r"^aperiod:"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_SET_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_balance_received),
            ],
            ST_EDIT_SELECT: [
                CallbackQueryHandler(edit_select_row, pattern=r"^edit_row:\d+$"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_EDIT_FIELD: [
                CallbackQueryHandler(edit_field_selected, pattern=r"^edit_field:"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
            ],
            ST_EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value_received),
            ],
        },
        fallbacks=[CommandHandler("help", cmd_help)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_error_handler(error_handler)
    return app


def run():
    app = build_app()

    # [+] Graceful shutdown для Railway
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _shutdown(sig_name: str):
        logger.info("Received %s, shutting down...", sig_name)
        await app.stop()
        await app.shutdown()
        await close_http_session()
        loop.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.ensure_future(_shutdown(s.name)))
        except NotImplementedError:
            pass

    if WEBHOOK_URL:
        url_path = WEBHOOK_PATH or _default_webhook_path()
        full_webhook = f"{WEBHOOK_URL.rstrip('/')}/{url_path}"
        logger.info("Starting webhook on 0.0.0.0:%s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=url_path,
            webhook_url=full_webhook,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Starting polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run()
