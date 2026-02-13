import os
import re
import random
import logging
import hashlib
from typing import Optional, Dict, Any, List
from difflib import get_close_matches

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

# Для webhook (Railway)
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
# Алиасы категорий для быстрого парсинга
# =========================
# Короткие варианты для категорий расходов
EXPENSE_ALIASES = {
    # Основные категории
    "дети": "Дети",
    "детям": "Дети",
    "ребенку": "Дети",
    "задолженности": "Задолженности",
    "долги": "Задолженности",
    "кредит": "Задолженности",
    "образование": "Образование",
    "учеба": "Образование",
    "развлечения": "Развлечения",
    "отдых": "Развлечения",
    "повседневные": "Повседневные расходы",
    "продукты": "Повседневные расходы",
    "еда": "Повседневные расходы",
    "кафе": "Повседневные расходы",
    "ресторан": "Повседневные расходы",
    "одежда": "Повседневные расходы",
    "подарки": "Подарки",
    "подарок": "Подарки",
    "здоровье": "Здоровье",
    "врач": "Здоровье",
    "лекарства": "Здоровье",
    "аптека": "Здоровье",
    "дом": "Дом",
    "мебель": "Дом",
    "ремонт": "Дом",
    "страхование": "Страхование",
    "страховка": "Страхование",
    "животные": "Домашние животные",
    "питомец": "Домашние животные",
    "кот": "Домашние животные",
    "собака": "Домашние животные",
    "техника": "Техника",
    "гаджеты": "Техника",
    "транспорт": "Транспорт",
    "топливо": "Транспорт",
    "бензин": "Транспорт",
    "такси": "Транспорт",
    "метро": "Транспорт",
    "путешествия": "Путешествия",
    "поездка": "Путешествия",
    "отель": "Путешествия",
    "жкх": "Услуги ЖКХ",
    "коммуналка": "Услуги ЖКХ",
    "свет": "Услуги ЖКХ",
    "вода": "Услуги ЖКХ",
    "интернет": "Услуги ЖКХ",
    "красота": "Красота",
    "маникюр": "Красота",
    "парикмахер": "Красота",
}

# Алиасы для доходов
INCOME_ALIASES = {
    "муж": "Муж",
    "зарплата": "Муж",
    "государство": "Государство",
    "пособие": "Государство",
    "проценты": "% по вкладам",
    "вклад": "% по вкладам",
    "возврат": "Возвраты",
    "вернули": "Возвраты",
    "подарок": "Подарки",
    "подарки": "Подарки",
    "продажа": "Продажи",
}

# Маппинг алиасов расходов на подкатегории
EXPENSE_SUBCATEGORY_MAP = {
    "продукты": "Продукты",
    "еда": "Продукты",
    "кафе": "Рестораны и кафе",
    "ресторан": "Рестораны и кафе",
    "одежда": "Одежда",
    "врач": "Обследования врачей/стоматолога/окулиста",
    "лекарства": "Лекарства",
    "аптека": "Лекарства",
    "мебель": "Мебель",
    "ремонт": "Ремонт",
    "такси": "Такси и каршеринг",
    "метро": "Общественный транспорт",
    "бензин": "Топливо",
    "топливо": "Топливо",
    "отель": "Отели",
    "свет": "Электричество",
    "вода": "Вода",
    "интернет": "Интернет",
    "жкх": "Другое",
    "коммуналка": "Другое",
    "маникюр": "Маникюр",
    "парикмахер": "Парикмахер",
}


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
    ST_QUICK_CONFIRM,
    ST_QUICK_EDIT_FIELD,
    ST_QUICK_EDIT_VALUE,
) = range(16)


# =========================
# Helpers: temp messages
# =========================
async def delete_working_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Удалить текущее рабочее сообщение"""
    msg_id = context.user_data.get("working_message_id")
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.debug(f"Couldn't delete message {msg_id}: {e}")
    context.user_data["working_message_id"] = None


# =========================
# Helpers: keyboards
# =========================
def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == WIFE_TG_ID)


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


def kb_quick_confirm() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения быстрой транзакции"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, сохранить", callback_data="quick:save")],
        [InlineKeyboardButton("✏️ Изменить данные", callback_data="quick:edit")],
        [InlineKeyboardButton("❌ Отмена", callback_data="quick:cancel")],
    ])


def kb_quick_edit(quick_tx: Dict) -> InlineKeyboardMarkup:
    """Клавиатура для редактирования быстрой транзакции с отображением текущих значений"""
    tx_type = quick_tx.get('type', 'расход')
    amount = quick_tx.get('amount', 0)
    category = quick_tx.get('category', '?')
    subcategory = quick_tx.get('subcategory', '')
    comment = quick_tx.get('comment', '')
    
    emoji = '➖' if tx_type == 'расход' else '➕'
    
    buttons = []
    
    # Тип
    buttons.append([InlineKeyboardButton(
        f"Тип: {emoji} {tx_type.capitalize()}", 
        callback_data="quickedit:type"
    )])
    
    # Сумма
    buttons.append([InlineKeyboardButton(
        f"💰 Сумма: {amount:,.0f} ₽".replace(",", " "), 
        callback_data="quickedit:amount"
    )])
    
    # Категория
    buttons.append([InlineKeyboardButton(
        f"📁 Категория: {category}", 
        callback_data="quickedit:category"
    )])
    
    # Подкатегория (только для расходов)
    if tx_type == 'расход':
        subcat_text = subcategory if subcategory else "(не указана)"
        buttons.append([InlineKeyboardButton(
            f"📂 Подкатегория: {subcat_text}", 
            callback_data="quickedit:subcategory"
        )])
    
    # Комментарий
    comment_preview = comment[:20] + "..." if len(comment) > 20 else comment
    comment_text = f"📝 Комментарий: {comment_preview}" if comment else "📝 Комментарий: (пусто)"
    buttons.append([InlineKeyboardButton(
        comment_text, 
        callback_data="quickedit:comment"
    )])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад к подтверждению", callback_data="quickedit:back")])
    
    return InlineKeyboardMarkup(buttons)



def kb_quick_category_select(suggestions: List[str], tx_type: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора из предложенных категорий"""
    rows = []
    for i, cat in enumerate(suggestions):
        rows.append([InlineKeyboardButton(f"✅ {cat}", callback_data=f"quickcat:{i}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="quick:cancel")])
    return InlineKeyboardMarkup(rows)


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
    """Клавиатура со списком последних записей"""
    rows = []
    for tx in transactions:
        row_id = tx["row_id"]
        date_str = tx["date"][:10]  # YYYY-MM-DD
        tx_type = tx["type"]
        emoji = "➖" if tx_type == "расход" else "➕"
        cat = tx["category"]
        amt = tx["amount"]
        label = f"{emoji} {date_str} | {cat} | {amt:,.0f} ₽".replace(",", " ")
        rows.append([InlineKeyboardButton(label, callback_data=f"edit_row:{row_id}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:menu")])
    return InlineKeyboardMarkup(rows)


def kb_edit_field() -> InlineKeyboardMarkup:
    """Клавиатура для выбора что редактировать"""
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
    else:
        pass

    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        val = float(s) * mult
        if val < 0:
            return None
        return round(val, 2)
    except Exception:
        return None


# =========================
# Quick transaction parsing
# =========================
# Служебные слова, которые нужно пропускать при парсинге категории
SKIP_WORDS = {'рублей', 'руб', 'рубля', 'рублик', 'рубликов', 'р', 'р.', '₽'}

def quick_parse_transaction(text: str) -> tuple[Optional[Dict], Optional[str]]:
    """
    Парсит строку быстрого ввода типа:
    - "продукты 1500"
    - "1500 продукты"  
    - "кафе 800 обед с другом"
    - "муж 50000"
    
    Возвращает: (parsed_data, error_message)
    """
    text = text.strip().lower()
    
    # Регулярка для поиска числа
    amount_pattern = r'\d+(?:[.,]\d{1,2})?(?:к|k)?'
    
    # Ищем все числа в строке
    amounts = re.findall(amount_pattern, text)
    if not amounts:
        return None, "Не нашел сумму в сообщении 🙈\n\nПример: <i>продукты 1500</i> или <i>муж 50000</i>"
    
    # Берем первое найденное число как сумму
    amount = parse_amount(amounts[0])
    if not amount or amount <= 0:
        return None, "Не понял сумму 🙈\n\nПример: <i>продукты 1500</i>"
    
    # Удаляем сумму из текста
    text_without_amount = re.sub(amount_pattern, '', text, count=1).strip()
    
    # Разделяем на слова
    words = text_without_amount.split()
    
    # Пропускаем служебные слова (рублей, руб и т.д.)
    words = [w for w in words if w.lower() not in SKIP_WORDS]
    
    if not words:
        return None, "Не нашел категорию 🙈\n\nПример: <i>продукты 1500</i> или <i>1500 продукты</i>"
    
    # Первое слово - вероятная категория
    category_keyword = words[0]
    
    # Остальные слова - потенциальный комментарий
    # Убираем слова-алиасы категорий (они избыточны)
    all_aliases_lower = {k.lower() for k in EXPENSE_ALIASES.keys()} | {k.lower() for k in INCOME_ALIASES.keys()}
    comment_words = [w for w in words[1:] if w not in all_aliases_lower]
    comment = ' '.join(comment_words)
    
    # Сначала проверяем алиасы доходов
    if category_keyword in INCOME_ALIASES:
        return {
            'amount': amount,
            'category': INCOME_ALIASES[category_keyword],
            'type': 'доход',
            'subcategory': '',
            'comment': comment,
            'status': 'ready'
        }, None
    
    # Проверяем алиасы расходов
    if category_keyword in EXPENSE_ALIASES:
        category = EXPENSE_ALIASES[category_keyword]
        # Пытаемся найти конкретную подкатегорию из маппинга
        subcategory = EXPENSE_SUBCATEGORY_MAP.get(category_keyword)
        # Если не нашли - берем первую подкатегорию (или "Другое" если есть)
        if not subcategory:
            subs = EXPENSES.get(category, [])
            subcategory = subs[-1] if subs else "Другое"
        return {
            'amount': amount,
            'category': category,
            'type': 'расход',
            'subcategory': subcategory,
            'comment': comment,
            'status': 'ready'
        }, None
    
    # Fuzzy matching для расходов
    all_expense_keywords = list(EXPENSE_ALIASES.keys())
    expense_matches = get_close_matches(category_keyword, all_expense_keywords, n=3, cutoff=0.6)
    
    # Fuzzy matching для доходов
    all_income_keywords = list(INCOME_ALIASES.keys())
    income_matches = get_close_matches(category_keyword, all_income_keywords, n=3, cutoff=0.6)
    
    # Если нашли похожие категории
    if expense_matches or income_matches:
        suggestions = []
        
        # Добавляем предложения расходов
        for match in expense_matches[:2]:
            cat = EXPENSE_ALIASES[match]
            suggestions.append(f"➖ {cat}")
        
        # Добавляем предложения доходов
        for match in income_matches[:2]:
            cat = INCOME_ALIASES[match]
            suggestions.append(f"➕ {cat}")
        
        return {
            'amount': amount,
            'category_keyword': category_keyword,
            'suggestions': suggestions,
            'expense_matches': expense_matches,
            'income_matches': income_matches,
            'comment': comment,
            'status': 'needs_clarification'
        }, None
    
    # Если ничего не нашли
    return None, (
        f"Не нашел категорию '<i>{category_keyword}</i>' 🙈\n\n"
        f"<b>Примеры расходов:</b>\n"
        f"продукты 1500\n"
        f"кафе 800\n"
        f"такси 300\n\n"
        f"<b>Примеры доходов:</b>\n"
        f"муж 50000\n"
        f"подарок 5000"
    )


# =========================
# GAS API
# =========================
async def gas_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["user_id"] = WIFE_TG_ID

    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(SCRIPT_URL, json=payload) as resp:
            txt = await resp.text()
            try:
                data = await resp.json()
            except Exception:
                logger.error("GAS non-json response: %s", txt)
                raise RuntimeError("GAS вернул не-JSON ответ")
            if not data.get("ok"):
                raise RuntimeError(data.get("error") or "GAS error")
            return data["data"]


async def month_screen_text() -> str:
    s = await gas_request({"cmd": "summary_month"})
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
        f"📊 Баланс месяца: <b>{bal:,.2f}</b> ₽\n"
        f"💳 Текущий баланс: <b>{curr_bal:,.2f}</b> ₽"
    ).replace(",", " ")


# =========================
# Handlers
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    txt = await month_screen_text()
    await update.message.reply_text(
        f"Привет, Иришка! 🙂\n\n{txt}",
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )
    return ST_MENU


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action = q.data.split(":")[1]

    if action == "add":
        await q.edit_message_text(
            "Что вносим?",
            reply_markup=kb_choose_type()
        )
        return ST_ADD_CHOOSE_TYPE

    elif action == "edit":
        # Запрашиваем последние 10 записей
        result = await gas_request({"cmd": "get_recent_transactions", "limit": 10})
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
        await q.edit_message_text(
            "Что анализируем?",
            reply_markup=kb_analysis_kind()
        )
        return ST_ANALYSIS_KIND

    elif action == "set_balance":
        msg = await q.edit_message_text(
            "Окей, напиши текущий баланс (число):"
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_SET_BALANCE

    return ST_MENU


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tx_type = q.data.split(":")[1]

    # Проверяем, пришли ли мы из быстрого редактирования
    if context.user_data.get("quick_tx"):
        # Быстрое редактирование - не создаем новый tx
        if tx_type == "expense":
            msg = await q.edit_message_text(
                random.choice(PH_EXP_CAT),
                reply_markup=kb_expense_categories()
            )
            context.user_data["working_message_id"] = msg.message_id
            return ST_EXP_CATEGORY
        else:
            msg = await q.edit_message_text(
                random.choice(PH_INC_CAT),
                reply_markup=kb_income_categories()
            )
            context.user_data["working_message_id"] = msg.message_id
            return ST_INC_CATEGORY
    else:
        # Обычный flow
        context.user_data["tx"] = {"type": "расход" if tx_type == "expense" else "доход"}

        if tx_type == "expense":
            msg = await q.edit_message_text(
                random.choice(PH_EXP_CAT),
                reply_markup=kb_expense_categories()
            )
            context.user_data["working_message_id"] = msg.message_id
            return ST_EXP_CATEGORY
        else:
            msg = await q.edit_message_text(
                random.choice(PH_INC_CAT),
                reply_markup=kb_income_categories()
            )
            context.user_data["working_message_id"] = msg.message_id
            return ST_INC_CATEGORY


async def expense_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    idx = int(q.data.split(":")[1])
    cats = list(EXPENSES.keys())
    cat = cats[idx]

    # Проверяем, пришли ли мы из быстрого редактирования
    if context.user_data.get("quick_edit_field") == "category":
        quick_tx = context.user_data.get("quick_tx", {})
        quick_tx["category"] = cat
        quick_tx["type"] = "расход"
        context.user_data["quick_tx"] = quick_tx
        
        phrase = random.choice(PH_EXP_SUB).replace("{cat}", cat)
        await q.edit_message_text(
            phrase,
            reply_markup=kb_expense_subcategories(cat),
            parse_mode=ParseMode.MARKDOWN
        )
        return ST_QUICK_EDIT_VALUE
    elif context.user_data.get("quick_edit_field") == "subcategory":
        # Не должны сюда попасть, но на всякий случай
        quick_tx = context.user_data.get("quick_tx", {})
        quick_tx["category"] = cat
        context.user_data["quick_tx"] = quick_tx
        
        phrase = random.choice(PH_EXP_SUB).replace("{cat}", cat)
        await q.edit_message_text(
            phrase,
            reply_markup=kb_expense_subcategories(cat),
            parse_mode=ParseMode.MARKDOWN
        )
        return ST_QUICK_EDIT_VALUE
    elif context.user_data.get("quick_tx"):
        # Старый путь быстрого редактирования (сейчас не используется)
        quick_tx = context.user_data.get("quick_tx", {})
        quick_tx["category"] = cat
        quick_tx["type"] = "расход"
        context.user_data["quick_tx"] = quick_tx
        
        phrase = random.choice(PH_EXP_SUB).replace("{cat}", cat)
        msg = await q.edit_message_text(
            phrase,
            reply_markup=kb_expense_subcategories(cat),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_EXP_SUBCATEGORY
    else:
        tx = context.user_data.get("tx", {})
        tx["category"] = cat
        context.user_data["tx"] = tx

        phrase = random.choice(PH_EXP_SUB).replace("{cat}", cat)
        msg = await q.edit_message_text(
            phrase,
            reply_markup=kb_expense_subcategories(cat),
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_EXP_SUBCATEGORY


async def expense_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    idx = int(q.data.split(":")[1])
    
    # Проверяем, пришли ли мы из быстрого редактирования
    if context.user_data.get("quick_edit_field") in ["category", "subcategory"]:
        quick_tx = context.user_data.get("quick_tx", {})
        cat = quick_tx.get("category")
        subs = EXPENSES.get(cat, [])
        sub = subs[idx]
        
        quick_tx["subcategory"] = sub
        context.user_data["quick_tx"] = quick_tx
        
        # Возвращаемся в меню редактирования
        await q.edit_message_text(
            "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_edit(quick_tx)
        )
        return ST_QUICK_EDIT_FIELD
    elif context.user_data.get("quick_tx"):
        # Старый путь (сейчас не используется)
        quick_tx = context.user_data.get("quick_tx", {})
        cat = quick_tx.get("category")
        subs = EXPENSES.get(cat, [])
        sub = subs[idx]
        
        quick_tx["subcategory"] = sub
        context.user_data["quick_tx"] = quick_tx
        
        # Возвращаем к подтверждению
        emoji = '➖'
        text = (
            f"{emoji} <b>Расход</b>\n"
            f"💰 Сумма: <b>{quick_tx.get('amount', 0):,.2f}</b> ₽\n".replace(",", " ") +
            f"📁 Категория: {cat} → {sub}"
        )
        
        if quick_tx.get('comment'):
            text += f"\n📝 Комментарий: {quick_tx.get('comment')}"
        
        text += "\n\n<b>Всё верно?</b>"
        
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_confirm()
        )
        return ST_QUICK_CONFIRM
    else:
        # Обычный flow
        tx = context.user_data.get("tx", {})
        cat = tx.get("category")
        subs = EXPENSES.get(cat, [])
        sub = subs[idx]

        tx["subcategory"] = sub
        context.user_data["tx"] = tx

        msg = await q.edit_message_text(random.choice(PH_AMOUNT_EXP))
        context.user_data["working_message_id"] = msg.message_id
        return ST_AMOUNT


async def income_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    idx = int(q.data.split(":")[1])
    cat = INCOME_CATEGORIES[idx]

    # Проверяем, пришли ли мы из быстрого редактирования
    if context.user_data.get("quick_edit_field") == "category":
        quick_tx = context.user_data.get("quick_tx", {})
        quick_tx["category"] = cat
        quick_tx["type"] = "доход"
        quick_tx["subcategory"] = ""
        context.user_data["quick_tx"] = quick_tx
        
        # Возвращаемся в меню редактирования
        await q.edit_message_text(
            "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_edit(quick_tx)
        )
        return ST_QUICK_EDIT_FIELD
    elif context.user_data.get("quick_tx"):
        # Старый путь (сейчас не используется)
        quick_tx = context.user_data.get("quick_tx", {})
        quick_tx["category"] = cat
        quick_tx["type"] = "доход"
        quick_tx["subcategory"] = ""
        context.user_data["quick_tx"] = quick_tx
        
        # Возвращаем к подтверждению
        emoji = '➕'
        text = (
            f"{emoji} <b>Доход</b>\n"
            f"💰 Сумма: <b>{quick_tx.get('amount', 0):,.2f}</b> ₽\n".replace(",", " ") +
            f"📁 Категория: {cat}"
        )
        
        if quick_tx.get('comment'):
            text += f"\n📝 Комментарий: {quick_tx.get('comment')}"
        
        text += "\n\n<b>Всё верно?</b>"
        
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_confirm()
        )
        return ST_QUICK_CONFIRM
    else:
        tx = context.user_data.get("tx", {})
        tx["category"] = cat
        tx["subcategory"] = ""
        context.user_data["tx"] = tx

        msg = await q.edit_message_text(random.choice(PH_AMOUNT_INC))
        context.user_data["working_message_id"] = msg.message_id
        return ST_AMOUNT


async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    # Удаляем сообщение пользователя
    try:
        await update.message.delete()
    except Exception:
        pass

    amt = parse_amount(update.message.text)
    if amt is None or amt <= 0:
        await delete_working_message(context, update.effective_chat.id)
        msg = await update.effective_chat.send_message(
            "Не понял сумму 🙈\nНапиши, пожалуйста, например: 2500 / 2 500 / 2к"
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_AMOUNT

    tx = context.user_data.get("tx", {})
    tx["amount"] = amt
    context.user_data["tx"] = tx

    await delete_working_message(context, update.effective_chat.id)

    if tx.get("type") == "расход":
        phrase = random.choice(PH_COMMENT_EXP)
    else:
        phrase = random.choice(PH_COMMENT_INC)

    msg = await update.effective_chat.send_message(
        phrase,
        reply_markup=kb_skip_comment()
    )
    context.user_data["working_message_id"] = msg.message_id
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

    # Удаляем сообщение пользователя
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
    """Сохранить транзакцию и показать финальное подтверждение + главный экран"""
    
    # Удаляем рабочее сообщение
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

    # Отправляем финальное подтверждение
    await update.effective_chat.send_message(f"{header}\n{detail}")

    # Отправляем главный экран
    txt_month = await month_screen_text()
    await update.effective_chat.send_message(
        txt_month,
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )


async def analysis_kind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    kind = q.data.split(":")[1]
    context.user_data["analysis_kind"] = kind

    await q.edit_message_text(
        "За какой период?",
        reply_markup=kb_analysis_period()
    )
    return ST_ANALYSIS_PERIOD


async def analysis_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    period = q.data.split(":")[1]
    kind = context.user_data.get("analysis_kind", "expense")
    
    # Преобразуем из английского в русский для Google Sheets
    kind_map = {
        "expense": "расход",
        "income": "доход"
    }
    kind_rus = kind_map.get(kind, "расход")

    await delete_working_message(context, update.effective_chat.id)

    result = await gas_request({
        "cmd": "analysis",
        "kind": kind_rus,  # Отправляем по-русски!
        "period": period
    })

    title = result.get("title", "Анализ")
    items = result.get("items", [])

    if not items:
        text = f"<b>{title}</b>\n\nДанных пока нет."
    else:
        text = f"<b>{title}</b>\n\n"
        for it in items:
            cat = it.get("category", "?")
            amt = it.get("amount", 0)
            text += f"• {cat}: <b>{amt:,.2f}</b> ₽\n".replace(",", " ")

    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML)

    txt_month = await month_screen_text()
    await update.effective_chat.send_message(
        txt_month,
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )
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
        await delete_working_message(context, update.effective_chat.id)
        msg = await update.effective_chat.send_message(
            "Не понял число 🙈 Напиши ещё раз, например: 25000 / 25 000 / 25к"
        )
        context.user_data["working_message_id"] = msg.message_id
        return ST_SET_BALANCE

    await gas_request({"cmd": "set_balance", "balance": bal})

    await delete_working_message(context, update.effective_chat.id)
    await update.effective_chat.send_message(
        f"✅ Баланс установлен: <b>{bal:,.2f}</b> ₽".replace(",", " "),
        parse_mode=ParseMode.HTML
    )

    txt_month = await month_screen_text()
    await update.effective_chat.send_message(
        txt_month,
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )
    return ST_MENU


async def back_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    dest = q.data.split(":")[1]
    
    # Проверяем, находимся ли в режиме quick_edit
    if context.user_data.get("quick_edit_field"):
        # Возврат в меню редактирования
        quick_tx = context.user_data.get("quick_tx", {})
        await q.edit_message_text(
            "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_edit(quick_tx)
        )
        return ST_QUICK_EDIT_FIELD

    if dest == "menu":
        await delete_working_message(context, update.effective_chat.id)
        txt = await month_screen_text()
        await update.effective_chat.send_message(
            txt,
            reply_markup=kb_main(),
            parse_mode=ParseMode.HTML
        )
        return ST_MENU

    elif dest == "choose_type":
        await q.edit_message_text(
            "Что вносим?",
            reply_markup=kb_choose_type()
        )
        return ST_ADD_CHOOSE_TYPE

    elif dest == "exp_cat":
        tx = context.user_data.get("tx", {})
        tx.pop("subcategory", None)
        context.user_data["tx"] = tx
        await q.edit_message_text(
            random.choice(PH_EXP_CAT),
            reply_markup=kb_expense_categories()
        )
        return ST_EXP_CATEGORY

    elif dest == "analysis_kind":
        await q.edit_message_text(
            "Что анализируем?",
            reply_markup=kb_analysis_kind()
        )
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
    """Пользователь выбрал запись для редактирования"""
    q = update.callback_query
    await q.answer()

    row_id = int(q.data.split(":")[1])
    
    # Находим транзакцию
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
    
    # Показываем детали записи
    tx_type = selected_tx["type"]
    emoji = "➖" if tx_type == "расход" else "➕"
    date_str = selected_tx["date"][:16]  # YYYY-MM-DD HH:MM
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
    """Пользователь выбрал что редактировать"""
    q = update.callback_query
    await q.answer()

    field = q.data.split(":")[1]
    context.user_data["edit_field"] = field
    
    selected_tx = context.user_data.get("selected_transaction", {})
    
    if field == "delete":
        # Удаление записи
        row_id = selected_tx["row_id"]
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
    """Пользователь ввел новое значение"""
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END

    # Удаляем сообщение пользователя
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
    
    # Показываем главный экран
    txt = await month_screen_text()
    await update.effective_chat.send_message(txt, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    
    return ST_MENU


# =========================
# QUICK INPUT HANDLERS
# =========================
async def handle_quick_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик быстрого ввода транзакций одной строкой"""
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END
    
    # Парсим сообщение
    result, error = quick_parse_transaction(update.message.text)
    
    if error:
        await update.message.reply_text(error, parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    
    # Если нужно уточнение категории
    if result['status'] == 'needs_clarification':
        context.user_data["quick_tx"] = {
            'amount': result['amount'],
            'comment': result['comment'],
            'suggestions': result['suggestions'],
            'expense_matches': result['expense_matches'],
            'income_matches': result['income_matches'],
        }
        
        kb = kb_quick_category_select(result['suggestions'], "mixed")
        
        await update.message.reply_text(
            f"💰 Сумма: <b>{result['amount']:,.2f}</b> ₽\n".replace(",", " ") +
            f"📝 Возможно, ты имела в виду:\n\n"
            f"Выбери категорию:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return ST_QUICK_CONFIRM
    
    # Если все распарсилось успешно
    if result['status'] == 'ready':
        context.user_data["quick_tx"] = result
        
        emoji = '➖' if result['type'] == 'расход' else '➕'
        text = (
            f"{emoji} <b>{result['type'].capitalize()}</b>\n"
            f"💰 Сумма: <b>{result['amount']:,.2f}</b> ₽\n".replace(",", " ") +
            f"📁 Категория: {result['category']}"
        )
        
        if result['type'] == 'расход' and result.get('subcategory'):
            text += f" → {result['subcategory']}"
        
        if result['comment']:
            text += f"\n📝 Комментарий: {result['comment']}"
        
        text += "\n\n<b>Всё верно?</b>"
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_confirm()
        )
        return ST_QUICK_CONFIRM
    
    return ConversationHandler.END


async def quick_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь выбрал категорию из предложенных"""
    q = update.callback_query
    await q.answer()
    
    idx = int(q.data.split(":")[1])
    quick_tx = context.user_data.get("quick_tx", {})
    
    suggestion = quick_tx['suggestions'][idx]
    
    # Определяем тип и категорию
    if suggestion.startswith("➖"):
        tx_type = "расход"
        category = suggestion[2:].strip()  # Убираем "➖ "
        
        # Находим оригинальное название категории и подкатегорию
        expense_matches = quick_tx.get('expense_matches', [])
        if idx < len(expense_matches):
            keyword = expense_matches[idx]
            category = EXPENSE_ALIASES[keyword]
        
        subcategory = EXPENSES[category][-1] if EXPENSES.get(category) else "Другое"
    else:
        tx_type = "доход"
        category = suggestion[2:].strip()  # Убираем "➕ "
        subcategory = ""
        
        # Находим оригинальное название категории
        income_matches = quick_tx.get('income_matches', [])
        expense_matches = quick_tx.get('expense_matches', [])
        income_idx = idx - len(expense_matches)
        
        if 0 <= income_idx < len(income_matches):
            keyword = income_matches[income_idx]
            category = INCOME_ALIASES[keyword]
    
    # Обновляем транзакцию
    quick_tx['type'] = tx_type
    quick_tx['category'] = category
    quick_tx['subcategory'] = subcategory
    quick_tx['status'] = 'ready'
    context.user_data["quick_tx"] = quick_tx
    
    emoji = '➖' if tx_type == 'расход' else '➕'
    text = (
        f"{emoji} <b>{tx_type.capitalize()}</b>\n"
        f"💰 Сумма: <b>{quick_tx['amount']:,.2f}</b> ₽\n".replace(",", " ") +
        f"📁 Категория: {category}"
    )
    
    if tx_type == 'расход' and subcategory:
        text += f" → {subcategory}"
    
    if quick_tx.get('comment'):
        text += f"\n📝 Комментарий: {quick_tx['comment']}"
    
    text += "\n\n<b>Всё верно?</b>"
    
    await q.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb_quick_confirm()
    )
    return ST_QUICK_CONFIRM


async def quick_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение быстрой транзакции"""
    q = update.callback_query
    await q.answer()
    
    quick_tx = context.user_data.get("quick_tx", {})
    
    # Сохраняем в GAS
    payload = {
        "cmd": "add",
        "type": quick_tx.get("type"),
        "category": quick_tx.get("category"),
        "subcategory": quick_tx.get("subcategory", ""),
        "amount": quick_tx.get("amount"),
        "comment": quick_tx.get("comment", ""),
    }
    
    await gas_request(payload)
    
    # Формируем сообщение
    if quick_tx.get("type") == "расход":
        header = random.choice(PH_SAVED_EXP)
    else:
        header = random.choice(PH_SAVED_INC)
    
    await q.edit_message_text(f"{header} 🎉")
    
    # Показываем главный экран
    txt_month = await month_screen_text()
    await update.effective_chat.send_message(
        txt_month,
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )
    
    # Очищаем данные
    context.user_data.pop("quick_tx", None)
    context.user_data.pop("quick_edit_field", None)  # ВАЖНО!
    
    return ST_MENU


async def quick_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню редактирования быстрой транзакции"""
    q = update.callback_query
    await q.answer()
    
    quick_tx = context.user_data.get("quick_tx", {})
    
    await q.edit_message_text(
        "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_quick_edit(quick_tx)
    )
    
    return ST_QUICK_EDIT_FIELD


async def quick_edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора поля для редактирования"""
    q = update.callback_query
    await q.answer()
    
    field = q.data.split(":")[1]
    
    if field == "back":
        # Вернуться к подтверждению
        quick_tx = context.user_data.get("quick_tx", {})
        
        # ВАЖНО: очищаем флаг редактирования
        context.user_data.pop("quick_edit_field", None)
        
        emoji = '➖' if quick_tx.get('type') == 'расход' else '➕'
        text = (
            f"{emoji} <b>{quick_tx.get('type', '?').capitalize()}</b>\n"
            f"💰 Сумма: <b>{quick_tx.get('amount', 0):,.2f}</b> ₽\n".replace(",", " ") +
            f"📁 Категория: {quick_tx.get('category', '?')}"
        )
        
        if quick_tx.get('type') == 'расход' and quick_tx.get('subcategory'):
            text += f" → {quick_tx.get('subcategory')}"
        
        if quick_tx.get('comment'):
            text += f"\n📝 Комментарий: {quick_tx.get('comment')}"
        
        text += "\n\n<b>Всё верно?</b>"
        
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_confirm()
        )
        return ST_QUICK_CONFIRM
    
    context.user_data["quick_edit_field"] = field
    quick_tx = context.user_data.get("quick_tx", {})
    
    if field == "type":
        # Показываем кнопки выбора типа
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➖ Расход", callback_data="quicktype:expense")],
            [InlineKeyboardButton("➕ Доход", callback_data="quicktype:income")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="quicktype:back")],
        ])
        await q.edit_message_text(
            "Выбери тип транзакции:",
            reply_markup=kb
        )
        return ST_QUICK_EDIT_VALUE
    
    elif field == "amount":
        current = quick_tx.get('amount', 0)
        await q.edit_message_text(
            f"Текущая сумма: <b>{current:,.2f}</b> ₽\n\n"
            f"Введи новую сумму:\n"
            f"(например: 2500 / 2 500 / 2к)".replace(",", " "),
            parse_mode=ParseMode.HTML
        )
        return ST_QUICK_EDIT_VALUE
    
    elif field == "category":
        # Показываем категории в зависимости от типа
        tx_type = quick_tx.get('type', 'расход')
        if tx_type == 'расход':
            await q.edit_message_text(
                "Выбери категорию расхода:",
                reply_markup=kb_expense_categories()
            )
        else:
            await q.edit_message_text(
                "Выбери категорию дохода:",
                reply_markup=kb_income_categories()
            )
        return ST_QUICK_EDIT_VALUE
    
    elif field == "subcategory":
        category = quick_tx.get('category')
        if category:
            await q.edit_message_text(
                f"Выбери подкатегорию в <b>{category}</b>:",
                reply_markup=kb_expense_subcategories(category),
                parse_mode=ParseMode.HTML
            )
        else:
            await q.answer("Сначала выбери категорию", show_alert=True)
            return ST_QUICK_EDIT_FIELD
        return ST_QUICK_EDIT_VALUE
    
    elif field == "comment":
        current = quick_tx.get('comment', '')
        text = "Текущий комментарий: "
        if current:
            text += f"<i>{current}</i>"
        else:
            text += "<i>(пусто)</i>"
        text += "\n\nВведи новый комментарий:"
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        return ST_QUICK_EDIT_VALUE
    
    return ST_QUICK_EDIT_FIELD


async def quick_edit_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного нового значения"""
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return ConversationHandler.END
    
    # Удаляем сообщение пользователя
    try:
        await update.message.delete()
    except Exception:
        pass
    
    field = context.user_data.get("quick_edit_field")
    quick_tx = context.user_data.get("quick_tx", {})
    
    if field == "amount":
        amt = parse_amount(update.message.text)
        if amt is None or amt <= 0:
            msg = await update.effective_chat.send_message(
                "Не понял сумму 🙈\nНапиши, пожалуйста, например: 2500 / 2 500 / 2к"
            )
            context.user_data["working_message_id"] = msg.message_id
            return ST_QUICK_EDIT_VALUE
        quick_tx['amount'] = amt
        context.user_data["quick_tx"] = quick_tx
    
    elif field == "comment":
        comment = (update.message.text or "").strip()
        quick_tx['comment'] = comment
        context.user_data["quick_tx"] = quick_tx
    
    # Возвращаемся в меню редактирования (не сразу к подтверждению!)
    await update.effective_chat.send_message(
        "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_quick_edit(quick_tx)
    )
    
    return ST_QUICK_EDIT_FIELD


async def quick_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа при редактировании"""
    q = update.callback_query
    await q.answer()
    
    action = q.data.split(":")[1]
    
    if action == "back":
        quick_tx = context.user_data.get("quick_tx", {})
        await q.edit_message_text(
            "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_quick_edit(quick_tx)
        )
        return ST_QUICK_EDIT_FIELD
    
    quick_tx = context.user_data.get("quick_tx", {})
    old_type = quick_tx.get('type')
    new_type = "расход" if action == "expense" else "доход"
    
    quick_tx['type'] = new_type
    
    # Если тип изменился, сбрасываем категорию и подкатегорию
    if old_type != new_type:
        quick_tx['category'] = '?'
        quick_tx['subcategory'] = ''
    
    context.user_data["quick_tx"] = quick_tx
    
    # Возвращаемся в меню редактирования
    await q.edit_message_text(
        "<b>Что хочешь изменить?</b>\n\nНажми на поле для редактирования:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_quick_edit(quick_tx)
    )
    
    return ST_QUICK_EDIT_FIELD


async def quick_confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена быстрой транзакции"""
    q = update.callback_query
    await q.answer()
    
    await q.edit_message_text("Отменено ❌")
    
    # Очищаем данные
    context.user_data.pop("quick_tx", None)
    context.user_data.pop("quick_edit_field", None)  # ВАЖНО!
    
    # Показываем главный экран
    txt_month = await month_screen_text()
    await update.effective_chat.send_message(
        txt_month,
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML
    )
    
    return ST_MENU


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text(DENY_TEXT)
        return
    await update.message.reply_text(
        "🎯 <b>Быстрый ввод</b>\n"
        "Просто напиши одной строкой:\n"
        "• <i>продукты 1500</i>\n"
        "• <i>кафе 800 обед с другом</i>\n"
        "• <i>муж 50000</i>\n\n"
        "📋 <b>Или используй кнопки:</b>\n"
        "• Внести транзакцию\n"
        "• Скорректировать записи\n"
        "• Анализ\n"
        "• Установить баланс",
        parse_mode=ParseMode.HTML
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
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quick_input),
        ],
        states={
            ST_MENU: [
                CallbackQueryHandler(on_menu, pattern=r"^menu:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quick_input),
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
            ST_QUICK_CONFIRM: [
                CallbackQueryHandler(quick_category_selected, pattern=r"^quickcat:\d+$"),
                CallbackQueryHandler(quick_confirm_save, pattern=r"^quick:save$"),
                CallbackQueryHandler(quick_edit_menu, pattern=r"^quick:edit$"),
                CallbackQueryHandler(quick_confirm_cancel, pattern=r"^quick:cancel$"),
            ],
            ST_QUICK_EDIT_FIELD: [
                CallbackQueryHandler(quick_edit_field_selected, pattern=r"^quickedit:"),
            ],
            ST_QUICK_EDIT_VALUE: [
                CallbackQueryHandler(quick_type_selected, pattern=r"^quicktype:"),
                CallbackQueryHandler(expense_category, pattern=r"^expcat:\d+$"),
                CallbackQueryHandler(expense_subcategory, pattern=r"^expsub:\d+$"),
                CallbackQueryHandler(income_category, pattern=r"^inccat:\d+$"),
                CallbackQueryHandler(back_router, pattern=r"^back:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, quick_edit_value_received),
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
