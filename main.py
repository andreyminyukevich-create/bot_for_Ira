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
# Persistent HTTP session
# =========================
_http_session: Optional[aiohttp.ClientSession] = None


async def get_http_session() -> aiohttp.ClientSession:
    """Возвращает единую сессию, пересоздаёт если закрыта."""
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=15)
        _http_session = aiohttp.ClientSession(timeout=timeout)
        logger.info("HTTP session created")
    return _http_session


async def close_http_session() -> None:
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        logger.info("HTTP session closed")


# =========================
# Month summary cache (60 sec)
# =========================
_month_cache: Dict[str, Any] = {}
CACHE_TTL = 60  # секунд


def _invalidate_month_cache() -> None:
    _month_cache.clear()


async def _fetch_month_summary() -> Dict[str, Any]:
    now = time.monotonic()
    if _month_cache.get("ts") and now - _month_cache["ts"] < CACHE_TTL:
        return _month_cache["data"]
    data = await gas_request({"cmd": "summary_month"})
    _month_cache["data"] = data
    _month_cache["ts"] = now
    return data


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
    "<b>{cat}</b>, а точнее?",
    "Понял. А внутри <b>{cat}</b> — что именно?",
    "Уточним: <b>{cat}</b> → какой пункт?",
    "Что конкретно в <b>{cat}</b>?",
    "Окей, а точнее в <b>{cat}</b>?",
    "Выбери подкатегорию, пожалуйста.",
    "Какая подкатегория подходит лучше всего?",
    "В <b>{cat}</b> какой раздел?",
    "Давай точнее в рамках <b>{cat}</b>.",
    "Что именно из <b>{cat}</b>?",
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
    "Записала! Добавишь коммент?",
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
    "Записано ✅",
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
GAS_ERROR_TEXT = "Не получилось связаться с таблицей 🙈 Попробуй ещё раз."


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
async def delete_working_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    msg_id = context.user_data.get("working_message_id")
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.debug(f"Couldn't delete message {msg_id}: {e}")
    context.user_data["working_message_id"] = None


def reset_dialog(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сбрасывает состояние диалога при ошибке."""
    for key in ("tx", "edit_transactions", "selected_transaction", "edit_field", "analysis_kind", "working_message_id"):
        context.user_data.pop(key, None)


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == WIFE_TG_ID)


async def typing(update: Update) -> None:
    """Показывает индикатор 'печатает...' пока идёт запрос к GAS."""
    try:
        from telegram.constants import ChatAction
        await update.effective_chat.send_chat_action(ChatAction.TYPING)
    except Exception:
        pass


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
        emoji = "➖" if tx["type"] == "расход" else "➕"
        label = f"{emoji} {date_str} | {tx['category']} | {tx['amount']:,.0f} ₽".replace(",", " ")
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
    s = re.sub(r"\s+", "", text.strip().lower())
    mult = 1.0
    if s.endswith("к") or s.endswith("k"):
        mult = 1000.0
        s = s[:-1]

    has_comma = "," in s
    has_dot = "." in s
    if has_comma and has_dot:
        dec_pos = max(s.rfind(","), s.rfind("."))
        int_part = re.sub(r"[.,]", "", s[:dec_pos])
        frac_part = re.sub(r"[.,]", "", s[dec_pos + 1:])
        s = f"{int_part}.{frac_part}"
    elif has_comma:
        s = s.replace(",", ".")

    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        val = float(s) * mult
        return round(val, 2) if val > 0 else None
    except Exception:
        return None


# =========================
# GAS API
# =========================
async def gas_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["user_id"] = WIFE_TG_ID
    cmd = payload.get("cmd", "?")
    logger.info("GAS >> cmd=%s payload=%s", cmd, {k: v for k, v in payload.items() if k != "user_id"})
    session = await get_http_session()
    try:
        async with session.post(SCRIPT_URL, json=payload) as resp:
            txt = await resp.text()
            logger.info("GAS << cmd=%s status=%s body=%.300s", cmd, resp.status, txt)
            try:
                data = await resp.json(content_type=None)
            except Exception:
                logger.error("GAS non-json response cmd=%s: %s", cmd, txt)
                raise RuntimeError("GAS вернул не-JSON ответ")
            if not data.get("ok"):
                err = data.get("error") or "GAS error"
                logger.error("GAS error cmd=%s: %s", cmd, err)
                raise RuntimeError(err)
            return data["data"]
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("GAS request failed cmd=%s: %s", cmd, e)
        raise


async def month_screen_text() -> str:
    s = await _fetch_month_summary()
    return (
        f"<b>{s.get('month_label', 'Текущий месяц')}</b>\n"
        f"💰 Начальный баланс: <b>{s.get('initial_balance', 0):,.2f}</b> ₽\n"
        f"➖ Расходы: <b>{s.get('expenses', 0):,.2f}</b> ₽\n"
        f"➕ Доходы: <b>{s.get('incomes', 0):,.2f}</b> ₽\n"
        f"📊 Баланс месяца: <b>{s.get('balance', 0):,.2f}</b> ₽\n"
        f"💳 Текущий баланс: <b>{s.get('current_balance', 0):,.2f}</b> ₽"
    ).replace(",", " ")


async def safe_month_text() -> Optional[str]:
    """Возвращает текст экрана месяца или None при ошибке."""
    try:
        return await month_screen_text()
    except Exception:
        logger.warning("Could not fetch month summary")
        return None


# =========================
# Handlers
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    month_txt = await safe_month_text()
    body = f"Привет, Иришка! 🙂\n\n{month_txt}" if month_txt else f"Привет, Иришка! 🙂\n\n{GAS_ERROR_TEXT}"
    await update.message.reply_text(body, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    return ST_MENU


async def handle_text_in_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    month_txt = await safe_month_text()
    body = f"Используй кнопки ниже 🙂\n\n{month_txt}" if month_txt else "Используй кнопки ниже 🙂"
    await update.message.reply_text(body, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    return ST_MENU


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action = q.data.split(":")[1]

    if action == "add":
        await q.edit_message_text("Что вносим?", reply_markup=kb_choose_type())
        return ST_ADD_CHOOSE_TYPE

    elif action == "edit":
        await typing(update)
        try:
            result = await gas_request({"cmd": "get_recent_transactions", "limit": 10})
        except Exception:
            logger.exception("on_menu edit: GAS error")
            await q.edit_message_text(GAS_ERROR_TEXT, reply_markup=kb_main())
            return ST_MENU

        transactions = result.get("transactions", [])
        if not transactions:
            await q.answer("Записей пока нет", show_alert=True)
            return ST_MENU

        context.user_data["edit_transactions"] = transactions
        await q.edit_message_text(
            "<b>Последние записи:</b>\n\nВыбери что исправить:",
            reply_markup=kb_edit_list(transactions),
            parse_mode=ParseMode.HTML
        )
        return ST_EDIT_SELECT

    elif action == "analysis":
        await q.edit_message_text("Что анализируем?", reply_markup=kb_analysis_kind())
        return ST_ANALYSIS_KIND

    elif action == "set_balance":
        await q.edit_message_text("Окей, напиши текущий баланс (число):")
        return ST_SET_BALANCE

    return ST_MENU


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tx_type = q.data.split(":")[1]
    context.user_data["tx"] = {"type": "расход" if tx_type == "expense" else "доход"}

    if tx_type == "expense":
        await q.edit_message_text(random.choice(PH_EXP_CAT), reply_markup=kb_expense_categories())
        return ST_EXP_CATEGORY
    else:
        await q.edit_message_text(random.choice(PH_INC_CAT), reply_markup=kb_income_categories())
        return ST_INC_CATEGORY


async def expense_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])
    cat = list(EXPENSES.keys())[idx]

    tx = context.user_data.get("tx", {})
    tx["category"] = cat
    context.user_data["tx"] = tx

    phrase = random.choice(PH_EXP_SUB).replace("{cat}", cat)
    await q.edit_message_text(phrase, reply_markup=kb_expense_subcategories(cat), parse_mode=ParseMode.HTML)
    return ST_EXP_SUBCATEGORY


async def expense_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])
    tx = context.user_data.get("tx", {})
    tx["subcategory"] = EXPENSES.get(tx.get("category"), [])[idx]
    context.user_data["tx"] = tx

    await q.edit_message_text(random.choice(PH_AMOUNT_EXP))
    return ST_AMOUNT


async def income_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split(":")[1])
    tx = context.user_data.get("tx", {})
    tx["category"] = INCOME_CATEGORIES[idx]
    tx["subcategory"] = ""
    context.user_data["tx"] = tx

    await q.edit_message_text(random.choice(PH_AMOUNT_INC))
    return ST_AMOUNT


async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    try:
        await update.message.delete()
    except Exception:
        pass

    amt = parse_amount(update.message.text)
    if amt is None:
        await update.effective_chat.send_message(
            "Не понял сумму 🙈\nНапиши, пожалуйста, например: 2500 / 2 500 / 2к"
        )
        return ST_AMOUNT

    tx = context.user_data.get("tx", {})
    tx["amount"] = amt
    context.user_data["tx"] = tx

    phrase = random.choice(PH_COMMENT_EXP if tx.get("type") == "расход" else PH_COMMENT_INC)
    await update.effective_chat.send_message(phrase, reply_markup=kb_skip_comment())
    return ST_COMMENT


async def comment_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tx = context.user_data.get("tx", {})
    tx["comment"] = ""
    context.user_data["tx"] = tx
    await save_and_finish(update, context, via_callback=True)
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
    await save_and_finish(update, context, via_callback=False)
    return ST_MENU


async def save_and_finish(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    via_callback: bool = False,
) -> None:
    """Сохраняет транзакцию, всегда шлёт новое сообщение с итогом."""
    tx = context.user_data.get("tx", {})
    _invalidate_month_cache()

    # Убираем кнопку "Пропустить" со старого сообщения
    if via_callback:
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    await typing(update)
    try:
        await gas_request({
            "cmd": "add",
            "type": tx.get("type"),
            "category": tx.get("category"),
            "subcategory": tx.get("subcategory", ""),
            "amount": tx.get("amount"),
            "comment": tx.get("comment", ""),
        })
    except Exception:
        logger.exception("save_and_finish: GAS error")
        reset_dialog(context)
        await update.effective_chat.send_message(
            f"{GAS_ERROR_TEXT}\nДанные не сохранились, попробуй ещё раз.",
            reply_markup=kb_main()
        )
        return

    if tx.get("type") == "расход":
        header = random.choice(PH_SAVED_EXP)
        detail = f"<i>{tx.get('category')} → {tx.get('subcategory')}</i> — <b>{tx.get('amount'):,.2f} ₽</b>".replace(",", " ")
    else:
        header = random.choice(PH_SAVED_INC)
        detail = f"<i>{tx.get('category')}</i> — <b>{tx.get('amount'):,.2f} ₽</b>".replace(",", " ")

    if tx.get("comment", "").strip():
        detail += f"\n💬 {tx['comment'].strip()}"

    month_txt = await safe_month_text()
    text = f"{header}\n{detail}\n\n{month_txt}" if month_txt else f"{header}\n{detail}"

    # Всегда новое сообщение — видно внизу чата, не теряется
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())


async def analysis_kind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["analysis_kind"] = q.data.split(":")[1]
    await q.edit_message_text("За какой период?", reply_markup=kb_analysis_period())
    return ST_ANALYSIS_PERIOD


async def analysis_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    period = q.data.split(":")[1]
    kind_rus = "расход" if context.user_data.get("analysis_kind") == "expense" else "доход"

    await typing(update)
    try:
        result = await gas_request({"cmd": "analysis", "kind": kind_rus, "period": period})
    except Exception:
        logger.exception("analysis_period: GAS error")
        await q.edit_message_text(GAS_ERROR_TEXT, reply_markup=kb_main())
        return ST_MENU

    title = result.get("title", "Анализ")
    items = result.get("items", [])

    if not items:
        text = f"<b>{title}</b>\n\nДанных пока нет."
    else:
        text = f"<b>{title}</b>\n\n"
        for it in items:
            text += f"• {it.get('category', '?')}: <b>{it.get('amount', 0):,.2f}</b> ₽\n".replace(",", " ")

    month_txt = await safe_month_text()
    if month_txt:
        text += f"\n\n{month_txt}"

    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    return ST_MENU


async def set_balance_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    try:
        await update.message.delete()
    except Exception:
        pass

    bal = parse_amount(update.message.text)
    if bal is None:
        await update.effective_chat.send_message(
            "Не понял число 🙈 Напиши ещё раз, например: 25000 / 25 000 / 25к"
        )
        return ST_SET_BALANCE

    _invalidate_month_cache()

    await typing(update)
    try:
        await gas_request({"cmd": "set_balance", "balance": bal})
    except Exception:
        logger.exception("set_balance_received: GAS error")
        reset_dialog(context)
        await update.effective_chat.send_message(GAS_ERROR_TEXT, reply_markup=kb_main())
        return ST_MENU

    month_txt = await safe_month_text()
    conf = f"✅ Баланс установлен: <b>{bal:,.2f} ₽</b>".replace(",", " ")
    text = f"{conf}\n\n{month_txt}" if month_txt else conf
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    return ST_MENU


async def back_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    dest = q.data.split(":")[1]

    if dest == "menu":
        month_txt = await safe_month_text()
        text = month_txt or "Главное меню"
        await q.edit_message_text(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
        return ST_MENU
    elif dest == "choose_type":
        await q.edit_message_text("Что вносим?", reply_markup=kb_choose_type())
        return ST_ADD_CHOOSE_TYPE
    elif dest == "exp_cat":
        tx = context.user_data.get("tx", {})
        tx.pop("subcategory", None)
        context.user_data["tx"] = tx
        await q.edit_message_text(random.choice(PH_EXP_CAT), reply_markup=kb_expense_categories())
        return ST_EXP_CATEGORY
    elif dest == "analysis_kind":
        await q.edit_message_text("Что анализируем?", reply_markup=kb_analysis_kind())
        return ST_ANALYSIS_KIND
    elif dest == "edit_list":
        transactions = context.user_data.get("edit_transactions", [])
        await q.edit_message_text(
            "<b>Последние записи:</b>\n\nВыбери что исправить:",
            reply_markup=kb_edit_list(transactions),
            parse_mode=ParseMode.HTML
        )
        return ST_EDIT_SELECT

    return ST_MENU


async def edit_select_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    row_id = int(q.data.split(":")[1])
    transactions = context.user_data.get("edit_transactions", [])
    selected_tx = next((t for t in transactions if t["row_id"] == row_id), None)

    if not selected_tx:
        await q.answer("Ошибка: запись не найдена", show_alert=True)
        return ST_EDIT_SELECT

    context.user_data["selected_transaction"] = selected_tx

    emoji = "➖" if selected_tx["type"] == "расход" else "➕"
    text = (
        f"<b>{emoji} {selected_tx['type'].capitalize()}</b>\n"
        f"📅 {selected_tx['date'][:16]}\n"
        f"📂 {selected_tx['category']}"
    )
    if selected_tx.get("subcategory"):
        text += f" → {selected_tx['subcategory']}"
    text += f"\n💰 {selected_tx['amount']:,.2f} ₽".replace(",", " ")
    if selected_tx.get("comment"):
        text += f"\n💬 {selected_tx['comment']}"
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
        _invalidate_month_cache()
        await typing(update)
        try:
            await gas_request({"cmd": "delete_transaction", "row_id": selected_tx["row_id"]})
        except Exception:
            logger.exception("edit_field_selected delete: GAS error")
            reset_dialog(context)
            await q.edit_message_text(GAS_ERROR_TEXT, reply_markup=kb_main())
            return ST_MENU

        month_txt = await safe_month_text()
        text = f"✅ Запись удалена\n\n{month_txt}" if month_txt else "✅ Запись удалена"
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
        return ST_MENU

    elif field == "amount":
        current_amt = selected_tx.get("amount", 0)
        await q.edit_message_text(
            f"Текущая сумма: <b>{current_amt:,.2f} ₽</b>\n\nВведи новую сумму:\n(например: 2500 / 2 500 / 2к)".replace(",", " "),
            parse_mode=ParseMode.HTML
        )
        return ST_EDIT_VALUE

    elif field == "comment":
        current = selected_tx.get("comment", "")
        note = f"<i>{current}</i>" if current else "<i>(пусто)</i>"
        await q.edit_message_text(
            f"Текущий комментарий: {note}\n\nВведи новый комментарий:",
            parse_mode=ParseMode.HTML
        )
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
        if amt is None:
            await update.effective_chat.send_message(
                "Не понял сумму 🙈\nНапиши, пожалуйста, например: 2500 / 2 500 / 2к"
            )
            return ST_EDIT_VALUE
        _invalidate_month_cache()
        await typing(update)
        try:
            await gas_request({"cmd": "update_transaction", "row_id": row_id, "field": "amount", "value": amt})
        except Exception:
            logger.exception("edit_value_received amount: GAS error")
            reset_dialog(context)
            await update.effective_chat.send_message(GAS_ERROR_TEXT, reply_markup=kb_main())
            return ST_MENU
        conf = f"✅ Сумма изменена на <b>{amt:,.2f} ₽</b>".replace(",", " ")

    elif field == "comment":
        comment = (update.message.text or "").strip()
        await typing(update)
        try:
            await gas_request({"cmd": "update_transaction", "row_id": row_id, "field": "comment", "value": comment})
        except Exception:
            logger.exception("edit_value_received comment: GAS error")
            reset_dialog(context)
            await update.effective_chat.send_message(GAS_ERROR_TEXT, reply_markup=kb_main())
            return ST_MENU
        conf = "✅ Комментарий изменён"
    else:
        conf = "✅ Готово"

    month_txt = await safe_month_text()
    text = f"{conf}\n\n{month_txt}" if month_txt else conf
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    return ST_MENU


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return
    await update.message.reply_text(
        "📋 <b>Как пользоваться:</b>\n\n"
        "Нажми <b>➕ Внести транзакцию</b> и отвечай на вопросы 🙂\n\n"
        "Доступные действия:\n"
        "• <b>Внести транзакцию</b> — добавить расход или доход\n"
        "• <b>Скорректировать записи</b> — изменить или удалить последние записи\n"
        "• <b>Анализ</b> — посмотреть статистику\n"
        "• <b>Установить баланс</b> — задать начальный баланс",
        parse_mode=ParseMode.HTML
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error: %s", context.error)
    try:
        if isinstance(update, Update):
            reset_dialog(context)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Ой, что-то пошло не так 🙈\nПопробуй начать заново — нажми /start",
                    reply_markup=kb_main()
                )
    except Exception:
        pass


# =========================
# App + graceful shutdown
# =========================
def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_in_menu),
        ],
        states={
            ST_MENU: [
                CallbackQueryHandler(on_menu, pattern=r"^menu:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_in_menu),
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
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_error_handler(error_handler)
    return app


def run():
    app = build_app()

    # Graceful shutdown: ловим SIGTERM (Railway) и SIGINT (Ctrl+C)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _shutdown(sig_name: str):
        logger.info("Received %s, shutting down gracefully...", sig_name)
        await app.stop()
        await app.shutdown()
        await close_http_session()
        loop.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.ensure_future(_shutdown(s.name))
            )
        except NotImplementedError:
            pass  # Windows не поддерживает add_signal_handler

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
