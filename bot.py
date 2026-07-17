import json
import os
import random
import time
import html
import asyncio
from datetime import datetime, timedelta
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)

# ============================ КОНФИГУРАЦИЯ ============================
TOKEN = input("Введите токен бота: ")
CHANNEL_ID = "-1002899939309"
CHANNEL_LINK = "https://t.me/cabakoff"
ADMIN_ID = 1106828306

# ============================ ЕЖЕДНЕВНАЯ НАГРАДА ============================
DAILY_COINS_AMOUNT = 50
DAILY_CARD_CHANCE = 0.25  # 25% шанс получить случайную карточку вместе с монетами
DAILY_COOLDOWN_SECONDS = 24 * 60 * 60

# ============================ ПУТИ К ФАЙЛАМ ============================
CARDS_FILE = "cards.json"
USERS_FILE = "users.json"
BLACKLIST_FILE = "blacklist.json"
MODERATORS_FILE = "moderators.json"
COINS_FILE = "coins.json"
RARITIES_FILE = "rarities.json"
SHOP_FILE = "shop.json"
PROMOCODES_FILE = "promocodes.json"
EVENTS_FILE = "events.json"
BETS_FILE = "bets.json"
CARDS_IMAGE_DIR = "cards_images"

# ============================ СОСТОЯНИЯ ============================
ADMIN_CARD_NAME, ADMIN_CARD_RARITY, ADMIN_CARD_DESCRIPTION, ADMIN_CARD_IMAGE = range(4)
ADMIN_SHOP_NAME, ADMIN_SHOP_TYPE, ADMIN_SHOP_PRICE, ADMIN_SHOP_CARDS, ADMIN_SHOP_DURATION = range(5)
ADMIN_RARITY_NAME, ADMIN_RARITY_EMOJI, ADMIN_RARITY_DROPPABLE = range(3)
EDIT_CARD_SELECT, EDIT_CARD_FIELD, EDIT_CARD_VALUE = range(3)
CRAFT_SELECT_CARDS = range(1)

# Промокоды
PROMO_NAME, PROMO_TYPE, PROMO_VALUE, PROMO_USES, PROMO_DURATION = range(5)

# Рейтинговый режим
RATING_TEAM_GK, RATING_TEAM_FIELD = range(2)

# ============================ ЛОГГИРОВАНИЕ ============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ========================
def load_data(filename, default=None):
    if default is None:
        default = {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_data(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_banned(user_id: int) -> bool:
    blacklist = load_data(BLACKLIST_FILE, [])
    return user_id in blacklist

async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def is_moderator(user_id: int) -> bool:
    moderators = load_data(MODERATORS_FILE, [])
    return user_id in moderators

def has_admin_access(user_id: int) -> bool:
    return is_admin(user_id) or is_moderator(user_id)

def get_rarity_emoji(rarity_name: str) -> str:
    rarities = load_data(RARITIES_FILE, [])
    for rarity in rarities:
        if rarity["name"] == rarity_name:
            return rarity["emoji"]
    emoji_map = {
        "Легендарная": "🔥",
        "Эксклюзивная": "😎",
        "Блещет умом": "🧠",
        "Эпическая": "💎",
        "Редкая": "✨",
        "Обычная": "🃏"
    }
    return emoji_map.get(rarity_name, "🃏")

async def show_collection_with_ids(user_id: int) -> str:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_cards = user_data.get("cards", [])
    if not user_cards:
        return "📭 Ваша коллекция пуста!"
    all_cards = load_data(CARDS_FILE, [])
    rarities = load_data(RARITIES_FILE, [])
    card_counts = {}
    for card_id in user_cards:
        card_counts[card_id] = card_counts.get(card_id, 0) + 1
    grouped = {}
    for card in all_cards:
        card_id = card["id"]
        if card_id in card_counts:
            if card["rarity"] not in grouped:
                grouped[card["rarity"]] = []
            grouped[card["rarity"]].append((card, card_counts[card_id]))
    rarity_order = [r["name"] for r in rarities] + ["Легендарная", "Блещет умом", "Эпическая", "Редкая", "Обычная", "Эксклюзивная"]
    unique_rarities = list(set(grouped.keys()))
    sorted_rarities = sorted(unique_rarities, key=lambda r: rarity_order.index(r) if r in rarity_order else len(rarity_order))
    message = "🃏 <b>Ваша коллекция карточек</b>:\n\n"
    total_count = 0
    for rarity in sorted_rarities:
        cards_in_rarity = grouped[rarity]
        count_in_rarity = sum(count for _, count in cards_in_rarity)
        total_count += count_in_rarity
        emoji = get_rarity_emoji(rarity)
        message += f"{emoji} <b>{rarity}</b> ({count_in_rarity}):\n"
        sorted_cards = sorted(cards_in_rarity, key=lambda x: x[0]['id'])
        for card, count in sorted_cards:
            count_text = f" (x{count})" if count > 1 else ""
            message += f"   • {html.escape(card['name'])}{count_text} [ID: {card['id']}]\n"
        message += "\n"
    message += f"📚 <b>Всего карточек: {total_count}</b>"
    return message

def get_coins(user_id: int) -> int:
    coins_data = load_data(COINS_FILE, {})
    return coins_data.get(str(user_id), 0)

def update_coins(user_id: int, amount: int) -> int:
    coins_data = load_data(COINS_FILE, {})
    current = coins_data.get(str(user_id), 0)
    new_amount = max(0, current + amount)
    coins_data[str(user_id)] = new_amount
    save_data(COINS_FILE, coins_data)
    return new_amount

# Streak для казино и монетки
def get_casino_streak(user_id: int) -> int:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    return user_data.get("casino_streak", 0)

def set_casino_streak(user_id: int, streak: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_data["casino_streak"] = streak
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

def get_coin_streak(user_id: int) -> int:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    return user_data.get("coin_streak", 0)

def set_coin_streak(user_id: int, streak: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_data["coin_streak"] = streak
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

# ============================ БАФФЫ ============================
def get_active_buff(user_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    return user_data.get("buff_card", None)

def set_active_buff(user_id: int, card_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_data["buff_card"] = {"card_id": card_id, "level": 1}
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

def update_buff_level(user_id: int, new_level: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    if "buff_card" in user_data:
        user_data["buff_card"]["level"] = new_level
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)

def clear_active_buff(user_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    if "buff_card" in user_data:
        del user_data["buff_card"]
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)

def get_cooldown_multiplier(user_id: int) -> float:
    buff = get_active_buff(user_id)
    if not buff:
        return 1.0
    level = buff["level"]
    reduction = min(level * 5, 80)
    return 1.0 - reduction / 100.0

def get_coin_bonus_multiplier(user_id: int) -> float:
    buff = get_active_buff(user_id)
    if not buff:
        return 1.0
    level = buff["level"]
    bonus = level * 5
    return 1.0 + bonus / 100.0

def is_legendary_or_higher(rarity: str) -> bool:
    return rarity in ["Легендарная", "Блещет умом", "Эксклюзивная"]

# ============================ РЕЙТИНГОВЫЙ РЕЖИМ: СИЛА КАРТОЧЕК ============================
RARITY_POWER = {
    "Эксклюзивная": 110,
    "Легендарная": 100,
    "Блещет умом": 90,
    "Эпическая": 70,
    "Редкая": 50,
    "Обычная": 30
}
DEFAULT_CARD_POWER = 40

def get_card_power(card: dict) -> int:
    return RARITY_POWER.get(card.get("rarity"), DEFAULT_CARD_POWER)

def get_rating_elo(user_id: int) -> int:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    return user_data.get("rating_elo", 1000)

def set_rating_elo(user_id: int, elo: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_data["rating_elo"] = elo
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

def get_rating_team(user_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    return user_data.get("rating_team")

def set_rating_team(user_id: int, gk_id: int, field_ids: list):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_data["rating_team"] = {"gk": gk_id, "field": field_ids}
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

# ======================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПРОФИЛЯ ========================
def add_seen_card(user_id: int, card_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    if "seen_cards" not in user_data:
        user_data["seen_cards"] = []
    if card_id not in user_data["seen_cards"]:
        user_data["seen_cards"].append(card_id)
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)

# ============================ ОСНОВНЫЕ КОМАНДЫ ============================

USER_COMMANDS_TEXT = (
    "📋 Основные команды:\n"
    "/get_card - получить карточку\n"
    "/my_cards - моя коллекция\n"
    "/shop - магазин\n"
    "/givecard <user_id> <card_id> - передать карточку\n"
    "/balance - баланс монет\n"
    "/card_info <card_id> - информация о карточке\n"
    "/craft - улучшить карточки\n"
    "/leaderboard - таблица лидеров\n"
    "/casino <сумма> - сыграть в казино\n"
    "/coin <орел|решка> <сумма> - подбросить монетку\n"
    "/buff - информация о баффе\n"
    "/set_buff <card_id> - выбрать карту для баффа\n"
    "/upgrade_buff - улучшить бафф\n"
    "/redeem <код> - активировать промокод\n"
    "/profile - ваш профиль\n"
    "/bet - сделать ставку (инлайн-меню)\n"
    "/my_bets - мои ставки\n"
    "/daily - забрать ежедневную награду\n"
    "/rating_team - собрать состав для рейтингового режима\n"
    "/find_match - найти соперника (рейтинговый режим)\n"
    "/rating - мой рейтинг и текущий состав\n\n"
    "⏳ Карточку можно получать каждые 6 часов!"
)

ADMIN_ONLY_COMMANDS_TEXT = (
    "/admin_addcard - добавить карточку\n"
    "/admin_listcards - список всех карточек\n"
    "/admin_deletecard <card_id> - удалить карточку\n"
    "/admin_resettimer <user_id> - сбросить таймер\n"
    "/admin_givecard <user_id> <card_id> - выдать карточку\n"
    "/admin_broadcast <message> - сделать рассылку\n"
    "/ban <user_id> - заблокировать пользователя\n"
    "/unban <user_id> - разблокировать пользователя\n"
    "/add_moderator <user_id> - добавить модератора\n"
    "/remove_moderator <user_id> - удалить модератора\n"
    "/admin_givecoins <user_id> <amount> - выдать монеты\n"
    "/admin_removecoins <user_id> <amount> - забрать монеты\n"
    "/admin_addrarity - добавить редкость\n"
    "/admin_listrarities - список редкостей\n"
    "/admin_addshopitem - добавить товар в магазин\n"
    "/admin_listshop - список товаров\n"
    "/admin_editcard <card_id> - изменить карточку\n"
    "/create_promo - создать промокод\n"
    "/create_match <команда1> <команда2> <часы> - создать матч (приём ставок N часов)\n"
    "/finish_match <match_id> <счёт> - завершить матч (например 3:1)"
)

MODERATOR_ONLY_COMMANDS_TEXT = (
    "/admin_addcard - добавить карточку\n"
    "/admin_listcards - список всех карточек\n"
    "/admin_deletecard <card_id> - удалить карточку\n"
    "/admin_addrarity - добавить редкость\n"
    "/admin_listrarities - список редкостей\n"
    "/admin_addshopitem - добавить товар в магазин\n"
    "/admin_listshop - список товаров\n"
    "/admin_editcard <card_id> - изменить карточку\n"
    "/create_promo - создать промокод\n"
    "/create_match <команда1> <команда2> <часы> - создать матч (приём ставок N часов)\n"
    "/finish_match <match_id> <счёт> - завершить матч"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал!\n"
            f"Подпишитесь здесь: {CHANNEL_LINK}\n"
            "После подписки отправьте /start снова."
        )
        return

    users = load_data(USERS_FILE, {})
    is_new_user = str(user.id) not in users
    if is_new_user:
        users[str(user.id)] = {
            "cards": [],
            "last_drop": 0,
            "username": user.username,
            "casino_streak": 0,
            "coin_streak": 0,
            "seen_cards": []
        }
        save_data(USERS_FILE, users)
        coins_data = load_data(COINS_FILE, {})
        if str(user.id) not in coins_data:
            coins_data[str(user.id)] = 0
            save_data(COINS_FILE, coins_data)
        if not is_admin(user.id) and not is_moderator(user.id):
            await context.bot.send_message(
                ADMIN_ID,
                f"Новый пользователь: @{user.username} | ID: {user.id}"
            )
    else:
        user_data = users.get(str(user.id), {})
        if "casino_streak" not in user_data:
            user_data["casino_streak"] = 0
        if "coin_streak" not in user_data:
            user_data["coin_streak"] = 0
        if "seen_cards" not in user_data:
            user_data["seen_cards"] = []
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)

    # Все пользователи (включая админов/модераторов) видят обычные команды.
    # Админы и модераторы дополнительно видят свой набор команд.
    # ВАЖНО: тексты команд содержат плейсхолдеры вида "card_id", "user_id" в угловых скобках.
    # При parse_mode="HTML" Telegram пытается разобрать их как теги и падает,
    # поэтому текст экранируем через html.escape(), а настоящие теги <b> добавляем уже поверх.
    if is_admin(user.id):
        await update.message.reply_text(
            "👑 Вы администратор.\n\n"
            "🛠 <b>Админские команды:</b>\n" + html.escape(ADMIN_ONLY_COMMANDS_TEXT) + "\n\n"
            "👤 <b>Обычные команды:</b>\n" + html.escape(USER_COMMANDS_TEXT),
            parse_mode="HTML"
        )
    elif is_moderator(user.id):
        await update.message.reply_text(
            "🛡 Вы модератор.\n\n"
            "🛠 <b>Модераторские команды:</b>\n" + html.escape(MODERATOR_ONLY_COMMANDS_TEXT) + "\n\n"
            "👤 <b>Обычные команды:</b>\n" + html.escape(USER_COMMANDS_TEXT),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "🎮 Добро пожаловать в REKHL CARDS!\n\n" + USER_COMMANDS_TEXT
        )

# Выдача карточки (с баффами и seen_cards)
async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return

    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    current_time = time.time()
    last_drop = user_data.get("last_drop", 0)
    base_cooldown = 6 * 3600
    cooldown_multiplier = get_cooldown_multiplier(user.id)
    effective_cooldown = base_cooldown * cooldown_multiplier
    time_left = effective_cooldown - (current_time - last_drop)
    if time_left > 0:
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        if hours > 0:
            time_text = f"{hours} час(ов) и {minutes} минут(ы)"
        else:
            time_text = f"{minutes} минут(ы)"
        await update.message.reply_text(f"⏳ Следующую карточку можно получить через: {time_text}")
        return

    # Загружаем редкости
    rarities = load_data(RARITIES_FILE, [])
    if not rarities:
        # Если файл пуст – создаём стандартные
        default_rarities = [
            {"name": "Легендарная", "emoji": "🔥", "droppable": True},
            {"name": "Блещет умом", "emoji": "🧠", "droppable": True},
            {"name": "Эпическая", "emoji": "💎", "droppable": True},
            {"name": "Редкая", "emoji": "✨", "droppable": True},
            {"name": "Обычная", "emoji": "🃏", "droppable": True},
            {"name": "Эксклюзивная", "emoji": "😎", "droppable": False}
        ]
        save_data(RARITIES_FILE, default_rarities)
        rarities = default_rarities

    droppable_rarities = [r["name"] for r in rarities if r.get("droppable", True)]
    all_cards = load_data(CARDS_FILE, [])
    cards = [c for c in all_cards if c["rarity"] in droppable_rarities]

    if not cards:
        # Если нет выпадаемых – используем все карточки (fallback)
        if all_cards:
            cards = all_cards
            logger.warning("Нет выпадаемых карточек, используем все карточки.")
        else:
            await update.message.reply_text("⚠️ В базе нет ни одной карточки! Обратитесь к администратору.")
            return

    RARITY_CHANCES = {
        "Легендарная": 0.05,
        "Блещет умом": 0.07,
        "Эпическая": 0.15,
        "Редкая": 0.3,
        "Обычная": 0.5
    }
    rarities_list = list(RARITY_CHANCES.keys())
    weights = [RARITY_CHANCES[r] for r in rarities_list]
    chosen_rarity = random.choices(rarities_list, weights=weights, k=1)[0]
    rarity_cards = [c for c in cards if c["rarity"] == chosen_rarity]
    if not rarity_cards:
        logger.warning(f"Для редкости '{chosen_rarity}' нет карточек! Пробуем другие редкости.")
        for rarity in rarities_list:
            rarity_cards = [c for c in cards if c["rarity"] == rarity]
            if rarity_cards:
                logger.info(f"Нашли карточки для редкости: {rarity}")
                break
    if not rarity_cards:
        logger.error("В базе нет карточек ни для одной редкости!")
        await update.message.reply_text("⚠️ Ошибка в базе карточек! Обратитесь к администратору.")
        return

    card = random.choice(rarity_cards)
    if "cards" not in user_data:
        user_data["cards"] = []
    user_data["cards"].append(card["id"])
    user_data["last_drop"] = current_time
    users[str(user.id)] = user_data
    save_data(USERS_FILE, users)  # сначала сохраняем cards

    # Теперь добавляем seen_card (отдельно, чтобы не перезаписать)
    add_seen_card(user.id, card["id"])

    base_coins = random.randint(10, 50)
    coin_multiplier = get_coin_bonus_multiplier(user.id)
    coins_earned = int(base_coins * coin_multiplier)
    new_balance = update_coins(user.id, coins_earned)
    card_count = user_data["cards"].count(card["id"])
    count_text = f" (x{card_count})" if card_count > 1 else ""

    caption = (
        f"🎉 Вы получили карточку!\n\n"
        f"🏷 Название: {card['name']}{count_text}\n"
        f"⭐ Редкость: {card['rarity']}\n"
    )
    if "description" in card:
        caption += f"📝 Описание: {card['description']}\n"
    caption += (
        f"💰 Получено монет: +{coins_earned}\n"
        f"💰 Ваш баланс: {new_balance}\n\n"
        f"📚 Теперь в вашей коллекции: {len(user_data['cards'])}"
    )
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        await update.message.reply_photo(photo=open(image_path, "rb"), caption=caption)
    else:
        logger.warning(f"Изображение карточки не найдено: {image_path}")
        await update.message.reply_text(caption)

# Показ коллекции
async def show_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    message = await show_collection_with_ids(user.id)
    if len(message) > 4000:
        parts = []
        current = ""
        for line in message.split("\n"):
            if len(current) + len(line) < 4000:
                current += line + "\n"
            else:
                parts.append(current)
                current = line + "\n"
        if current:
            parts.append(current)
        for part in parts:
            await update.message.reply_text(part, parse_mode="HTML")
    else:
        await update.message.reply_text(message, parse_mode="HTML")

# Информация о карточке
async def card_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /card_info <ID карточки>")
        return
    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")
        return
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    if card_id not in user_data.get("cards", []):
        await update.message.reply_text("❌ У вас нет этой карточки в коллекции!")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена в базе данных!")
        return
    emoji = get_rarity_emoji(card["rarity"])
    caption = (
        f"🃏 <b>Информация о карточке</b>\n\n"
        f"🏷 <b>Название</b>: {card['name']}\n"
        f"{emoji} <b>Редкость</b>: {card['rarity']}\n"
    )
    if "description" in card:
        caption += f"📝 <b>Описание</b>: {card['description']}\n"
    card_count = user_data["cards"].count(card_id)
    caption += f"📊 <b>В вашей коллекции</b>: {card_count} шт.\n"
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        await update.message.reply_photo(photo=open(image_path, "rb"), caption=caption, parse_mode="HTML")
    else:
        logger.warning(f"Изображение карточки не найдено: {image_path}")
        await update.message.reply_text(caption, parse_mode="HTML")

# Баланс
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    balance = get_coins(user.id)
    await update.message.reply_text(f"💰 Ваш баланс: {balance} монет")

# ============================ ЕЖЕДНЕВНАЯ НАГРАДА ============================
async def daily_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return

    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    last_daily = user_data.get("last_daily", 0)
    current_time = time.time()
    elapsed = current_time - last_daily

    if elapsed < DAILY_COOLDOWN_SECONDS:
        remaining = DAILY_COOLDOWN_SECONDS - elapsed
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        await update.message.reply_text(
            f"⏳ Вы уже забирали ежедневную награду.\n"
            f"Следующая награда будет доступна через: {hours}ч {minutes}мин"
        )
        return

    # Начисляем фиксированные монеты
    new_balance = update_coins(user.id, DAILY_COINS_AMOUNT)

    # Обновляем дату последнего получения
    user_data["last_daily"] = current_time
    users[str(user.id)] = user_data
    save_data(USERS_FILE, users)

    message = (
        f"🎁 <b>Ежедневная награда получена!</b>\n\n"
        f"💰 +{DAILY_COINS_AMOUNT} монет\n"
        f"💰 Новый баланс: {new_balance} монет\n"
    )

    # Шанс дополнительно получить случайную карточку
    if random.random() < DAILY_CARD_CHANCE:
        rarities = load_data(RARITIES_FILE, [])
        droppable_rarities = [r["name"] for r in rarities if r.get("droppable", True)]
        all_cards = load_data(CARDS_FILE, [])
        droppable_cards = [c for c in all_cards if c["rarity"] in droppable_rarities]
        if not droppable_cards:
            droppable_cards = all_cards
        if droppable_cards:
            card = random.choice(droppable_cards)
            user_data = users.get(str(user.id), {})
            if "cards" not in user_data:
                user_data["cards"] = []
            user_data["cards"].append(card["id"])
            users[str(user.id)] = user_data
            save_data(USERS_FILE, users)
            add_seen_card(user.id, card["id"])
            message += (
                f"\n🃏 Бонус! Вам выпала карточка:\n"
                f"🏷 {card['name']} ({get_rarity_emoji(card['rarity'])} {card['rarity']})"
            )

    await update.message.reply_text(message, parse_mode="HTML")

# Магазин
async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    shop_items = load_data(SHOP_FILE, [])
    current_time = time.time()
    active_items = [item for item in shop_items if item.get("expire_time", 0) == 0 or item["expire_time"] > current_time]
    save_data(SHOP_FILE, active_items)
    if not active_items:
        await update.message.reply_text("🛒 Магазин пуст! Загляните позже.")
        return
    message = "🛒 Товары в магазине\n\n"
    for item in active_items:
        message += f"🆔 ID: {item['id']}\n"
        message += f"🏷 Название: {item['name']}\n"
        message += f"💵 Цена: {item['price']} монет\n"
        if item.get("expire_time", 0) > 0:
            time_left = item["expire_time"] - current_time
            if time_left > 0:
                hours = int(time_left // 3600)
                minutes = int((time_left % 3600) // 60)
                message += f"⏳ Осталось: {hours}ч {minutes}мин\n"
        if item["type"] == "reset":
            message += "📝 Тип: Сброс таймера получения карточки\n\n"
        elif item["type"] == "pack":
            message += "📝 Тип: Набор карточек\n"
            message += f"🃏 Карточек в наборе: {len(item['cards'])}\n\n"
    message += "ℹ️ Для покупки используйте /buy <ID товара>"
    if len(message) > 4000:
        parts = []
        while message:
            if len(message) <= 4000:
                parts.append(message)
                break
            last_newline = message[:4000].rfind('\n')
            if last_newline == -1:
                parts.append(message[:4000])
                message = message[4000:]
            else:
                parts.append(message[:last_newline])
                message = message[last_newline+1:]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(message)

# Покупка
async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /buy <ID товара>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID товара! Используйте только цифры.")
        return
    shop_items = load_data(SHOP_FILE, [])
    item = next((i for i in shop_items if i["id"] == item_id), None)
    if not item:
        await update.message.reply_text("❌ Товар не найден!")
        return
    current_time = time.time()
    if item.get("expire_time", 0) > 0 and item["expire_time"] < current_time:
        await update.message.reply_text("❌ Срок действия этого товара истек!")
        return
    balance = get_coins(user.id)
    if balance < item["price"]:
        await update.message.reply_text("❌ Недостаточно монет для покупки!")
        return
    new_balance = update_coins(user.id, -item["price"])
    if item["type"] == "reset":
        users = load_data(USERS_FILE, {})
        user_data = users.get(str(user.id), {})
        user_data["last_drop"] = 0
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        await update.message.reply_text(
            f"✅ Таймер успешно сброшен!\n"
            f"💰 Потрачено: {item['price']} монет\n"
            f"💰 Остаток: {new_balance} монет\n\n"
            f"Теперь вы можете получить карточку с помощью /get_card"
        )
    elif item["type"] == "pack":
        users = load_data(USERS_FILE, {})
        user_data = users.get(str(user.id), {})
        if "cards" not in user_data:
            user_data["cards"] = []
        card_id = random.choice(item["cards"])
        user_data["cards"].append(card_id)
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        add_seen_card(user.id, card_id)  # после сохранения
        cards = load_data(CARDS_FILE, [])
        card = next((c for c in cards if c["id"] == card_id), None)
        if card:
            card_name = card["name"]
            card_rarity = card["rarity"]
            emoji = get_rarity_emoji(card_rarity)
        else:
            card_name = f"Карточка ID {card_id}"
            card_rarity = "Неизвестная"
            emoji = "❓"
        card_count = user_data["cards"].count(card_id)
        count_text = f" (x{card_count})" if card_count > 1 else ""
        await update.message.reply_text(
            f"✅ Вы успешно приобрели набор карточек!\n"
            f"🎁 Полученная карточка:\n"
            f"<b>{emoji} {card_rarity}</b>: {card_name}{count_text}\n\n"
            f"💰 Потрачено: {item['price']} монет\n"
            f"💰 Остаток: {new_balance} монет\n\n"
            f"Просмотреть коллекцию: /my_cards",
            parse_mode="HTML"
        )

# Проверка подписки
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if is_banned(user.id):
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        warn_msg = await message.reply_text("❌ Вы заблокированы в этом боте.")
        time.sleep(5)
        await context.bot.delete_message(chat_id=message.chat_id, message_id=warn_msg.message_id)
        return
    if not await is_subscribed(user.id, context):
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        warn_msg = await message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал!\n"
            f"Подпишитесь здесь: {CHANNEL_LINK}\n"
            "После подписки отправьте /start"
        )
        time.sleep(10)
        await context.bot.delete_message(chat_id=message.chat_id, message_id=warn_msg.message_id)

# ============================ АДМИН-КОМАНДЫ ============================
async def admin_addcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    await update.message.reply_text("Введите название новой карточки:")
    return ADMIN_CARD_NAME

async def admin_card_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_card"] = {"name": update.message.text}
    rarities = load_data(RARITIES_FILE, [])
    if not rarities:
        await update.message.reply_text("❌ Сначала добавьте редкости с помощью /admin_addrarity")
        return ConversationHandler.END
    rarities_text = "\n".join([f"{r['emoji']} {r['name']}" for r in rarities])
    await update.message.reply_text(
        f"Выберите редкость карточки из списка:\n\n{rarities_text}\n\n"
        "Введите название редкости:"
    )
    return ADMIN_CARD_RARITY

async def admin_card_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    rarity = update.message.text.strip()
    rarities = load_data(RARITIES_FILE, [])
    if rarity not in [r["name"] for r in rarities]:
        await update.message.reply_text("❌ Редкость не найдена! Введите существующую редкость.")
        return ADMIN_CARD_RARITY
    context.user_data["new_card"]["rarity"] = rarity
    await update.message.reply_text("Введите описание карточки:")
    return ADMIN_CARD_DESCRIPTION

async def admin_card_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_card"]["description"] = update.message.text
    await update.message.reply_text("Отправьте изображение карточки (фото):")
    return ADMIN_CARD_IMAGE

async def admin_card_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text("❌ Пожалуйста, отправьте изображение карточки!")
        return ADMIN_CARD_IMAGE
    photo = update.message.photo[-1]
    file = await photo.get_file()
    os.makedirs(CARDS_IMAGE_DIR, exist_ok=True)
    filename = f"{int(time.time())}.jpg"
    image_path = os.path.join(CARDS_IMAGE_DIR, filename)
    await file.download_to_drive(image_path)
    new_card = context.user_data["new_card"]
    cards = load_data(CARDS_FILE, [])
    new_id = max(card["id"] for card in cards) + 1 if cards else 1
    new_card["id"] = new_id
    new_card["image"] = filename
    cards.append(new_card)
    save_data(CARDS_FILE, cards)
    await update.message.reply_text(f"✅ Карточка '{new_card['name']}' успешно добавлена!")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_addcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление карточки отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_listcards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
    cards = load_data(CARDS_FILE, [])
    if not cards:
        await update.message.reply_text("ℹ️ Карточек нет в базе данных.")
        return
    sorted_cards = sorted(cards, key=lambda x: x["id"])
    message = "<b>Список всех карточек:</b>\n\n"
    for card in sorted_cards:
        emoji = get_rarity_emoji(card["rarity"])
        message += f"{card['id']}. {html.escape(card['name'])} ({emoji} {card['rarity']})\n"
    if len(message) > 4000:
        parts = []
        while message:
            if len(message) <= 4000:
                parts.append(message)
                break
            split_index = message[:4000].rfind('\n')
            if split_index == -1:
                split_index = 4000
            parts.append(message[:split_index])
            message = message[split_index:]
        for part in parts:
            await update.message.reply_text(part, parse_mode="HTML")
    else:
        await update.message.reply_text(message, parse_mode="HTML")

async def admin_deletecard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите ID карточки: /admin_deletecard <card_id>")
        return
    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")
        return

    cards = load_data(CARDS_FILE, [])
    card_index = next((i for i, c in enumerate(cards) if c["id"] == card_id), -1)
    if card_index == -1:
        await update.message.reply_text("❌ Карточка не найдена!")
        return

    # Удаляем изображение
    card = cards[card_index]
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        try:
            os.remove(image_path)
        except Exception as e:
            logger.error(f"Ошибка удаления изображения: {e}")

    # Удаляем карточку из базы
    del cards[card_index]
    save_data(CARDS_FILE, cards)

    # Удаляем карточку у всех пользователей (из коллекций)
    users = load_data(USERS_FILE, {})
    for uid, user_data in users.items():
        if "cards" in user_data and card_id in user_data["cards"]:
            user_data["cards"] = [c for c in user_data["cards"] if c != card_id]
            users[uid] = user_data
    save_data(USERS_FILE, users)

    await update.message.reply_text(f"✅ Карточка '{card['name']}' (ID: {card_id}) удалена из базы и из коллекций всех пользователей.")

async def admin_resettimer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /admin_resettimer <user_id>")
        return
    try:
        user_id = int(context.args[0])
        users = load_data(USERS_FILE, {})
        if str(user_id) not in users:
            await update.message.reply_text("❌ Пользователь не найден!")
            return
        users[str(user_id)]["last_drop"] = 0
        save_data(USERS_FILE, users)
        await update.message.reply_text(f"✅ Таймер пользователя {user_id} сброшен!")
        try:
            await context.bot.send_message(
                user_id,
                "⏱ Администратор сбросил ваш таймер!\n"
                "Теперь вы можете получить новую карточку сразу с помощью /get_card"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

async def admin_givecard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Укажите ID пользователя и ID карточки: /admin_givecard <user_id> <card_id>")
        return
    try:
        user_id = int(context.args[0])
        card_id = int(context.args[1])
        users = load_data(USERS_FILE, {})
        cards = load_data(CARDS_FILE, [])
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await update.message.reply_text("❌ Карточка не найдена!")
            return
        if str(user_id) not in users:
            users[str(user_id)] = {"cards": [], "last_drop": 0}
        users[str(user_id)]["cards"].append(card_id)
        save_data(USERS_FILE, users)
        add_seen_card(user_id, card_id)  # добавляем в seen_cards
        card_count = users[str(user_id)]["cards"].count(card_id)
        count_text = f" (x{card_count})" if card_count > 1 else ""
        await update.message.reply_text(f"✅ Карточка '{card['name']}{count_text}' выдана пользователю {user_id}!")
        try:
            await context.bot.send_message(
                user_id,
                f"🎁 Администратор выдал вам карточку!\n\n"
                f"🏷 Название: {card['name']}{count_text}\n"
                f"⭐ Редкость: {card['rarity']}\n"
                f"📝 Описание: {card.get('description', 'Отсутствует')}"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID!")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите сообщение для рассылки: /admin_broadcast <сообщение>")
        return
    message = " ".join(context.args)
    users = load_data(USERS_FILE, {})
    blacklist = load_data(BLACKLIST_FILE, [])
    count = 0
    errors = 0
    for user_id in users:
        uid = int(user_id)
        if uid in blacklist:
            continue
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 Рассылка от администратора:\n\n{message}")
            count += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки для {user_id}: {e}")
            errors += 1
    await update.message.reply_text(f"✅ Рассылка завершена!\nОтправлено: {count} пользователям\nОшибок: {errors}")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /ban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        if user_id == ADMIN_ID:
            await update.message.reply_text("❌ Нельзя заблокировать администратора!")
            return
        blacklist = load_data(BLACKLIST_FILE, [])
        if user_id in blacklist:
            await update.message.reply_text("ℹ️ Этот пользователь уже заблокирован.")
            return
        blacklist.append(user_id)
        save_data(BLACKLIST_FILE, blacklist)
        await update.message.reply_text(f"✅ Пользователь {user_id} заблокирован!")
        try:
            await context.bot.send_message(
                user_id,
                "⛔ Вы были заблокированы в этом боте администратором.\n"
                "Теперь вы не можете использовать команды бота."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        blacklist = load_data(BLACKLIST_FILE, [])
        if user_id not in blacklist:
            await update.message.reply_text("ℹ️ Этот пользователь не заблокирован.")
            return
        blacklist.remove(user_id)
        save_data(BLACKLIST_FILE, blacklist)
        await update.message.reply_text(f"✅ Пользователь {user_id} разблокирован!")
        try:
            await context.bot.send_message(
                user_id,
                "🎉 Вы были разблокированы администратором!\n"
                "Теперь вы снова можете использовать команды бота."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

async def add_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /add_moderator <user_id>")
        return
    try:
        user_id = int(context.args[0])
        moderators = load_data(MODERATORS_FILE, [])
        if user_id in moderators:
            await update.message.reply_text("ℹ️ Этот пользователь уже является модератором.")
            return
        moderators.append(user_id)
        save_data(MODERATORS_FILE, moderators)
        await update.message.reply_text(f"✅ Пользователь {user_id} теперь модератор!")
        try:
            await context.bot.send_message(
                user_id,
                "🎉 Вам были выданы права модератора!\n"
                "Теперь вы можете использовать специальные команды."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

async def remove_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /remove_moderator <user_id>")
        return
    try:
        user_id = int(context.args[0])
        moderators = load_data(MODERATORS_FILE, [])
        if user_id not in moderators:
            await update.message.reply_text("ℹ️ Этот пользователь не является модератором.")
            return
        moderators.remove(user_id)
        save_data(MODERATORS_FILE, moderators)
        await update.message.reply_text(f"✅ Пользователь {user_id} больше не модератор!")
        try:
            await context.bot.send_message(
                user_id,
                "ℹ️ У вас были отозваны права модератора."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

async def admin_givecoins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Укажите ID пользователя и количество монет: /admin_givecoins <user_id> <amount>")
        return
    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ Количество монет должно быть положительным числом!")
            return
        new_balance = update_coins(user_id, amount)
        await update.message.reply_text(f"✅ Пользователю {user_id} выдано {amount} монет!\n💰 Новый баланс: {new_balance}")
        try:
            await context.bot.send_message(
                user_id,
                f"🎉 Администратор выдал вам {amount} монет!\n"
                f"💰 Ваш новый баланс: {new_balance}"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат параметров! Используйте только цифры.")

async def admin_removecoins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Укажите ID пользователя и количество монет: /admin_removecoins <user_id> <amount>")
        return
    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ Количество монет должно быть положительным числом!")
            return
        new_balance = update_coins(user_id, -amount)
        await update.message.reply_text(f"✅ У пользователя {user_id} изъято {amount} монет!\n💰 Новый баланс: {new_balance}")
        try:
            await context.bot.send_message(
                user_id,
                f"ℹ️ Администратор изъял у вас {amount} монет.\n"
                f"💰 Ваш новый баланс: {new_balance}"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат параметров! Используйте только цифры.")

# Редкости
async def admin_addrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    await update.message.reply_text("Введите название новой редкости:")
    return ADMIN_RARITY_NAME

async def admin_rarity_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_rarity"] = {"name": update.message.text}
    await update.message.reply_text("Введите смайлик для этой редкости:")
    return ADMIN_RARITY_EMOJI

async def admin_rarity_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_rarity"]["emoji"] = update.message.text
    await update.message.reply_text(
        "Могут ли карточки этой редкости выпадать через /get_card?\n"
        "1 - Да, 0 - Нет:"
    )
    return ADMIN_RARITY_DROPPABLE

async def admin_rarity_droppable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        droppable = int(update.message.text)
        if droppable not in [0, 1]:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Неверный формат! Введите 1 или 0.")
        return ADMIN_RARITY_DROPPABLE
    new_rarity = context.user_data["new_rarity"]
    new_rarity["droppable"] = bool(droppable)
    rarities = load_data(RARITIES_FILE, [])
    rarities.append(new_rarity)
    save_data(RARITIES_FILE, rarities)
    await update.message.reply_text(
        f"✅ Редкость '{new_rarity['name']}' успешно добавлена!\n"
        f"Смайлик: {new_rarity['emoji']}\n"
        f"Выпадает через /get_card: {'Да' if new_rarity['droppable'] else 'Нет'}"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_addrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление редкости отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_listrarities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
    rarities = load_data(RARITIES_FILE, [])
    if not rarities:
        await update.message.reply_text("ℹ️ Редкостей нет в базе данных.")
        return
    message = "<b>Список всех редкостей:</b>\n\n"
    for rarity in rarities:
        message += (
            f"{rarity['emoji']} <b>Название</b>: {html.escape(rarity['name'])}\n"
            f"📦 Выпадает через /get_card: {'Да' if rarity.get('droppable', True) else 'Нет'}\n\n"
        )
    await update.message.reply_text(message, parse_mode="HTML")

# Магазин админ
async def admin_addshopitem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    await update.message.reply_text("Введите название товара:")
    return ADMIN_SHOP_NAME

async def admin_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_shop_item"] = {"name": update.message.text}
    keyboard = [
        [InlineKeyboardButton("Сброс таймера", callback_data="reset")],
        [InlineKeyboardButton("Набор карточек", callback_data="pack")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите тип товара:", reply_markup=reply_markup)
    return ADMIN_SHOP_TYPE

async def admin_shop_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    item_type = query.data
    context.user_data["new_shop_item"]["type"] = item_type
    await query.edit_message_text(
        f"Тип товара: {'Сброс таймера' if item_type == 'reset' else 'Набор карточек'}\n\n"
        "Введите цену товара:"
    )
    return ADMIN_SHOP_PRICE

async def admin_shop_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = int(update.message.text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Неверный формат цены! Введите положительное число.")
        return ADMIN_SHOP_PRICE
    context.user_data["new_shop_item"]["price"] = price
    if context.user_data["new_shop_item"]["type"] == "reset":
        await update.message.reply_text(
            "Введите продолжительность действия товара в часах (0 - бессрочно):\n"
            "Пример: 24 - товар будет доступен 24 часа"
        )
        return ADMIN_SHOP_DURATION
    else:
        await update.message.reply_text(
            "Введите ID карточек через пробел, которые будут в наборе:\n"
            "(Пример: 1 5 7 12)"
        )
        return ADMIN_SHOP_CARDS

async def admin_shop_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        card_ids = [int(id_str) for id_str in update.message.text.split()]
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте цифры, разделенные пробелами.")
        return ADMIN_SHOP_CARDS
    cards = load_data(CARDS_FILE, [])
    existing_ids = [card["id"] for card in cards]
    for card_id in card_ids:
        if card_id not in existing_ids:
            await update.message.reply_text(f"❌ Карточка с ID {card_id} не найдена!")
            return ADMIN_SHOP_CARDS
    context.user_data["new_shop_item"]["cards"] = card_ids
    await update.message.reply_text(
        "Введите продолжительность действия товара в часах (0 - бессрочно):\n"
        "Пример: 24 - товар будет доступен 24 часа"
    )
    return ADMIN_SHOP_DURATION

async def admin_shop_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        duration = float(update.message.text)
        if duration < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Неверный формат! Введите число (0 для бессрочного товара).")
        return ADMIN_SHOP_DURATION
    new_item = context.user_data["new_shop_item"]
    shop_items = load_data(SHOP_FILE, [])
    if duration > 0:
        new_item["expire_time"] = time.time() + duration * 3600
    else:
        new_item["expire_time"] = 0
    new_id = max(item["id"] for item in shop_items) + 1 if shop_items else 1
    new_item["id"] = new_id
    shop_items.append(new_item)
    save_data(SHOP_FILE, shop_items)
    message = f"✅ Товар '{html.escape(new_item['name'])}' успешно добавлен в магазин!\n"
    message += f"💵 Цена: {new_item['price']} монет\n"
    message += f"📝 Тип: {'Сброс таймера' if new_item['type'] == 'reset' else 'Набор карточек'}\n"
    if duration > 0:
        hours = int(duration)
        minutes = int((duration - hours) * 60)
        message += f"⏳ Длительность: {hours}ч {minutes}мин\n"
    else:
        message += "⏳ Длительность: бессрочно\n"
    if new_item["type"] == "pack":
        card_names = [str(card_id) for card_id in new_item["cards"]]
        message += f"🃏 Карточки: {', '.join(card_names)}\n"
    await update.message.reply_text(message)
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_addshopitem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление товара отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_listshop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
    shop_items = load_data(SHOP_FILE, [])
    current_time = time.time()
    active_items = [item for item in shop_items if item.get("expire_time", 0) == 0 or item["expire_time"] > current_time]
    save_data(SHOP_FILE, active_items)
    if not active_items:
        await update.message.reply_text("🛒 Магазин пуст!")
        return
    message = "🛒 <b>Товары в магазине</b>\n\n"
    for item in active_items:
        message += f"🆔 <b>ID</b>: {item['id']}\n"
        message += f"🏷 <b>Название</b>: {html.escape(item['name'])}\n"
        message += f"💵 <b>Цена</b>: {item['price']} монет\n"
        if item.get("expire_time", 0) > 0:
            time_left = item["expire_time"] - current_time
            if time_left > 0:
                hours = int(time_left // 3600)
                minutes = int((time_left % 3600) // 60)
                message += f"⏳ <b>Осталось</b>: {hours}ч {minutes}мин\n"
            else:
                continue
        if item["type"] == "reset":
            message += "📝 <b>Тип</b>: Сброс таймера получения карточки\n\n"
        elif item["type"] == "pack":
            message += "📝 <b>Тип</b>: Набор карточек\n"
            card_names = ", ".join([str(card_id) for card_id in item["cards"]])
            message += f"🃏 <b>Карточки</b>: {card_names}\n\n"
    await update.message.reply_text(message, parse_mode="HTML")

# Редактирование карточки
async def admin_editcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    if not context.args:
        await update.message.reply_text("❌ Укажите ID карточки: /admin_editcard <card_id>")
        return ConversationHandler.END
    try:
        card_id = int(context.args[0])
        cards = load_data(CARDS_FILE, [])
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await update.message.reply_text("❌ Карточка не найдена!")
            return ConversationHandler.END
        context.user_data["edit_card"] = card
        context.user_data["card_id"] = card_id
        keyboard = [
            [InlineKeyboardButton("Название", callback_data="name")],
            [InlineKeyboardButton("Редкость", callback_data="rarity")],
            [InlineKeyboardButton("Описание", callback_data="description")],
            [InlineKeyboardButton("Изображение", callback_data="image")],
            [InlineKeyboardButton("Отмена", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"🃏 Выберите поле для изменения карточки {card['name']} (ID: {card_id}):",
            reply_markup=reply_markup
        )
        return EDIT_CARD_FIELD
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")
        return ConversationHandler.END

async def edit_card_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "cancel":
        await query.edit_message_text("❌ Изменение карточки отменено.")
        context.user_data.clear()
        return ConversationHandler.END
    context.user_data["edit_field"] = data
    if data == "image":
        await query.edit_message_text("📷 Отправьте новое изображение для карточки:")
    else:
        await query.edit_message_text(f"✏️ Введите новое значение для поля {data}:")
    return EDIT_CARD_VALUE

async def edit_card_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    field = user_data["edit_field"]
    card_id = user_data["card_id"]
    cards = load_data(CARDS_FILE, [])
    card_index = next((i for i, c in enumerate(cards) if c["id"] == card_id), -1)
    if card_index == -1:
        await update.message.reply_text("❌ Карточка не найдена!")
        context.user_data.clear()
        return ConversationHandler.END
    if field == "image":
        if not update.message.photo:
            await update.message.reply_text("❌ Пожалуйста, отправьте изображение!")
            return EDIT_CARD_VALUE
        photo = update.message.photo[-1]
        file = await photo.get_file()
        os.makedirs(CARDS_IMAGE_DIR, exist_ok=True)
        filename = f"{int(time.time())}.jpg"
        image_path = os.path.join(CARDS_IMAGE_DIR, filename)
        await file.download_to_drive(image_path)
        old_image = cards[card_index]["image"]
        old_path = os.path.join(CARDS_IMAGE_DIR, old_image)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception as e:
                logger.error(f"Ошибка удаления старого изображения: {e}")
        cards[card_index]["image"] = filename
        save_data(CARDS_FILE, cards)
        await update.message.reply_text("✅ Изображение карточки успешно обновлено!")
    else:
        new_value = update.message.text
        cards[card_index][field] = new_value
        save_data(CARDS_FILE, cards)
        await update.message.reply_text(f"✅ Поле '{field}' успешно обновлено!")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_editcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Изменение карточки отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# ============================ КРАФТ ============================
async def start_craft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return ConversationHandler.END
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return ConversationHandler.END
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    user_cards = user_data.get("cards", [])
    if len(user_cards) < 3:
        await update.message.reply_text("❌ У вас менее 3 карточек в коллекции!")
        return ConversationHandler.END
    message = await show_collection_with_ids(user.id)
    message += "\n\n🛠 <b>Система крафта</b>\n" \
               "Выберите 3 карточки ОДНОЙ редкости (Обычная или Редкая) для улучшения.\n" \
               "Введите ID карточек через пробел (например: 5 12 8):"
    await update.message.reply_text(message, parse_mode="HTML")
    return CRAFT_SELECT_CARDS

async def process_craft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text
    try:
        card_ids = [int(id_str) for id_str in text.split()]
        if len(card_ids) != 3:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Неверный формат! Введите ровно 3 ID карточек через пробел.")
        return CRAFT_SELECT_CARDS
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    user_cards = user_data.get("cards", [])
    missing_cards = [card_id for card_id in card_ids if card_id not in user_cards]
    if missing_cards:
        await update.message.reply_text(f"❌ У вас нет карточек с ID: {', '.join(map(str, missing_cards))}")
        return CRAFT_SELECT_CARDS
    cards_data = load_data(CARDS_FILE, [])
    selected_cards = [c for c in cards_data if c["id"] in card_ids]
    rarities = set(card["rarity"] for card in selected_cards)
    if len(rarities) != 1:
        await update.message.reply_text("❌ Все карточки должны быть одинаковой редкости!")
        return CRAFT_SELECT_CARDS
    rarity = next(iter(rarities))
    if rarity not in ["Обычная", "Редкая"]:
        await update.message.reply_text("❌ Крафт доступен только для карточек Обычной и Редкой редкости!")
        return CRAFT_SELECT_CARDS
    new_rarity = "Редкая" if rarity == "Обычная" else "Эпическая"
    success = random.random() < 0.4
    for card_id in card_ids:
        user_cards.remove(card_id)
    if success:
        new_cards = [c for c in cards_data if c["rarity"] == new_rarity]
        if not new_cards:
            await update.message.reply_text("❌ Ошибка: нет карточек нужной редкости!")
            return ConversationHandler.END
        new_card = random.choice(new_cards)
        user_cards.append(new_card["id"])
        user_data["cards"] = user_cards
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        card_count = user_cards.count(new_card["id"])
        count_text = f" (x{card_count})" if card_count > 1 else ""
        await update.message.reply_text(
            f"🎉 Крафт успешен!\n"
            f"Вы получили: {new_card['name']} ({new_rarity}){count_text}\n\n"
            f"📚 Теперь в вашей коллекции: {len(user_cards)} карточек"
        )
    else:
        user_data["cards"] = user_cards
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        await update.message.reply_text(
            "❌ Крафт не удался!\n"
            "Все карточки были потеряны.\n\n"
            f"📚 Теперь в вашей коллекции: {len(user_cards)} карточек"
        )
    return ConversationHandler.END

async def cancel_craft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Крафт отменен.")
    context.user_data.clear()
    return ConversationHandler.END

# ============================ ТАБЛИЦА ЛИДЕРОВ ============================
async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        return
    if not await is_subscribed(user.id, context):
        return
    moderators = load_data(MODERATORS_FILE, [])
    exclude_ids = [ADMIN_ID] + moderators
    coins_data = load_data(COINS_FILE, {})
    coins_leaders = []
    for user_id, coins in coins_data.items():
        uid = int(user_id)
        if uid not in exclude_ids:
            coins_leaders.append((uid, coins))
    coins_leaders.sort(key=lambda x: x[1], reverse=True)
    coins_top = coins_leaders[:5]

    users_data = load_data(USERS_FILE, {})
    cards_data = load_data(CARDS_FILE, [])
    rare_cards = [card["id"] for card in cards_data if card["rarity"] in ["Легендарная", "Эксклюзивная"]]

    rare_leaders = []
    total_cards_leaders = []
    unique_cards_leaders = []
    buff_leaders = []

    for user_id, user_data in users_data.items():
        uid = int(user_id)
        if uid in exclude_ids:
            continue
        user_cards = user_data.get("cards", [])
        rare_count = sum(1 for card_id in user_cards if card_id in rare_cards)
        rare_leaders.append((uid, rare_count))
        total_cards_leaders.append((uid, len(user_cards)))
        unique_cards_leaders.append((uid, len(set(user_cards))))
        buff = user_data.get("buff_card")
        buff_level = buff.get("level", 0) if buff else 0
        if buff_level > 0:
            buff_leaders.append((uid, buff_level))

    rare_leaders.sort(key=lambda x: x[1], reverse=True)
    total_cards_leaders.sort(key=lambda x: x[1], reverse=True)
    unique_cards_leaders.sort(key=lambda x: x[1], reverse=True)
    buff_leaders.sort(key=lambda x: x[1], reverse=True)

    rare_top = rare_leaders[:5]
    total_cards_top = total_cards_leaders[:5]
    unique_cards_top = unique_cards_leaders[:5]
    buff_top = buff_leaders[:5]

    async def format_section(title: str, entries, unit: str) -> str:
        section = f"\n<b>{title}</b>\n"
        if not entries:
            return section + "Нет данных\n"
        for i, (user_id, value) in enumerate(entries, 1):
            try:
                user_chat = await context.bot.get_chat(user_id)
                username = user_chat.username or f"ID: {user_id}"
                section += f"{i}. @{username}: {value} {unit}\n"
            except Exception:
                section += f"{i}. ID {user_id}: {value} {unit}\n"
        return section

    message = "<b>🏆 Таблица лидеров</b>\n"
    message += await format_section("💰 Топ по монетам:", coins_top, "монет")
    message += await format_section("🃏 Топ по редким карточкам:", rare_top, "карточек")
    message += await format_section("📚 Топ по общему количеству карточек:", total_cards_top, "карточек")
    message += await format_section("📖 Рейтинг по коллекциям (уникальные карточки):", unique_cards_top, "уникальных карточек")
    message += await format_section("⚡ Топ по уровню баффа:", buff_top, "уровень")

    await update.message.reply_text(message, parse_mode="HTML")

# ============================ КАЗИНО ============================
async def casino(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /casino <сумма>")
        return
    try:
        bet = int(context.args[0])
        if bet <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return
    balance = get_coins(user.id)
    if balance < bet:
        await update.message.reply_text("❌ Недостаточно монет!")
        return
    streak = get_casino_streak(user.id)
    win_chance = max(0.1, 0.5 - streak * 0.05)
    if random.random() < win_chance:
        # Пул множителей для "удачного" броска. 0 / 0.25 / 0.5 / 0.75 всё ещё
        # можно получить - но это НЕ выигрыш, просто частичный (или полный) возврат ставки.
        multipliers = [0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        multiplier = random.choice(multipliers)
    else:
        # Гарантированный проигрыш без шанса на возврат
        multiplier = 0

    payout = int(bet * multiplier)
    net = payout - bet  # реальное изменение баланса
    update_coins(user.id, -bet)
    update_coins(user.id, payout)
    new_balance = get_coins(user.id)

    if multiplier > 1.0:
        # Настоящий выигрыш
        new_streak = streak + 1
        set_casino_streak(user.id, new_streak)
        result_line = f"🎉 Вы выиграли! +{net} монет"
        streak_line = f"🔥 Серия побед: {new_streak}"
    elif multiplier == 1.0:
        # Просто повезло - ставка вернулась, ни выигрыша, ни проигрыша
        result_line = "😐 Повезло! Ставка вернулась, вы остались при своих (0)"
        streak_line = "🔥 Серия побед не изменилась"
    elif multiplier > 0:
        # Частичный проигрыш - часть ставки вернулась, но по сути минус
        set_casino_streak(user.id, 0)
        result_line = f"😞 Вы проиграли часть ставки. Вернулось {payout} из {bet} ({net} монет)"
        streak_line = "🔥 Серия побед сброшена."
    else:
        # Полный проигрыш
        set_casino_streak(user.id, 0)
        result_line = f"💀 Вы проиграли всё. -{bet} монет"
        streak_line = "🔥 Серия побед сброшена."

    await update.message.reply_text(
        f"🎰 <b>Казино</b>\n\n"
        f"Ставка: {bet} монет\n"
        f"Множитель: x{multiplier:.2f}\n"
        f"{result_line}\n"
        f"💰 Новый баланс: {new_balance} монет\n"
        f"{streak_line}",
        parse_mode="HTML"
    )

# ============================ МОНЕТКА ============================
async def coin_flip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if len(context.args) < 2:
        await update.message.reply_text("ℹ️ Использование: /coin <орел|решка> <сумма>")
        return
    choice = context.args[0].lower()
    if choice not in ["орел", "решка"]:
        await update.message.reply_text("❌ Выберите 'орел' или 'решка'.")
        return
    try:
        bet = int(context.args[1])
        if bet <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return
    balance = get_coins(user.id)
    if balance < bet:
        await update.message.reply_text("❌ Недостаточно монет!")
        return
    streak = get_coin_streak(user.id)
    if random.random() < 0.1:
        new_balance = get_coins(user.id)
        await update.message.reply_text(
            f"🪙 <b>Монетка</b>\n\n"
            f"Ваш выбор: {choice}\n"
            f"Выпало: ребро!\n"
            f"💰 Ставка возвращена. Баланс: {new_balance} монет",
            parse_mode="HTML"
        )
        return
    win_chance = max(0.1, 0.5 - streak * 0.05)
    if random.random() < win_chance:
        result = choice
        set_coin_streak(user.id, streak + 1)
        update_coins(user.id, -bet)
        update_coins(user.id, bet * 2)
        new_balance = get_coins(user.id)
        await update.message.reply_text(
            f"🪙 <b>Монетка</b>\n\n"
            f"Ваш выбор: {choice}\n"
            f"Выпало: {result}!\n"
            f"🎉 Вы выиграли! +{bet*2} монет\n"
            f"💰 Новый баланс: {new_balance} монет\n"
            f"🔥 Серия побед: {streak+1}",
            parse_mode="HTML"
        )
    else:
        result = "орел" if choice == "решка" else "решка"
        set_coin_streak(user.id, 0)
        update_coins(user.id, -bet)
        new_balance = get_coins(user.id)
        await update.message.reply_text(
            f"🪙 <b>Монетка</b>\n\n"
            f"Ваш выбор: {choice}\n"
            f"Выпало: {result}!\n"
            f"😞 Вы проиграли. -{bet} монет\n"
            f"💰 Новый баланс: {new_balance} монет\n"
            f"🔥 Серия побед сброшена.",
            parse_mode="HTML"
        )

# ============================ БАФФЫ ============================
async def buff_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    buff = get_active_buff(user.id)
    if not buff:
        await update.message.reply_text(
            "❌ У вас нет активной карты баффа.\n"
            "Чтобы выбрать карту, используйте /set_buff <card_id>"
        )
        return
    card_id = buff["card_id"]
    level = buff["level"]
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Активная карта больше не существует. Очистите бафф.")
        return
    cooldown_reduction = min(level * 5, 80)
    coin_bonus = level * 5
    current_cooldown_hours = 6 * (1 - cooldown_reduction / 100)
    message = (
        f"🃏 <b>Ваш активный бафф</b>\n\n"
        f"Карта: {card['name']} (ID: {card_id})\n"
        f"Редкость: {card['rarity']}\n"
        f"Уровень: {level}\n\n"
        f"<b>Эффекты:</b>\n"
        f"⏳ Уменьшение кулдауна: -{cooldown_reduction}% (текущий кулдаун: {current_cooldown_hours:.1f} ч)\n"
        f"💰 Бонус к монетам: +{coin_bonus}%\n\n"
        f"Чтобы улучшить бафф, используйте /upgrade_buff (потребуются копии карты)"
    )
    await update.message.reply_text(message, parse_mode="HTML")

async def set_buff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /set_buff <card_id>")
        return
    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")
        return
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    user_cards = user_data.get("cards", [])
    if card_id not in user_cards:
        await update.message.reply_text("❌ У вас нет такой карточки в коллекции!")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена в базе!")
        return
    if not is_legendary_or_higher(card["rarity"]):
        await update.message.reply_text("❌ Для баффа можно выбрать только карту редкости Легендарная, Блещет умом или Эксклюзивная!")
        return
    current_buff = get_active_buff(user.id)
    if current_buff:
        keyboard = [
            [InlineKeyboardButton("✅ Да, заменить", callback_data=f"confirm_set_buff_{card_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_set_buff")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"У вас уже есть активная карта баффа. Заменить её на '{card['name']}'?",
            reply_markup=reply_markup
        )
        return
    set_active_buff(user.id, card_id)
    await update.message.reply_text(
        f"✅ Карта '{card['name']}' теперь активна как бафф (уровень 1)!\n"
        "Посмотреть эффекты: /buff"
    )

async def set_buff_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if data == "cancel_set_buff":
        await query.edit_message_text("❌ Замена баффа отменена.")
        return
    if data.startswith("confirm_set_buff_"):
        card_id = int(data[len("confirm_set_buff_"):])
        users = load_data(USERS_FILE, {})
        user_data = users.get(str(user_id), {})
        if card_id not in user_data.get("cards", []):
            await query.edit_message_text("❌ У вас больше нет этой карточки!")
            return
        cards = load_data(CARDS_FILE, [])
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await query.edit_message_text("❌ Карточка не найдена!")
            return
        set_active_buff(user_id, card_id)
        await query.edit_message_text(
            f"✅ Карта '{card['name']}' теперь активна как бафф (уровень 1)!\n"
            "Посмотреть эффекты: /buff"
        )

async def upgrade_buff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    buff = get_active_buff(user.id)
    if not buff:
        await update.message.reply_text("❌ У вас нет активной карты баффа. Выберите с помощью /set_buff")
        return
    card_id = buff["card_id"]
    current_level = buff["level"]
    required_cards = current_level + 1
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    user_cards = user_data.get("cards", [])
    total_copies = user_cards.count(card_id)
    available_for_upgrade = total_copies - 1
    if available_for_upgrade < required_cards:
        await update.message.reply_text(
            f"❌ Недостаточно копий для улучшения.\n"
            f"Текущий уровень: {current_level}\n"
            f"Для улучшения до уровня {current_level+1} нужно потратить {required_cards} копий.\n"
            f"У вас есть {available_for_upgrade} доступных копий (всего {total_copies} карт этого типа)."
        )
        return
    keyboard = [
        [InlineKeyboardButton("✅ Улучшить", callback_data="confirm_upgrade_buff")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_upgrade_buff")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🔄 Вы собираетесь улучшить бафф карты с уровня {current_level} до {current_level+1}.\n"
        f"Будет потрачено {required_cards} копий этой карты.\n"
        f"Подтверждаете?",
        reply_markup=reply_markup
    )

async def upgrade_buff_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if data == "cancel_upgrade_buff":
        await query.edit_message_text("❌ Улучшение баффа отменено.")
        return
    if data == "confirm_upgrade_buff":
        buff = get_active_buff(user_id)
        if not buff:
            await query.edit_message_text("❌ У вас больше нет активной карты баффа.")
            return
        card_id = buff["card_id"]
        current_level = buff["level"]
        required_cards = current_level + 1
        users = load_data(USERS_FILE, {})
        user_data = users.get(str(user_id), {})
        user_cards = user_data.get("cards", [])
        total_copies = user_cards.count(card_id)
        if total_copies < required_cards + 1:
            await query.edit_message_text("❌ Недостаточно копий для улучшения.")
            return
        removed = 0
        new_cards = []
        for cid in user_cards:
            if cid == card_id and removed < required_cards:
                removed += 1
                continue
            new_cards.append(cid)
        if removed != required_cards:
            await query.edit_message_text("❌ Ошибка при удалении карт.")
            return
        user_data["cards"] = new_cards
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)
        new_level = current_level + 1
        update_buff_level(user_id, new_level)
        await query.edit_message_text(
            f"✅ Бафф улучшен до уровня {new_level}!\n"
            f"Потрачено {required_cards} копий карты.\n"
            f"Посмотреть эффекты: /buff"
        )

# ============================ ПРОМОКОДЫ ============================
async def create_promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    await update.message.reply_text("Введите код промокода (латиница, без пробелов):")
    return PROMO_NAME

async def promo_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    if " " in code:
        await update.message.reply_text("❌ Код не должен содержать пробелов. Введите снова:")
        return PROMO_NAME
    promos = load_data(PROMOCODES_FILE, {})
    if code in promos:
        await update.message.reply_text("❌ Такой промокод уже существует. Введите другой:")
        return PROMO_NAME
    context.user_data["promo_code"] = code
    await update.message.reply_text("Выберите тип награды:\n1 - монеты\n2 - сброс таймера")
    return PROMO_TYPE

async def promo_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "1":
        promo_type = "coins"
    elif text == "2":
        promo_type = "reset"
    else:
        await update.message.reply_text("❌ Введите 1 или 2.")
        return PROMO_TYPE
    context.user_data["promo_type"] = promo_type
    if promo_type == "coins":
        await update.message.reply_text("Введите количество монет для начисления:")
    else:
        await update.message.reply_text("Введите значение (для сброса таймера введите 1):")
    return PROMO_VALUE

async def promo_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int(update.message.text)
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return PROMO_VALUE
    context.user_data["promo_value"] = value
    await update.message.reply_text("Введите максимальное количество использований (например, 10):")
    return PROMO_USES

async def promo_uses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        uses = int(update.message.text)
        if uses <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return PROMO_USES
    context.user_data["promo_uses"] = uses
    await update.message.reply_text("Введите срок действия в часах (0 - бессрочно):")
    return PROMO_DURATION

async def promo_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        duration = float(update.message.text)
        if duration < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите число (0 для бессрочного).")
        return PROMO_DURATION
    code = context.user_data["promo_code"]
    promo_type = context.user_data["promo_type"]
    value = context.user_data["promo_value"]
    uses = context.user_data["promo_uses"]
    promos = load_data(PROMOCODES_FILE, {})
    promos[code] = {
        "type": promo_type,
        "value": value,
        "max_uses": uses,
        "used": 0,
        "expire": time.time() + duration * 3600 if duration > 0 else 0,
        "users": []
    }
    save_data(PROMOCODES_FILE, promos)
    await update.message.reply_text(f"✅ Промокод '{code}' создан!\nТип: {promo_type}\nЗначение: {value}\nИспользований: {uses}\nСрок: {'бессрочно' if duration == 0 else f'{duration} ч'}")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Создание промокода отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def redeem_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /redeem <код>")
        return
    code = context.args[0].strip()
    promos = load_data(PROMOCODES_FILE, {})
    if code not in promos:
        await update.message.reply_text("❌ Неверный промокод.")
        return
    promo = promos[code]
    if promo["expire"] != 0 and promo["expire"] < time.time():
        await update.message.reply_text("❌ Срок действия промокода истёк.")
        return
    if promo["used"] >= promo["max_uses"]:
        await update.message.reply_text("❌ Промокод уже использован максимальное число раз.")
        return
    if str(user.id) in promo["users"]:
        await update.message.reply_text("❌ Вы уже использовали этот промокод.")
        return
    if promo["type"] == "coins":
        new_balance = update_coins(user.id, promo["value"])
        await update.message.reply_text(f"✅ Промокод активирован! Вы получили {promo['value']} монет.\n💰 Новый баланс: {new_balance}")
    elif promo["type"] == "reset":
        users = load_data(USERS_FILE, {})
        user_data = users.get(str(user.id), {})
        user_data["last_drop"] = 0
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        await update.message.reply_text("✅ Промокод активирован! Таймер получения карточки сброшен.")
    promos[code]["used"] += 1
    promos[code]["users"].append(str(user.id))
    save_data(PROMOCODES_FILE, promos)

# ============================ ПРОФИЛЬ ============================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return

    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    cards = load_data(CARDS_FILE, [])
    total_cards = len(cards)
    user_cards = user_data.get("cards", [])
    seen_cards = user_data.get("seen_cards", [])
    unique_opened = len(seen_cards)
    unique_not_opened = total_cards - unique_opened

    balance = get_coins(user.id)
    buff = get_active_buff(user.id)

    message = f"👤 <b>Профиль игрока</b>\n\n"
    message += f"💰 Баланс: <b>{balance}</b> монет\n"
    message += f"🃏 Всего карточек в коллекции: <b>{len(user_cards)}</b> шт.\n"
    message += f"📊 Уникальных открыто: <b>{unique_opened}</b> из {total_cards} "
    if total_cards > 0:
        progress = unique_opened / total_cards * 100
        message += f"({progress:.1f}%)\n"
    else:
        message += "(0%)\n"
    message += f"🔒 Ещё не открыто: <b>{unique_not_opened}</b> карточек\n"

    if buff:
        card_id = buff["card_id"]
        level = buff["level"]
        card = next((c for c in cards if c["id"] == card_id), None)
        card_name = card["name"] if card else f"ID {card_id}"
        message += f"⚡ Активный бафф: <b>{card_name}</b> (уровень {level})\n"
    else:
        message += "⚡ Активный бафф: <b>нет</b>\n"

    await update.message.reply_text(message, parse_mode="HTML")

# ============================ ПЕРЕДАЧА КАРТОЧКИ (ПОДАРОК) ============================
async def givecard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("ℹ️ Использование: /givecard <user_id> <card_id>")
        return

    try:
        recipient_id = int(args[0])
        card_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Используйте только цифры.")
        return

    if recipient_id == user.id:
        await update.message.reply_text("❌ Нельзя передать карточку самому себе.")
        return

    users = load_data(USERS_FILE, {})
    if str(recipient_id) not in users:
        await update.message.reply_text("❌ Получатель не найден в базе бота.")
        return

    user_cards = users.get(str(user.id), {}).get("cards", [])
    if card_id not in user_cards:
        await update.message.reply_text("❌ У вас нет такой карточки.")
        return

    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена в базе данных.")
        return

    # Удаляем у отправителя
    user_cards.remove(card_id)
    users[str(user.id)]["cards"] = user_cards

    # Добавляем получателю
    if str(recipient_id) not in users:
        users[str(recipient_id)] = {"cards": [], "last_drop": 0}
    recipient_cards = users[str(recipient_id)].get("cards", [])
    recipient_cards.append(card_id)
    users[str(recipient_id)]["cards"] = recipient_cards

    save_data(USERS_FILE, users)
    # Теперь добавляем seen_card получателю
    add_seen_card(recipient_id, card_id)

    await update.message.reply_text(
        f"✅ Вы передали карточку '{card['name']}' (ID: {card_id}) пользователю {recipient_id}."
    )
    try:
        await context.bot.send_message(
            recipient_id,
            f"🎁 Пользователь @{user.username or user.id} передал вам карточку '{card['name']}' (ID: {card_id})!"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить получателя: {e}")

# ============================ СТАВКИ (БУКМЕКЕРСКАЯ СИСТЕМА) ============================
def generate_outcomes():
    """Возвращает список стандартных исходов для матча с типами и коэффициентами"""
    outcomes = [
        {"label": "П1", "type": "p1", "coefficient": 2.0},
        {"label": "П2", "type": "p2", "coefficient": 2.0},
        {"label": "ТБ 2.5", "type": "tb", "threshold": 2.5, "coefficient": 1.8},
        {"label": "ТМ 2.5", "type": "tm", "threshold": 2.5, "coefficient": 1.9},
        {"label": "ТБ 3.5", "type": "tb", "threshold": 3.5, "coefficient": 2.2},
        {"label": "ТМ 3.5", "type": "tm", "threshold": 3.5, "coefficient": 1.7},
        {"label": "ТБ 4.5", "type": "tb", "threshold": 4.5, "coefficient": 2.6},
        {"label": "ТМ 4.5", "type": "tm", "threshold": 4.5, "coefficient": 1.5},
    ]
    return outcomes

async def create_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "ℹ️ Использование: /create_match <команда1> <команда2> <часы_приёма_ставок>\n"
            "Пример: /create_match ЦСКА СКА 3\n"
            "(бот будет принимать ставки на этот матч в течение 3 часов с момента создания)"
        )
        return
    team1 = args[0]
    team2 = args[1]
    try:
        hours = float(args[2].replace(",", "."))
        if hours <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Количество часов должно быть положительным числом. Пример: 3 или 1.5")
        return
    deadline = datetime.now() + timedelta(hours=hours)
    events = load_data(EVENTS_FILE, [])
    new_id = max([e["id"] for e in events], default=0) + 1
    outcomes = generate_outcomes()
    for i, o in enumerate(outcomes):
        o["id"] = i + 1
    events.append({
        "id": new_id,
        "team1": team1,
        "team2": team2,
        "deadline": deadline.timestamp(),
        "betting_hours": hours,
        "status": "active",
        "outcomes": outcomes,
        "winning_outcome_id": None,
        "score": None
    })
    save_data(EVENTS_FILE, events)
    await update.message.reply_text(f"✅ Матч {team1} - {team2} создан (ID: {new_id}).\n"
                                    f"Приём ставок открыт на {hours} ч. - до {deadline.strftime('%d.%m.%Y %H:%M')}.\n"
                                    "Исходы созданы автоматически.")

async def finish_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("ℹ️ Использование: /finish_match <match_id> <счёт> (например 3:1)")
        return
    try:
        match_id = int(args[0])
        score = args[1]
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID.")
        return
    try:
        parts = score.split(":")
        if len(parts) != 2:
            raise ValueError
        g1 = int(parts[0])
        g2 = int(parts[1])
    except:
        await update.message.reply_text("❌ Неверный формат счёта. Используйте X:Y (например 3:1)")
        return
    events = load_data(EVENTS_FILE, [])
    event = next((e for e in events if e["id"] == match_id), None)
    if not event:
        await update.message.reply_text("❌ Матч не найден.")
        return
    if event["status"] != "active":
        await update.message.reply_text("❌ Матч уже завершён.")
        return
    if not event.get("outcomes"):
        await update.message.reply_text("❌ У этого матча нет исходов. Матч создан старой версией бота, удалите events.json и создайте новый матч.")
        return

    event["status"] = "finished"
    event["score"] = score
    save_data(EVENTS_FILE, events)

    bets = load_data(BETS_FILE, [])
    total_wins = 0
    total_loses = 0
    for bet in bets:
        if bet["match_id"] == match_id and bet["status"] == "pending":
            outcome = next((o for o in event["outcomes"] if o["id"] == bet["outcome_id"]), None)
            if not outcome:
                continue
            o_type = outcome.get("type")
            win = False
            if o_type == "p1":
                win = g1 > g2
            elif o_type == "p2":
                win = g2 > g1
            elif o_type == "draw":
                win = g1 == g2
            elif o_type == "tb":
                threshold = outcome.get("threshold", 0)
                win = (g1 + g2) > threshold
            elif o_type == "tm":
                threshold = outcome.get("threshold", 0)
                win = (g1 + g2) < threshold
            else:
                continue

            if win:
                bet["status"] = "win"
                win_amount = int(bet["amount"] * outcome["coefficient"])
                update_coins(bet["user_id"], win_amount)
                total_wins += 1
                try:
                    await context.bot.send_message(
                        bet["user_id"],
                        f"🎉 Ваша ставка на матч {event['team1']} - {event['team2']} выиграла!\n"
                        f"Исход: {outcome['label']}\nСумма выигрыша: {win_amount} монет."
                    )
                except:
                    pass
            else:
                bet["status"] = "lose"
                total_loses += 1
                try:
                    await context.bot.send_message(
                        bet["user_id"],
                        f"❌ Ваша ставка на матч {event['team1']} - {event['team2']} проиграла.\nИсход: {outcome['label']}"
                    )
                except:
                    pass
    save_data(BETS_FILE, bets)

    await update.message.reply_text(f"✅ Матч '{event['team1']} - {event['team2']}' завершён со счётом {score}.\n"
                                    f"Обработано ставок: выигрышных - {total_wins}, проигрышных - {total_loses}.")

# Инлайн-меню для ставок
async def bet_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    events = load_data(EVENTS_FILE, [])
    active_events = [e for e in events if e["status"] == "active" and time.time() < e["deadline"]]
    if not active_events:
        await update.message.reply_text("📭 Активных матчей для ставок нет.")
        return
    keyboard = []
    for e in active_events:
        keyboard.append([InlineKeyboardButton(f"{e['team1']} - {e['team2']}", callback_data=f"bet_match_{e['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите матч для ставки:", reply_markup=reply_markup)

async def bet_match_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    match_id = int(data.split("_")[2])
    context.user_data["bet_match_id"] = match_id
    events = load_data(EVENTS_FILE, [])
    event = next((e for e in events if e["id"] == match_id), None)
    if not event:
        await query.edit_message_text("❌ Матч не найден.")
        return
    if not event["outcomes"]:
        await query.edit_message_text("❌ Для этого матча нет исходов.")
        return
    keyboard = []
    for o in event["outcomes"]:
        keyboard.append([InlineKeyboardButton(f"{o['label']} (коэф {o['coefficient']})", callback_data=f"bet_outcome_{match_id}_{o['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"Выберите исход для матча {event['team1']} - {event['team2']}:", reply_markup=reply_markup)

async def bet_outcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split("_")
    match_id = int(parts[2])
    outcome_id = int(parts[3])
    context.user_data["bet_outcome_id"] = outcome_id
    context.user_data["bet_match_id"] = match_id
    await query.edit_message_text("Введите сумму ставки (в монетах):")
    context.user_data["bet_state"] = "awaiting_amount"

async def bet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("bet_state") != "awaiting_amount":
        return
    user = update.effective_user
    try:
        amount = int(update.message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return
    match_id = context.user_data["bet_match_id"]
    outcome_id = context.user_data["bet_outcome_id"]
    events = load_data(EVENTS_FILE, [])
    event = next((e for e in events if e["id"] == match_id), None)
    if not event:
        await update.message.reply_text("❌ Матч не найден.")
        return
    if event["status"] != "active" or time.time() > event["deadline"]:
        await update.message.reply_text("❌ Время приёма ставок истекло или матч завершён.")
        return
    outcome = next((o for o in event["outcomes"] if o["id"] == outcome_id), None)
    if not outcome:
        await update.message.reply_text("❌ Исход не найден.")
        return
    bets = load_data(BETS_FILE, [])
    existing_bet = next((b for b in bets if b["user_id"] == user.id and b["match_id"] == match_id and b["status"] == "pending"), None)
    if existing_bet:
        await update.message.reply_text("❌ Вы уже сделали ставку на этот матч. Повторная ставка запрещена.")
        return
    balance = get_coins(user.id)
    if balance < amount:
        await update.message.reply_text("❌ Недостаточно монет.")
        return
    bets.append({
        "user_id": user.id,
        "match_id": match_id,
        "outcome_id": outcome_id,
        "amount": amount,
        "status": "pending"
    })
    save_data(BETS_FILE, bets)
    outcome["total_bet"] = outcome.get("total_bet", 0) + amount
    save_data(EVENTS_FILE, events)
    update_coins(user.id, -amount)
    await update.message.reply_text(
        f"✅ Ставка принята!\n"
        f"Матч: {event['team1']} - {event['team2']}\n"
        f"Исход: {outcome['label']} (коэф {outcome['coefficient']})\n"
        f"Сумма: {amount} монет"
    )
    context.user_data.pop("bet_state", None)
    context.user_data.pop("bet_match_id", None)
    context.user_data.pop("bet_outcome_id", None)

async def my_bets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    bets = load_data(BETS_FILE, [])
    user_bets = [b for b in bets if b["user_id"] == user.id]
    if not user_bets:
        await update.message.reply_text("📭 У вас нет ставок.")
        return
    events = load_data(EVENTS_FILE, [])
    message = "📋 <b>Мои ставки:</b>\n\n"
    for b in user_bets:
        event = next((e for e in events if e["id"] == b["match_id"]), None)
        event_name = f"{event['team1']} - {event['team2']}" if event else f"Матч {b['match_id']}"
        outcome_label = "неизвестно"
        if event:
            outcome = next((o for o in event["outcomes"] if o["id"] == b["outcome_id"]), None)
            if outcome:
                outcome_label = outcome["label"]
        status_emoji = {"pending": "⏳", "win": "✅", "lose": "❌"}
        status_text = {"pending": "Ожидает", "win": "Выигрыш", "lose": "Проигрыш"}
        message += f"🆔 {b.get('id', '?')}: {event_name} -> {outcome_label}\n"
        message += f"   Сумма: {b['amount']} монет, Статус: {status_emoji.get(b['status'], '❓')} {status_text.get(b['status'], 'Неизвестно')}\n\n"
    await update.message.reply_text(message, parse_mode="HTML")

# ============================ РЕЙТИНГОВЫЙ РЕЖИМ ============================

async def rating_team_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return ConversationHandler.END
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return ConversationHandler.END
    collection_msg = await show_collection_with_ids(user.id)
    users = load_data(USERS_FILE, {})
    user_cards = users.get(str(user.id), {}).get("cards", [])
    if len(set(user_cards)) < 4:
        await update.message.reply_text(
            "❌ Для составления команды нужно минимум 4 РАЗНЫЕ карточки в коллекции "
            "(1 вратарь + 3 полевых игрока). Получите больше карточек через /get_card."
        )
        return ConversationHandler.END
    await update.message.reply_text(collection_msg, parse_mode="HTML")
    await update.message.reply_text(
        "🥅 Введите ID карточки, которая будет вашим ВРАТАРЁМ:"
    )
    return RATING_TEAM_GK

async def rating_team_gk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    try:
        gk_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите числовой ID карточки.")
        return RATING_TEAM_GK
    users = load_data(USERS_FILE, {})
    user_cards = users.get(str(user.id), {}).get("cards", [])
    if gk_id not in user_cards:
        await update.message.reply_text("❌ У вас нет такой карточки. Проверьте ID и попробуйте снова.")
        return RATING_TEAM_GK
    context.user_data["rating_gk"] = gk_id
    await update.message.reply_text(
        "⚔️ Теперь введите ID трёх ПОЛЕВЫХ игроков через запятую (все разные и не совпадают с вратарём).\n"
        "Пример: 2, 5, 7"
    )
    return RATING_TEAM_FIELD

async def rating_team_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    raw = update.message.text.strip()
    try:
        field_ids = [int(x.strip()) for x in raw.split(",")]
    except ValueError:
        await update.message.reply_text("❌ Введите три ID через запятую, например: 2, 5, 7")
        return RATING_TEAM_FIELD
    if len(field_ids) != 3:
        await update.message.reply_text("❌ Нужно указать ровно 3 карточки через запятую.")
        return RATING_TEAM_FIELD
    gk_id = context.user_data.get("rating_gk")
    all_ids = [gk_id] + field_ids
    if len(set(all_ids)) != 4:
        await update.message.reply_text("❌ Все 4 карточки (вратарь + 3 полевых) должны быть РАЗНЫМИ. Попробуйте снова.")
        return RATING_TEAM_FIELD
    users = load_data(USERS_FILE, {})
    user_cards = users.get(str(user.id), {}).get("cards", [])
    missing = [cid for cid in field_ids if cid not in user_cards]
    if missing:
        await update.message.reply_text(f"❌ У вас нет карточек с ID: {', '.join(map(str, missing))}. Попробуйте снова.")
        return RATING_TEAM_FIELD

    set_rating_team(user.id, gk_id, field_ids)
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    gk_card = card_map.get(gk_id)
    lines = [f"🥅 Вратарь: {gk_card['name'] if gk_card else gk_id}"]
    for fid in field_ids:
        fc = card_map.get(fid)
        lines.append(f"⚔️ Полевой: {fc['name'] if fc else fid}")
    await update.message.reply_text(
        "✅ Состав сохранён!\n\n" + "\n".join(lines) + "\n\nТеперь используйте /find_match, чтобы найти соперника."
    )
    context.user_data.pop("rating_gk", None)
    return ConversationHandler.END

async def cancel_rating_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Составление команды отменено.")
    context.user_data.pop("rating_gk", None)
    return ConversationHandler.END

async def rating_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    elo = get_rating_elo(user.id)
    team = get_rating_team(user.id)
    if not team:
        await update.message.reply_text(
            f"⭐ Ваш рейтинг: {elo}\n\n❌ У вас ещё нет состава. Используйте /rating_team, чтобы его создать."
        )
        return
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    gk_card = card_map.get(team["gk"])
    lines = [f"🥅 Вратарь: {gk_card['name'] if gk_card else team['gk']}"]
    for fid in team["field"]:
        fc = card_map.get(fid)
        lines.append(f"⚔️ Полевой: {fc['name'] if fc else fid}")
    await update.message.reply_text(f"⭐ Ваш рейтинг: {elo}\n\n" + "\n".join(lines))

def _team_strength(team: dict, card_map: dict) -> float:
    gk_power = get_card_power(card_map.get(team["gk"], {}))
    field_power = sum(get_card_power(card_map.get(fid, {})) for fid in team["field"])
    return gk_power * 1.5 + field_power

async def _get_display_name(context: ContextTypes.DEFAULT_TYPE, user_id) -> str:
    if user_id is None:
        return "Бот-соперник"
    try:
        chat = await context.bot.get_chat(user_id)
        return f"@{chat.username}" if chat.username else f"Игрок {user_id}"
    except Exception:
        return f"Игрок {user_id}"

def _generate_bot_team() -> dict:
    all_cards = load_data(CARDS_FILE, [])
    if len(all_cards) < 4:
        # На случай очень маленькой базы карточек - дублировать нельзя, но и падать не надо
        ids = [c["id"] for c in all_cards]
        while len(ids) < 4:
            ids.append(ids[0] if ids else 1)
        return {"gk": ids[0], "field": ids[1:4]}
    chosen = random.sample(all_cards, 4)
    return {"gk": chosen[0]["id"], "field": [c["id"] for c in chosen[1:4]]}

HIT_EVENTS = [
    "💥 {team} наносит жёсткий силовой приём!",
    "🥅 {team} упускает стопроцентный момент!",
    "🧤 Вратарь соперника вытаскивает шайбу из девятки против {team}!",
    "🥊 Игрок команды {team} отправляется на скамейку штрафников (2 минуты)!",
]
GOAL_EVENTS = [
    "🚨 ГОЛ! {team} забрасывает шайбу!",
    "⚡ {team} реализует большинство и открывает счёт!",
    "🎯 Точный бросок в упор - {team} забивает красивый гол!",
]

async def _simulate_match(context: ContextTypes.DEFAULT_TYPE, user_a: int, user_b):
    """user_b может быть None (матч против бота)."""
    team_a = get_rating_team(user_a)
    team_b = get_rating_team(user_b) if user_b else _generate_bot_team()

    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}

    strength_a = _team_strength(team_a, card_map)
    strength_b = _team_strength(team_b, card_map)
    total = strength_a + strength_b if (strength_a + strength_b) > 0 else 1
    p_a = strength_a / total

    name_a = await _get_display_name(context, user_a)
    name_b = await _get_display_name(context, user_b)

    goals_a, goals_b = 0, 0
    highlights = []
    for period in range(1, 4):
        highlights.append(f"\n<b>Период {period}:</b>")
        num_events = random.randint(2, 4)
        for _ in range(num_events):
            acting_team_is_a = random.random() < p_a
            team_name = name_a if acting_team_is_a else name_b
            if random.random() < 0.35:
                event = random.choice(GOAL_EVENTS).format(team=team_name)
                if acting_team_is_a:
                    goals_a += 1
                else:
                    goals_b += 1
            else:
                event = random.choice(HIT_EVENTS).format(team=team_name)
            highlights.append(event)

    winner = None
    if goals_a > goals_b:
        winner = user_a
    elif goals_b > goals_a:
        winner = user_b  # может быть None (победил бот)

    # Обновление ELO только для реальных пользователей
    elo_a = get_rating_elo(user_a)
    elo_b = get_rating_elo(user_b) if user_b else 1000
    K = 32
    expected_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    if goals_a > goals_b:
        score_a = 1.0
    elif goals_a < goals_b:
        score_a = 0.0
    else:
        score_a = 0.5
    new_elo_a = round(elo_a + K * (score_a - expected_a))
    set_rating_elo(user_a, new_elo_a)
    if user_b:
        expected_b = 1 - expected_a
        new_elo_b = round(elo_b + K * ((1 - score_a) - expected_b))
        set_rating_elo(user_b, new_elo_b)

    result_text_a = "🏆 Победа!" if goals_a > goals_b else ("🤝 Ничья." if goals_a == goals_b else "😞 Поражение.")
    summary_a = (
        f"⚔️ <b>Матч завершён: {name_a} {goals_a}:{goals_b} {name_b}</b>\n"
        + "".join(f"\n{h}" for h in highlights)
        + f"\n\n{result_text_a}\n⭐ Рейтинг: {elo_a} → {new_elo_a}"
    )
    try:
        await context.bot.send_message(user_a, summary_a, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить результат матча пользователю {user_a}: {e}")

    if user_b:
        result_text_b = "🏆 Победа!" if goals_b > goals_a else ("🤝 Ничья." if goals_a == goals_b else "😞 Поражение.")
        summary_b = (
            f"⚔️ <b>Матч завершён: {name_a} {goals_a}:{goals_b} {name_b}</b>\n"
            + "".join(f"\n{h}" for h in highlights)
            + f"\n\n{result_text_b}\n⭐ Рейтинг: {elo_b} → {new_elo_b}"
        )
        try:
            await context.bot.send_message(user_b, summary_b, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить результат матча пользователю {user_b}: {e}")

async def _wait_and_fallback_to_bot(context: ContextTypes.DEFAULT_TYPE, user_id: int, wait_seconds: int = 90):
    await asyncio.sleep(wait_seconds)
    queue = context.bot_data.setdefault("rating_queue", [])
    entry = next((q for q in queue if q["user_id"] == user_id), None)
    if not entry:
        return  # уже нашли соперника
    queue.remove(entry)
    try:
        await context.bot.send_message(user_id, "🤖 Соперник не найден за отведённое время - вы сыграете с ботом.")
    except Exception:
        pass
    await _simulate_match(context, user_id, None)

async def find_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not get_rating_team(user.id):
        await update.message.reply_text("❌ У вас нет состава. Сначала используйте /rating_team.")
        return

    queue = context.bot_data.setdefault("rating_queue", [])
    queue[:] = [q for q in queue if q["user_id"] != user.id]

    opponent_entry = next((q for q in queue), None)
    if opponent_entry:
        queue.remove(opponent_entry)
        await update.message.reply_text("⚔️ Соперник найден! Матч начнётся примерно через минуту...")
        try:
            await context.bot.send_message(opponent_entry["user_id"], "⚔️ Соперник найден! Матч начнётся примерно через минуту...")
        except Exception:
            pass
        await asyncio.sleep(60)
        await _simulate_match(context, user.id, opponent_entry["user_id"])
    else:
        queue.append({"user_id": user.id, "joined": time.time()})
        await update.message.reply_text(
            "🔍 Ищем соперника... Если никого не найдётся в течение 90 секунд, вы сыграете с ботом."
        )
        asyncio.create_task(_wait_and_fallback_to_bot(context, user.id, 90))

# ============================ MAIN ============================
def main() -> None:
    os.makedirs(CARDS_IMAGE_DIR, exist_ok=True)

    # Инициализация файлов
    if not os.path.exists(CARDS_FILE):
        save_data(CARDS_FILE, [
            {"id": 1, "name": "Тумба", "rarity": "Легендарная", "image": "tumba.png", "description": "x2 Чемпион РЕКХЛ"},
            {"id": 2, "name": "Тимахез", "rarity": "Редкая", "image": "tima.png", "description": "Тимакез дота 2"},
            {"id": 3, "name": "Казума", "rarity": "Эпическая", "image": "kazuma.png", "description": "Алкаш"},
            {"id": 4, "name": "Китаец", "rarity": "Обычная", "image": "kitaec.png", "description": "Узкоглазый"}
        ])

    # Создаём файлы, если их нет
    for f in [USERS_FILE, BLACKLIST_FILE, MODERATORS_FILE, COINS_FILE, SHOP_FILE, PROMOCODES_FILE, EVENTS_FILE, BETS_FILE]:
        if not os.path.exists(f):
            if f in [BLACKLIST_FILE, MODERATORS_FILE, SHOP_FILE, EVENTS_FILE, BETS_FILE]:
                save_data(f, [])
            else:
                save_data(f, {})

    # Инициализация редкостей
    if not os.path.exists(RARITIES_FILE):
        save_data(RARITIES_FILE, [
            {"name": "Легендарная", "emoji": "🔥", "droppable": True},
            {"name": "Блещет умом", "emoji": "🧠", "droppable": True},
            {"name": "Эпическая", "emoji": "💎", "droppable": True},
            {"name": "Редкая", "emoji": "✨", "droppable": True},
            {"name": "Обычная", "emoji": "🃏", "droppable": True},
            {"name": "Эксклюзивная", "emoji": "😎", "droppable": False}
        ])
    else:
        # Проверяем, есть ли хоть одна droppable редкость
        rarities = load_data(RARITIES_FILE, [])
        if not rarities or not any(r.get("droppable", True) for r in rarities):
            default_rarities = [
                {"name": "Легендарная", "emoji": "🔥", "droppable": True},
                {"name": "Блещет умом", "emoji": "🧠", "droppable": True},
                {"name": "Эпическая", "emoji": "💎", "droppable": True},
                {"name": "Редкая", "emoji": "✨", "droppable": True},
                {"name": "Обычная", "emoji": "🃏", "droppable": True},
                {"name": "Эксклюзивная", "emoji": "😎", "droppable": False}
            ]
            save_data(RARITIES_FILE, default_rarities)
            logger.warning("Файл редкостей был пуст или не содержал выпадаемых – пересоздан.")

    application = Application.builder().token(TOKEN).build()

    # ConversationHandler'ы
    addcard_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin_addcard", admin_addcard)],
        states={
            ADMIN_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_name)],
            ADMIN_CARD_RARITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_rarity)],
            ADMIN_CARD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_description)],
            ADMIN_CARD_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, admin_card_image)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addcard)],
    )

    addrarity_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin_addrarity", admin_addrarity)],
        states={
            ADMIN_RARITY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_name)],
            ADMIN_RARITY_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_emoji)],
            ADMIN_RARITY_DROPPABLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_droppable)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addrarity)],
    )

    addshopitem_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin_addshopitem", admin_addshopitem)],
        states={
            ADMIN_SHOP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_name)],
            ADMIN_SHOP_TYPE: [CallbackQueryHandler(admin_shop_type)],
            ADMIN_SHOP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_price)],
            ADMIN_SHOP_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_cards)],
            ADMIN_SHOP_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addshopitem)],
    )

    editcard_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin_editcard", admin_editcard)],
        states={
            EDIT_CARD_FIELD: [CallbackQueryHandler(edit_card_field)],
            EDIT_CARD_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_card_value),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, edit_card_value)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_editcard)],
    )

    craft_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("craft", start_craft)],
        states={
            CRAFT_SELECT_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_craft)],
        },
        fallbacks=[CommandHandler("cancel", cancel_craft)],
    )

    promo_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("create_promo", create_promo_start)],
        states={
            PROMO_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_name)],
            PROMO_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_type)],
            PROMO_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_value)],
            PROMO_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_uses)],
            PROMO_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel_promo)],
    )

    rating_team_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("rating_team", rating_team_start)],
        states={
            RATING_TEAM_GK: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_gk)],
            RATING_TEAM_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_field)],
        },
        fallbacks=[CommandHandler("cancel", cancel_rating_team)],
    )

    application.add_handler(addcard_conv_handler)
    application.add_handler(addrarity_conv_handler)
    application.add_handler(addshopitem_conv_handler)
    application.add_handler(editcard_conv_handler)
    application.add_handler(craft_conv_handler)
    application.add_handler(promo_conv_handler)
    application.add_handler(rating_team_conv_handler)

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_card", get_card))
    application.add_handler(CommandHandler("my_cards", show_collection))
    application.add_handler(CommandHandler("card_info", card_info))
    application.add_handler(CommandHandler("balance", show_balance))
    application.add_handler(CommandHandler("daily", daily_claim))
    application.add_handler(CommandHandler("shop", show_shop))
    application.add_handler(CommandHandler("buy", buy_item))
    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CommandHandler("admin_listcards", admin_listcards))
    application.add_handler(CommandHandler("admin_deletecard", admin_deletecard))
    application.add_handler(CommandHandler("admin_resettimer", admin_resettimer))
    application.add_handler(CommandHandler("admin_givecard", admin_givecard))
    application.add_handler(CommandHandler("admin_broadcast", admin_broadcast))
    application.add_handler(CommandHandler("ban", admin_ban))
    application.add_handler(CommandHandler("unban", admin_unban))
    application.add_handler(CommandHandler("add_moderator", add_moderator))
    application.add_handler(CommandHandler("remove_moderator", remove_moderator))
    application.add_handler(CommandHandler("admin_givecoins", admin_givecoins))
    application.add_handler(CommandHandler("admin_removecoins", admin_removecoins))
    application.add_handler(CommandHandler("admin_listrarities", admin_listrarities))
    application.add_handler(CommandHandler("admin_listshop", admin_listshop))
    application.add_handler(CommandHandler("casino", casino))
    application.add_handler(CommandHandler("coin", coin_flip))
    application.add_handler(CommandHandler("buff", buff_info))
    application.add_handler(CommandHandler("set_buff", set_buff))
    application.add_handler(CommandHandler("upgrade_buff", upgrade_buff))
    application.add_handler(CommandHandler("redeem", redeem_promo))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("givecard", givecard))
    application.add_handler(CommandHandler("create_match", create_match))
    application.add_handler(CommandHandler("finish_match", finish_match))
    application.add_handler(CommandHandler("bet", bet_start))
    application.add_handler(CommandHandler("my_bets", my_bets))
    application.add_handler(CommandHandler("find_match", find_match))
    application.add_handler(CommandHandler("rating", rating_profile))

    # CallbackQueryHandler'ы
    application.add_handler(CallbackQueryHandler(admin_shop_type, pattern=r"^(reset|pack)"))
    application.add_handler(CallbackQueryHandler(set_buff_buttons, pattern=r"^(confirm_set_buff_|cancel_set_buff)"))
    application.add_handler(CallbackQueryHandler(upgrade_buff_buttons, pattern=r"^(confirm_upgrade_buff|cancel_upgrade_buff)"))
    application.add_handler(CallbackQueryHandler(bet_match_callback, pattern=r"^bet_match_"))
    application.add_handler(CallbackQueryHandler(bet_outcome_callback, pattern=r"^bet_outcome_"))

    # MessageHandler для ввода суммы ставки
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bet_amount))

    # Проверка подписки (обрабатывает все сообщения)
    application.add_handler(MessageHandler(filters.ALL, check_subscription))

    application.run_polling()

if __name__ == "__main__":
    main()