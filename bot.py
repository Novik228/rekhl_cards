import json
import os
import random
import time
import html
import asyncio
from datetime import datetime, timedelta
import logging
from collections import Counter
import io

# Pillow нужен для картинки рейтингового состава (/rating).
# Если не установлен (pip install Pillow) — бот работает, состав показывается текстом.
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    PollHandler,
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
CLANS_FILE = "clans.json"
MARKET_FILE = "market.json"
TRADES_FILE = "trades.json"
SEASON_FILE = "season.json"
CHANNEL_EVENTS_FILE = "channel_events.json"
DROP_BOOSTS_FILE = "drop_boosts.json"
ISSUED_PROMO_CODES_FILE = "issued_promo_ids.json"
CARDS_IMAGE_DIR = "cards_images"

# ============================ СИСТЕМА КЛАНОВ ============================
CLAN_CREATE_COST = 1000          # стоимость создания клана
CLAN_BUFF_TIERS = {1: 8, 2: 5, 3: 3}  # % бонуса к монетам по месту клана в рейтинге казны (1 - самый большой)
CLAN_UPGRADE_COSTS = {1: 500, 2: 1000, 3: 2000, 4: 3500, 5: 5000}
CLAN_UPGRADE_BONUS_PER_LEVEL = 2   # +2% к клан-баффу за каждый уровень прокачки

# ============================ РЕДКОСТИ: ДЕФОЛТНЫЕ ШАНСЫ ============================
DEFAULT_RARITY_CHANCES = {
    "Легендарная": 0.05,
    "Блещет умом": 0.07,
    "Эпическая": 0.15,
    "Редкая": 0.30,
    "Обычная": 0.50,
}

# ============================ МАРКЕТ ============================
MARKET_MIN_PRICES = {
    "Легендарная": 500,
    "Эксклюзивная": 1000,
}

# ============================ РАБОТА КАРТОЧКАМИ ============================
WORK_COOLDOWN_SECONDS = 2 * 3600
WORK_DURATION_SECONDS = 3600
WORK_REWARDS = {
    "Обычная": (20, 40),
    "Редкая": (40, 70),
    "Эпическая": (70, 100),
    "Блещет умом": (100, 150),
    "Легендарная": (150, 250),
    "Эксклюзивная": (250, 400),
}

DEFAULT_RATING_ELO = 1000

# ============================ СОСТОЯНИЯ ============================
ADMIN_CARD_NAME, ADMIN_CARD_RARITY, ADMIN_CARD_DESCRIPTION, ADMIN_CARD_IMAGE = range(60, 64)
ADMIN_SHOP_NAME, ADMIN_SHOP_TYPE, ADMIN_SHOP_PRICE, ADMIN_SHOP_CARDS, ADMIN_SHOP_DURATION = range(70, 75)
ADMIN_RARITY_NAME, ADMIN_RARITY_EMOJI, ADMIN_RARITY_DROPPABLE, ADMIN_RARITY_CHANCE = range(80, 84)
ADMIN_EDIT_RARITY_NAME, ADMIN_EDIT_RARITY_EMOJI, ADMIN_EDIT_RARITY_DROPPABLE, ADMIN_EDIT_RARITY_CHANCE = range(90, 94)
EDIT_CARD_SELECT, EDIT_CARD_FIELD, EDIT_CARD_VALUE = range(100, 103)
CRAFT_SELECT_CARDS = 20

# Промокоды
PROMO_NAME, PROMO_TYPE, PROMO_VALUE, PROMO_USES, PROMO_DURATION = range(40, 45)

# Рейтинговый режим
RATING_TEAM_GK, RATING_TEAM_FIELD = 30, 31

# Сезоны рейтинга
SEASON_NUMBER, SEASON_PRIZE_1, SEASON_PRIZE_2, SEASON_PRIZE_3 = range(50, 54)

# События канала (админ)
EVENT_BOOST_RARITY, EVENT_BOOST_MULT, EVENT_BOOST_DURATION = range(3)
EVENT_SCHED_DELAY, EVENT_SCHED_RARITY, EVENT_SCHED_MULT, EVENT_SCHED_DURATION = range(3, 7)
EVENT_POLL_TYPE, EVENT_POLL_VALUE, EVENT_POLL_DURATION, EVENT_PROMO_DURATION = range(7, 11)

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

def _next_promo_id(prefix: str) -> int:
    issued = load_data(ISSUED_PROMO_CODES_FILE, {})
    ids = issued.get(prefix, [])
    new_id = 1
    while new_id in ids:
        new_id += 1
    ids.append(new_id)
    issued[prefix] = ids
    save_data(ISSUED_PROMO_CODES_FILE, issued)
    return new_id

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

# ============================ ЛОГИ ДЕЙСТВИЙ МОДЕРАТОРОВ ============================
async def log_moderator_action(context: ContextTypes.DEFAULT_TYPE, actor_id: int, action: str) -> None:
    """Отправляет администратору лог о действии модератора (администратора не спамим о его же действиях)."""
    if actor_id == ADMIN_ID:
        return
    try:
        actor_name = f"ID {actor_id}"
        try:
            chat = await context.bot.get_chat(actor_id)
            if chat.username:
                actor_name = f"@{chat.username} (ID {actor_id})"
        except Exception:
            pass
        await context.bot.send_message(
            ADMIN_ID,
            f"🛡 <b>Лог модератора</b>\n👤 {html.escape(actor_name)}\n📋 {html.escape(action)}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить лог модератора администратору: {e}")

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
    user_cards = get_available_card_ids(user_id)
    locked = get_locked_card_ids(user_id)
    if not user_cards and not locked:
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
        message += f"{emoji} <b>{html.escape(rarity)}</b> ({count_in_rarity}):\n"
        sorted_cards = sorted(cards_in_rarity, key=lambda x: x[0]['id'])
        for card, count in sorted_cards:
            count_text = f" (x{count})" if count > 1 else ""
            message += f"   • {html.escape(card['name'])}{count_text} [ID: {card['id']}]\n"
        message += "\n"
    if locked:
        all_cards = load_data(CARDS_FILE, [])
        card_map = {c["id"]: c for c in all_cards}
        locked_counts = Counter(locked)
        message += f"🔒 <b>Недоступны</b> ({len(locked)} — на маркете или в работе):\n"
        for cid in sorted(locked_counts):
            cname = card_map.get(cid, {}).get("name", f"ID {cid}")
            count = locked_counts[cid]
            count_text = f" (x{count})" if count > 1 else ""
            message += f"   • {html.escape(cname)}{count_text} [ID: {cid}]\n"
        message += "\n"
    # Всего = карточки на руках + копии на маркете/в работе (они удалены из cards).
    total_all = len(user_data.get("cards", [])) + len(locked)
    message += f"📚 <b>Доступно карточек: {total_count}</b>"
    if locked:
        message += f" (всего в коллекции: {total_all})"
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

# ============================ КРАСИВЫЕ РАМКИ КАРТОЧЕК (Pillow) ============================
FRAMED_CARDS_DIR = "cards_images_framed"

# Цвета рамок по редкости: (основной, светлый акцент)
RARITY_FRAME_COLORS = {
    "Обычная": ((150, 155, 165), (205, 210, 220)),
    "Редкая": ((60, 150, 255), (150, 205, 255)),
    "Эпическая": ((165, 85, 255), (215, 165, 255)),
    "Легендарная": ((255, 190, 30), (255, 235, 140)),
    "Блещет умом": ((0, 210, 190), (150, 255, 240)),
    "Эксклюзивная": ((255, 55, 90), (255, 155, 175)),
}

def get_framed_card_photo(card: dict):
    """Картинка карточки с рамкой по редкости (файл) или None.

    Результат кэшируется на диск: рамка рисуется ОДИН раз, дальше отдаётся
    готовый файл — никакой нагрузки при большом потоке игроков.
    None -> отправляем оригинал, как раньше (нет Pillow / ошибка)."""
    if not PIL_AVAILABLE:
        return None
    src_path = os.path.join(CARDS_IMAGE_DIR, card.get("image", ""))
    if not os.path.exists(src_path):
        return None
    try:
        os.makedirs(FRAMED_CARDS_DIR, exist_ok=True)
        # Ключ кэша: id + имя + редкость + время изменения исходника.
        # Если админ заменит фото/название/редкость — рамка перерисуется сама.
        mtime = int(os.path.getmtime(src_path))
        cache_key = f"{card['id']}_{abs(hash((card.get('name'), card['rarity'], mtime))) % 10**10}.png"
        cache_path = os.path.join(FRAMED_CARDS_DIR, cache_key)
        if os.path.exists(cache_path):
            return open(cache_path, "rb")

        main, light = RARITY_FRAME_COLORS.get(card["rarity"], RARITY_FRAME_COLORS["Обычная"])
        img = Image.open(src_path).convert("RGB")
        target_w = 512
        target_h = max(1, int(img.height * target_w / max(1, img.width)))
        img = img.resize((target_w, target_h))

        border = 26
        panel = 118
        width = target_w + border * 2
        height = target_h + border * 2 + panel
        canvas = Image.new("RGB", (width, height), (16, 20, 30))
        draw = ImageDraw.Draw(canvas)

        legendary = is_legendary_or_higher(card["rarity"])
        # "Свечение" для легендарных и выше: несколько рамок от тёмного к светлому
        if legendary:
            glow = (tuple(c // 3 for c in main), tuple(c // 2 for c in main), main)
            for i, col in enumerate(glow):
                draw.rectangle([i * 3, i * 3, width - 1 - i * 3, height - 1 - i * 3], outline=col, width=3)
        # Основная рамка вокруг изображения + светлая линия внутри
        draw.rectangle([border - 8, border - 8, width - border + 8, target_h + border + 8], outline=main, width=6)
        draw.rectangle([border - 2, border - 2, width - border + 2, target_h + border + 2], outline=light, width=2)
        canvas.paste(img, (border, border))
        # Уголки-акценты
        cl = 34
        corners = (
            (border - 8, border - 8, 1, 1),
            (width - border + 8, border - 8, -1, 1),
            (border - 8, target_h + border + 8, 1, -1),
            (width - border + 8, target_h + border + 8, -1, -1),
        )
        for cx, cy, dx, dy in corners:
            draw.line([cx, cy, cx + dx * cl, cy], fill=light, width=6)
            draw.line([cx, cy, cx, cy + dy * cl], fill=light, width=6)
        # Нижняя панель: название + редкость
        name = str(card.get("name", "?"))
        if len(name) > 24:
            name = name[:23] + "..."
        rarity_text = str(card["rarity"]).upper()
        if legendary:
            rarity_text = f"★ {rarity_text} ★"
        font_name = _load_team_font(40)
        font_rarity = _load_team_font(26)
        try:
            name_w = draw.textlength(name, font=font_name)
            rar_w = draw.textlength(rarity_text, font=font_rarity)
        except Exception:
            name_w = rar_w = 0
        y0 = target_h + border * 2
        draw.text((max(0, (width - name_w) / 2), y0 + 10), name, font=font_name, fill=(240, 243, 250))
        draw.text((max(0, (width - rar_w) / 2), y0 + 62), rarity_text, font=font_rarity, fill=main)

        canvas.save(cache_path, format="PNG")
        return open(cache_path, "rb")
    except Exception as e:
        logger.warning(f"Не удалось нарисовать рамку карточки: {e}")
        return None

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

# ============================ РЕЙТИНГ: ЗВАНИЯ И СТАТИСТИКА ============================
RATING_TITLES = [
    (1400, "🌌", "Легенда"),
    (1300, "👑", "Элита"),
    (1200, "💎", "Мастер"),
    (1100, "🥇", "Профи"),
    (1000, "🥈", "Полупрофи"),
    (900, "⚪", "Любитель"),
    (0, "🥉", "Новичок"),
]

def get_rating_title(elo: int):
    for threshold, emoji, name in RATING_TITLES:
        if elo >= threshold:
            return emoji, name
    return "🥉", "Новичок"

def get_rating_stats(user_id: int) -> dict:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    stats = user_data.get("rating_stats", {})
    return {
        "wins": stats.get("wins", 0),
        "losses": stats.get("losses", 0),
        "draws": stats.get("draws", 0),
    }

def add_rating_result(user_id: int, result: str) -> None:
    """result: 'win' | 'loss' | 'draw'"""
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    stats = user_data.get("rating_stats", {"wins": 0, "losses": 0, "draws": 0})
    key = {"win": "wins", "loss": "losses", "draw": "draws"}.get(result)
    if key:
        stats[key] = stats.get(key, 0) + 1
    user_data["rating_stats"] = stats
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

# ============================ КЛАНЫ: ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============================
def load_clans() -> list:
    return load_data(CLANS_FILE, [])

def save_clans(clans: list) -> None:
    save_data(CLANS_FILE, clans)

def get_clan_by_id(clan_id):
    if clan_id is None:
        return None
    clans = load_clans()
    return next((c for c in clans if c["id"] == clan_id), None)

def get_user_clan_id(user_id: int):
    users = load_data(USERS_FILE, {})
    return users.get(str(user_id), {}).get("clan_id")

def set_user_clan_id(user_id: int, clan_id) -> None:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    if clan_id is None:
        user_data.pop("clan_id", None)
    else:
        user_data["clan_id"] = clan_id
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

def get_ranked_clans() -> list:
    """Кланы, участвующие в рейтинге (есть участники и казна > 0), отсортированные по казне."""
    clans = load_clans()
    eligible = [c for c in clans if c.get("members") and c.get("treasury", 0) > 0]
    return sorted(eligible, key=lambda c: c["treasury"], reverse=True)

def get_clan_rank(clan_id) -> int:
    """Место клана в рейтинге казны (1 = первое место), либо None, если клан не в рейтинге."""
    if clan_id is None:
        return None
    ranked = get_ranked_clans()
    for i, c in enumerate(ranked, 1):
        if c["id"] == clan_id:
            return i
    return None

def get_top_clan():
    """Клан на первом месте рейтинга казны, либо None."""
    ranked = get_ranked_clans()
    return ranked[0] if ranked else None

def get_clan_coin_multiplier(user_id: int) -> float:
    """Небольшой бафф к получаемым монетам для участников топ-3 кланов по казне (+ прокачка из казны)."""
    clan_id = get_user_clan_id(user_id)
    if clan_id is None:
        return 1.0
    bonus = get_clan_buff_bonus_percent(clan_id)
    if bonus > 0:
        return 1.0 + bonus / 100.0
    return 1.0

def get_total_coin_multiplier(user_id: int) -> float:
    """Итоговый множитель монет: бафф-карта + клановый бафф.

    Бонусы СКЛАДЫВАЮТСЯ (а не перемножаются), а при стаке сразу
    нескольких баффов суммарный бонус урезается на 15%,
    чтобы множители не становились слишком большими.
    Применяется везде, где начисляются монеты:
    /get_card, /daily, /work, казино, монетка, слоты."""
    bonuses = []
    card_bonus = get_coin_bonus_multiplier(user_id) - 1.0
    if card_bonus > 0:
        bonuses.append(card_bonus)
    clan_bonus = get_clan_coin_multiplier(user_id) - 1.0
    if clan_bonus > 0:
        bonuses.append(clan_bonus)
    total_bonus = sum(bonuses)
    if len(bonuses) > 1:
        total_bonus *= 0.85  # небольшой минус за стак нескольких баффов
    return 1.0 + total_bonus

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

# ============================ КАРТОЧКИ: ДОСТУПНОСТЬ И РЕДКОСТИ ============================
def is_default_rarity(rarity_name: str) -> bool:
    return rarity_name in DEFAULT_RARITY_CHANCES

def get_rarity_drop_chance(rarity_name: str) -> float:
    if rarity_name in DEFAULT_RARITY_CHANCES:
        return DEFAULT_RARITY_CHANCES[rarity_name]
    rarities = load_data(RARITIES_FILE, [])
    for rarity in rarities:
        if rarity["name"] == rarity_name:
            return rarity.get("chance", 0.01)
    return 0.0

def get_all_rarity_chances_display() -> list:
    """Список (name, emoji, chance, droppable, is_default) для отображения админу."""
    rarities = load_data(RARITIES_FILE, [])
    result = []
    seen = set()
    for rarity in rarities:
        name = rarity["name"]
        seen.add(name)
        result.append({
            "name": name,
            "emoji": rarity.get("emoji", "🃏"),
            "chance": get_rarity_drop_chance(name),
            "droppable": rarity.get("droppable", True),
            "is_default": is_default_rarity(name),
        })
    for name, chance in DEFAULT_RARITY_CHANCES.items():
        if name not in seen:
            result.append({
                "name": name,
                "emoji": get_rarity_emoji(name),
                "chance": chance,
                "droppable": name != "Эксклюзивная",
                "is_default": True,
            })
    return result

def get_active_drop_boosts() -> list:
    boosts = load_data(DROP_BOOSTS_FILE, [])
    now = time.time()
    active = [b for b in boosts if b.get("until", 0) > now]
    if len(active) != len(boosts):
        save_data(DROP_BOOSTS_FILE, active)
    return active

def get_drop_weights() -> dict:
    rarities = load_data(RARITIES_FILE, [])
    droppable = [r for r in rarities if r.get("droppable", True)]
    weights = {}
    for rarity in droppable:
        name = rarity["name"]
        weights[name] = get_rarity_drop_chance(name)
        if weights[name] <= 0:
            weights[name] = 0.01
    if not weights:
        weights = dict(DEFAULT_RARITY_CHANCES)
    for boost in get_active_drop_boosts():
        rarity = boost.get("rarity")
        if rarity in weights:
            weights[rarity] *= boost.get("multiplier", 2.0)
    return weights

def pick_rarity_for_drop() -> str:
    weights = get_drop_weights()
    if not weights:
        return "Обычная"
    names = list(weights.keys())
    vals = [weights[n] for n in names]
    return random.choices(names, weights=vals, k=1)[0]

def get_user_listed_card_ids(user_id: int) -> list:
    market = load_data(MARKET_FILE, [])
    return [item["card_id"] for item in market if item["seller_id"] == user_id]

def get_user_working_card(user_id: int):
    users = load_data(USERS_FILE, {})
    work = users.get(str(user_id), {}).get("working_card")
    if work and time.time() < work.get("finish_at", 0):
        return work
    return None

def get_locked_card_ids(user_id: int) -> list:
    locked = list(get_user_listed_card_ids(user_id))
    work = get_user_working_card(user_id)
    if work:
        locked.append(work["card_id"])
    return locked

def get_available_card_ids(user_id: int) -> list:
    users = load_data(USERS_FILE, {})
    # Копии на маркете и в работе уже физически удалены из cards
    # (см. sell_card/work_command -> remove_one_card), поэтому всё, что осталось
    # в cards, доступно. Повторное вычитание locked прятало оставшиеся
    # дубликаты выставленной карточки.
    return list(users.get(str(user_id), {}).get("cards", []))

def remove_one_card(user_id: int, card_id: int) -> bool:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    cards = user_data.get("cards", [])
    if card_id not in cards:
        return False
    cards.remove(card_id)
    user_data["cards"] = cards
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)
    return True

def add_one_card(user_id: int, card_id: int) -> None:
    users = load_data(USERS_FILE, {})
    user_data = users.setdefault(str(user_id), {"cards": [], "last_drop": 0})
    if "cards" not in user_data:
        user_data["cards"] = []
    user_data["cards"].append(card_id)
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)
    add_seen_card(user_id, card_id)

async def post_to_channel(context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = "HTML") -> None:
    try:
        await context.bot.send_message(CHANNEL_ID, text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в канал: {e}")

def get_clan_buff_bonus_percent(clan_id) -> int:
    clan = get_clan_by_id(clan_id)
    if not clan:
        return 0
    rank = get_clan_rank(clan_id)
    base = CLAN_BUFF_TIERS.get(rank, 0)
    upgrade = clan.get("buff_upgrade_level", 0) * CLAN_UPGRADE_BONUS_PER_LEVEL
    return base + upgrade

# ============================ ОСНОВНЫЕ КОМАНДЫ ============================

USER_COMMANDS_TEXT = (
    "📋 Основные команды:\n"
    "/get_card - получить карточку\n"
    "/my_cards - моя коллекция\n"
    "/shop - магазин\n"
    "/trade <user_id> <card_id> - предложить обмен карточкой\n"
    "/market - маркет карточек\n"
    "/sell <card_id> <цена> - выставить карточку на продажу\n"
    "/my_listings - мои объявления на маркете\n"
    "/work <card_id> - отправить карточку работать (раз в 2 часа)\n"
    "/balance - баланс монет\n"
    "/card_info <card_id> - информация о карточке\n"
    "/craft - улучшить карточки\n"
    "/leaderboard - таблица лидеров\n"
    "/casino <сумма> - сыграть в казино\n"
    "/coin <орел|решка> <сумма> - подбросить монетку\n"
    "/slots <сумма> - игровые автоматы \U0001F3B0\n"
    "/keyboard - включить удобную клавиатуру\n"
    "/hide - скрыть клавиатуру\n"
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
    "🏰 Кланы:\n"
    "/create_clan <название> - создать клан (1000 монет)\n"
    "/join_clan <ID> - вступить в клан\n"
    "/leave_clan - покинуть клан\n"
    "/clan_deposit <сумма> - пополнить казну клана\n"
    "/clan_info [ID] - информация о клане\n"
    "/clan_members - участники и вклады (создатель)\n"
    "/clan_kick <user_id> - исключить участника (создатель)\n"
    "/clan_type <open|closed> - тип клана (создатель)\n"
    "/clan_invite <user_id> - пригласить в закрытый клан\n"
    "/clan_upgrade - прокачать клан-бафф из казны (создатель)\n"
    "/clans - рейтинг кланов\n\n"
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
    "/admin_unlist <ID объявления> - снять любой лот с маркета\n"
    "/admin_viewcards <user_id> - посмотреть коллекцию игрока\n"
    "/admin_takecard <user_id> <card_id> [кол-во] - забрать карточку у игрока\n"
    "/admin_addrarity - добавить редкость\n"
    "/admin_editrarity - изменить редкость\n"
    "/admin_listrarities - список редкостей и шансов\n"
    "/admin_addshopitem - добавить товар в магазин\n"
    "/admin_listshop - список товаров\n"
    "/admin_editcard <card_id> - изменить карточку\n"
    "/create_promo - создать промокод\n"
    "/events - события и посты в канал\n"
    "/start_season - начать новый рейтинговый сезон\n"
    "/end_season - завершить сезон и выдать призы\n"
    "/create_match <команда1> <команда2> <часы> - создать матч (приём ставок N часов)\n"
    "/finish_match <match_id> <счёт> - завершить матч (например 3:1)"
)

MODERATOR_ONLY_COMMANDS_TEXT = (
    "/admin_addcard - добавить карточку\n"
    "/admin_listcards - список всех карточек\n"
    "/admin_deletecard <card_id> - удалить карточку\n"
    "/admin_addshopitem - добавить товар в магазин\n"
    "/admin_listshop - список товаров\n"
    "/admin_editcard <card_id> - изменить карточку"
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
        # В личке сразу включаем удобную клавиатуру с командами
        kb = get_main_keyboard() if update.effective_chat.type == "private" else None
        await update.message.reply_text(
            "🎮 Добро пожаловать в REKHL CARDS!\n\n" + USER_COMMANDS_TEXT,
            reply_markup=kb
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

    RARITY_CHANCES = get_drop_weights()
    rarities_list = list(RARITY_CHANCES.keys())
    if not rarities_list:
        await update.message.reply_text("⚠️ Нет выпадаемых редкостей! Обратитесь к администратору.")
        return
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
    # Все монетные баффы (карта + клан) складываются со штрафом за стак
    coin_multiplier = get_total_coin_multiplier(user.id)
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
    # Анимация зависит от редкости: чем реже карта — тем длиннее и эффектнее
    RARITY_ANIMATIONS = {
        "Эксклюзивная": [
            "🃏 Тянем карточку из колоды...",
            "🃏 ✨ Колода дрожит...",
            "😎 💫 Карта СИЯЕТ нереальным светом...",
            "😎 🌟 Это что-то ЭКСКЛЮЗИВНОЕ...",
            "😎 🎆 НЕВЕРОЯТНО! Открываем!",
        ],
        "Легендарная": [
            "🃏 Тянем карточку из колоды...",
            "🃏 ✨ Колода нагревается...",
            "🔥 Карта пылает огнём...",
            "🔥 💛 Она СИЯЕТ золотом...",
            "🔥 🎇 ЛЕГЕНДА! Открываем!",
        ],
        "Блещет умом": [
            "🃏 Тянем карточку из колоды...",
            "🧠 ⚡ Карта искрит идеями...",
            "🧠 💡 Она блещет умом...",
            "🧠 🎓 Гениально! Открываем!",
        ],
        "Эпическая": [
            "🃏 Тянем карточку из колоды...",
            "💎 Карта отливает синим...",
            "💎 ✨ Эпично! Открываем!",
        ],
        "Редкая": [
            "🃏 Тянем карточку из колоды...",
            "✨ Что-то блеснуло! Открываем!",
        ],
        "Обычная": [
            "🃏 Тянем карточку из колоды...",
            "🃏 Открываем!",
        ],
    }
    frames = RARITY_ANIMATIONS.get(card["rarity"], RARITY_ANIMATIONS["Обычная"])
    try:
        anim_msg = await update.message.reply_text(frames[0])
        for frame in frames[1:]:
            await asyncio.sleep(0.9)
            await anim_msg.edit_text(frame)
        await asyncio.sleep(0.9)
        await anim_msg.delete()
    except Exception:
        pass
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        photo = get_framed_card_photo(card) or open(image_path, "rb")
        await update.message.reply_photo(photo=photo, caption=caption)
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
        f"🏷 <b>Название</b>: {html.escape(card['name'])}\n"
        f"{emoji} <b>Редкость</b>: {html.escape(card['rarity'])}\n"
    )
    if "description" in card:
        caption += f"📝 <b>Описание</b>: {html.escape(card['description'])}\n"
    card_count = user_data["cards"].count(card_id)
    caption += f"📊 <b>В вашей коллекции</b>: {card_count} шт.\n"
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        photo = get_framed_card_photo(card) or open(image_path, "rb")
        await update.message.reply_photo(photo=photo, caption=caption, parse_mode="HTML")
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

    # Начисляем фиксированные монеты (бафф-карта + клан-бафф складываются)
    total_multiplier = get_total_coin_multiplier(user.id)
    daily_amount = int(DAILY_COINS_AMOUNT * total_multiplier)
    new_balance = update_coins(user.id, daily_amount)

    # Обновляем дату последнего получения
    user_data["last_daily"] = current_time
    users[str(user.id)] = user_data
    save_data(USERS_FILE, users)

    message = (
        f"🎁 <b>Ежедневная награда получена!</b>\n\n"
        f"💰 +{daily_amount} монет\n"
        f"💰 Новый баланс: {new_balance} монет\n"
    )
    if total_multiplier > 1.0:
        bonus_percent = round((total_multiplier - 1.0) * 100)
        message += f"🌟 Бонус баффов (карта + клан): +{bonus_percent}%\n"

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
                f"🏷 {html.escape(card['name'])} ({get_rarity_emoji(card['rarity'])} {html.escape(card['rarity'])})"
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
            card_name = html.escape(card["name"])
            card_rarity = html.escape(card["rarity"])
            emoji = get_rarity_emoji(card["rarity"])
        else:
            card_name = f"Карточка ID {card_id}"
            card_rarity = "Неизвестная"
            emoji = "❓"
        card_count = user_data["cards"].count(card_id)
        count_text = f" (x{card_count})" if card_count > 1 else ""
        pack_text = (
            f"✅ Вы успешно приобрели набор карточек!\n"
            f"🎁 Полученная карточка:\n"
            f"<b>{emoji} {card_rarity}</b>: {card_name}{count_text}\n\n"
            f"💰 Потрачено: {item['price']} монет\n"
            f"💰 Остаток: {new_balance} монет\n\n"
            f"Просмотреть коллекцию: /my_cards"
        )
        # Небольшая анимация открытия пака (для легендарных — подлиннее)
        try:
            anim_msg = await update.message.reply_text("🎁 Открываем набор...")
            await asyncio.sleep(0.8)
            await anim_msg.edit_text("🎁 ✨ Внутри что-то блестит...")
            if card and is_legendary_or_higher(card["rarity"]):
                await asyncio.sleep(0.8)
                await anim_msg.edit_text("🎁 🔥 Оно СИЯЕТ! Неужели...")
            await asyncio.sleep(0.8)
            await anim_msg.edit_text(pack_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(pack_text, parse_mode="HTML")

# Проверка подписки
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if is_banned(user.id):
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        warn_msg = await message.reply_text("❌ Вы заблокированы в этом боте.")
        await asyncio.sleep(5)
        await context.bot.delete_message(chat_id=message.chat_id, message_id=warn_msg.message_id)
        return
    if not await is_subscribed(user.id, context):
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        warn_msg = await message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал!\n"
            f"Подпишитесь здесь: {CHANNEL_LINK}\n"
            "После подписки отправьте /start"
        )
        await asyncio.sleep(10)
        await context.bot.delete_message(chat_id=message.chat_id, message_id=warn_msg.message_id)

# ============================ КЛАВИАТУРА ============================
KEYBOARD_LAYOUT = [
    ["🎴 Получить карту", "📚 Коллекция", "🎁 Награда"],
    ["🛒 Магазин", "🏪 Маркет", "💰 Баланс"],
    ["👤 Профиль", "🏆 Топ", "🃏 Бафф"],
    ["📊 Мои ставки", "🏰 Клан", "⚔️ Рейтинг"],
    ["❌ Скрыть клавиатуру"],
]
ALL_KEYBOARD_BUTTONS = [btn for row in KEYBOARD_LAYOUT for btn in row]

def get_main_keyboard(selective: bool = False) -> ReplyKeyboardMarkup:
    """Основная reply-клавиатура: красивые кнопки вместо голых команд."""
    return ReplyKeyboardMarkup(
        KEYBOARD_LAYOUT,
        resize_keyboard=True,
        selective=selective,
    )

async def show_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    chat = update.effective_chat
    text = "⌨️ Клавиатура включена!\nСкрыть её можно командой /hide"
    if chat.type == "private":
        await update.message.reply_text(text, reply_markup=get_main_keyboard())
    else:
        # В группах используем selective=True + ответ на сообщение пользователя:
        # клавиатуру увидит только тот, кто вызвал команду, а не весь чат.
        await update.message.reply_text(
            text,
            reply_markup=get_main_keyboard(selective=True),
            reply_to_message_id=update.message.message_id,
        )

async def hide_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    text = "⌨️ Клавиатура скрыта. Вернуть: /keyboard"
    if chat.type == "private":
        await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(
            text,
            reply_markup=ReplyKeyboardRemove(selective=True),
            reply_to_message_id=update.message.message_id,
        )

async def keyboard_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Нажатия красивых кнопок клавиатуры -> вызов соответствующей команды."""
    if not update.message or not update.message.text:
        return
    mapping = {
        "🎴 Получить карту": get_card,
        "📚 Коллекция": show_collection,
        "🎁 Награда": daily_claim,
        "🛒 Магазин": show_shop,
        "🏪 Маркет": show_market,
        "💰 Баланс": show_balance,
        "👤 Профиль": profile,
        "🏆 Топ": show_leaderboard,
        "🃏 Бафф": buff_info,
        "📊 Мои ставки": my_bets,
        "🏰 Клан": clan_info,
        "⚔️ Рейтинг": rating_profile,
        "❌ Скрыть клавиатуру": hide_keyboard,
    }
    handler = mapping.get(update.message.text.strip())
    if handler:
        context.args = []
        await handler(update, context)

# ============================ АДМИН-КОМАНДЫ ============================
async def admin_addcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    context.user_data.clear()
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
    await log_moderator_action(
        context, update.effective_user.id,
        f"Добавил новую карточку: {new_card['name']} (ID: {new_id}, редкость: {new_card.get('rarity')})"
    )
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
        message += f"{card['id']}. {html.escape(card['name'])} ({emoji} {html.escape(card['rarity'])})\n"
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
    # Чистим кэш красивых рамок этой карточки
    try:
        if os.path.isdir(FRAMED_CARDS_DIR):
            for fname in os.listdir(FRAMED_CARDS_DIR):
                if fname.startswith(f"{card_id}_"):
                    os.remove(os.path.join(FRAMED_CARDS_DIR, fname))
    except Exception as e:
        logger.error(f"Ошибка очистки кэша рамок: {e}")

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
    await log_moderator_action(
        context, update.effective_user.id,
        f"Удалил карточку: {card['name']} (ID: {card_id})"
    )

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

# Редкости (только админ)
async def admin_addrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("Введите название новой редкости:")
    return ADMIN_RARITY_NAME

async def admin_rarity_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if is_default_rarity(name):
        await update.message.reply_text("❌ Это стандартная редкость из кода — добавить её нельзя. Выберите другое название.")
        return ADMIN_RARITY_NAME
    context.user_data["new_rarity"] = {"name": name}
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
    context.user_data["new_rarity"]["droppable"] = bool(droppable)
    if context.user_data["new_rarity"]["droppable"]:
        await update.message.reply_text(
            "Введите шанс выпадения (от 0.001 до 1.0).\n"
            "Пример: 0.05 = 5%"
        )
        return ADMIN_RARITY_CHANCE
    context.user_data["new_rarity"]["chance"] = 0
    return await _save_new_rarity(update, context)

async def admin_rarity_chance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chance = float(update.message.text.replace(",", "."))
        if not (0.001 <= chance <= 1.0):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите число от 0.001 до 1.0.")
        return ADMIN_RARITY_CHANCE
    context.user_data["new_rarity"]["chance"] = chance
    return await _save_new_rarity(update, context)

async def _save_new_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_rarity = context.user_data["new_rarity"]
    rarities = load_data(RARITIES_FILE, [])
    if any(r["name"] == new_rarity["name"] for r in rarities):
        await update.message.reply_text("❌ Редкость с таким названием уже существует.")
        context.user_data.clear()
        return ConversationHandler.END
    rarities.append(new_rarity)
    save_data(RARITIES_FILE, rarities)
    chance_text = f"{new_rarity.get('chance', 0) * 100:.2f}%" if new_rarity.get("droppable") else "—"
    await update.message.reply_text(
        f"✅ Редкость '{new_rarity['name']}' успешно добавлена!\n"
        f"Смайлик: {new_rarity['emoji']}\n"
        f"Выпадает через /get_card: {'Да' if new_rarity['droppable'] else 'Нет'}\n"
        f"Шанс выпадения: {chance_text}"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_addrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление редкости отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def admin_listrarities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    all_rarities = get_all_rarity_chances_display()
    if not all_rarities:
        await update.message.reply_text("ℹ️ Редкостей нет в базе данных.")
        return
    total_chance = sum(r["chance"] for r in all_rarities if r["droppable"])
    message = "<b>📊 Список редкостей и шансов выпадения</b>\n\n"
    for rarity in all_rarities:
        pct = rarity["chance"] * 100
        norm_pct = (rarity["chance"] / total_chance * 100) if total_chance > 0 and rarity["droppable"] else 0
        lock = " 🔒" if rarity["is_default"] else ""
        message += (
            f"{rarity['emoji']} <b>{html.escape(rarity['name'])}</b>{lock}\n"
            f"   📦 Выпадает: {'Да' if rarity['droppable'] else 'Нет'}\n"
            f"   🎲 Шанс: {pct:.2f}%"
        )
        if rarity["droppable"] and total_chance > 0:
            message += f" (≈{norm_pct:.1f}% от пула)"
        if rarity["is_default"]:
            message += " — <i>стандартная, изменить нельзя</i>"
        message += "\n\n"
    boosts = get_active_drop_boosts()
    if boosts:
        message += "<b>⚡ Активные бусты:</b>\n"
        for b in boosts:
            left = int((b["until"] - time.time()) // 60)
            message += f"• {html.escape(b['rarity'])} x{b.get('multiplier', 2)} — ещё {left} мин\n"
    await update.message.reply_text(message, parse_mode="HTML")

async def admin_editrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return ConversationHandler.END
    rarities = load_data(RARITIES_FILE, [])
    custom = [r for r in rarities if not is_default_rarity(r["name"])]
    if not custom:
        await update.message.reply_text("ℹ️ Нет пользовательских редкостей для редактирования.")
        return ConversationHandler.END
    context.user_data.clear()
    lines = "\n".join(f"• {r['emoji']} {html.escape(r['name'])}" for r in custom)
    await update.message.reply_text(
        f"<b>Редактирование редкости</b>\n\nДоступные редкости:\n{lines}\n\n"
        "Введите название редкости для редактирования:",
        parse_mode="HTML"
    )
    return ADMIN_EDIT_RARITY_NAME

async def admin_edit_rarity_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if is_default_rarity(name):
        await update.message.reply_text("❌ Стандартные редкости нельзя редактировать.")
        return ADMIN_EDIT_RARITY_NAME
    rarities = load_data(RARITIES_FILE, [])
    rarity = next((r for r in rarities if r["name"] == name), None)
    if not rarity:
        await update.message.reply_text("❌ Редкость не найдена. Введите название из списка.")
        return ADMIN_EDIT_RARITY_NAME
    context.user_data["edit_rarity"] = rarity
    await update.message.reply_text(
        f"Редактируем: {rarity['emoji']} {rarity['name']}\n\n"
        f"Текущий смайлик: {rarity['emoji']}\nВведите новый смайлик (или «-» чтобы оставить):"
    )
    return ADMIN_EDIT_RARITY_EMOJI

async def admin_edit_rarity_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text != "-":
        context.user_data["edit_rarity"]["emoji"] = text
    await update.message.reply_text(
        "Могут ли карточки выпадать через /get_card?\n"
        "1 - Да, 0 - Нет (или «-» оставить текущее):"
    )
    return ADMIN_EDIT_RARITY_DROPPABLE

async def admin_edit_rarity_droppable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text != "-":
        try:
            val = int(text)
            if val not in [0, 1]:
                raise ValueError
            context.user_data["edit_rarity"]["droppable"] = bool(val)
        except ValueError:
            await update.message.reply_text("❌ Введите 1, 0 или «-».")
            return ADMIN_EDIT_RARITY_DROPPABLE
    if context.user_data["edit_rarity"].get("droppable", True):
        await update.message.reply_text(
            "Введите новый шанс выпадения (0.001–1.0) или «-» чтобы оставить текущий:"
        )
        return ADMIN_EDIT_RARITY_CHANCE
    context.user_data["edit_rarity"]["chance"] = 0
    return await _save_edited_rarity(update, context)

async def admin_edit_rarity_chance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text != "-":
        try:
            chance = float(text.replace(",", "."))
            if not (0.001 <= chance <= 1.0):
                raise ValueError
            context.user_data["edit_rarity"]["chance"] = chance
        except ValueError:
            await update.message.reply_text("❌ Введите число от 0.001 до 1.0 или «-».")
            return ADMIN_EDIT_RARITY_CHANCE
    return await _save_edited_rarity(update, context)

async def _save_edited_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    edited = context.user_data["edit_rarity"]
    rarities = load_data(RARITIES_FILE, [])
    for i, r in enumerate(rarities):
        if r["name"] == edited["name"]:
            rarities[i] = edited
            break
    save_data(RARITIES_FILE, rarities)
    chance_text = f"{edited.get('chance', 0) * 100:.2f}%" if edited.get("droppable") else "—"
    await update.message.reply_text(
        f"✅ Редкость «{edited['name']}» обновлена!\n"
        f"Смайлик: {edited['emoji']}\n"
        f"Выпадает: {'Да' if edited.get('droppable') else 'Нет'}\n"
        f"Шанс: {chance_text}"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_editrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Редактирование отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# Магазин админ
async def admin_addshopitem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
    context.user_data.clear()
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
    await log_moderator_action(
        context, update.effective_user.id,
        f"Добавил товар в магазин: {new_item['name']} (ID: {new_id}, цена: {new_item['price']})"
    )
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
        context.user_data.clear()
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
        await log_moderator_action(
            context, update.effective_user.id,
            f"Изменил изображение карточки: {cards[card_index]['name']} (ID: {card_id})"
        )
    else:
        new_value = update.message.text
        old_value = cards[card_index].get(field)
        cards[card_index][field] = new_value
        save_data(CARDS_FILE, cards)
        await update.message.reply_text(f"✅ Поле '{field}' успешно обновлено!")
        await log_moderator_action(
            context, update.effective_user.id,
            f"Изменил карточку (ID: {card_id}): поле '{field}' было «{old_value}» -> стало «{new_value}»"
        )
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
    user_cards = get_available_card_ids(user.id)
    if len(user_cards) < 3:
        await update.message.reply_text("❌ У вас менее 3 доступных карточек в коллекции!")
        return ConversationHandler.END
    message = await show_collection_with_ids(user.id)
    message += "\n\n🛠 <b>Система крафта</b>\n" \
               "Выберите 3 карточки ОДНОЙ редкости (Обычная или Редкая) для улучшения.\n" \
               "Введите ID карточек через пробел (например: 5 12 8):"
    await update.message.reply_text(message, parse_mode="HTML")
    context.user_data.clear()
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
    available = get_available_card_ids(user.id)
    available_temp = list(available)
    missing_cards = []
    for card_id in card_ids:
        if card_id in available_temp:
            available_temp.remove(card_id)
        else:
            missing_cards.append(card_id)
    if missing_cards:
        await update.message.reply_text(f"❌ Карточки недоступны (нет в коллекции, на маркете или в работе): {', '.join(map(str, missing_cards))}")
        return CRAFT_SELECT_CARDS
    user_cards = user_data.get("cards", [])
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
    await update.message.reply_text("❌ Действие отменено.")
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
    rating_leaders = []

    for user_id, user_data in users_data.items():
        uid = int(user_id)
        if uid in exclude_ids:
            continue
        user_cards = user_data.get("cards", [])
        rare_count = sum(1 for card_id in user_cards if card_id in rare_cards)
        rare_leaders.append((uid, rare_count))
        total_cards_leaders.append((uid, len(user_cards)))
        rating_leaders.append((uid, user_data.get("rating_elo", DEFAULT_RATING_ELO)))

    rare_leaders.sort(key=lambda x: x[1], reverse=True)
    total_cards_leaders.sort(key=lambda x: x[1], reverse=True)
    rating_leaders.sort(key=lambda x: x[1], reverse=True)

    rare_top = rare_leaders[:5]
    total_cards_top = total_cards_leaders[:5]
    rating_top = rating_leaders[:3]

    async def format_section(title: str, entries, unit: str) -> str:
        section = f"\n<b>{title}</b>\n"
        if not entries:
            return section + "Нет данных\n"
        for i, (user_id, value) in enumerate(entries, 1):
            try:
                user_chat = await context.bot.get_chat(user_id)
                username = user_chat.username or f"ID: {user_id}"
                section += f"{i}. @{html.escape(username)}: {value} {unit}\n"
            except Exception:
                section += f"{i}. ID {user_id}: {value} {unit}\n"
        return section

    message = "<b>🏆 Таблица лидеров</b>\n"
    message += await format_section("💰 Топ по монетам:", coins_top, "монет")
    message += await format_section("🃏 Топ по редким карточкам:", rare_top, "карточек")
    message += await format_section("📚 Топ по общему количеству карточек:", total_cards_top, "карточек")
    message += await format_section("⭐ Топ-3 рейтингового режима:", rating_top, "рейтинга")

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
    if multiplier > 1.0:
        # Баффы (карта + клан) применяются только к реальному выигрышу
        total_multiplier = get_total_coin_multiplier(user.id)
        payout = int(bet + (payout - bet) * total_multiplier)
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
        # Баффы (карта + клан) применяются только к чистому выигрышу (как в казино и слотах)
        total_multiplier = get_total_coin_multiplier(user.id)
        win_amount = int(bet + bet * total_multiplier)
        update_coins(user.id, -bet)
        update_coins(user.id, win_amount)
        new_balance = get_coins(user.id)
        await update.message.reply_text(
            f"🪙 <b>Монетка</b>\n\n"
            f"Ваш выбор: {choice}\n"
            f"Выпало: {result}!\n"
            f"🎉 Вы выиграли! +{win_amount} монет\n"
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

# ============================ СЛОТЫ (/slots) ============================
# Символы и их веса (чем реже символ — тем выше выплата).
# RTP автомата ~68% — это намеренный слив монет из экономики.
SLOT_SYMBOLS = ["🍏", "🍌", "🍒", "🍋", "🍇", "⚫️"]
SLOT_WEIGHTS = [6, 5, 4, 3, 2, 1]
SLOT_PAYOUTS = {"🍏": 3, "🍌": 4, "🍒": 5, "🍋": 8, "🍇": 15, "⚫️": 75}

# Анти-спам для слотов: минимальный интервал между спинами (секунды).
# Храним в памяти — никаких лишних чтений/записей файлов.
SLOTS_SPIN_COOLDOWN = 3
_SLOTS_LAST_SPIN = {}

async def slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    # Анти-спам: не чаще одного спина в SLOTS_SPIN_COOLDOWN секунд.
    # Спам-запросы игнорируем молча — ноль обращений к Telegram API.
    now = time.time()
    if now - _SLOTS_LAST_SPIN.get(user.id, 0) < SLOTS_SPIN_COOLDOWN:
        return
    _SLOTS_LAST_SPIN[user.id] = now
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Использование: /slots <сумма>\n\n"
            "🎰 Выплаты за три одинаковых:\n"
            "⚫️⚫️⚫️ — x75\n"
            "🍇🍇🍇 — x15\n"
            "🍋🍋🍋 — x8\n"
            "🍒🍒🍒 — x5\n"
            "🍌🍌🍌 — x4\n"
            "🍏🍏🍏 — x3\n"
            "Два одинаковых — возврат ставки"
        )
        return
    try:
        bet = int(context.args[0])
        if bet <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return
    if get_coins(user.id) < bet:
        await update.message.reply_text("❌ Недостаточно монет!")
        return
    update_coins(user.id, -bet)
    reels = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
    reels_text = " | ".join(reels)
    if reels[0] == reels[1] == reels[2]:
        mult = SLOT_PAYOUTS[reels[0]]
        win_amount = bet * mult
        # Баффы (карта + клан) применяются только к чистому выигрышу (как в казино).
        total_multiplier = get_total_coin_multiplier(user.id)
        win_amount = int(bet + (win_amount - bet) * total_multiplier)
        update_coins(user.id, win_amount)
        result_line = f"🎉 ДЖЕКПОТ x{mult}! +{win_amount - bet} монет"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        update_coins(user.id, bet)
        result_line = "😐 Два одинаковых — ставка вернулась (0)"
    else:
        result_line = f"💀 Пусто. -{bet} монет"
    new_balance = get_coins(user.id)
    final_text = (
        f"🎰 <b>Слоты</b>\n\n"
        f"[ {reels_text} ]\n\n"
        f"{result_line}\n"
        f"💰 Баланс: {new_balance} монет"
    )
    # Облегчённая анимация: 1 сообщение + 1 правка вместо четырёх запросов к API.
    # Нагрузка на бота при спаме слотами падает вдвое.
    spin_msg = None
    try:
        spin_msg = await update.message.reply_text(
            f"🎰 <b>Слоты</b>\n\n[ {reels[0]} | ❓ | ❓ ]\n\nКрутим барабаны...",
            parse_mode="HTML"
        )
        await asyncio.sleep(1.0)
        await spin_msg.edit_text(final_text, parse_mode="HTML")
    except Exception:
        # Анимация не критична: если что-то пошло не так — просто показываем результат
        try:
            if spin_msg:
                await spin_msg.edit_text(final_text, parse_mode="HTML")
            else:
                await update.message.reply_text(final_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(final_text, parse_mode="HTML")

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
        f"Карта: {html.escape(card['name'])} (ID: {card_id})\n"
        f"Редкость: {html.escape(card['rarity'])}\n"
        f"Уровень: {level}\n\n"
        f"<b>Эффекты:</b>\n"
        f"⏳ Уменьшение кулдауна: -{cooldown_reduction}% (текущий кулдаун: {current_cooldown_hours:.1f} ч)\n"
        f"💰 Бонус к монетам: +{coin_bonus}%\n"
        f"📌 Действует на: /get_card, /daily, /work, казино, монетку и слоты\n"
        f"🤝 Складывается с клан-баффом (при стаке общий бонус слегка урезается)\n\n"
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
    user_cards = get_available_card_ids(user.id)
    if card_id not in user_cards:
        await update.message.reply_text("❌ У вас нет такой карточки или она недоступна (на маркете/в работе).")
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
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return ConversationHandler.END
    context.user_data.clear()
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
        message += f"⚡ Активный бафф: <b>{html.escape(card_name)}</b> (уровень {level})\n"
    else:
        message += "⚡ Активный бафф: <b>нет</b>\n"

    await update.message.reply_text(message, parse_mode="HTML")

# ============================ ТРЕЙД СИСТЕМА ============================
def _next_trade_id() -> int:
    trades = load_data(TRADES_FILE, [])
    return max((t["id"] for t in trades), default=0) + 1

def _get_trade(trade_id: int):
    trades = load_data(TRADES_FILE, [])
    return next((t for t in trades if t["id"] == trade_id), None)

def _save_trades(trades: list) -> None:
    save_data(TRADES_FILE, trades)

async def trade_offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if len(context.args) < 2:
        await update.message.reply_text("ℹ️ Использование: /trade <user_id> <card_id>")
        return
    try:
        target_id = int(context.args[0])
        card_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID.")
        return
    if target_id == user.id:
        await update.message.reply_text("❌ Нельзя предложить обмен самому себе.")
        return
    users = load_data(USERS_FILE, {})
    if str(target_id) not in users:
        await update.message.reply_text("❌ Игрок не найден в базе бота.")
        return
    if card_id not in get_available_card_ids(user.id):
        await update.message.reply_text("❌ У вас нет этой карточки или она недоступна.")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена.")
        return
    trades = load_data(TRADES_FILE, [])
    active = [t for t in trades if t["status"] in ("pending", "counter", "confirm") and user.id in (t["from_user"], t["to_user"])]
    if active:
        await update.message.reply_text("❌ У вас уже есть активное предложение обмена. Дождитесь его завершения.")
        return
    trade_id = _next_trade_id()
    trades.append({
        "id": trade_id,
        "from_user": user.id,
        "to_user": target_id,
        "from_card": card_id,
        "to_card": None,
        "status": "pending",
        "created": time.time(),
    })
    _save_trades(trades)
    sender_name = user.username or str(user.id)
    keyboard = [
        [InlineKeyboardButton("✅ Принять обмен", callback_data=f"trade_accept_{trade_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"trade_decline_{trade_id}")],
    ]
    await update.message.reply_text(
        f"🔄 Предложение обмена отправлено игроку {target_id}!\n"
        f"Вы предлагаете: {card['name']} ({get_rarity_emoji(card['rarity'])} {card['rarity']})"
    )
    try:
        await context.bot.send_message(
            target_id,
            f"🔄 <b>Предложение обмена!</b>\n\n"
            f"От: @{html.escape(sender_name)}\n"
            f"Предлагает: <b>{html.escape(card['name'])}</b> ({get_rarity_emoji(card['rarity'])} {html.escape(card['rarity'])})\n\n"
            f"Примите обмен и выберите свою карточку для обмена.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить получателя обмена: {e}")

async def trade_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("trade_decline_"):
        trade_id = int(data.split("_")[2])
        trade = _get_trade(trade_id)
        if not trade or trade["status"] not in ("pending", "counter", "confirm"):
            await query.edit_message_text("❌ Обмен уже недействителен.")
            return
        if user_id not in (trade["from_user"], trade["to_user"]):
            await query.edit_message_text("❌ Это не ваш обмен.")
            return
        trades = load_data(TRADES_FILE, [])
        trades = [t for t in trades if t["id"] != trade_id]
        _save_trades(trades)
        await query.edit_message_text("❌ Обмен отменён.")
        other = trade["to_user"] if user_id == trade["from_user"] else trade["from_user"]
        try:
            await context.bot.send_message(other, "ℹ️ Обмен был отменён второй стороной.")
        except Exception:
            pass
        return

    if data.startswith("trade_accept_"):
        trade_id = int(data.split("_")[2])
        trade = _get_trade(trade_id)
        if not trade or trade["status"] != "pending":
            await query.edit_message_text("❌ Обмен уже недействителен.")
            return
        if user_id != trade["to_user"]:
            await query.edit_message_text("❌ Это предложение не для вас.")
            return
        trade["status"] = "counter"
        trades = load_data(TRADES_FILE, [])
        for i, t in enumerate(trades):
            if t["id"] == trade_id:
                trades[i] = trade
                break
        _save_trades(trades)
        collection = await show_collection_with_ids(user_id)
        await query.edit_message_text(
            f"✅ Вы приняли обмен #{trade_id}!\n\n"
            f"{collection}\n\n"
            f"📝 Ответьте сообщением с ID вашей карточки для обмена.",
            parse_mode="HTML",
        )
        context.user_data.clear()
        context.user_data["trade_counter_id"] = trade_id
        return

    if data.startswith("trade_confirm_"):
        trade_id = int(data.split("_")[2])
        trade = _get_trade(trade_id)
        if not trade or trade["status"] != "confirm":
            await query.edit_message_text("❌ Обмен уже недействителен.")
            return
        if user_id not in (trade["from_user"], trade["to_user"]):
            await query.edit_message_text("❌ Это не ваш обмен.")
            return
        trade.setdefault("confirmed", [])
        if user_id in trade["confirmed"]:
            await query.edit_message_text("✅ Вы уже подтвердили этот обмен.")
            return
        trade["confirmed"].append(user_id)
        trades = load_data(TRADES_FILE, [])
        for i, t in enumerate(trades):
            if t["id"] == trade_id:
                trades[i] = trade
                break
        _save_trades(trades)
        if len(trade["confirmed"]) < 2:
            await query.edit_message_text("✅ Вы подтвердили обмен! Ждём подтверждения второго игрока...")
            other = trade["to_user"] if user_id == trade["from_user"] else trade["from_user"]
            cards = load_data(CARDS_FILE, [])
            card_map = {c["id"]: c for c in cards}
            fc = card_map.get(trade["from_card"], {})
            tc = card_map.get(trade["to_card"], {})
            try:
                await context.bot.send_message(
                    other,
                    f"✅ Соперник подтвердил обмен!\n"
                    f"🔄 {fc.get('name', trade['from_card'])} ↔ {tc.get('name', trade['to_card'])}\n"
                    f"Нажмите «Подтвердить» для завершения.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Подтвердить обмен", callback_data=f"trade_confirm_{trade_id}"),
                        InlineKeyboardButton("❌ Отмена", callback_data=f"trade_decline_{trade_id}"),
                    ]]),
                )
            except Exception:
                pass
            return
        # Execute trade
        if not remove_one_card(trade["from_user"], trade["from_card"]):
            trades = [t for t in trades if t["id"] != trade_id]
            _save_trades(trades)
            await query.edit_message_text("❌ Обмен не удался — у отправителя нет карточки.")
            return
        if not remove_one_card(trade["to_user"], trade["to_card"]):
            add_one_card(trade["from_user"], trade["from_card"])
            trades = [t for t in trades if t["id"] != trade_id]
            _save_trades(trades)
            await query.edit_message_text("❌ Обмен не удался — у получателя нет карточки.")
            return
        add_one_card(trade["from_user"], trade["to_card"])
        add_one_card(trade["to_user"], trade["from_card"])
        trades = [t for t in trades if t["id"] != trade_id]
        _save_trades(trades)
        cards = load_data(CARDS_FILE, [])
        card_map = {c["id"]: c for c in cards}
        fc = card_map.get(trade["from_card"], {})
        tc = card_map.get(trade["to_card"], {})
        msg = (
            f"🎉 <b>Обмен завершён!</b>\n\n"
            f"Вы отдали: {html.escape(fc.get('name', str(trade['from_card'])))}\n"
            f"Вы получили: {html.escape(tc.get('name', str(trade['to_card'])))}"
        )
        await query.edit_message_text(msg, parse_mode="HTML")
        other = trade["to_user"] if user_id == trade["from_user"] else trade["from_user"]
        other_msg = (
            f"🎉 <b>Обмен завершён!</b>\n\n"
            f"Вы отдали: {html.escape(tc.get('name', str(trade['to_card'])))}\n"
            f"Вы получили: {html.escape(fc.get('name', str(trade['from_card'])))}"
        )
        try:
            await context.bot.send_message(other, other_msg, parse_mode="HTML")
        except Exception:
            pass

async def trade_counter_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("bet_state") == "awaiting_amount":
        return
    trade_id = context.user_data.get("trade_counter_id")
    if not trade_id:
        return
    user = update.effective_user
    trade = _get_trade(trade_id)
    if not trade or trade["status"] != "counter" or user.id != trade["to_user"]:
        context.user_data.pop("trade_counter_id", None)
        return
    try:
        card_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите числовой ID карточки.")
        return
    if card_id not in get_available_card_ids(user.id):
        await update.message.reply_text("❌ У вас нет этой карточки или она недоступна.")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена.")
        return
    trade["to_card"] = card_id
    trade["status"] = "confirm"
    trade["confirmed"] = []
    trades = load_data(TRADES_FILE, [])
    for i, t in enumerate(trades):
        if t["id"] == trade_id:
            trades[i] = trade
            break
    _save_trades(trades)
    context.user_data.pop("trade_counter_id", None)
    from_card = next((c for c in cards if c["id"] == trade["from_card"]), {})
    keyboard = [[
        InlineKeyboardButton("✅ Подтвердить обмен", callback_data=f"trade_confirm_{trade_id}"),
        InlineKeyboardButton("❌ Отмена", callback_data=f"trade_decline_{trade_id}"),
    ]]
    summary = (
        f"🔄 <b>Обмен #{trade_id}</b>\n\n"
        f"@{html.escape(user.username or str(user.id))} предлагает:\n"
        f"• {html.escape(from_card.get('name', '?'))} ↔ {html.escape(card['name'])}\n\n"
        f"Подтвердите обмен обе стороны."
    )
    await update.message.reply_text(f"✅ Вы выбрали {card['name']} для обмена. Ждём подтверждения обоих игроков.")
    for uid in (trade["from_user"], trade["to_user"]):
        try:
            await context.bot.send_message(uid, summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить подтверждение обмена {uid}: {e}")

# ============================ МАРКЕТ ============================
MARKET_PAGE_SIZE = 10

def _build_market_page(user_id: int, page: int):
    """Собирает текст и клавиатуру страницы маркета. Возвращает (None, None), если маркет пуст."""
    market = load_data(MARKET_FILE, [])
    if not market:
        return None, None
    cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in cards}
    total_pages = max(1, (len(market) + MARKET_PAGE_SIZE - 1) // MARKET_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * MARKET_PAGE_SIZE
    items = market[start_idx:start_idx + MARKET_PAGE_SIZE]
    lines = [f"🏪 <b>Маркет карточек</b> — стр. {page + 1}/{total_pages} (всего лотов: {len(market)})\n"]
    keyboard = []
    for item in items:
        card = card_map.get(item["card_id"], {})
        emoji = get_rarity_emoji(card.get("rarity", ""))
        lines.append(
            f"#{item['id']} {emoji} <b>{html.escape(card.get('name', '?'))}</b> — "
            f"💰 {_fmt_coins(item['price'])} (продавец: {item['seller_id']})"
        )
        if item["seller_id"] != user_id:
            keyboard.append([InlineKeyboardButton(
                f"Купить #{item['id']} за {_fmt_coins(item['price'])}",
                callback_data=f"market_buy_{item['id']}"
            )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"market_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"market_page_{page + 1}"))
    if nav:
        keyboard.append(nav)
    lines.append(f"\nℹ️ /sell {html.escape('<card_id>')} {html.escape('<цена>')} — выставить | /my_listings — мои объявления")
    return "\n".join(lines), InlineKeyboardMarkup(keyboard) if keyboard else None

async def show_market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        return
    if not await is_subscribed(user.id, context):
        return
    text, reply_markup = _build_market_page(user.id, 0)
    if text is None:
        await update.message.reply_text("🏪 Маркет пуст. Выставьте карточку: /sell <card_id> <цена>")
        return
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def market_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Перелистывание страниц маркета."""
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split("_")[2])
    except (IndexError, ValueError):
        return
    text, reply_markup = _build_market_page(query.from_user.id, page)
    if text is None:
        await query.edit_message_text("🏪 Маркет пуст. Выставьте карточку: /sell <card_id> <цена>")
        return
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        # Содержимое не изменилось (та же страница) — игнорируем.
        pass

async def sell_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        return
    if not await is_subscribed(user.id, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("ℹ️ Использование: /sell <card_id> <цена>")
        return
    try:
        card_id = int(context.args[0])
        price = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат.")
        return
    if price <= 0:
        await update.message.reply_text("❌ Цена должна быть положительной.")
        return
    if card_id not in get_available_card_ids(user.id):
        await update.message.reply_text("❌ Карточка недоступна для продажи.")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена.")
        return
    min_price = MARKET_MIN_PRICES.get(card["rarity"])
    if min_price and price < min_price:
        await update.message.reply_text(f"❌ Минимальная цена для {card['rarity']}: {_fmt_coins(min_price)} монет.")
        return
    market = load_data(MARKET_FILE, [])
    if len([m for m in market if m["seller_id"] == user.id]) >= 3:
        await update.message.reply_text("❌ У вас уже 3 активных лота. Снимите один через /my_listings.")
        return
    if not remove_one_card(user.id, card_id):
        await update.message.reply_text("❌ Не удалось снять карточку с коллекции.")
        return
    market = load_data(MARKET_FILE, [])
    listing_id = max((m["id"] for m in market), default=0) + 1
    market.append({
        "id": listing_id,
        "seller_id": user.id,
        "card_id": card_id,
        "price": price,
        "listed_at": time.time(),
    })
    save_data(MARKET_FILE, market)
    await update.message.reply_text(
        f"✅ Карточка «{card['name']}» выставлена на маркет!\n"
        f"🆔 Объявление #{listing_id}\n💰 Цена: {_fmt_coins(price)} монет\n\n"
        f"Отменить: /unlist {listing_id}"
    )

async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    market = load_data(MARKET_FILE, [])
    mine = [m for m in market if m["seller_id"] == user.id]
    if not mine:
        await update.message.reply_text("📭 У вас нет активных объявлений.")
        return
    cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in cards}
    lines = ["📋 <b>Ваши объявления</b>\n"]
    for item in mine:
        card = card_map.get(item["card_id"], {})
        lines.append(f"#{item['id']} {html.escape(card.get('name', '?'))} — 💰 {_fmt_coins(item['price'])}")
    lines.append(f"\nОтменить: /unlist {html.escape('<ID объявления>')}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def unlist_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /unlist <ID объявления>")
        return
    try:
        listing_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
        return
    market = load_data(MARKET_FILE, [])
    item = next((m for m in market if m["id"] == listing_id), None)
    if not item or item["seller_id"] != user.id:
        await update.message.reply_text("❌ Объявление не найдено.")
        return
    market = [m for m in market if m["id"] != listing_id]
    save_data(MARKET_FILE, market)
    add_one_card(user.id, item["card_id"])
    await update.message.reply_text(f"✅ Объявление #{listing_id} снято, карточка возвращена в коллекцию.")

async def admin_unlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ снимает любой лот с маркета; карточка возвращается продавцу."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /admin_unlist <ID объявления>")
        return
    try:
        listing_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
        return
    market = load_data(MARKET_FILE, [])
    item = next((m for m in market if m["id"] == listing_id), None)
    if not item:
        await update.message.reply_text("❌ Объявление не найдено.")
        return
    market = [m for m in market if m["id"] != listing_id]
    save_data(MARKET_FILE, market)
    add_one_card(item["seller_id"], item["card_id"])
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == item["card_id"]), {})
    card_name = html.escape(card.get("name", str(item["card_id"])))
    await update.message.reply_text(
        f"✅ Объявление #{listing_id} («{card_name}») снято. Карточка возвращена игроку {item['seller_id']}.",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            item["seller_id"],
            f"ℹ️ Ваше объявление #{listing_id} снято администратором. Карточка возвращена в коллекцию.",
        )
    except Exception:
        pass

async def admin_viewcards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ смотрит коллекцию любого игрока."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /admin_viewcards <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
        return
    users = load_data(USERS_FILE, {})
    if str(target_id) not in users:
        await update.message.reply_text("❌ Игрок не найден.")
        return
    header = (
        f"👤 <b>Игрок {target_id}</b>\n"
        f"💰 Монет: {get_coins(target_id)}\n\n"
    )
    collection = await show_collection_with_ids(target_id)
    await update.message.reply_text(header + collection, parse_mode="HTML")

async def admin_takecard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ изымает карточку (или несколько копий) у игрока."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    if len(context.args) < 2:
        await update.message.reply_text("ℹ️ Использование: /admin_takecard <user_id> <card_id> [количество]")
        return
    try:
        target_id = int(context.args[0])
        card_id = int(context.args[1])
        take_count = int(context.args[2]) if len(context.args) > 2 else 1
        if take_count <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Все аргументы — положительные числа.")
        return
    removed = 0
    for _ in range(take_count):
        if not remove_one_card(target_id, card_id):
            break
        removed += 1
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), {})
    card_name = html.escape(card.get("name", str(card_id)))
    if removed == 0:
        await update.message.reply_text(
            "❌ У игрока нет этой карточки в коллекции (копии на маркете/в работе не изымаются)."
        )
        return
    await update.message.reply_text(
        f"✅ Изъято «{card_name}» x{removed} у игрока {target_id}.",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            target_id,
            f"⚠️ Администратор изъял у вас карточку «{card_name}» (x{removed}).",
        )
    except Exception:
        pass

async def market_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        listing_id = int(query.data.split("_")[2])
    except (IndexError, ValueError):
        await query.edit_message_text("❌ Неверные данные.")
        return
    buyer_id = query.from_user.id
    market = load_data(MARKET_FILE, [])
    item = next((m for m in market if m["id"] == listing_id), None)
    if not item:
        await query.edit_message_text("❌ Объявление уже недоступно.")
        return
    if item["seller_id"] == buyer_id:
        await query.edit_message_text("❌ Нельзя купить свою карточку.")
        return
    if get_coins(buyer_id) < item["price"]:
        await query.edit_message_text("❌ Недостаточно монет!")
        return
    update_coins(buyer_id, -item["price"])
    update_coins(item["seller_id"], item["price"])
    add_one_card(buyer_id, item["card_id"])
    market = [m for m in market if m["id"] != listing_id]
    save_data(MARKET_FILE, market)
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == item["card_id"]), {})
    card_name = html.escape(card.get("name", "?"))
    price_text = _fmt_coins(item["price"])
    await query.edit_message_text(
        f"✅ Вы купили «{card_name}» за {price_text} монет!",
        parse_mode="HTML",
    )
    try:
        await context.bot.send_message(
            item["seller_id"],
            f"💰 Ваша карточка «{card_name}» продана за {price_text} монет!",
            parse_mode="HTML",
        )
    except Exception:
        pass

# ============================ РАБОТА (/work) ============================
async def _complete_work_if_ready(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    work = user_data.get("working_card")
    if not work or time.time() < work.get("finish_at", 0):
        return False
    card_id = work["card_id"]
    reward = work.get("reward", 50)
    cards = user_data.get("cards", [])
    cards.append(card_id)
    user_data["cards"] = cards
    del user_data["working_card"]
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)
    new_balance = update_coins(user_id, reward)
    cards_db = load_data(CARDS_FILE, [])
    card = next((c for c in cards_db if c["id"] == card_id), {})
    try:
        await context.bot.send_message(
            user_id,
            f"💼 <b>Карточка вернулась с работы!</b>\n\n"
            f"🃏 {html.escape(card.get('name', str(card_id)))}\n"
            f"💰 Заработано: +{reward} монет\n"
            f"💰 Баланс: {new_balance}",
            parse_mode="HTML",
        )
    except Exception:
        pass
    return True

async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        return
    if not await is_subscribed(user.id, context):
        return
    await _complete_work_if_ready(user.id, context)
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    if user_data.get("working_card") and time.time() < user_data["working_card"].get("finish_at", 0):
        left = int(user_data["working_card"]["finish_at"] - time.time())
        await update.message.reply_text(f"⏳ Карточка ещё работает. Осталось: {left // 60} мин.")
        return
    last_work = user_data.get("last_work", 0)
    # Бафф-карта сокращает и кулдаун работы (как кулдаун /get_card)
    work_cooldown = WORK_COOLDOWN_SECONDS * get_cooldown_multiplier(user.id)
    if time.time() - last_work < work_cooldown:
        left = int(work_cooldown - (time.time() - last_work))
        await update.message.reply_text(f"⏳ Следующая работа через {left // 60} мин.")
        return
    if not context.args:
        await update.message.reply_text(f"ℹ️ Использование: /work {html.escape('<card_id>')}\n\n" + await show_collection_with_ids(user.id), parse_mode="HTML")
        return
    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
        return
    if card_id not in get_available_card_ids(user.id):
        await update.message.reply_text("❌ Карточка недоступна.")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена.")
        return
    reward_range = WORK_REWARDS.get(card["rarity"], (15, 30))
    reward = random.randint(*reward_range)
    # Монетные баффы (карта + клан) действуют и на заработок с работы
    reward = int(reward * get_total_coin_multiplier(user.id))
    if not remove_one_card(user.id, card_id):
        await update.message.reply_text("❌ Не удалось отправить карточку на работу.")
        return
    # ВАЖНО: remove_one_card уже сохранил USERS_FILE без карточки.
    # Перезагружаем данные: запись старой копии users ниже вернула бы
    # карточку в коллекцию, а после работы она добавилась бы ещё раз (дюп).
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    user_data["working_card"] = {
        "card_id": card_id,
        "finish_at": time.time() + WORK_DURATION_SECONDS,
        "reward": reward,
    }
    user_data["last_work"] = time.time()
    users[str(user.id)] = user_data
    save_data(USERS_FILE, users)
    await update.message.reply_text(
        f"💼 <b>{html.escape(card['name'])}</b> отправлена работать на 1 час!\n"
        f"💰 Ожидаемый заработок: ~{reward} монет\n"
        f"⏳ Карточка вернётся через 60 минут.",
        parse_mode="HTML",
    )

# ============================ СОБЫТИЯ КАНАЛА (/events) ============================
async def events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    keyboard = [
        [InlineKeyboardButton("⚡ Буст выпадения сейчас", callback_data="evt_boost_now")],
        [InlineKeyboardButton("⏰ Запланировать буст", callback_data="evt_boost_sched")],
        [InlineKeyboardButton("🗳 Голосование за промокод", callback_data="evt_poll")],
        [InlineKeyboardButton("📋 Активные события", callback_data="evt_list")],
    ]
    await update.message.reply_text(
        "🎪 <b>Управление событиями</b>\n\nВыберите тип события:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )

async def events_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    data = query.data

    if data == "evt_list":
        boosts = get_active_drop_boosts()
        events = load_data(CHANNEL_EVENTS_FILE, [])
        active = [e for e in events if e.get("status") in ("scheduled", "active", "poll_active")]
        text = "📋 <b>Активные события</b>\n\n"
        if boosts:
            text += "<b>⚡ Бусты:</b>\n"
            for b in boosts:
                left = int((b["until"] - time.time()) // 60)
                text += f"• {html.escape(b['rarity'])} x{b.get('multiplier', 2)} — {left} мин\n"
        else:
            text += "Бустов нет.\n"
        if active:
            text += "\n<b>📅 Запланированные:</b>\n"
            for e in active:
                text += f"• #{e['id']} {html.escape(e.get('type', ''))} — {html.escape(e.get('status', ''))}\n"
        await query.edit_message_text(text, parse_mode="HTML")
        return

    if data == "evt_boost_now":
        context.user_data.clear()
        context.user_data["evt_flow"] = "boost_now"
        await query.edit_message_text(
            "⚡ <b>Буст выпадения</b>\n\nВведите редкость (например: Легендарная):",
            parse_mode="HTML",
        )
        return

    if data == "evt_boost_sched":
        context.user_data.clear()
        context.user_data["evt_flow"] = "boost_sched"
        await query.edit_message_text(
            "⏰ <b>Запланированный буст</b>\n\nЧерез сколько минут начать? (число):",
            parse_mode="HTML",
        )
        return

    if data == "evt_poll":
        context.user_data.clear()
        context.user_data["evt_flow"] = "poll"
        keyboard = [
            [InlineKeyboardButton("⏱ Сброс таймера", callback_data="evt_poll_reset")],
            [InlineKeyboardButton("💰 Монеты", callback_data="evt_poll_coins")],
        ]
        await query.edit_message_text(
            "🗳 <b>Голосование за промокод</b>\n\nВыберите тип награды:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return

    if data in ("evt_poll_reset", "evt_poll_coins"):
        context.user_data.clear()
        context.user_data["evt_flow"] = "poll"
        context.user_data["evt_poll_type"] = "reset" if data == "evt_poll_reset" else "coins"
        if data == "evt_poll_reset":
            await query.edit_message_text("💰 Если победят монеты, на какое количество выпустить промокод?")
        else:
            await query.edit_message_text("💰 Введите количество монет для промокода:")
        return

async def events_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("bet_state") == "awaiting_amount":
        return
    if context.user_data.get("trade_counter_id"):
        return
    flow = context.user_data.get("evt_flow")
    if not flow or not is_admin(update.effective_user.id):
        return
    text = update.message.text.strip()

    if flow == "boost_now":
        step = context.user_data.get("evt_step", "rarity")
        if step == "rarity":
            context.user_data["evt_rarity"] = text
            context.user_data["evt_step"] = "mult"
            await update.message.reply_text("Введите множитель шанса (например 2 или 3):")
            return
        if step == "mult":
            try:
                mult = float(text.replace(",", "."))
                if mult <= 1:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Множитель должен быть > 1.")
                return
            context.user_data["evt_mult"] = mult
            context.user_data["evt_step"] = "duration"
            await update.message.reply_text("Длительность буста в минутах (например 15):")
            return
        if step == "duration":
            try:
                mins = int(text)
                if mins <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Введите положительное число минут.")
                return
            rarity = context.user_data["evt_rarity"]
            mult = context.user_data["evt_mult"]
            until = time.time() + mins * 60
            boosts = load_data(DROP_BOOSTS_FILE, [])
            boosts.append({"rarity": rarity, "multiplier": mult, "until": until})
            save_data(DROP_BOOSTS_FILE, boosts)
            await post_to_channel(
                context,
                f"⚡ <b>СОБЫТИЕ!</b>\n\n"
                f"Увеличен шанс выпадения <b>{html.escape(rarity)}</b> карточек!\n"
                f"Множитель: x{mult}\n"
                f"⏳ Длительность: {mins} минут\n\n"
                f"🔥 Успей получить карточку: /get_card в боте!",
            )
            await update.message.reply_text(f"✅ Буст {rarity} x{mult} активирован на {mins} мин!")
            context.user_data.pop("evt_flow", None)
            context.user_data.pop("evt_step", None)
            return

    if flow == "boost_sched":
        step = context.user_data.get("evt_step", "delay")
        if step == "delay":
            try:
                delay = int(text)
                if delay < 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Введите число минут.")
                return
            context.user_data["evt_delay"] = delay
            context.user_data["evt_step"] = "rarity"
            await update.message.reply_text("Введите редкость:")
            return
        if step == "rarity":
            context.user_data["evt_rarity"] = text
            context.user_data["evt_step"] = "mult"
            await update.message.reply_text("Множитель шанса:")
            return
        if step == "mult":
            try:
                mult = float(text.replace(",", "."))
                if mult <= 1:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Множитель > 1.")
                return
            context.user_data["evt_mult"] = mult
            context.user_data["evt_step"] = "duration"
            await update.message.reply_text("Длительность буста (минуты):")
            return
        if step == "duration":
            try:
                mins = int(text)
                if mins <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Положительное число.")
                return
            delay = context.user_data["evt_delay"]
            rarity = context.user_data["evt_rarity"]
            mult = context.user_data["evt_mult"]
            start_at = time.time() + delay * 60
            end_at = start_at + mins * 60
            events = load_data(CHANNEL_EVENTS_FILE, [])
            eid = max((e["id"] for e in events), default=0) + 1
            events.append({
                "id": eid, "type": "scheduled_boost", "status": "scheduled",
                "rarity": rarity, "multiplier": mult,
                "start_at": start_at, "end_at": end_at, "duration_minutes": mins,
            })
            save_data(CHANNEL_EVENTS_FILE, events)
            await update.message.reply_text(
                f"✅ Буст запланирован! Начало через {delay} мин, длительность {mins} мин.\n"
                f"ID события: {eid}"
            )
            context.user_data.pop("evt_flow", None)
            context.user_data.pop("evt_step", None)
            return

    if flow == "poll":
        poll_type = context.user_data.get("evt_poll_type", "reset")
        step = context.user_data.get("evt_step", "value")
        if step == "value":
            try:
                value = int(text)
                if value <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Положительное число.")
                return
            context.user_data["evt_poll_value"] = value
            context.user_data["evt_step"] = "duration"
            if poll_type == "reset":
                await update.message.reply_text(
                    "💰 Если победят монеты, промокод будет на это количество монет.\n"
                    "Сколько минут длится голосование?"
                )
            else:
                await update.message.reply_text("Сколько минут длится голосование?")
            return
        if step == "duration":
            try:
                poll_mins = int(text)
                if poll_mins <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Положительное число минут.")
                return
            context.user_data["evt_poll_duration"] = poll_mins
            context.user_data["evt_step"] = "promo_hours"
            await update.message.reply_text("Срок действия промокода после создания (часов, 0 = бессрочно):")
            return
        if step == "promo_hours":
            try:
                promo_hours = float(text.replace(",", "."))
                if promo_hours < 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Число >= 0.")
                return
            poll_mins = context.user_data["evt_poll_duration"]
            poll_type = context.user_data["evt_poll_type"]
            poll_value = context.user_data.get("evt_poll_value", 0)
            end_at = time.time() + poll_mins * 60
            if poll_type == "reset":
                promo_label = "сброс таймера"
                options = ["Сброс таймера", "Монеты"]
            else:
                promo_label = f"{poll_value} монет"
                options = [f"{poll_value // 2} монет", f"{poll_value} монет"]
            question = f"Какой промокод выпустить? ({promo_label})"
            poll_seconds = int(poll_mins * 60)
            send_poll_kwargs = {
                "chat_id": CHANNEL_ID,
                "question": f"🗳 {question}",
                "options": options,
                "is_anonymous": True,
                "allows_multiple_answers": False,
            }
            if poll_seconds <= 600:
                send_poll_kwargs["open_period"] = poll_seconds
            try:
                poll_msg = await context.bot.send_poll(**send_poll_kwargs)
            except Exception as e:
                await update.message.reply_text(f"❌ Не удалось создать голосование: {e}")
                context.user_data.clear()
                return
            events = load_data(CHANNEL_EVENTS_FILE, [])
            eid = max((e["id"] for e in events), default=0) + 1
            events.append({
                "id": eid, "type": "poll", "status": "poll_active",
                "poll_id": getattr(poll_msg.poll, "id", None),
                "poll_message_id": poll_msg.message_id,
                "poll_chat_id": CHANNEL_ID,
                "end_at": end_at,
                "promo_type": poll_type,
                "promo_value": poll_value,
                "promo_duration_hours": promo_hours,
                "options": options,
            })
            save_data(CHANNEL_EVENTS_FILE, events)
            await update.message.reply_text(f"✅ Голосование запущено в канале! ID: {eid}, длительность {poll_mins} мин.")
            context.user_data.clear()


async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Диспетчер текстовых сообщений для нескольких мини-диалогов:
    ввод суммы ставки, выбор карточки для обмена, ввод параметров событий.
    """
    if context.user_data.get("bet_state") == "awaiting_amount":
        return await bet_amount(update, context)
    if context.user_data.get("trade_counter_id"):
        return await trade_counter_card(update, context)
    if context.user_data.get("evt_flow"):
        return await events_text_input(update, context)


async def _finalize_poll_event(event: dict, results, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Формирует промокод по итогам закрытого голосования и публикует результат.

    results — список пар (текст варианта, количество голосов).
    """
    if event.get("status") != "poll_active":
        return False
    try:
        winner_idx = 0
        max_votes = 0
        for i, (_opt_text, votes) in enumerate(results):
            if votes > max_votes:
                max_votes = votes
                winner_idx = i
        poll_type = event["promo_type"]
        poll_value = event.get("promo_value", 0)
        if poll_type == "reset":
            if winner_idx == 0:
                code = f"TIMER{_next_promo_id('TIMER')}"
                promo_data = {"type": "reset", "value": 0}
                reward_text = "сброс таймера /get_card"
            else:
                code = f"COINS{_next_promo_id('COINS')}"
                promo_data = {"type": "coins", "value": poll_value}
                reward_text = f"{poll_value} монет"
        else:
            final_value = poll_value if winner_idx == 1 else max(poll_value // 2, 10)
            code = f"COINS{_next_promo_id('COINS')}"
            promo_data = {"type": "coins", "value": final_value}
            reward_text = f"{final_value} монет"
        promo_hours = event.get("promo_duration_hours", 1)
        now = time.time()
        expire = 0 if promo_hours == 0 else now + promo_hours * 3600
        promos = load_data(PROMOCODES_FILE, {})
        promos[code] = {
            "type": promo_data["type"],
            "value": promo_data["value"],
            "max_uses": max(max_votes * 2, 10),
            "used": 0,
            "users": [],
            "expire": expire,
        }
        save_data(PROMOCODES_FILE, promos)
        event["status"] = "completed"
        event["promo_code"] = code
        expire_text = f"{int(promo_hours)} ч." if promo_hours else "бессрочно"
        logger.info(f"Голосование завершено: промокод {code}, награда {reward_text}")
        await context.bot.send_message(
            CHANNEL_ID,
            f"🎉 <b>Голосование завершено!</b>\n\n"
            f"🏆 Победил: {html.escape(results[winner_idx][0])} ({max_votes} голосов)\n\n"
            f"🎁 Промокод: <code>{code}</code>\n"
            f"🎁 Награда: {reward_text}\n"
            f"⏳ Действует: {expire_text}\n\n"
            f"Активировать: /redeem {code}",
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка завершения голосования: {e}")
        event["status"] = "completed"
        # Статус изменён — событие нужно сохранить, иначе цикл будет повторяться.
        return True


async def poll_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает обновления о состоянии голосования.

    Кэширует текущие голоса в событие при каждом апдейте: Telegram НЕ присылает
    финальный Poll-апдейт, когда опрос закрывается автоматически по open_period,
    поэтому кэш — единственный источник итогов для фонового воркера.
    """
    poll = update.poll
    if not poll:
        return
    events = load_data(CHANNEL_EVENTS_FILE, [])
    changed = False
    for event in events:
        if event.get("status") == "poll_active" and event.get("poll_id") == poll.id:
            event["last_results"] = [opt.voter_count for opt in poll.options]
            changed = True
            if poll.is_closed:
                results = [(opt.text, opt.voter_count) for opt in poll.options]
                await _finalize_poll_event(event, results, context)
            break
    if changed:
        save_data(CHANNEL_EVENTS_FILE, events)


async def process_channel_events(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = time.time()
    events = load_data(CHANNEL_EVENTS_FILE, [])
    changed = False
    for event in events:
        if event.get("status") == "scheduled" and event.get("type") == "scheduled_boost":
            if now >= event.get("start_at", 0):
                boosts = load_data(DROP_BOOSTS_FILE, [])
                boosts.append({
                    "rarity": event["rarity"],
                    "multiplier": event.get("multiplier", 2),
                    "until": event["end_at"],
                })
                save_data(DROP_BOOSTS_FILE, boosts)
                event["status"] = "active"
                changed = True
                mins = event.get("duration_minutes", 15)
                try:
                    await context.bot.send_message(
                        CHANNEL_ID,
                        f"⚡ <b>СОБЫТИЕ НАЧАЛОСЬ!</b>\n\n"
                        f"Увеличен шанс выпадения <b>{html.escape(event['rarity'])}</b>!\n"
                        f"Множитель: x{event.get('multiplier', 2)}\n"
                        f"⏳ На {mins} минут!",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        if event.get("status") == "active" and event.get("type") == "scheduled_boost":
            if now >= event.get("end_at", 0):
                event["status"] = "completed"
                changed = True
                try:
                    await context.bot.send_message(
                        CHANNEL_ID,
                        f"⏹ Буст <b>{html.escape(event['rarity'])}</b> завершён!",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        if event.get("status") == "poll_active" and now >= event.get("end_at", 0):
            poll = None
            try:
                poll = await context.bot.stop_poll(event["poll_chat_id"], event["poll_message_id"])
            except Exception as e:
                # Опрос уже закрыт Telegram'ом (open_period) — это штатная ситуация,
                # финализируем по закэшированным голосам вместо тихого completed.
                logger.warning(f"stop_poll не удался (вероятно, опрос уже закрыт): {e}")
            if poll is not None:
                results = [(opt.text, opt.voter_count) for opt in poll.options]
            else:
                cached = event.get("last_results") or []
                opts = event.get("options", [])
                total = max(len(opts), len(cached))
                results = [
                    (
                        opts[i] if i < len(opts) else f"Вариант {i + 1}",
                        cached[i] if i < len(cached) else 0,
                    )
                    for i in range(total)
                ]
            if await _finalize_poll_event(event, results, context):
                changed = True
    if changed:
        save_data(CHANNEL_EVENTS_FILE, events)
    get_active_drop_boosts()
    users = load_data(USERS_FILE, {})
    for uid in list(users.keys()):
        try:
            await _complete_work_if_ready(int(uid), context)
        except Exception:
            pass


async def _event_worker(application: Application) -> None:
    """Фоновая задача, которая гарантированно отслеживает события канала."""
    await asyncio.sleep(10)
    while True:
        try:
            context = CallbackContext(application)
            await process_channel_events(context)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Ошибка в фоновом обработчике событий")
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break


async def _post_init(application: Application) -> None:
    """Запускает фоновый воркер после инициализации приложения."""
    application.create_task(_event_worker(application))

# ============================ СЕЗОНЫ РЕЙТИНГА ============================
async def start_season_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора!")
        return ConversationHandler.END
    season = load_data(SEASON_FILE, {})
    if season.get("active"):
        await update.message.reply_text(
            f"⚠️ Сезон #{season.get('number', '?')} уже активен. Сначала /end_season"
        )
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("🏆 Введите номер нового сезона (1, 2, 3...):")
    return SEASON_NUMBER

async def season_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        num = int(update.message.text.strip())
        if num <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Положительное число.")
        return SEASON_NUMBER
    context.user_data["season_number"] = num
    await update.message.reply_text("💰 Монеты за 1 место:")
    return SEASON_PRIZE_1

async def season_prize_1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        p1 = int(update.message.text.strip())
        if p1 < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Число >= 0.")
        return SEASON_PRIZE_1
    context.user_data["prize_1"] = p1
    await update.message.reply_text("💰 Монеты за 2 место:")
    return SEASON_PRIZE_2

async def season_prize_2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        p2 = int(update.message.text.strip())
        if p2 < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Число >= 0.")
        return SEASON_PRIZE_2
    context.user_data["prize_2"] = p2
    await update.message.reply_text("💰 Монеты за 3 место:")
    return SEASON_PRIZE_3

async def season_prize_3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        p3 = int(update.message.text.strip())
        if p3 < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Число >= 0.")
        return SEASON_PRIZE_3
    num = context.user_data["season_number"]
    prizes = [context.user_data["prize_1"], context.user_data["prize_2"], p3]
    users = load_data(USERS_FILE, {})
    for uid, data in users.items():
        data["rating_elo"] = DEFAULT_RATING_ELO
        data.setdefault("rating_stats", {"wins": 0, "losses": 0, "draws": 0})
        users[uid] = data
    save_data(USERS_FILE, users)
    save_data(SEASON_FILE, {
        "active": True,
        "number": num,
        "prizes": prizes,
        "started_at": time.time(),
    })
    await post_to_channel(
        context,
        f"🏆 <b>Начался рейтинговый сезон #{num}!</b>\n\n"
        f"Рейтинг всех игроков сброшен до {DEFAULT_RATING_ELO}.\n"
        f"🥇 1 место: {prizes[0]} монет\n"
        f"🥈 2 место: {prizes[1]} монет\n"
        f"🥉 3 место: {prizes[2]} монет\n\n"
        f"⚔️ Играйте: /find_match",
    )
    await update.message.reply_text(f"✅ Сезон #{num} начался! Рейтинг сброшен.")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_season(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def end_season_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора!")
        return
    season = load_data(SEASON_FILE, {})
    if not season.get("active"):
        await update.message.reply_text("❌ Нет активного сезона.")
        return
    users = load_data(USERS_FILE, {})
    moderators = load_data(MODERATORS_FILE, [])
    exclude = {ADMIN_ID} | set(moderators)
    leaders = []
    for uid, data in users.items():
        if int(uid) in exclude:
            continue
        leaders.append((int(uid), data.get("rating_elo", DEFAULT_RATING_ELO)))
    leaders.sort(key=lambda x: x[1], reverse=True)
    top3 = leaders[:3]
    prizes = season.get("prizes", [0, 0, 0])
    medals = ["🥇", "🥈", "🥉"]
    result_lines = [f"🏁 <b>Сезон #{season.get('number')} завершён!</b>\n"]
    for i, (uid, elo) in enumerate(top3):
        prize = prizes[i] if i < len(prizes) else 0
        name = html.escape(await _get_display_name(context, uid))
        if prize > 0:
            update_coins(uid, prize)
            try:
                await context.bot.send_message(
                    uid,
                    f"{medals[i]} Вы заняли {i + 1} место в сезоне #{season.get('number')}!\n"
                    f"💰 Награда: {prize} монет\n⭐ Рейтинг: {elo}",
                )
            except Exception:
                pass
        result_lines.append(f"{medals[i]} {name} — ⭐ {elo} (+{prize} монет)")
    season["active"] = False
    season["ended_at"] = time.time()
    save_data(SEASON_FILE, season)
    await post_to_channel(context, "\n".join(result_lines))
    await update.message.reply_text("✅ Сезон завершён, призы выданы!")

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
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
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
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
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
    context.user_data.clear()
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
    bet_id = max((b.get("id") or 0 for b in bets), default=0) + 1
    bets.append({
        "id": bet_id,
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
        event_name = f"{html.escape(event['team1'])} - {html.escape(event['team2'])}" if event else f"Матч {b['match_id']}"
        outcome_label = "неизвестно"
        if event:
            outcome = next((o for o in event["outcomes"] if o["id"] == b["outcome_id"]), None)
            if outcome:
                outcome_label = html.escape(outcome["label"])
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
    available = get_available_card_ids(user.id)
    if len(set(available)) < 4:
        await update.message.reply_text(
            "❌ Для составления команды нужно минимум 4 РАЗНЫЕ карточки в коллекции "
            "(1 вратарь + 3 полевых игрока). Получите больше карточек через /get_card."
        )
        return ConversationHandler.END
    await update.message.reply_text(collection_msg, parse_mode="HTML")
    context.user_data.clear()
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
    available = get_available_card_ids(user.id)
    if gk_id not in available:
        await update.message.reply_text("❌ У вас нет такой карточки или она недоступна. Проверьте ID и попробуйте снова.")
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
    available = get_available_card_ids(user.id)
    missing = [cid for cid in field_ids if cid not in available]
    if missing:
        await update.message.reply_text(f"❌ Карточки недоступны: {', '.join(map(str, missing))}. Попробуйте снова.")
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

def _load_team_font(size: int):
    """Ищем шрифт с поддержкой кириллицы (Linux/Windows), иначе дефолтный."""
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "arialbd.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()

def build_rating_team_image(user_id: int):
    """Собирает красивую картинку рейтингового состава (PNG в памяти).

    Возвращает BytesIO или None (нет Pillow / нет состава) — тогда показываем текст."""
    if not PIL_AVAILABLE:
        return None
    team = get_rating_team(user_id)
    if not team:
        return None
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    members = [("ВРАТАРЬ", card_map.get(team["gk"]))]
    for fid in team["field"]:
        members.append(("ПОЛЕВОЙ", card_map.get(fid)))

    CARD_W, CARD_H, GAP, PAD, TOP = 220, 300, 24, 36, 120
    width = PAD * 2 + len(members) * CARD_W + (len(members) - 1) * GAP
    height = TOP + CARD_H + 116
    img = Image.new("RGB", (width, height), (13, 22, 38))
    draw = ImageDraw.Draw(img)
    font_title = _load_team_font(44)
    font_role = _load_team_font(22)
    font_name = _load_team_font(24)
    font_small = _load_team_font(20)

    elo = get_rating_elo(user_id)
    strength = int(_team_strength(team, card_map))
    draw.text((PAD, 28), "РЕЙТИНГОВЫЙ СОСТАВ", font=font_title, fill=(255, 214, 90))
    draw.text((PAD, 82), f"Рейтинг: {elo}   Сила состава: {strength}", font=font_small, fill=(150, 200, 255))

    for i, (role, card) in enumerate(members):
        x = PAD + i * (CARD_W + GAP)
        border = (255, 200, 60) if role == "ВРАТАРЬ" else (90, 150, 255)
        draw.rectangle([x - 4, TOP - 4, x + CARD_W + 4, TOP + CARD_H + 4], outline=border, width=4)
        card_img = None
        if card:
            path = os.path.join(CARDS_IMAGE_DIR, card.get("image", ""))
            if os.path.exists(path):
                try:
                    card_img = Image.open(path).convert("RGB").resize((CARD_W, CARD_H))
                except Exception:
                    card_img = None
        if card_img:
            img.paste(card_img, (x, TOP))
        else:
            draw.rectangle([x, TOP, x + CARD_W, TOP + CARD_H], fill=(30, 45, 70))
            draw.text((x + 48, TOP + CARD_H // 2 - 12), "НЕТ ФОТО", font=font_role, fill=(120, 140, 170))
        draw.text((x, TOP + CARD_H + 12), role, font=font_role, fill=border)
        name = (card.get("name", "?") if card else "?")[:18]
        draw.text((x, TOP + CARD_H + 42), name, font=font_name, fill=(235, 240, 250))
        power = get_card_power(card or {})
        draw.text((x, TOP + CARD_H + 74), f"Сила: {power}", font=font_small, fill=(150, 200, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

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
    caption = f"⭐ Ваш рейтинг: {elo}\n\n" + "\n".join(lines)
    # Пробуем отправить красивую картинку состава (нужен Pillow: pip install Pillow)
    photo = None
    try:
        photo = build_rating_team_image(user.id)
    except Exception as e:
        logger.warning(f"Не удалось построить картинку состава: {e}")
    if photo:
        await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text(caption)

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
    "💥 {player} ({team}) наносит жёсткий силовой приём!",
    "🥅 {player} ({team}) упускает стопроцентный момент!",
    "🧤 Вратарь {gk} вытаскивает шайбу из девятки против {team}!",
    "🥊 {player} ({team}) отправляется на скамейку штрафников (2 минуты)!",
    "🏒 {player} ({team}) обыгрывает одного защитника, но бросок мимо створа!",
    "🛡 Отличная силовая борьба у борта: {player} ({team}) выигрывает эпизод!",
    "🚫 {gk} эффектно перекрывает угол и спасает свою команду от гола {team}!",
    "🧊 {player} ({team}) бросает из выгодной позиции, но шайба попадает в штангу!",
    "⏱ {player} ({team}) получает лишние 2 минуты штрафа за задержку клюшкой!",
    "🤾 Вратарь {gk} совершает шпагат и вытаскивает верховой бросок {player}!",
    "🌀 {player} ({team}) закручивает шайбу у ворот, но она проходит впритирку мимо штанги!",
    "🧱 {gk} ловит шайбу прямо в ловушку после броска {player}!",
    "🔨 {player} ({team}) пробивает от синей линии, но вратарь {gk} справляется без проблем!",
    "🦵 Судья фиксирует подножку — {player} ({team}) удаляется на 2 минуты!",
    "🧤 {gk} накрывает шайбу телом на пятаке, не дав {player} ({team}) добить!",
    "🪃 {player} ({team}) бросает с неудобной руки — мимо ворот!",
    "🧨 Взрывной проход {player} ({team}), но передача партнёру срывается!",
    "🧊 Шайба со свистом пролетает над перекладиной после броска {player} ({team})!",
    "🛑 {gk} читает игру и перехватывает пас в средней зоне против {team}!",
    "🔁 {player} ({team}) бросает второй раз подряд — вратарь {gk} снова начеку!",
    "🥋 Жёсткая борьба на пятаке — {player} ({team}) остаётся без шайбы!",
    "📉 Реализация большинства не удаётся: {player} ({team}) мажет с близкой дистанции!",
    "🧯 {gk} гасит опасный отскок после броска {player}!",
    "⚔️ {player} ({team}) выигрывает силовую борьбу у борта, но время атаки истекает!",
    "🎣 Обманное движение {player} ({team}) не проходит — {gk} не поддаётся на финт!",
    "🕳 Бросок {player} ({team}) блокирует защитник в последний момент!",
    "🏒 {player} ({team}) выигрывает вбрасывание и создаёт момент у ворот {gk}!",
    "⚡ Контратака {team}! {player} выходит один на один, но {gk} читает игру!",
    "🧊 {player} ({team}) бросает с круга вбрасывания — шайба проходит рядом со штангой!",
    "🎯 {player} ({team}) расстреливает площадку, но {gk} стоит стеной!",
    "💫 {player} ({team}) делает no-look pass, но партнёр не успевает принять!",
    "🔥 Жаркая перепалка у борта — {player} ({team}) получает 2+2!",
    "🛡 Защитник {team} блокирует бросок {player} телом на линии огня!",
]
GOAL_EVENTS = [
    "🚨 ГОЛ! {player} ({team}) забрасывает шайбу!",
    "⚡ {player} ({team}) реализует большинство и открывает счёт!",
    "🎯 Точный бросок в упор - {player} ({team}) забивает красивый гол!",
    "🔥 {player} мощным щелчком в дальний угол оформляет гол за {team}!",
    "🎉 {player} ({team}) подбирает шайбу на пятаке и заталкивает её в ворота!",
    "🌟 {player} обыгрывает вратаря {gk} кистевым броском и забивает за {team}!",
    "💫 {player} ({team}) забивает гол с передачи партнёра прямо в касание!",
    "🚀 Невероятный бросок! {gk} даже не успевает среагировать — гол {player} ({team})!",
    "🥅 {player} ({team}) добивает шайбу после отскока от борта и заносит её в сетку!",
    "🏒 {player} эффектно обыгрывает защитников и хладнокровно поражает цель для {team}!",
    "🧨 {player} ({team}) забивает буллитом, безупречно обыграв {gk}!",
    "🎆 Красивая комбинация — {player} ({team}) завершает её точным броском в девятку!",
    "🎇 {player} ({team}) продавливает {gk} и заталкивает шайбу в упор!",
    "🌪 {player} закручивает шайбу над клюшкой {gk} — гол в пользу {team}!",
    "🧠 Хитрый буллит-финт: {player} ({team}) переигрывает {gk} и забивает!",
    "💣 Пушечный щелчок от синей линии — {player} ({team}) не оставляет шансов {gk}!",
    "🎊 {player} эффектно замыкает прострел партнёра и забивает за {team}!",
    "🪄 {player} ({team}) обыгрывает {gk} лёгким движением клюшки и закатывает шайбу!",
    "🏹 {player} ({team}) бросает из-под защитника прямо в девятку — гол!",
]
NEUTRAL_EVENTS = [
    "📣 Трибуны поддерживают {team} громким скандированием!",
    "🧊 Судья останавливает игру для заливки льда.",
    "🗣 Тренер {team} берёт тайм-аут для перестроения игры.",
    "❄️ Обе команды обмениваются жёсткими стыками у синей линии.",
    "📋 Тренерский штаб {team} меняет тройку нападения.",
    "🎥 Повтор на табло вызывает бурную реакцию трибун.",
    "🩹 Игрок {team} получает лёгкий ушиб, но остаётся на льду.",
    "🔄 {team} производит замену вратаря на паузе в игре.",
    "📢 Диктор объявляет статистику бросков по воротам.",
    "🥶 Короткая пауза на смазку коньков — игра вот-вот продолжится.",
    "🎶 Диджей арены заводит трибуны музыкой во время паузы.",
    "🧤 {player} ({team}) меняет сломанную клюшку у скамейки запасных.",
    "📸 Оператор ловит крупный план {player} ({team}) для повтора на экране.",
    "🍿 Болельщики {team} скандируют кричалку в поддержку своей команды.",
    "🧊 Мелкая заминка — рабочие устраняют выбоину на льду.",
    "🎙 Комментатор отмечает высокий темп сегодняшнего матча.",
    "🥅 Судьи проверяют крепление ворот после силового приёма.",
    "📝 Статистики фиксируют очередной силовой приём {player} ({team}).",
]

def _pick_field_player(team: dict, card_map: dict) -> int:
    """Выбирает полевого игрока команды с учётом его силы (более сильные игроки чаще участвуют в эпизодах)."""
    field_ids = team["field"]
    weights = [max(1, get_card_power(card_map.get(fid, {}))) for fid in field_ids]
    return random.choices(field_ids, weights=weights, k=1)[0]

def _card_name(card_id, card_map: dict) -> str:
    card = card_map.get(card_id)
    if not card:
        return f"Игрок {card_id}"
    return html.escape(card["name"])

def _generate_period_events(team_a: dict, team_b: dict, card_map: dict, name_a: str, name_b: str, p_a: float):
    """Генерирует события одного периода. Возвращает (events_text_list, goals_a, goals_b)."""
    events = []
    goals_a = 0
    goals_b = 0
    num_events = random.randint(4, 6)
    for _ in range(num_events):
        acting_a = random.random() < p_a
        acting_team = team_a if acting_a else team_b
        defending_team = team_b if acting_a else team_a
        team_name = name_a if acting_a else name_b
        player_name = _card_name(_pick_field_player(acting_team, card_map), card_map)
        gk_name = _card_name(defending_team["gk"], card_map)

        roll = random.random()
        if roll < 0.28:
            event = random.choice(GOAL_EVENTS).format(team=team_name, player=player_name, gk=gk_name)
            if acting_a:
                goals_a += 1
            else:
                goals_b += 1
        elif roll < 0.80:
            event = random.choice(HIT_EVENTS).format(team=team_name, player=player_name, gk=gk_name)
        else:
            event = random.choice(NEUTRAL_EVENTS).format(team=team_name, player=player_name, gk=gk_name)
        events.append(event)
    return events, goals_a, goals_b

async def _simulate_match(context: ContextTypes.DEFAULT_TYPE, user_a: int, user_b):
    """user_b может быть None (матч против бота). Результаты каждого периода отправляются
    игрокам сразу же по мере симуляции, а не одним большим сообщением в конце."""
    team_a = get_rating_team(user_a)
    team_b = get_rating_team(user_b) if user_b else _generate_bot_team()

    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}

    strength_a = _team_strength(team_a, card_map)
    strength_b = _team_strength(team_b, card_map)
    total = strength_a + strength_b if (strength_a + strength_b) > 0 else 1
    p_a = strength_a / total

    name_a = html.escape(await _get_display_name(context, user_a))
    name_b = html.escape(await _get_display_name(context, user_b))

    async def send_both(text: str):
        try:
            await context.bot.send_message(user_a, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_a}: {e}")
        if user_b:
            try:
                await context.bot.send_message(user_b, text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user_b}: {e}")

    await send_both(f"⚔️ <b>Матч начинается: {name_a} 🆚 {name_b}</b>\nПервый период стартует прямо сейчас!")

    goals_a, goals_b = 0, 0
    for period in range(1, 4):
        await asyncio.sleep(4)  # небольшая пауза для динамики матча вживую
        events, p_goals_a, p_goals_b = _generate_period_events(team_a, team_b, card_map, name_a, name_b, p_a)
        goals_a += p_goals_a
        goals_b += p_goals_b
        period_text = (
            f"🏒 <b>Период {period} завершён</b>\n"
            + "\n".join(events)
            + f"\n\n📊 Счёт после {period}-го периода: <b>{goals_a}:{goals_b}</b>"
        )
        await send_both(period_text)

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
        f"🏁 <b>Матч завершён: {name_a} {goals_a}:{goals_b} {name_b}</b>\n\n"
        f"{result_text_a}\n⭐ Рейтинг: {elo_a} → {new_elo_a}"
    )
    try:
        await context.bot.send_message(user_a, summary_a, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить результат матча пользователю {user_a}: {e}")

    if user_b:
        result_text_b = "🏆 Победа!" if goals_b > goals_a else ("🤝 Ничья." if goals_a == goals_b else "😞 Поражение.")
        summary_b = (
            f"🏁 <b>Матч завершён: {name_a} {goals_a}:{goals_b} {name_b}</b>\n\n"
            f"{result_text_b}\n⭐ Рейтинг: {elo_b} → {new_elo_b}"
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
        await update.message.reply_text("⚔️ Соперник найден! Матч начинается прямо сейчас...")
        try:
            await context.bot.send_message(opponent_entry["user_id"], "⚔️ Соперник найден! Матч начинается прямо сейчас...")
        except Exception:
            pass
        asyncio.create_task(_simulate_match(context, user.id, opponent_entry["user_id"]))
    else:
        queue.append({"user_id": user.id, "joined": time.time()})
        await update.message.reply_text(
            "🔍 Ищем соперника... Если никого не найдётся в течение 90 секунд, вы сыграете с ботом."
        )
        asyncio.create_task(_wait_and_fallback_to_bot(context, user.id, 90))

# ============================ СИСТЕМА КЛАНОВ ============================
async def create_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not context.args:
        await update.message.reply_text(f"ℹ️ Использование: /create_clan <название>\n💰 Стоимость создания: {CLAN_CREATE_COST} монет.")
        return
    if get_user_clan_id(user.id):
        await update.message.reply_text("❌ Вы уже состоите в клане. Сначала покиньте его через /leave_clan.")
        return

    name = " ".join(context.args).strip()
    if not (2 <= len(name) <= 32):
        await update.message.reply_text("❌ Название клана должно быть от 2 до 32 символов.")
        return

    clans = load_clans()
    if any(c["name"].lower() == name.lower() for c in clans):
        await update.message.reply_text("❌ Клан с таким названием уже существует. Выберите другое название.")
        return

    balance = get_coins(user.id)
    if balance < CLAN_CREATE_COST:
        await update.message.reply_text(f"❌ Для создания клана нужно {CLAN_CREATE_COST} монет. У вас: {balance}.")
        return

    update_coins(user.id, -CLAN_CREATE_COST)
    new_id = max((c["id"] for c in clans), default=0) + 1
    clan = {
        "id": new_id,
        "name": name,
        "owner": user.id,
        "members": [user.id],
        "treasury": 0,
        "contributions": {str(user.id): 0},
        "type": "open",
        "invites": [],
        "buff_upgrade_level": 0,
        "created": time.time()
    }
    clans.append(clan)
    save_clans(clans)
    set_user_clan_id(user.id, new_id)

    await update.message.reply_text(
        f"🏰 <b>Клан «{html.escape(name)}» создан!</b>\n"
        f"🆔 ID клана: {new_id}\n"
        f"💰 С вашего баланса списано {_fmt_coins(CLAN_CREATE_COST)} монет.\n\n"
        f"👥 Приглашайте участников: /join_clan {new_id}\n"
        f"🏦 Пополняйте казну клана: /clan_deposit {html.escape('<сумма>')}\n"
        f"📊 Топ-3 клана по казне получают бафф к монетам — смотрите /clans",
        parse_mode="HTML"
    )

async def join_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if get_user_clan_id(user.id):
        await update.message.reply_text("❌ Вы уже состоите в клане. Сначала покиньте его через /leave_clan.")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /join_clan <ID клана>\nСписок кланов: /clans")
        return
    try:
        clan_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Укажите числовой ID клана.")
        return

    clans = load_clans()
    clan = next((c for c in clans if c["id"] == clan_id), None)
    if not clan:
        await update.message.reply_text("❌ Клан с таким ID не найден. Список кланов: /clans")
        return

    if clan.get("type", "open") == "closed":
        invites = clan.get("invites", [])
        if user.id not in invites:
            await update.message.reply_text(
                "🔒 Это закрытый клан — вступление только по приглашению.\n"
                "Попросите создателя пригласить вас: /clan_invite"
            )
            return

    clan["members"].append(user.id)
    if "contributions" not in clan:
        clan["contributions"] = {}
    clan["contributions"][str(user.id)] = clan["contributions"].get(str(user.id), 0)
    if user.id in clan.get("invites", []):
        clan["invites"].remove(user.id)
    save_clans(clans)
    set_user_clan_id(user.id, clan_id)
    await update.message.reply_text(
        f"✅ Вы вступили в клан «{clan['name']}»!\n"
        f"👥 Теперь в клане: {len(clan['members'])} чел.\n"
        f"🏦 Казна клана: {_fmt_coins(clan.get('treasury', 0))} монет.\n"
        f"ℹ️ Подробности: /clan_info"
    )

async def leave_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не состоите ни в одном клане.")
        return

    clans = load_clans()
    clan = next((c for c in clans if c["id"] == clan_id), None)
    if not clan:
        set_user_clan_id(user.id, None)
        await update.message.reply_text("ℹ️ Клан не найден в базе, вы были отвязаны от него.")
        return

    if user.id in clan.get("members", []):
        clan["members"].remove(user.id)
    set_user_clan_id(user.id, None)

    disbanded = False
    clan_name = clan["name"]
    if clan["owner"] == user.id:
        if clan["members"]:
            clan["owner"] = clan["members"][0]
        else:
            clans.remove(clan)
            disbanded = True
    if not disbanded:
        clans = [c if c["id"] != clan_id else clan for c in clans]
    save_clans(clans)

    if disbanded:
        await update.message.reply_text(f"✅ Вы покинули клан «{clan_name}». Клан расформирован (не осталось участников).")
    else:
        await update.message.reply_text(f"✅ Вы покинули клан «{clan_name}».")

async def clan_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не состоите ни в одном клане. Создайте клан: /create_clan <название>")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /clan_deposit <сумма>")
        return
    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число монет.")
        return

    balance = get_coins(user.id)
    if balance < amount:
        await update.message.reply_text("❌ Недостаточно монет на балансе!")
        return

    clans = load_clans()
    clan = next((c for c in clans if c["id"] == clan_id), None)
    if not clan:
        await update.message.reply_text("❌ Клан не найден.")
        return

    update_coins(user.id, -amount)
    clan["treasury"] = clan.get("treasury", 0) + amount
    if "contributions" not in clan:
        clan["contributions"] = {}
    clan["contributions"][str(user.id)] = clan["contributions"].get(str(user.id), 0) + amount
    save_clans(clans)

    rank = get_clan_rank(clan["id"])
    bonus = get_clan_buff_bonus_percent(clan["id"])
    text = (
        f"✅ Вы внесли {_fmt_coins(amount)} монет в казну клана «{clan['name']}».\n"
        f"🏦 Казна клана: {_fmt_coins(clan['treasury'])} монет."
    )
    if bonus:
        text += f"\n{_clan_rank_badge(rank)} Клан в топ-3! Участники получают +{bonus}% к монетам."
    await update.message.reply_text(text)

def _clan_rank_badge(rank) -> str:
    if rank == 1:
        return "🥇"
    if rank == 2:
        return "🥈"
    if rank == 3:
        return "🥉"
    if rank:
        return f"#{rank}"
    return "—"

def _fmt_coins(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")

async def clan_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if context.args:
        try:
            clan_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Укажите числовой ID клана.")
            return

    if not clan_id:
        await update.message.reply_text(
            "❌ Вы не состоите ни в одном клане.\n"
            "Создайте свой: /create_clan <название>\n"
            "Или вступите в существующий: /join_clan <ID> (список: /clans)"
        )
        return

    clan = get_clan_by_id(clan_id)
    if not clan:
        await update.message.reply_text("❌ Клан не найден.")
        return

    rank = get_clan_rank(clan["id"])
    bonus = get_clan_buff_bonus_percent(clan["id"])
    badge = _clan_rank_badge(rank)
    owner_name = html.escape(await _get_display_name(context, clan["owner"]))
    members = clan.get("members", [])
    clan_type = "🔓 Открытый" if clan.get("type", "open") == "open" else "🔒 Закрытый"
    upgrade_lvl = clan.get("buff_upgrade_level", 0)

    lines = [
        f"🏰 <b>{html.escape(clan['name'])}</b>",
        f"🆔 ID клана: {clan['id']}",
        f"👑 Владелец: {owner_name}",
        f"🔐 Тип: {clan_type}",
        f"👥 Участников: {len(members)}",
        f"🏦 Казна: {_fmt_coins(clan.get('treasury', 0))} монет",
        f"⬆️ Прокачка баффа: ур. {upgrade_lvl}",
        f"📊 Место в рейтинге: {badge}" + (f" (из {len(get_ranked_clans())} в зачёте)" if rank else " (нет в зачёте — казна пуста)"),
    ]
    if bonus:
        lines.append(f"\n🌟 Активный бафф клана: <b>+{bonus}%</b> к получаемым монетам для всех участников!")
    else:
        lines.append(f"\nℹ️ Бафф получают кланы в топ-3 по казне: {', '.join(f'{_clan_rank_badge(r)} +{p}%' for r, p in sorted(CLAN_BUFF_TIERS.items()))}.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def clan_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не в клане.")
        return
    clan = get_clan_by_id(clan_id)
    if not clan or clan["owner"] != user.id:
        await update.message.reply_text("❌ Только создатель клана может просматривать вклады.")
        return
    contributions = clan.get("contributions", {})
    lines = [f"👥 <b>Участники клана «{html.escape(clan['name'])}»</b>\n"]
    member_data = []
    for mid in clan.get("members", []):
        contrib = contributions.get(str(mid), 0)
        name = html.escape(await _get_display_name(context, mid))
        member_data.append((mid, name, contrib))
    member_data.sort(key=lambda x: x[2], reverse=True)
    for i, (mid, name, contrib) in enumerate(member_data, 1):
        crown = " 👑" if mid == clan["owner"] else ""
        lines.append(f"{i}. {name}{crown} — 🏦 {_fmt_coins(contrib)} монет (ID: {mid})")
    lines.append(f"\n/clan_kick {html.escape('<user_id>')} — исключить | /clan_type — сменить тип")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def clan_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не в клане.")
        return
    clan = get_clan_by_id(clan_id)
    if not clan or clan["owner"] != user.id:
        await update.message.reply_text("❌ Только создатель может исключать участников.")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ /clan_kick <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
        return
    if target_id == user.id:
        await update.message.reply_text("❌ Нельзя исключить себя. Используйте /leave_clan.")
        return
    if target_id not in clan.get("members", []):
        await update.message.reply_text("❌ Этот игрок не в вашем клане.")
        return
    clan["members"].remove(target_id)
    clans = load_clans()
    for i, c in enumerate(clans):
        if c["id"] == clan_id:
            clans[i] = clan
            break
    save_clans(clans)
    set_user_clan_id(target_id, None)
    await update.message.reply_text(f"✅ Игрок {target_id} исключён из клана.")
    try:
        await context.bot.send_message(target_id, f"ℹ️ Вас исключили из клана «{clan['name']}».")
    except Exception:
        pass

async def clan_type_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не в клане.")
        return
    clan = get_clan_by_id(clan_id)
    if not clan or clan["owner"] != user.id:
        await update.message.reply_text("❌ Только создатель может менять тип клана.")
        return
    if not context.args or context.args[0].lower() not in ("open", "closed"):
        current = "открытый" if clan.get("type", "open") == "open" else "закрытый"
        await update.message.reply_text(
            f"ℹ️ Текущий тип: {current}\n"
            "Использование: /clan_type open — любой может вступить\n"
            "/clan_type closed — только по приглашению"
        )
        return
    new_type = context.args[0].lower()
    clan["type"] = new_type
    clans = load_clans()
    for i, c in enumerate(clans):
        if c["id"] == clan_id:
            clans[i] = clan
            break
    save_clans(clans)
    label = "🔓 открытым" if new_type == "open" else "🔒 закрытым"
    await update.message.reply_text(f"✅ Клан теперь {label}.")

async def clan_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не в клане.")
        return
    clan = get_clan_by_id(clan_id)
    if not clan or clan["owner"] != user.id:
        await update.message.reply_text("❌ Только создатель может приглашать.")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ /clan_invite <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
        return
    if get_user_clan_id(target_id):
        await update.message.reply_text("❌ Игрок уже состоит в клане.")
        return
    if "invites" not in clan:
        clan["invites"] = []
    if target_id not in clan["invites"]:
        clan["invites"].append(target_id)
    clans = load_clans()
    for i, c in enumerate(clans):
        if c["id"] == clan_id:
            clans[i] = clan
            break
    save_clans(clans)
    await update.message.reply_text(f"✅ Игрок {target_id} приглашён в клан.")
    try:
        await context.bot.send_message(
            target_id,
            f"📨 Вас пригласили в клан «{clan['name']}»!\n/join_clan {clan_id}",
        )
    except Exception:
        pass

async def clan_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clan_id = get_user_clan_id(user.id)
    if not clan_id:
        await update.message.reply_text("❌ Вы не в клане.")
        return
    clan = get_clan_by_id(clan_id)
    if not clan:
        await update.message.reply_text("❌ Клан не найден.")
        return
    if user.id not in clan.get("members", []):
        await update.message.reply_text("❌ Вы не участник этого клана.")
        return
    if clan.get("owner") != user.id:
        await update.message.reply_text("❌ Прокачивать клан из казны может только создатель клана.")
        return
    level = clan.get("buff_upgrade_level", 0)
    next_level = level + 1
    cost = CLAN_UPGRADE_COSTS.get(next_level)
    if not cost:
        await update.message.reply_text(f"❌ Максимальный уровень прокачки ({level}) достигнут.")
        return
    if clan.get("treasury", 0) < cost:
        await update.message.reply_text(
            f"❌ Нужно {_fmt_coins(cost)} монет в казне. Сейчас: {_fmt_coins(clan.get('treasury', 0))}."
        )
        return
    clan["treasury"] -= cost
    clan["buff_upgrade_level"] = next_level
    clans = load_clans()
    for i, c in enumerate(clans):
        if c["id"] == clan_id:
            clans[i] = clan
            break
    save_clans(clans)
    rank = get_clan_rank(clan_id)
    bonus = get_clan_buff_bonus_percent(clan_id)
    await update.message.reply_text(
        f"⬆️ <b>Бафф клана прокачан до ур. {next_level}!</b>\n"
        f"💰 Потрачено из казны: {_fmt_coins(cost)}\n"
        f"🏦 Остаток казны: {_fmt_coins(clan['treasury'])}\n"
        f"🌟 Текущий бонус: +{bonus}% к монетам"
        + (f" (место {_clan_rank_badge(rank)})" if rank else ""),
        parse_mode="HTML",
    )

async def clans_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clans = load_clans()
    if not clans:
        await update.message.reply_text("ℹ️ Пока не создано ни одного клана. Создайте первый: /create_clan <название>")
        return

    sorted_clans = sorted(clans, key=lambda c: c.get("treasury", 0), reverse=True)
    lines = ["🏆 <b>Рейтинг кланов по казне</b>\n"]
    for i, c in enumerate(sorted_clans[:10], 1):
        eligible = c.get("treasury", 0) > 0 and c.get("members")
        badge = _clan_rank_badge(i) if eligible else "•"
        bonus = CLAN_BUFF_TIERS.get(i, 0) if eligible else 0
        bonus_text = f" (+{bonus}%)" if bonus else ""
        lines.append(
            f"{badge} «{html.escape(c['name'])}»{bonus_text} — 🏦 {_fmt_coins(c.get('treasury', 0))} монет, 👥 {len(c.get('members', []))} чел. (ID: {c['id']})"
        )
    tiers_text = ", ".join(f"{_clan_rank_badge(r)} +{p}%" for r, p in sorted(CLAN_BUFF_TIERS.items()))
    lines.append(f"\n🌟 Топ-3 клана по казне получают бафф к получаемым монетам: {tiers_text}.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

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
    for f in [USERS_FILE, BLACKLIST_FILE, MODERATORS_FILE, COINS_FILE, SHOP_FILE, PROMOCODES_FILE, EVENTS_FILE, BETS_FILE, CLANS_FILE, ISSUED_PROMO_CODES_FILE]:
        if not os.path.exists(f):
            if f in [BLACKLIST_FILE, MODERATORS_FILE, SHOP_FILE, EVENTS_FILE, BETS_FILE, CLANS_FILE]:
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

    application = Application.builder().token(TOKEN).post_init(_post_init).build()

    # Периодическая фоновая задача запускается через post_init, не зависит от наличия JobQueue

    # ConversationHandler'ы (все многошаговые потоки в одном обработчике, чтобы не было конфликтов состояний)
    async def _bet_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear()
        await bet_start(update, context)
        return ConversationHandler.END

    async def _trade_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear()
        await trade_offer(update, context)
        return ConversationHandler.END

    async def _events_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear()
        await events_menu(update, context)
        return ConversationHandler.END

    all_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("admin_addcard", admin_addcard),
            CommandHandler("admin_addrarity", admin_addrarity),
            CommandHandler("admin_editrarity", admin_editrarity),
            CommandHandler("admin_addshopitem", admin_addshopitem),
            CommandHandler("admin_editcard", admin_editcard),
            CommandHandler("craft", start_craft),
            CommandHandler("bet", _bet_entry),
            CommandHandler("trade", _trade_entry),
            CommandHandler("events", _events_entry),
            CommandHandler("rating_team", rating_team_start),
            CommandHandler("create_promo", create_promo_start),
            CommandHandler("start_season", start_season_cmd),
        ],
        states={
            ADMIN_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_name)],
            ADMIN_CARD_RARITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_rarity)],
            ADMIN_CARD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_description)],
            ADMIN_CARD_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, admin_card_image)],
            ADMIN_RARITY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_name)],
            ADMIN_RARITY_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_emoji)],
            ADMIN_RARITY_DROPPABLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_droppable)],
            ADMIN_RARITY_CHANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_chance)],
            ADMIN_EDIT_RARITY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_rarity_name)],
            ADMIN_EDIT_RARITY_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_rarity_emoji)],
            ADMIN_EDIT_RARITY_DROPPABLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_rarity_droppable)],
            ADMIN_EDIT_RARITY_CHANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_rarity_chance)],
            ADMIN_SHOP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_name)],
            ADMIN_SHOP_TYPE: [CallbackQueryHandler(admin_shop_type, pattern=r"^(reset|pack)$")],
            ADMIN_SHOP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_price)],
            ADMIN_SHOP_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_cards)],
            ADMIN_SHOP_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_duration)],
            EDIT_CARD_FIELD: [CallbackQueryHandler(edit_card_field, pattern=r"^(name|rarity|description|image|cancel)$")],
            EDIT_CARD_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_card_value),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, edit_card_value)
            ],
            CRAFT_SELECT_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_craft)],
            RATING_TEAM_GK: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_gk)],
            RATING_TEAM_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_field)],
            PROMO_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_name)],
            PROMO_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_type)],
            PROMO_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_value)],
            PROMO_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_uses)],
            PROMO_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_duration)],
            SEASON_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_number)],
            SEASON_PRIZE_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_prize_1)],
            SEASON_PRIZE_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_prize_2)],
            SEASON_PRIZE_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_prize_3)],
        },
        fallbacks=[CommandHandler("cancel", cancel_craft)],
        allow_reentry=True,
    )

    application.add_handler(all_conv_handler)

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
    application.add_handler(CommandHandler("work", work_command))
    application.add_handler(CommandHandler("market", show_market))
    application.add_handler(CommandHandler("sell", sell_card))
    application.add_handler(CommandHandler("my_listings", my_listings))
    application.add_handler(CommandHandler("unlist", unlist_card))
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
    application.add_handler(CommandHandler("admin_unlist", admin_unlist))
    application.add_handler(CommandHandler("admin_viewcards", admin_viewcards))
    application.add_handler(CommandHandler("admin_takecard", admin_takecard))
    application.add_handler(CommandHandler("admin_listrarities", admin_listrarities))
    application.add_handler(CommandHandler("admin_listshop", admin_listshop))
    application.add_handler(CommandHandler("casino", casino))
    application.add_handler(CommandHandler("coin", coin_flip))
    application.add_handler(CommandHandler("slots", slots))
    application.add_handler(CommandHandler("keyboard", show_keyboard))
    application.add_handler(CommandHandler("hide", hide_keyboard))
    application.add_handler(CommandHandler("buff", buff_info))
    application.add_handler(CommandHandler("set_buff", set_buff))
    application.add_handler(CommandHandler("upgrade_buff", upgrade_buff))
    application.add_handler(CommandHandler("redeem", redeem_promo))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("create_match", create_match))
    application.add_handler(CommandHandler("finish_match", finish_match))
    application.add_handler(CommandHandler("my_bets", my_bets))
    application.add_handler(CommandHandler("find_match", find_match))
    application.add_handler(CommandHandler("rating", rating_profile))
    application.add_handler(CommandHandler("create_clan", create_clan))
    application.add_handler(CommandHandler("join_clan", join_clan))
    application.add_handler(CommandHandler("leave_clan", leave_clan))
    application.add_handler(CommandHandler("clan_deposit", clan_deposit))
    application.add_handler(CommandHandler("clan_info", clan_info))
    application.add_handler(CommandHandler("clans", clans_leaderboard))
    application.add_handler(CommandHandler("clan_members", clan_members))
    application.add_handler(CommandHandler("clan_kick", clan_kick))
    application.add_handler(CommandHandler("kick", clan_kick))
    application.add_handler(CommandHandler("clan_type", clan_type_cmd))
    application.add_handler(CommandHandler("clan_invite", clan_invite))
    application.add_handler(CommandHandler("clan_upgrade", clan_upgrade))
    application.add_handler(CommandHandler("end_season", end_season_cmd))

    # CallbackQueryHandler'ы
    application.add_handler(CallbackQueryHandler(admin_shop_type, pattern=r"^(reset|pack)"))
    application.add_handler(CallbackQueryHandler(set_buff_buttons, pattern=r"^(confirm_set_buff_|cancel_set_buff)"))
    application.add_handler(CallbackQueryHandler(upgrade_buff_buttons, pattern=r"^(confirm_upgrade_buff|cancel_upgrade_buff)"))
    application.add_handler(CallbackQueryHandler(bet_match_callback, pattern=r"^bet_match_"))
    application.add_handler(CallbackQueryHandler(bet_outcome_callback, pattern=r"^bet_outcome_"))
    application.add_handler(CallbackQueryHandler(trade_callbacks, pattern=r"^trade_"))
    application.add_handler(CallbackQueryHandler(market_buy_callback, pattern=r"^market_buy_"))
    application.add_handler(CallbackQueryHandler(market_page_callback, pattern=r"^market_page_"))
    application.add_handler(CallbackQueryHandler(events_callbacks, pattern=r"^evt_"))

    # Обработка обновлений голосований (ручная/автоматическая остановка)
    application.add_handler(PollHandler(poll_update_handler))

    # Кнопки красивой клавиатуры (точное совпадение текста кнопки)
    application.add_handler(MessageHandler(filters.Text(ALL_KEYBOARD_BUTTONS), keyboard_button_handler))

    # MessageHandler для текстового ввода (ставки, обмен, события)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    # Проверка подписки (обрабатывает оставшиеся сообщения)
    application.add_handler(MessageHandler(filters.ALL, check_subscription))

    # Явно запрашиваем все типы апдейтов, чтобы гарантированно получать Poll-апдейты.
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()