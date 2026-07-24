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
import sys
import subprocess
import re
import threading
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Pillow нужен для картинки рейтингового состава (/rating).
# Если не установлен (pip install Pillow) — бот работает, состав показывается текстом.
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
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

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует любые необработанные ошибки обработчиков и не даёт им бесследно останавливать бота."""
    try:
        if context.error:
            err = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
        else:
            err = "Unknown error"
        logger.error("Необработанная ошибка Telegram-хэндлера:\n%s", err)
        with open(os.path.join(BASE_DIR, "bot_errors.log"), "a", encoding="utf-8") as f:
            f.write(f"\n\n===== {datetime.now().isoformat()} =====\n")
            f.write(err)
    except Exception:
        pass

# ============================ КОНФИГУРАЦИЯ ============================
# Токен хранится в bot_token.txt: при ПЕРВОМ запуске бот спросит его в консоли
# и сохранит, а при самообновлении (/update) перезапустится уже без вопросов.
# Папка, где лежит сам bot.py и все json-файлы. Бот ВСЕГДА работает из неё:
# os.chdir ниже гарантирует, что рабочая папка не поменяется, откуда бы его ни запустили.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

TOKEN_FILE = os.path.join(BASE_DIR, "bot_token.txt")

def _load_bot_token() -> str:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, encoding="utf-8") as f:
                saved = f.read().strip()
            if saved:
                return saved
    except Exception:
        pass
    try:
        token = input("Введите токен бота: ").strip()
    except (EOFError, OSError):
        print("ОШИБКА: рядом с bot.py нет файла bot_token.txt, а консоль недоступна для ввода токена.")
        print(f"Создайте файл {TOKEN_FILE} и положите в него токен бота одной строкой.")
        sys.exit(1)
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
    except Exception:
        pass
    return token

TOKEN = _load_bot_token()
CHANNEL_ID = "-1002899939309"
CHANNEL_LINK = "https://t.me/cabakoff"
EVENTS_CHANNEL_ID = "-1004369187055"
EVENTS_CHANNEL_LINK = "https://t.me/RUHOCKEYCARDS"
REQUIRED_CHANNELS = [
    {"id": CHANNEL_ID, "link": CHANNEL_LINK, "name": "основной канал"},
    {"id": EVENTS_CHANNEL_ID, "link": EVENTS_CHANNEL_LINK, "name": "канал Хоккейные карточки"},
]
ADMIN_ID = 1106828306
MSK_OFFSET_SECONDS = 3 * 3600
QUESTS_FILE = "daily_quests.json"
REPORTS_FILE = "reports.json"
NOTIFICATIONS_FILE = "notifications.json"
ACTION_HISTORY_FILE = "action_history.json"
SECURITY_LOG_FILE = "security_log.json"
BOT_MARKET_FILE = "bot_market_state.json"
INJURIES_FILE = "injuries.json"
PITY_RARE_LIMIT = 25
PITY_EPIC_LIMIT = 60
PITY_LEGENDARY_LIMIT = 120

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
# Бонусный чат за активность
BONUS_CHAT_ID = -1002896874318
CHAT_ACTIVITY_FILE = "chat_activity.json"
RARITIES_FILE = "rarities.json"
SHOP_FILE = "shop.json"
COSMETIC_SHOP_FILE = "cosmetic_shop.json"
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
REFERRALS_FILE = "referrals.json"
MARKET_MAX_PRICE = 10_000
REFERRAL_REWARD = 50
REFERRAL_MIN_ACCOUNT_AGE_SECONDS = 600
CARDS_IMAGE_DIR = "cards_images"

# ============================ СИСТЕМА КЛАНОВ ============================
CLAN_CREATE_COST = 1000          # стоимость создания клана
CLAN_BUFF_TIERS = {1: 8, 2: 5, 3: 3}  # % бонуса к монетам по месту клана в рейтинге казны (1 - самый большой)
CLAN_UPGRADE_COSTS = {1: 500, 2: 1000, 3: 2000, 4: 3500, 5: 5000, 6: 7500, 7: 10500, 8: 14000, 9: 18000, 10: 23000}
CLAN_UPGRADE_BONUS_PER_LEVEL = 2   # +2% к клан-баффу за каждый уровень прокачки

# ============================ РЕДКОСТИ: ДЕФОЛТНЫЕ ШАНСЫ ============================
DEFAULT_RARITY_CHANCES = {
    "Легендарная": 0.03,
    "Мифическая": 0.07,
    "Эпическая": 0.15,
    "Сверхредкая": 0.25,
    "Редкая": 0.35,
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
# РЕБАЛАНС НАГРАД (нерф /work):
# Раньше эксклюзив приносил 250-400 монет, а с прокачанным баффом и клановым
# бонусом выходило 500+ за одну отправку. Минимальная цена эксклюзивной карты
# на маркете - 1000 монет (MARKET_MIN_PRICES), то есть карта окупалась за 2 работы.
# Теперь даже с максимальными баффами одна работа эксклюзивом даёт не больше
# WORK_REWARD_HARD_CAP монет: на эксклюзив нужно копить 5+ отправок.
WORK_REWARDS = {
    "Обычная": (12, 25),
    "Редкая": (22, 40),
    "Эпическая": (35, 60),
    "Мифическая": (55, 85),
    "Легендарная": (75, 115),
    "Эксклюзивная": (110, 170),
}
# Баффы (карта + клан) на работе действуют ослабленно: учитывается только
# половина суммарного бонуса и не больше +25% сверху базовой награды.
WORK_BUFF_BONUS_CAP = 0.25
# Кулдаун работы бафф-карта сокращает не более чем на 30% (раньше до 80%,
# из-за чего работать можно было почти каждый час).
WORK_MAX_COOLDOWN_REDUCTION = 0.30
# Жёсткий потолок награды за одну работу (страховка от стака будущих бонусов).
WORK_REWARD_HARD_CAP = 200

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
RATING_TEAM_GK, RATING_TEAM_FIELD, RATING_TEAM_COACH, RATING_TEAM_TACTIC, RATING_TEAM_NAME = 30, 31, 32, 33, 34

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
    """Crash-safe JSON write: readers see either the old complete file or the new one."""
    directory = os.path.dirname(os.path.abspath(filename)) or "."
    tmp_name = os.path.join(directory, f".{os.path.basename(filename)}.tmp")
    with open(tmp_name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_name, filename)

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
    """Игрок должен быть подписан на оба обязательных канала."""
    ok_statuses = ["member", "administrator", "creator"]
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status not in ok_statuses:
                return False
        except Exception as e:
            logger.error(f"Ошибка проверки подписки на {channel.get('id')}: {e}")
            return False
    return True

def subscription_required_text() -> str:
    links = "\n".join(f"• {ch['link']}" for ch in REQUIRED_CHANNELS)
    return f"❌ Для игры нужно быть подписанным на оба канала:\n{links}"

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
        "Мифическая": "🧠",
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
    # Сортировка по РЕАЛЬНОМУ шансу выпадения:
    # невыпадающие (эксклюзивные) всегда сверху, дальше от самых редких к частым.
    rarity_info = {r["name"]: r for r in rarities}
    def _collection_sort_key(rarity_name):
        info = rarity_info.get(rarity_name, {})
        droppable = info.get("droppable", rarity_name != "Эксклюзивная")
        chance = get_rarity_drop_chance(rarity_name)
        if chance <= 0:
            chance = 1.0
        return (0 if not droppable else 1, chance, rarity_name)
    sorted_rarities = sorted(grouped.keys(), key=_collection_sort_key)
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
            lvl = int(user_data.get("card_upgrades", {}).get(str(card["id"]), 0))
            lvl_text = f" ⭐ур.{lvl}" if lvl > 0 else ""
            message += f"   • {html.escape(card['name'])}{lvl_text}{count_text} [ID: {card['id']}]\n"
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
MAX_BUFF_LEVEL = 10  # prevents unbounded multipliers and coin inflation

def get_active_buff(user_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    buff = user_data.get("buff_card")
    # A buff cannot survive selling/losing its last source card.
    if buff and user_data.get("cards", []).count(buff.get("card_id")) < 1:
        user_data.pop("buff_card", None)
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)
        return None
    if buff and int(buff.get("level", 1)) > MAX_BUFF_LEVEL:
        buff["level"] = MAX_BUFF_LEVEL
        user_data["buff_card"] = buff
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)
    return buff

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
    level = min(int(buff.get("level", 1)), MAX_BUFF_LEVEL)
    bonus = level * 5
    return 1.0 + bonus / 100.0

def is_legendary_or_higher(rarity: str) -> bool:
    return rarity in ["Эпическая", "Мифическая", "Легендарная", "Эксклюзивная"]

# ============================ РЕЙТИНГОВЫЙ РЕЖИМ: СИЛА КАРТОЧЕК ============================
DEFAULT_CARD_POWER = 40

def get_card_power(card: dict) -> int:
    """Сила рейтинговой карты считается от шанса выпадения редкости.
    Это работает и для стандартных, и для админских кастомных редкостей.
    Чем меньше шанс — тем выше сила. Эксклюзивные/невыпадающие получают топ-силу.
    """
    rarity = card.get("rarity", "Обычная")
    try:
        chance = float(get_rarity_drop_chance(rarity))
    except Exception:
        chance = DEFAULT_RARITY_CHANCES.get("Обычная", 0.50)
    if chance <= 0:
        return 110
    # Плавная шкала: 50% ≈ 35 силы, 3% ≈ 100 силы, 1% и ниже ≈ 110 силы.
    import math
    power = 30 + int(round(-math.log10(max(chance, 0.001)) * 45))
    return max(30, min(110, power))

def get_card_rating_cap(card: dict) -> int:
    """Потолок прокачки зависит от шанса редкости, поэтому работает и для кастомных редкостей."""
    return min(140, get_card_power(card) + 35)

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
    "Мифическая": ((0, 210, 190), (150, 255, 240)),
    "Эксклюзивная": ((255, 55, 90), (255, 155, 175)),
    "Мифическая": ((255, 60, 185), (255, 170, 230)),
    "Сверхредкая": ((40, 205, 120), (160, 255, 210)),
}

# Палитра для ЛЮБЫХ будущих кастомных редкостей:
# цвет стабильно выбирается по имени — больше никаких серых дефолтов.
_CUSTOM_FRAME_PALETTE = [
    ((255, 120, 40), (255, 190, 140)),   # оранжевый
    ((240, 80, 255), (250, 175, 255)),   # неоново-розовый
    ((120, 220, 40), (200, 255, 150)),   # лаймовый
    ((80, 120, 255), (170, 195, 255)),   # индиго
    ((25, 220, 255), (170, 245, 255)),   # неоново-голубой
    ((255, 210, 0), (255, 240, 150)),    # янтарный
]

def _rarity_frame_colors(rarity_name: str):
    """Цвет рамки для редкости. Неизвестные получают яркий цвет из палитры."""
    if rarity_name in RARITY_FRAME_COLORS:
        return RARITY_FRAME_COLORS[rarity_name]
    idx = sum(ord(ch) for ch in str(rarity_name)) % len(_CUSTOM_FRAME_PALETTE)
    return _CUSTOM_FRAME_PALETTE[idx]

def _is_premium_rarity(rarity_name: str) -> bool:
    """Топ-редкости получают свечение и звёзды на рамке.

    Это легендарные-и-выше ПЛЮС любая кастомная редкость с шансом <= 8%
    (Мифическая и т.п. автоматически считаются крутыми)."""
    if is_legendary_or_higher(rarity_name):
        return True
    try:
        chance = get_rarity_drop_chance(rarity_name)
    except Exception:
        return False
    return 0 < chance <= 0.08

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
        # Стабильный ключ (без hash(), который меняется при каждом рестарте бота):
        # кэш теперь переживает перезапуски и не перерисовывается зря.
        name_sig = sum(ord(ch) for ch in (str(card.get('name', '')) + str(card['rarity']))) % 100000
        cache_key = f"{card['id']}_{mtime}_{name_sig}.png"
        cache_path = os.path.join(FRAMED_CARDS_DIR, cache_key)
        if os.path.exists(cache_path):
            return open(cache_path, "rb")

        main, light = _rarity_frame_colors(card["rarity"])
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

        legendary = _is_premium_rarity(card["rarity"])
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

def set_rating_team(user_id: int, gk_id: int, field_ids: list, coach_id=None, tactic: str = "balanced", team_name=None):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    user_data["rating_team"] = {
        "gk": gk_id,
        "field": field_ids,
        "coach": coach_id,
        "tactic": tactic,
        "name": team_name,
    }
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

# ============================ РЕЙТИНГ: ТРЕНЕР И ТАКТИКА ============================
TACTIC_LABELS = {"attack": "⚔️ Нападение", "bus": "🚌 Автобус", "balanced": "⚖️ Сбалансировано"}
TACTIC_PLAIN = {"attack": "Нападение", "bus": "Автобус", "balanced": "Баланс"}

def get_coach_bonus(rarity_name: str) -> float:
    """Сила баффа тактики тренера: чем реже выпадает карта-тренер, тем сильнее бафф (3%..10%)."""
    chance = get_rarity_drop_chance(rarity_name)
    if chance <= 0:
        return 0.10  # недоступные в дропе (эксклюзив) — максимальный бафф
    if chance >= 0.45:
        return 0.03
    if chance >= 0.25:
        return 0.04
    if chance >= 0.12:
        return 0.05
    if chance >= 0.06:
        return 0.065
    if chance >= 0.02:
        return 0.08
    return 0.10

def _team_tactic_mods(team, card_map):
    """Возвращает (бонус к своему шансу забить, бонус к шансу СОПЕРНИКА забить).
    Нападение: больше забиваем, но больше пропускаем. Автобус: меньше и то и то.
    Сбалансировано: небольшой бафф в обе стороны."""
    coach_id = (team or {}).get("coach")
    if not coach_id:
        return 0.0, 0.0
    card = card_map.get(coach_id)
    bonus = get_coach_bonus(card.get("rarity", "")) if card else 0.03
    tactic = (team or {}).get("tactic", "balanced")
    if tactic == "attack":
        return bonus, bonus * 0.8
    if tactic == "bus":
        return -bonus * 0.7, -bonus
    return bonus * 0.35, -bonus * 0.35

def _team_title(team, base_name: str) -> str:
    """«Название команды (@юзер)», если название задано, иначе просто юзер."""
    tn = (team or {}).get("name")
    return f"{tn} ({base_name})" if tn else base_name

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

# ============================ РАНГИ ДЛЯ МАТЧМЕЙКИНГА ============================
# Категории Хоккейные карточки: Prospect → Average → Elite → Franchise.
# Соперник в /find_match подбирается ТОЛЬКО внутри одного ранга.
RATING_RANKS = [
    (1300, "🌟", "Franchise"),
    (1150, "💎", "Elite"),
    (1000, "🥈", "Average"),
    (0, "🥉", "Prospect"),
]

def get_rating_rank(elo: int):
    """Возвращает (номер_ранга, эмодзи, название). Чем выше номер — тем выше ранг."""
    for i, (threshold, emoji, name) in enumerate(RATING_RANKS):
        if elo >= threshold:
            return len(RATING_RANKS) - i, emoji, name
    return 1, "🥉", "Prospect"

# ======================== СИСТЕМА ЗВАНИЙ ========================
# Очки трофеев начисляются за каждый сезон:
# 1-е место = 10 очков, 2-е = 5, 3-е = 3, топ-10 = 1 очко
TROPHY_POINTS_FILE = "trophy_points.json"

TITLES = [
    (100, "Godlike",     "Божество",      "💀"),
    ( 70, "Legend",      "Легенда",       "🌟"),
    ( 50, "Grandmaster", "Гроссмейстер",  "👑"),
    ( 35, "Elite",       "Элита",         "🔥"),
    ( 25, "Dominator",   "Доминатор",     "⚔️"),
    ( 17, "Specialist",  "Специалист",    "💪"),
    ( 12, "Hunter",      "Охотник",       "🎯"),
    (  8, "Survivor",    "Выживший",      "🛡️"),
    (  5, "Hardstuck",   "Застрявший",    "🔒"),
    (  3, "Apprentice",  "Подмастерье",   "📖"),
    (  1, "Scout",       "Разведчик",     "🔍"),
    (  0, "Average",     "Обыватель",     "👥"),
]

def get_trophy_points(user_id: int) -> int:
    data = load_data(TROPHY_POINTS_FILE, {})
    return data.get(str(user_id), 0)

def add_trophy_points(user_id: int, pts: int) -> int:
    data = load_data(TROPHY_POINTS_FILE, {})
    current = data.get(str(user_id), 0)
    data[str(user_id)] = current + pts
    save_data(TROPHY_POINTS_FILE, data)
    return data[str(user_id)]

def get_user_title(user_id: int):
    """Возвращает (name_en, name_ru, emoji) текущего звания."""
    pts = get_trophy_points(user_id)
    for threshold, name_en, name_ru, emoji in TITLES:
        if pts >= threshold:
            return name_en, name_ru, emoji
    return "Average", "Обыватель", "👥"

def get_next_title(current_pts: int):
    """Возвращает (name_en, pts_needed) следующего звания или None."""
    for threshold, name_en, name_ru, emoji in reversed(TITLES):
        if threshold > current_pts:
            return name_en, threshold - current_pts
    return None, 0

# ==================================================================

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
    buff = user_data.get("buff_card")
    if buff and buff.get("card_id") == card_id and cards.count(card_id) <= 1:
        return False  # reserve the active buff's source copy
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

NOTIFICATION_CATEGORIES = {
    "news": "новости/ивенты",
    "market": "магазин/маркет",
    "giveaways": "розыгрыши",
    "matches": "матчи/ставки",
    "season": "сезоны",
}

def _load_notification_settings() -> dict:
    data = load_data(NOTIFICATIONS_FILE, {})
    return data if isinstance(data, dict) else {}

def _save_notification_settings(data: dict) -> None:
    save_data(NOTIFICATIONS_FILE, data)

def _user_notification_enabled(user_id: int, category: str = "news") -> bool:
    data = _load_notification_settings()
    user_cfg = data.get(str(user_id), {})
    return bool(user_cfg.get(category, False))

def _notification_subscribers(category: str = "news") -> list[int]:
    data = _load_notification_settings()
    result = []
    for uid, cfg in data.items():
        try:
            if isinstance(cfg, dict) and cfg.get(category, False):
                result.append(int(uid))
        except Exception:
            continue
    return result

async def notify_users_in_dm(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: str = "HTML",
    user_ids=None,
    batch_size: int = 25,
    pause_seconds: float = 0.20,
    category: str = "news",
):
    """Рассылка только пользователям, которые сами включили нужную категорию в /notifications."""
    if user_ids is None:
        ids = _notification_subscribers(category)
    else:
        ids = []
        for uid in user_ids:
            try:
                uid_int = int(uid)
                if _user_notification_enabled(uid_int, category):
                    ids.append(uid_int)
            except Exception:
                continue
    ids = list(dict.fromkeys(uid for uid in ids if uid > 0))
    sent = 0
    failed = 0
    for i, uid in enumerate(ids, start=1):
        try:
            await context.bot.send_message(uid, text, parse_mode=parse_mode)
            sent += 1
        except Exception:
            failed += 1
        if i % batch_size == 0:
            await asyncio.sleep(pause_seconds)
    return {"sent": sent, "failed": failed, "total": len(ids), "category": category}

async def post_to_channel(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: str = "HTML",
    mirror_dm: bool = True,
    dm_text: str | None = None,
    user_ids=None,
    notification_category: str = "news",
) -> None:
    # Пост в канал идёт всегда.
    try:
        await context.bot.send_message(EVENTS_CHANNEL_ID, text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в канал: {e}")
    # В ЛС — только тем, кто включил категорию уведомлений.
    if mirror_dm:
        try:
            await notify_users_in_dm(
                context,
                dm_text or text,
                parse_mode=parse_mode,
                user_ids=user_ids,
                category=notification_category,
            )
        except Exception as e:
            logger.error(f"Не удалось отправить ЛС-рассылку: {e}")

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
    "🎴 Карточки:\n"
    "/get_card - получить карточку\n"
    "/my_cards - моя коллекция\n"
    "/card_info <card_id или mINSTANCE_ID> - информация о карточке\n"
    "/craft - крафт: обменять карточки на более редкую\n"
    "/upgrade_card <card_id> - прокачать карту дубликатами (+2 силы за уровень)\n"
    "/buff - информация о баффе\n"
    "/set_buff <card_id> - выбрать карту для баффа\n"
    "/upgrade_buff - улучшить бафф\n\n"
    "💰 Экономика:\n"
    "/balance - баланс монет\n"
    "/daily - ежедневная награда (серия дней даёт до +100%)\n"
    "/work <card_id> - отправить карточку работать (раз в 2 часа)\n"
    "/shop - магазин\n"
    "/buy <ID товара> - купить товар в магазине\n"
    "/redeem <код> - активировать промокод\n"
    "/ref - реферальная ссылка (приглашай друзей — получай монеты)\n\n"
    "🏪 Маркет и обмен:\n"
    "/market - маркет карточек\n"
    "/sell <card_id или mINSTANCE_ID> <цена> - выставить карточку на маркет\n"
    "/offer_sell <user_id> <card_id или mINSTANCE_ID> <цена> - личное предложение продажи\n"
    "/my_listings - мои объявления на маркете\n"
    "/unlist <ID объявления> - снять свой лот\n"
    "/trade <user_id> <card_id...до 10> - предложить обмен до 10 карт\n"
    "/cancel_trade - отменить активный обмен\n\n"
    "🎲 Игры и ставки:\n"
    "/casino <сумма> - сыграть в казино\n"
    "/coin <орел|решка> <сумма> - подбросить монетку (макс. 300, рискованно!)\n"
    "/slots <сумма> - игровые автоматы 🎰\n"
    "/duel <ставка> [random|bestof3] - дуэль на монеты\n"
    "/bet - сделать ставку на матч (инлайн-меню)\n"
    "/my_bets - мои ставки\n"
    "\n"
    "⚔️ Рейтинговый режим:\n"
    "/rating_team - собрать состав для рейтингового режима\n"
    "/find_match - найти соперника (рейтинговый режим)\n"
    "/rating - мой рейтинг и текущий состав\n\n"
    "👤 Профиль, косметика и прочее:\n"
    "/profile - ваш профиль\n"
    "/profile_custom - кастомизация профиля\n"
    "/profile_bg <ключ> - выбрать фон профиля\n"
    "/profile_frame <ключ> - выбрать рамку профиля\n"
    "/profile_badge <ключ> - выбрать значок профиля\n"
    "/profile_showcase <id id id> - витрина до 3 карт\n"
    "/cosmetic_shop - магазин косметики (обновление раз в 2 часа)\n"
    "/buy_cosmetic <ID> - купить косметику из магазина\n"
    "/my_cosmetics - моя открытая косметика\n"
    "/titles - титулы профиля\n"
    "/quests - ежедневные задания\n"
    "/pity - гарант редкости\n"
    "/injuries - лазарет\n"
    "/notifications - настройки уведомлений\n"
    "/report <текст> - отправить баг/проблему администратору\n"
    "/id [@юзер] - ваш ID или ID игрока по юзернейму\n"
    "/leaderboard - таблица лидеров\n"
    "/keyboard - включить удобную клавиатуру\n"
    "/hide - скрыть клавиатуру\n\n"
    "🏰 Кланы:\n"
    "/create_clan <название> - создать клан (1000 монет)\n"
    "/join_clan <ID> - вступить в клан\n"
    "/leave_clan - покинуть клан\n"
    "/clan_deposit <сумма> - пополнить казну клана\n"
    "/clan_info [ID] - информация о клане\n"
    "/clan_members - участники и вклады (создатель)\n"
    "/clan_kick <user_id> - исключить участника (создатель)\n"
    "/kick <user_id> - короткая команда исключения из клана\n"
    "/clan_type <open|closed> - тип клана (создатель)\n"
    "/clan_invite <user_id> - пригласить в закрытый клан\n"
    "/clan_upgrade - прокачать клан-бафф из казны (создатель)\n"
    "/clans - рейтинг кланов\n\n"
    "⏳ Карточку можно получать каждые 6 часов!"
)


ADMIN_ONLY_COMMANDS_TEXT = (
    "🎴 Карточки и редкости:\n"
    "/admin_addcard - добавить карточку\n"
    "/admin_listcards - список всех карточек\n"
    "/admin_editcard <card_id> - изменить карточку\n"
    "/admin_deletecard <card_id> - удалить карточку\n"
    "/admin_addrarity - добавить редкость\n"
    "/admin_editrarity - изменить редкость\n"
    "/admin_listrarities - список редкостей и шансов\n\n"
    "👥 Игроки и модерация:\n"
    "/ban <user_id> - заблокировать пользователя\n"
    "/unban <user_id> - разблокировать пользователя\n"
    "/add_moderator <user_id> - добавить модератора\n"
    "/remove_moderator <user_id> - удалить модератора\n"
    "/admin_resettimer <user_id> - сбросить таймер\n"
    "/admin_broadcast <message> - сделать рассылку\n\n"
    "💰 Экономика и выдача:\n"
    "/admin_givecard <user_id> <card_id> - выдать карточку\n"
    "/admin_takecard <user_id> <card_id> [кол-во] - забрать карточку у игрока\n"
    "/admin_viewcards <user_id> - посмотреть коллекцию игрока\n"
    "/admin_givecoins <user_id> <amount> - выдать монеты\n"
    "/admin_removecoins <user_id> <amount> - забрать монеты\n"
    "/admin_unlist <ID объявления> - снять любой лот с маркета\n\n"
    "🏪 Магазин:\n"
    "/admin_addshopitem - добавить товар в магазин\n"
    "/admin_listshop - список товаров\n\n"
    "🎉 События и розыгрыши:\n"
    "/giveaway - создать розыгрыш в канале (призы, победители, условия)\n"
    "/giveaways - активные розыгрыши\n"
    "/create_promo - создать промокод\n"
    "/events - события и посты в канал\n\n"
    "⚔️ Рейтинг и матчи:\n"
    "/start_season - начать новый рейтинговый сезон\n"
    "/end_season - завершить сезон и выдать призы\n"
    "/create_match <команда1> <команда2> <часы> - создать матч (приём ставок N часов)\n"
    "/finish_match <match_id> <счёт> - завершить матч (например 3:1)\n"
    "/view_matches - список матчей для ставок\n\n"
    "⚙️ Система:\n"
    "/history [user_id] - история игрока\n"
    "/security - логи безопасности\n"
    "/reply_report <ID> <текст> - ответить на репорт игрока\n"
    "/update - обновить бота (токен + файл bot.py, авто-перезапуск)"
)

# ПОЛНЫЙ список команд, доступных модераторам (все команды с проверкой has_admin_access).
# Раньше здесь не было /create_match и /finish_match, хотя они модераторам доступны.
MODERATOR_ONLY_COMMANDS_TEXT = (
    "🎴 Карточки:\n"
    "/admin_addcard - добавить карточку\n"
    "/admin_listcards - список всех карточек\n"
    "/admin_editcard <card_id> - изменить карточку\n"
    "/admin_deletecard <card_id> - удалить карточку\n\n"
    "🏪 Магазин:\n"
    "/admin_addshopitem - добавить товар в магазин\n"
    "/admin_listshop - список товаров\n\n"
    "🏒 Матчи и ставки:\n"
    "/create_match <команда1> <команда2> <часы> - создать матч (приём ставок N часов)\n"
    "/finish_match <match_id> <счёт> - завершить матч (например 3:1)\n"
    "/view_matches - список матчей для ставок"
)

# Выдача карточки (с баффами и seen_cards)
async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
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
            {"name": "Мифическая", "emoji": "🧠", "droppable": True},
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
    await finalize_referral_after_first_card(user, context)

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
    # Анимации оставлены только для эпической, мифической и легендарной редкости.
    RARITY_ANIMATIONS = {
        "Эпическая": [
            "🃏 Тянем карточку из хоккейного пака...",
            "💎 Лёд под карточкой сияет...",
            "💎 ✨ ЭПИЧЕСКАЯ карточка! Открываем!",
        ],
        "Мифическая": [
            "🃏 Тянем карточку из хоккейного пака...",
            "🌌 Арена гаснет, прожектор падает на карту...",
            "🔮 МИФИЧЕСКАЯ карточка выходит на лёд!",
        ],
        "Легендарная": [
            "🃏 Тянем карточку из хоккейного пака...",
            "🏆 Кубок сияет над льдом...",
            "🔥 Трибуны ревут...",
            "✨ ЛЕГЕНДАРНАЯ карточка! Открываем!",
        ],
    }
    frames = RARITY_ANIMATIONS.get(card["rarity"])
    if frames:
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


async def _reply_long_html(message, text: str, limit: int = 3900) -> None:
    """Отправляет длинный HTML-текст частями, чтобы Telegram не ломался на коллекциях с большим числом карт."""
    text = str(text or "")
    if len(text) <= limit:
        await message.reply_text(text, parse_mode="HTML")
        return
    chunk = ""
    for line in text.split("\n"):
        add = line + "\n"
        if len(chunk) + len(add) > limit and chunk.strip():
            await message.reply_text(chunk.rstrip(), parse_mode="HTML")
            chunk = ""
        # если одна строка вдруг огромная — режем её безопасными кусками
        while len(add) > limit:
            await message.reply_text(add[:limit], parse_mode="HTML")
            add = add[limit:]
        chunk += add
    if chunk.strip():
        await message.reply_text(chunk.rstrip(), parse_mode="HTML")

# Показ коллекции
async def show_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    message = await show_collection_with_ids(user.id)
    await _reply_long_html(update.message, message)

# Информация о карточке
async def card_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
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
    # Сила с учётом прокачки (/upgrade_card)
    card_map = {c["id"]: c for c in cards}
    lvl = int(user_data.get("card_upgrades", {}).get(str(card_id), 0))
    caption += f"💪 <b>Сила</b>: {get_player_card_power(user.id, card_id, card_map)}"
    if lvl > 0:
        caption += f" (⭐ прокачана до ур. {lvl}, потолок {get_card_rating_cap(card)})"
    caption += "\n"
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        photo = get_framed_card_photo(card) or open(image_path, "rb")
        await update.message.reply_photo(photo=photo, caption=caption, parse_mode="HTML")
    else:
        logger.warning(f"Изображение карточки не найдено: {image_path}")
        if 'forced_pity' in locals() and forced_pity:
            caption += f"\n🎯 Сработал гарант: {forced_pity}"
        inc_stat(user.id,'get_card',1)
        if card.get('rarity') in ('Легендарная','Мифическая','Эксклюзивная'): inc_stat(user.id,'legendary_drops',1)
        log_action(user.id,'get_card',card.get('name',''))
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
        await update.message.reply_text(subscription_required_text())
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

    # 🔥 Стрик ежедневных наград: забрал вовремя (не пропустил больше суток
    # после отката) — серия растёт. Каждый день серии даёт +10% к награде (до +100%).
    daily_streak = user_data.get("daily_streak", 0)
    if last_daily > 0 and elapsed < DAILY_COOLDOWN_SECONDS * 2:
        daily_streak += 1
    else:
        daily_streak = 1
    user_data["daily_streak"] = daily_streak
    streak_bonus = min((daily_streak - 1) * 0.10, 1.0)

    # Начисляем фиксированные монеты (бафф-карта + клан-бафф складываются, стрик — сверху)
    total_multiplier = get_total_coin_multiplier(user.id)
    daily_amount = int(DAILY_COINS_AMOUNT * total_multiplier * (1.0 + streak_bonus))
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
    if daily_streak > 1:
        message += f"🔥 Серия: {daily_streak} дн. подряд (+{round(streak_bonus * 100)}% к награде, максимум +100%)\n"
    else:
        message += "🔥 Забирай награду каждый день — серия даёт до +100% монет!\n"

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
    balance = get_coins(user.id)
    header = (
        "🏪 <b>МАГАЗИН Хоккейные карточки</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ваш баланс: <b>{balance}</b> монет\n\n"
    )
    if not active_items:
        await update.message.reply_text(
            header + "📭 Витрина пока пуста — загляните позже, товары появляются регулярно!",
            parse_mode="HTML",
        )
        return
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    blocks = []
    for item in active_items:
        can_afford = balance >= item["price"]
        status = "✅ доступно" if can_afford else f"🔒 не хватает {item['price'] - balance}"
        icon = "🎁" if item.get("type") == "pack" else ("⏱" if item.get("type") == "reset" else "🛍")
        lines = [f"{icon} <b>{html.escape(str(item['name']))}</b>  •  {status}"]
        lines.append(f"┃ 💵 Цена: <b>{item['price']}</b> монет")
        if item.get("type") == "reset":
            lines.append("┃ 📝 Мгновенный сброс таймера — /get_card сразу после покупки")
        elif item.get("type") == "pack":
            pack_cards = item.get("cards", [])
            rarity_counts = {}
            for cid in pack_cards:
                card = card_map.get(cid)
                if card:
                    rarity_counts[card["rarity"]] = rarity_counts.get(card["rarity"], 0) + 1
            lines.append(f"┃ 🃏 Набор: одна случайная карта из {len(pack_cards)}")
            if rarity_counts:
                inside = ", ".join(f"{get_rarity_emoji(r)} {html.escape(r)} ×{cnt}" for r, cnt in rarity_counts.items())
                lines.append(f"┃ 🎲 Возможные редкости: {inside}")
        if item.get("expire_time", 0) > 0:
            time_left = item["expire_time"] - current_time
            hours = int(time_left // 3600)
            minutes = int((time_left % 3600) // 60)
            lines.append(f"┃ ⏳ Товар исчезнет через: {hours}ч {minutes}мин")
        lines.append(f"┗ 🛒 Купить: <code>/buy {item['id']}</code>")
        blocks.append("\n".join(lines))
    footer = "\n\n━━━━━━━━━━━━━━━━━━━━\nℹ️ Нажмите на команду <code>/buy ID</code> у товара, чтобы скопировать её"
    message = header + "\n\n".join(blocks) + footer
    # Длинную витрину отправляем частями по целым блокам товаров (лимит Telegram)
    if len(message) > 4000:
        chunk = header
        for block in blocks:
            if len(chunk) + len(block) + 2 > 3900:
                await update.message.reply_text(chunk.rstrip(), parse_mode="HTML")
                chunk = ""
            chunk += block + "\n\n"
        if chunk.strip():
            await update.message.reply_text(chunk.rstrip() + footer, parse_mode="HTML")
    else:
        await update.message.reply_text(message, parse_mode="HTML")

# Покупка
async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
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
        cards = load_data(CARDS_FILE, [])
        card = next((c for c in cards if c["id"] == card_id), None)
        mutation_instance = None
        if card and random.random() < _get_effective_mutation_drop_chance():
            mutation_instance = add_mutated_card(user.id, card_id, _roll_mutation_key())
        else:
            users[str(user.id)] = user_data
            save_data(USERS_FILE, users)
            add_one_card(user.id, card_id)
        if card:
            card_name = html.escape(card["name"])
            card_rarity = html.escape(card["rarity"])
            emoji = get_rarity_emoji(card["rarity"])
        else:
            card_name = f"Карточка ID {card_id}"
            card_rarity = "Неизвестная"
            emoji = "❓"
        if mutation_instance:
            meta = _get_mutation_meta(mutation_instance.get("mutation")) or {}
            mutation_label = html.escape(meta.get("label", "Мутация"))
            mutation_emoji = meta.get("emoji", "🧬")
            mutation_bonus = int(meta.get("power_bonus", 0) or 0)
            pack_text = (
                f"✅ Вы успешно приобрели набор карточек!\n"
                f"🎁 Полученная карточка:\n"
                f"<b>{emoji} {card_rarity}</b>: {card_name}\n"
                f"{mutation_emoji} <b>Мутация: {mutation_label}</b> (+{mutation_bonus} силы)\n"
                f"🆔 <b>M-ID:</b> <code>{html.escape(str(mutation_instance.get('instance_id')))}</code>\n\n"
                f"💰 Потрачено: {item['price']} монет\n"
                f"💰 Остаток: {new_balance} монет\n\n"
                f"Мутированная карта уже добавлена отдельным экземпляром.\n"
                f"Посмотреть её можно в /my_cards"
            )
        else:
            users_after = load_data(USERS_FILE, {})
            user_data_after = users_after.get(str(user.id), {})
            card_count = user_data_after.get("cards", []).count(card_id)
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

# ===================== АКТИВНОСТЬ ЧАТА ===========================

def _get_chat_activity(user_id: int) -> dict:
    data = load_data(CHAT_ACTIVITY_FILE, {})
    return data.get(str(user_id), {})

def _save_chat_activity(user_id: int, entry: dict):
    data = load_data(CHAT_ACTIVITY_FILE, {})
    data[str(user_id)] = entry
    save_data(CHAT_ACTIVITY_FILE, data)


async def handle_chat_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Бонусы за сообщения в бонусном чате."""
    msg = update.message
    if not msg or not msg.from_user:
        return
    if msg.chat_id != BONUS_CHAT_ID:
        return
    user = msg.from_user
    if user.is_bot:
        return

    now   = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    act   = _get_chat_activity(user.id)

    last_reward  = act.get("last_reward", 0)
    last_day     = act.get("day", "")
    daily_count  = act.get("daily_count", 0) if last_day == today else 0

    COOLDOWN  = 8 * 60   # 8 минут между наградами
    DAILY_CAP = 6        # макс награждений в день

    # Не дошла до награды ещё
    if now - last_reward < COOLDOWN or daily_count >= DAILY_CAP:
        return

    coins     = random.randint(10, 20)
    new_count = daily_count + 1

    act["last_reward"]    = now
    act["day"]            = today
    act["daily_count"]    = new_count
    act["total_messages"] = act.get("total_messages", 0) + 1
    _save_chat_activity(user.id, act)

    update_coins(user.id, coins)
    balance = get_coins(user.id)

    lines = [f"✅ +{coins} монет за активность в чате!"]

    # Милстоун 3 сообщения/день
    if new_count == 3:
        bonus = 35
        update_coins(user.id, bonus)
        balance = get_coins(user.id)
        lines.append(f"✨ Бонус за 3 сообщения: +{bonus} монет!")

    # Милстоун 6 сообщений/день (максимальный дневной)
    if new_count == DAILY_CAP:
        bonus2 = 70
        update_coins(user.id, bonus2)
        balance = get_coins(user.id)
        lines.append(f"🔥 Максимум за день! +{bonus2} монет бонус!")
        # 7% шанс на случайную Common-карточку
        if random.random() < 0.07:
            all_cards = load_data(CARDS_FILE, [])
            common_cards = [c for c in all_cards if str(c.get("rarity", "")).lower() == "common"]
            if common_cards:
                prize_card = random.choice(common_cards)
                users_data = load_data(USERS_FILE, {})
                udata = users_data.get(str(user.id), {})
                if "cards" not in udata:
                    udata["cards"] = []
                udata["cards"].append(prize_card["id"])
                users_data[str(user.id)] = udata
                save_data(USERS_FILE, users_data)
                lines.append(f"🏆 Сюрприз! Получена карточка: {prize_card.get('name', '?')} (Common)!")

    lines.append(f"💰 Баланс: {balance} монет")
    if new_count < DAILY_CAP:
        lines.append(f"💬 Сегодня: {new_count}/{DAILY_CAP} награждений")
    else:
        lines.append("🌟 Лимит дня исчерпан! Заходи завтра снова ♥")

    try:
        _text = "\n".join(lines)
        await context.bot.send_message(user.id, _text)
    except Exception:
        pass  # пользователь не запустил бота или заблокировал

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
            f"Подпишитесь здесь:\n{CHANNEL_LINK}\n{EVENTS_CHANNEL_LINK}\n"
            "После подписки отправьте /start"
        )
        await asyncio.sleep(10)
        await context.bot.delete_message(chat_id=message.chat_id, message_id=warn_msg.message_id)

# ============================ КЛАВИАТУРА ============================
KEYBOARD_LAYOUT = [
    ["🎴 Карта", "🗂 Коллекция"],
    ["🎁 Daily", "💰 Баланс", "👤 Профиль"],
    ["⚔️ Рейтинг", "🏆 Топ", "🏥 Лазарет"],
    ["🏪 Маркет", "🛒 Магазин", "🃏 Бафф"],
    ["🏰 Клан", "📊 Ставки"],
    ["🙈 Скрыть"],
]
KEYBOARD_ALIASES = {
    "🎴 Карта": "🎴 Получить карту",
    "🗂 Коллекция": "📚 Коллекция",
    "🎁 Daily": "🎁 Награда",
    "🏥 Лазарет": "🏥 Лазарет",
    "📊 Ставки": "📊 Мои ставки",
    "🙈 Скрыть": "❌ Скрыть клавиатуру",
}
ALL_KEYBOARD_BUTTONS = [btn for row in KEYBOARD_LAYOUT for btn in row] + list(KEYBOARD_ALIASES.values())

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
        await update.message.reply_text(subscription_required_text())
        return
    chat = update.effective_chat
    text = "✨ Новая клавиатура включена!\nОсновные разделы теперь под рукой. Скрыть: /hide"
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
    text = "🙈 Клавиатура скрыта. Вернуть: /keyboard"
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
        "🏥 Лазарет": injuries_cmd,
    }
    text = update.message.text.strip()
    text = KEYBOARD_ALIASES.get(text, text)
    handler = mapping.get(text)
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
    # Защита: колбэк зарегистрирован глобально, поэтому проверяем права явно.
    if not has_admin_access(query.from_user.id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return ConversationHandler.END
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
    await post_to_channel(context, f"🛒 <b>Новинка в магазине!</b>\n\n<b>{html.escape(new_item['name'])}</b>\n💰 Цена: {_fmt_coins(new_item['price'])} монет\n📦 Тип: {'Сброс таймера' if new_item['type'] == 'reset' else 'Набор карточек'}\n\nОткрыть магазин: /shop", notification_category="market")
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
        await update.message.reply_text(subscription_required_text())
        return ConversationHandler.END
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    normal_available = get_available_card_ids(user.id)
    mutated_available = list(user_data.get("mutated_cards", []))
    if len(normal_available) < 3 and len(mutated_available) < 3:
        await update.message.reply_text("❌ Для крафта нужно минимум 3 обычные карты или 3 мутированные карты.")
        return ConversationHandler.END
    message = await show_collection_with_ids(user.id)
    message += (
        "\n\n🛠 <b>Система крафта</b>\n"
        "<b>Обычный крафт:</b> 3 обычные карты одной редкости: <code>5 12 8</code>\n"
        "• Обычная → Редкая\n"
        "• Редкая → Эпическая\n"
        "• шанс успеха 40%, при неудаче обычные карты сгорают\n\n"
        "<b>Мутированный крафт:</b> 3 мутированные карты одной редкости: <code>m123 m456 m789</code>\n"
        "• Обычная → Редкая\n"
        "• Редкая → Эпическая\n"
        "• мутированный крафт не сжигает карты впустую: результат будет всегда\n"
        "• шанс 0.1%, что новая карта выйдет без мутации\n\n"
        "⚠️ Нельзя смешивать обычные ID и M-ID в одном крафте."
    )
    await _reply_long_html(update.message, message)
    context.user_data.clear()
    return CRAFT_SELECT_CARDS


def _parse_craft_token(token: str):
    token = token.strip()
    if not token:
        raise ValueError("empty")
    if token.lower().startswith("m"):
        return {"type": "mutated", "instance_id": _normalize_mutation_token(token) if '_normalize_mutation_token' in globals() else token[1:]}
    return {"type": "normal", "card_id": int(token)}

async def process_craft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    raw_tokens = update.message.text.replace(",", " ").replace(";", " ").split()
    try:
        items = [_parse_craft_token(t) for t in raw_tokens]
        if len(items) != 3:
            raise ValueError
    except Exception:
        await update.message.reply_text("❌ Неверный формат! Введите ровно 3 карты: обычные ID <code>1 2 3</code> или мутированные <code>mID mID mID</code>.", parse_mode="HTML")
        return CRAFT_SELECT_CARDS
    kinds = {i["type"] for i in items}
    if len(kinds) != 1:
        await update.message.reply_text("❌ Нельзя смешивать обычные и мутированные карты в одном крафте.")
        return CRAFT_SELECT_CARDS
    cards_data = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in cards_data}

    # ================= Обычный крафт =================
    if items[0]["type"] == "normal":
        card_ids = [int(i["card_id"]) for i in items]
        available = get_available_card_ids(user.id)
        available_temp = list(available)
        missing_cards = []
        for card_id in card_ids:
            if card_id in available_temp:
                available_temp.remove(card_id)
            else:
                missing_cards.append(card_id)
        if missing_cards:
            await update.message.reply_text(f"❌ Карточки недоступны: {', '.join(map(str, missing_cards))}")
            return CRAFT_SELECT_CARDS
        selected_cards = [card_map.get(cid) for cid in card_ids]
        if any(c is None for c in selected_cards):
            await update.message.reply_text("❌ Одна или несколько карточек больше не существуют в базе. Карты не были списаны.")
            return CRAFT_SELECT_CARDS
        rarities = {card["rarity"] for card in selected_cards}
        if len(rarities) != 1:
            await update.message.reply_text("❌ Все карточки должны быть одинаковой редкости!")
            return CRAFT_SELECT_CARDS
        rarity = next(iter(rarities))
        if rarity not in ["Обычная", "Редкая"]:
            await update.message.reply_text("❌ Обычный крафт доступен только для Обычной и Редкой редкости!")
            return CRAFT_SELECT_CARDS
        new_rarity = "Редкая" if rarity == "Обычная" else "Эпическая"
        # Списываем только после всех проверок.
        for cid in card_ids:
            if 'remove_one_normal_card' in globals():
                ok = remove_one_normal_card(user.id, cid)
            else:
                ok = remove_one_card(user.id, cid)
            if not ok:
                # rollback уже списанных обычных карт
                for old in card_ids[:card_ids.index(cid)]:
                    add_one_card(user.id, old)
                await update.message.reply_text("❌ Не удалось списать карты. Крафт отменён, карты возвращены.")
                return ConversationHandler.END
        await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'craft_attempts', 1)) if '_notify_quest_rewards' in globals() else None
        success = random.random() < 0.4
        if success:
            new_cards = [c for c in cards_data if c.get("rarity") == new_rarity]
            if not new_cards:
                for cid in card_ids:
                    add_one_card(user.id, cid)
                await update.message.reply_text("❌ Нет карт нужной редкости. Крафт отменён, карты возвращены.")
                return ConversationHandler.END
            new_card = random.choice(new_cards)
            add_one_card(user.id, new_card["id"])
            inc_stat(user.id, 'craft_success', 1)
            log_action(user.id, 'craft_success', f"normal->{new_card['id']}") if 'log_action' in globals() else None
            await update.message.reply_text(f"🎉 Крафт успешен!\nВы получили: <b>{html.escape(new_card['name'])}</b> ({new_rarity})", parse_mode="HTML")
        else:
            log_action(user.id, 'craft_fail', 'normal') if 'log_action' in globals() else None
            await update.message.reply_text("❌ Крафт не удался!\nВсе 3 обычные карты были потеряны.")
        return ConversationHandler.END

    # ================= Мутированный крафт =================
    instance_ids = [str(i["instance_id"]) for i in items]
    if len(set(instance_ids)) != 3:
        await update.message.reply_text("❌ Нужно указать 3 разные мутированные карты. Один и тот же M-ID нельзя использовать дважды.")
        return CRAFT_SELECT_CARDS
    instances = []
    for mid in instance_ids:
        inst = _get_mutation_instance(user.id, mid)
        if not inst:
            await update.message.reply_text(f"❌ Мутированная карта M-ID <code>{html.escape(mid)}</code> не найдена или недоступна.", parse_mode="HTML")
            return CRAFT_SELECT_CARDS
        instances.append(inst)
    base_cards = [card_map.get(int(inst.get("card_id", -1))) for inst in instances]
    if any(c is None for c in base_cards):
        await update.message.reply_text("❌ Базовая карта одной из мутаций не найдена. Крафт отменён.")
        return CRAFT_SELECT_CARDS
    rarities = {c.get("rarity") for c in base_cards}
    if len(rarities) != 1:
        await update.message.reply_text("❌ Все мутированные карты должны быть одной редкости!")
        return CRAFT_SELECT_CARDS
    rarity = next(iter(rarities))
    if rarity not in ["Обычная", "Редкая"]:
        await update.message.reply_text("❌ Мутированный крафт доступен только для мутированных карт Обычной и Редкой редкости!")
        return CRAFT_SELECT_CARDS
    new_rarity = "Редкая" if rarity == "Обычная" else "Эпическая"
    # Списываем после проверок, с rollback.
    removed_instances = []
    for mid in instance_ids:
        removed, mutated_cards = remove_mutated_card_instance(user.id, mid)
        if not removed:
            for old in removed_instances:
                add_mutated_card_instance(user.id, old)
            await update.message.reply_text("❌ Не удалось списать мутированные карты. Крафт отменён, карты возвращены.")
            return ConversationHandler.END
        _save_user_mutated_cards(user.id, mutated_cards)
        removed_instances.append(removed)
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'craft_attempts', 1)) if '_notify_quest_rewards' in globals() else None
    new_cards = [c for c in cards_data if c.get("rarity") == new_rarity]
    if not new_cards:
        for old in removed_instances:
            add_mutated_card_instance(user.id, old)
        await update.message.reply_text("❌ Нет карт нужной редкости. Крафт отменён, мутированные карты возвращены.")
        return ConversationHandler.END
    new_card = random.choice(new_cards)
    no_mutation = random.random() < 0.001
    mutation_instance = None
    if no_mutation:
        add_one_card(user.id, new_card["id"])
        result_text = (
            f"🎉 <b>Мутированный крафт завершён!</b>\n"
            f"Редкий сбой мутации 0.1%: новая карта вышла без мутации.\n\n"
            f"Получено: <b>{html.escape(new_card['name'])}</b> ({new_rarity})"
        )
    else:
        mutation_instance = add_mutated_card(user.id, new_card["id"], _roll_mutation_key())
        meta = _get_mutation_meta(mutation_instance.get("mutation")) or {}
        result_text = (
            f"🎉 <b>Мутированный крафт успешен!</b>\n\n"
            f"Получено: <b>{html.escape(new_card['name'])}</b> ({new_rarity})\n"
            f"{meta.get('emoji','🧬')} Мутация: <b>{html.escape(meta.get('label','Мутация'))}</b> (+{meta.get('power_bonus',0)} силы)\n"
            f"🆔 M-ID: <code>{html.escape(str(mutation_instance.get('instance_id')))}</code>"
        )
    inc_stat(user.id, 'craft_success', 1)
    log_action(user.id, 'mutated_craft_success', f"{new_card['id']} mutation={not no_mutation}") if 'log_action' in globals() else None
    try:
        photo = get_framed_card_photo(new_card, mutation_instance) if mutation_instance else get_framed_card_photo(new_card)
        if photo:
            await update.message.reply_photo(photo=photo, caption=result_text, parse_mode="HTML")
        else:
            await update.message.reply_text(result_text, parse_mode="HTML")
    except Exception:
        await update.message.reply_text(result_text, parse_mode="HTML")
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
        await update.message.reply_text(subscription_required_text())
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

    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'gamble_count', 1))
    log_action(user.id, 'casino', str(bet))
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
# ============================ МОНЕТКА: НАСТРОЙКИ ============================
# Раньше было 50/50 при выплате x2 + баффы -> матожидание в ПЛЮС игроку,
# люди стабильно фармили тысячи монет. Теперь:
#  - базовый шанс победы 35% (было 50%)
#  - каждая победа в серии режет шанс ещё на 7% (было 5%)
#  - ставка ограничена COINFLIP_MAX_BET
# Итог: монетка теперь сливает монеты из экономики, а не печатает их.
COINFLIP_BASE_WIN_CHANCE = 0.35
COINFLIP_MAX_BET = 300

async def coin_flip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "ℹ️ Использование: /coin <орел|решка> <сумма>\n\n"
            f"⚠️ Максимальная ставка: {COINFLIP_MAX_BET} монет.\n"
            "🪙 Монетка хитрая: победить непросто, а серия побед снижает шанс ещё сильнее."
        )
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
    if bet > COINFLIP_MAX_BET:
        await update.message.reply_text(f"❌ Максимальная ставка в монетке: {COINFLIP_MAX_BET} монет.")
        return
    balance = get_coins(user.id)
    if balance < bet:
        await update.message.reply_text("❌ Недостаточно монет!")
        return
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'gamble_count', 1))
    log_action(user.id, 'coin', str(bet))
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
    win_chance = max(0.05, COINFLIP_BASE_WIN_CHANCE - streak * 0.07)
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
        await update.message.reply_text(subscription_required_text())
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
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'gamble_count', 1))
    log_action(user.id, 'slots', str(bet))
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
        await asyncio.sleep(2.2)
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
        await update.message.reply_text(subscription_required_text())
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
        await update.message.reply_text(subscription_required_text())
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
        await update.message.reply_text("❌ Для баффа можно выбрать только карту редкости Легендарная, Мифическая или Эксклюзивная!")
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
        await update.message.reply_text(subscription_required_text())
        return
    buff = get_active_buff(user.id)
    if not buff:
        await update.message.reply_text("❌ У вас нет активной карты баффа. Выберите с помощью /set_buff")
        return
    card_id = buff["card_id"]
    current_level = int(buff.get("level", 1))
    if current_level >= MAX_BUFF_LEVEL:
        await update.message.reply_text(f"✅ Достигнут максимальный уровень баффа ({MAX_BUFF_LEVEL}).")
        return
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
        current_level = int(buff.get("level", 1))
        if current_level >= MAX_BUFF_LEVEL:
            await query.edit_message_text(f"✅ Достигнут максимальный уровень баффа ({MAX_BUFF_LEVEL}).")
            return
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
        await update.message.reply_text(subscription_required_text())
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
    # max_uses = 0 / None означает без общего лимита: каждый пользователь всё равно может активировать код только 1 раз.
    max_uses = promo.get("max_uses", 0)
    if max_uses and promo.get("used", 0) >= max_uses:
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


# ============================ НОВЫЕ СИСТЕМЫ: ТИТУЛЫ / КВЕСТЫ / ГАРАНТ / ЛОГИ ============================
def _msk_day_key(ts=None):
    ts = time.time() if ts is None else ts
    return datetime.utcfromtimestamp(ts + MSK_OFFSET_SECONDS).strftime("%Y-%m-%d")

def _append_limited_json(file_name, item, limit=2000):
    data = load_data(file_name, [])
    if not isinstance(data, list): data = []
    data.append(item)
    save_data(file_name, data[-limit:])

def log_action(user_id:int, action:str, details:str=""):
    _append_limited_json(ACTION_HISTORY_FILE, {"ts":time.time(),"user_id":int(user_id),"action":action,"details":str(details)[:350]})

def log_security(event:str, user_id=None, details:str="", severity:str="info"):
    _append_limited_json(SECURITY_LOG_FILE, {"ts":time.time(),"event":event,"user_id":user_id,"details":str(details)[:600],"severity":severity})

def _get_user_stats(user_id:int):
    users=load_data(USERS_FILE,{})
    u=users.setdefault(str(user_id),{})
    st=u.setdefault("stats",{})
    return users,u,st

def inc_stat(user_id:int, key:str, amount:int=1):
    users,u,st = _get_user_stats(user_id)
    st[key] = int(st.get(key,0)) + int(amount)
    u["stats"] = st
    users[str(user_id)] = u
    save_data(USERS_FILE, users)
    return _quest_progress(user_id, key, amount)

async def _notify_quest_rewards(update_or_context, user_id:int, rewards):
    if not rewards:
        return
    total, names = rewards
    if not total:
        return
    text = "🎉 <b>Ежедневное задание выполнено!</b>" + chr(10) + chr(10).join(f"✅ {html.escape(n)}" for n in names) + chr(10) + chr(10) + f"💰 Начислено: <b>{total}</b> монет"
    try:
        msg = getattr(update_or_context, 'message', None)
        if msg:
            await msg.reply_text(text, parse_mode='HTML')
            return
    except Exception:
        pass
    try:
        bot = update_or_context.bot if hasattr(update_or_context, 'bot') else None
        if bot:
            await bot.send_message(user_id, text, parse_mode='HTML')
    except Exception:
        pass

TITLE_DEFS = [
    {"key":"rookie","name":"🆕 Новичок","need":"доступен сразу","check":lambda u,s,uid: True},
    {"key":"collector","name":"📚 Коллекционер","need":"иметь 25 обычных карт","check":lambda u,s,uid: len(u.get('cards',[]))>=25},
    {"key":"archive","name":"🧺 Архивариус","need":"иметь 100 обычных карт","check":lambda u,s,uid: len(u.get('cards',[]))>=100},
    {"key":"mutant","name":"🧬 Мутант","need":"получить 1 мутированную карту","check":lambda u,s,uid: len(u.get('mutated_cards',[]))>=1},
    {"key":"mutlord","name":"👑 Повелитель мутаций","need":"иметь 10 мутированных карт","check":lambda u,s,uid: len(u.get('mutated_cards',[]))>=10},
    {"key":"rich","name":"💰 Богач","need":"иметь 10 000 монет на балансе","check":lambda u,s,uid: get_coins(uid)>=10000},
    {"key":"duelist","name":"⚔️ Дуэлянт","need":"выиграть 5 дуэлей","check":lambda u,s,uid: s.get('duel_wins',0)>=5},
    {"key":"duelking","name":"🏴‍☠️ Король дуэлей","need":"выиграть 25 дуэлей","check":lambda u,s,uid: s.get('duel_wins',0)>=25},
    {"key":"hockey","name":"🏒 Хоккеист","need":"сыграть 5 рейтинговых матчей","check":lambda u,s,uid: s.get('rating_matches',0)>=5},
    {"key":"champ","name":"🏆 Победитель","need":"выиграть 10 рейтинговых матчей","check":lambda u,s,uid: s.get('rating_wins',0)>=10},
    {"key":"crafter","name":"🛠 Крафтер","need":"сделать 5 успешных крафтов","check":lambda u,s,uid: s.get('craft_success',0)>=5},
    {"key":"mastercraft","name":"⚒ Мастер крафта","need":"сделать 25 успешных крафтов","check":lambda u,s,uid: s.get('craft_success',0)>=25},
    {"key":"market","name":"🏪 Рыночник","need":"продать 5 карт на маркете/личной продаже","check":lambda u,s,uid: s.get('market_sales',0)>=5},
    {"key":"worker","name":"💼 Работяга","need":"10 раз отправить карту работать","check":lambda u,s,uid: s.get('work_count',0)>=10},
    {"key":"lucky","name":"🍀 Везунчик","need":"выбить легендарную/эксклюзивную карту","check":lambda u,s,uid: s.get('legendary_drops',0)>=1},
    {"key":"old","name":"🦴 Олд","need":"забрать /daily 14 раз","check":lambda u,s,uid: s.get('daily_claims',0)>=14},
]

def unlocked_titles(user_id:int):
    users = load_data(USERS_FILE,{})
    u = users.get(str(user_id),{})
    st = u.get('stats',{})
    return [(t['key'], t['name']) for t in TITLE_DEFS if t['check'](u, st, user_id)]

def active_title(user_id:int):
    got = unlocked_titles(user_id)
    users = load_data(USERS_FILE,{})
    key = users.get(str(user_id),{}).get('active_title')
    d = dict(got)
    if key in d:
        return key, d[key]
    return got[-1] if got else ("rookie", "🆕 Новичок")


QUEST_POOL = [
    {"id":"get","name":"Получить любую карточку через /get_card","stat":"get_card","target":1,"reward":80},
    {"id":"get3","name":"Получить 3 карточки через /get_card","stat":"get_card","target":3,"reward":140},
    {"id":"daily","name":"Забрать ежедневную награду /daily","stat":"daily_claims","target":1,"reward":70},
    {"id":"work","name":"Отправить любую карту работать через /work","stat":"work_count","target":1,"reward":90},
    {"id":"work2","name":"Отправить карты работать 2 раза","stat":"work_count","target":2,"reward":150},
    {"id":"duel","name":"Сыграть любую дуэль /duel","stat":"duel_played","target":1,"reward":120},
    {"id":"duel2","name":"Сыграть 2 дуэли /duel","stat":"duel_played","target":2,"reward":190},
    {"id":"duel_win","name":"Выиграть дуэль","stat":"duel_wins","target":1,"reward":180},
    {"id":"rating","name":"Сыграть рейтинговый матч /find_match","stat":"rating_matches","target":1,"reward":130},
    {"id":"rating_win","name":"Выиграть рейтинговый матч","stat":"rating_wins","target":1,"reward":220},
    {"id":"market","name":"Сделать операцию на маркете/личной продаже","stat":"market_ops","target":1,"reward":110},
    {"id":"market2","name":"Сделать 2 операции на маркете","stat":"market_ops","target":2,"reward":180},
    {"id":"craft","name":"Сделать любой крафт через /craft","stat":"craft_attempts","target":1,"reward":120},
    {"id":"craft_success","name":"Сделать успешный крафт","stat":"craft_success","target":1,"reward":170},
    {"id":"casino","name":"Сыграть 2 раза в /casino, /coin или /slots","stat":"gamble_count","target":2,"reward":100},
    {"id":"casino4","name":"Сыграть 4 раза в мини-игры на монеты","stat":"gamble_count","target":4,"reward":170},
    {"id":"cosmetic","name":"Купить косметику профиля","stat":"buy_cosmetic","target":1,"reward":150},
    {"id":"profile_style","name":"Изменить стиль профиля","stat":"profile_customized","target":1,"reward":80},
]
def _daily_quest_set(user_id:int):
    data = load_data(QUESTS_FILE,{})
    day = _msk_day_key()  # сброс строго по московской дате, не раньше 00:00 МСК
    ud = data.get(str(user_id),{})
    if ud.get('day') != day:
        rng = random.Random(f"{day}:{user_id}")
        # разнообразие: 5 заданий в день, без дублей по id
        qs = rng.sample(QUEST_POOL, min(5, len(QUEST_POOL)))
        # запоминаем базовые значения статов на начало дня, чтобы прогресс шёл только за сегодняшние действия
        users = load_data(USERS_FILE,{})
        stats = users.get(str(user_id),{}).get('stats',{})
        ud = {"day":day,"quests":[{**q,"progress":0,"claimed":False,"base":int(stats.get(q.get('stat'),0))} for q in qs]}
        data[str(user_id)] = ud
        save_data(QUESTS_FILE,data)
    return ud

def _title_progress_line(user_id:int, t:dict):
    users = load_data(USERS_FILE,{})
    u = users.get(str(user_id),{})
    st = u.get('stats',{})
    unlocked = t['check'](u, st, user_id)
    mark = '✅' if unlocked else '🔒'
    return f"{mark} <code>{t['key']}</code> — {html.escape(t['name'])}" + chr(10) + f"   Нужно: {html.escape(t['need'])}"

def _quest_progress(user_id:int, stat:str, amount:int=1):
    data = load_data(QUESTS_FILE, {})
    ud = _daily_quest_set(user_id)
    changed = False
    reward_total = 0
    completed_names = []
    for q in ud.get('quests', []):
        if q.get('stat') == stat and not q.get('claimed'):
            before = int(q.get('progress', 0))
            target = int(q.get('target', 1))
            users_now = load_data(USERS_FILE,{})
            stat_now = int(users_now.get(str(user_id),{}).get('stats',{}).get(stat, 0))
            base = int(q.get('base', stat_now - before - int(amount)))
            q['base'] = base
            q['progress'] = min(target, max(before + int(amount), stat_now - base))
            changed = True
            if before < target and q['progress'] >= target:
                q['claimed'] = True
                reward_total += int(q.get('reward', 0))
                completed_names.append(q.get('name', 'задание'))
    if changed:
        data[str(user_id)] = ud
        save_data(QUESTS_FILE, data)
    if reward_total > 0:
        update_coins(user_id, reward_total)
        log_action(user_id, 'quest_auto_claim', f"+{reward_total}: {', '.join(completed_names)}")
    return reward_total, completed_names


async def quests_cmd(update, context):
    uid = update.effective_user.id
    ud = _daily_quest_set(uid)
    lines = ["📋 <b>Ежедневные задания</b>", "Сброс каждый день в 00:00 МСК.", "Награда выдаётся автоматически сразу после выполнения.\n"]
    for q in ud['quests']:
        done = int(q.get('progress', 0)) >= int(q['target'])
        mark = '✅' if done else '⏳'
        extra = ' — награда получена' if q.get('claimed') else ''
        lines.append(f"{mark} {html.escape(q['name'])}: {q.get('progress',0)}/{q['target']} • {q['reward']} монет{extra}")
    await update.message.reply_text('\n'.join(lines), parse_mode='HTML')

async def claim_quests_cmd(update, context):
    uid=update.effective_user.id; data=load_data(QUESTS_FILE,{}) ; ud=_daily_quest_set(uid); total=0
    for q in ud['quests']:
        if not q.get('claimed') and int(q.get('progress',0))>=int(q['target']): q['claimed']=True; total+=int(q['reward'])
    data[str(uid)]=ud; save_data(QUESTS_FILE,data)
    if total: update_coins(uid,total); log_action(uid,'quest_claim',f'+{total}'); await update.message.reply_text(f'✅ Получено за задания: +{total} монет')
    else: await update.message.reply_text('📭 Нет выполненных заданий.')

async def titles_cmd(update, context):
    uid = update.effective_user.id
    got = dict(unlocked_titles(uid))
    active = active_title(uid)[0]
    if context.args:
        key = context.args[0]
        if key not in got:
            await update.message.reply_text("❌ Этот титул ещё закрыт или не существует. Посмотрите список: /titles")
            return
        users = load_data(USERS_FILE,{})
        u = users.setdefault(str(uid),{})
        u['active_title'] = key
        users[str(uid)] = u
        save_data(USERS_FILE,users)
        await update.message.reply_text(f"✅ Титул выбран: {got[key]}")
        return
    lines = ["🏷 <b>Титулы</b>", "Выбрать открытый титул: <code>/titles ключ</code>", ""]
    for t in TITLE_DEFS:
        prefix = '⭐ ' if t['key'] == active else ''
        lines.append(prefix + _title_progress_line(uid, t))
    text = chr(10).join(lines)
    if '_reply_long_html' in globals():
        await _reply_long_html(update.message, text)
    else:
        await update.message.reply_text(text, parse_mode='HTML')


async def notifications_cmd(update, context):
    uid = update.effective_user.id
    data = _load_notification_settings()
    cfg = data.setdefault(str(uid), {k: False for k in NOTIFICATION_CATEGORIES})
    # миграция старых ключей
    for k in NOTIFICATION_CATEGORIES:
        cfg.setdefault(k, False)
    aliases = {"giveaway": "giveaways", "розыгрыши": "giveaways", "match": "matches", "games": "matches", "shop": "market"}
    if context.args:
        raw = context.args[0].lower().strip()
        key = aliases.get(raw, raw)
        if key == "all":
            value = not all(cfg.get(k, False) for k in NOTIFICATION_CATEGORIES)
            for k in NOTIFICATION_CATEGORIES:
                cfg[k] = value
        elif key in NOTIFICATION_CATEGORIES:
            cfg[key] = not bool(cfg.get(key, False))
        else:
            await update.message.reply_text("❌ Нет такой категории. Используйте /notifications")
            return
        data[str(uid)] = cfg
        _save_notification_settings(data)
    lines = [
        "🔔 <b>Уведомления</b>",
        "По умолчанию все уведомления в ЛС выключены.",
        "Посты в канал бот публикует всегда, а в ЛС пишет только тем, кто включил категорию.",
        "Переключить: <code>/notifications ключ</code>",
        "Все сразу: <code>/notifications all</code>",
        "",
    ]
    for k, label in NOTIFICATION_CATEGORIES.items():
        lines.append(f"{'✅' if cfg.get(k) else '❌'} <code>{k}</code> — {label}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def _pity_state(user_id:int):
    users=load_data(USERS_FILE,{}); u=users.setdefault(str(user_id),{}); return users,u,u.setdefault('pity',{'rare':0,'epic':0,'legendary':0})

def choose_card_with_pity(user_id:int, cards:list):
    weights=get_drop_weights(); users,u,p=_pity_state(user_id); forced=None
    if p.get('legendary',0)>=PITY_LEGENDARY_LIMIT: forced='Легендарная'
    elif p.get('epic',0)>=PITY_EPIC_LIMIT: forced='Эпическая'
    elif p.get('rare',0)>=PITY_RARE_LIMIT: forced='Редкая'
    rarity=forced or random.choices(list(weights.keys()),weights=list(weights.values()),k=1)[0]
    pool=[c for c in cards if c.get('rarity')==rarity] or cards
    card=random.choice(pool); r=card.get('rarity')
    p['rare']=0 if r in ('Редкая','Эпическая','Легендарная','Мифическая','Эксклюзивная') else p.get('rare',0)+1
    p['epic']=0 if r in ('Эпическая','Легендарная','Мифическая','Эксклюзивная') else p.get('epic',0)+1
    p['legendary']=0 if r in ('Легендарная','Мифическая','Эксклюзивная') else p.get('legendary',0)+1
    u['pity']=p; users[str(user_id)]=u; save_data(USERS_FILE,users)
    return card, forced

async def pity_cmd(update, context):
    _,_,p=_pity_state(update.effective_user.id)
    await update.message.reply_text(f"🎯 <b>Гарант редкости</b>\nРедкая: {p.get('rare',0)}/{PITY_RARE_LIMIT}\nЭпическая: {p.get('epic',0)}/{PITY_EPIC_LIMIT}\nЛегендарная: {p.get('legendary',0)}/{PITY_LEGENDARY_LIMIT}",parse_mode='HTML')

def validate_rating_team(user_id:int):
    team=get_rating_team(user_id)
    if not team: return False,'нет состава'
    refs=[team.get('gk')]+list(team.get('field',[]))+([team.get('coach')] if team.get('coach') else [])
    refs=[r for r in refs if r is not None]
    if len({str(r) for r in refs}) != len(refs):
        return False,'одна карта указана в составе несколько раз'
    normal_cards=list(load_data(USERS_FILE,{}).get(str(user_id),{}).get('cards',[]))
    for ref in refs:
        if _is_team_mutation_ref(ref):
            if not _team_ref_mutation_instance(user_id, ref):
                return False,'мутированная карта из состава недоступна'
            continue
        cid=_team_ref_card_id(ref)
        if cid in normal_cards:
            normal_cards.remove(cid)
        else:
            return False,'карта из состава недоступна'
    return True,''

def _injuries(user_id:int):
    data=load_data(INJURIES_FILE,{}); now=time.time(); arr=[x for x in data.get(str(user_id),[]) if float(x.get('until',0))>now]
    data[str(user_id)]=arr; save_data(INJURIES_FILE,data); return arr

def team_injury(user_id:int):
    team=get_rating_team(user_id) or {}; refs={str(x) for x in [team.get('gk')]+list(team.get('field',[]))+([team.get('coach')] if team.get('coach') else [])}
    for x in _injuries(user_id):
        if str(x.get('ref')) in refs: return x
    return None

async def injuries_cmd(update, context):
    arr=_injuries(update.effective_user.id)
    if not arr: return await update.message.reply_text('🏥 Лазарет пуст. Травмы могут появиться после рейтинговых матчей с небольшим шансом; травмированную карту временно нельзя использовать в составе.')
    lines=['🏥 <b>Лазарет</b>', 'Травмированные карты временно блокируют поиск рейтингового матча, если стоят в составе.']
    for x in arr: lines.append(f"▫️ {html.escape(str(x.get('name','карта')))} — ещё {int((x['until']-time.time())//60)+1} мин.")
    await update.message.reply_text('\n'.join(lines),parse_mode='HTML')

async def history_cmd(update, context):
    if not is_admin(update.effective_user.id): return await update.message.reply_text('❌ Только админ.')
    target=int(context.args[0]) if context.args else update.effective_user.id
    rows=[x for x in load_data(ACTION_HISTORY_FILE,[]) if int(x.get('user_id',0))==target][-20:]
    await update.message.reply_text('\n'.join([f"📜 История {target}:"]+[f"{datetime.fromtimestamp(r['ts']).strftime('%d.%m %H:%M')} — {r.get('action')} {html.escape(str(r.get('details','')))}" for r in rows]) if rows else 'История пуста.',parse_mode='HTML')

async def security_cmd(update, context):
    if not is_admin(update.effective_user.id): return await update.message.reply_text('❌ Только админ.')
    rows=load_data(SECURITY_LOG_FILE,[])[-30:]
    await update.message.reply_text('\n'.join(["🛡 Security log"]+[f"{datetime.fromtimestamp(r['ts']).strftime('%d.%m %H:%M')} [{r.get('severity')}] {r.get('event')} u={r.get('user_id')} — {html.escape(str(r.get('details','')))}" for r in rows]) if rows else 'Логи пусты.',parse_mode='HTML')

async def bot_market_buy_cycle(context):
    state=load_data(BOT_MARKET_FILE,{}) ; now=time.time()
    if now-float(state.get('last_buy',0))<4*3600: return
    state['last_buy']=now; save_data(BOT_MARKET_FILE,state)
    market=load_data(MARKET_FILE,[]); cards=load_data(CARDS_FILE,[]); cmap={c['id']:c for c in cards}
    limits={'Обычная':(10,60),'Редкая':(50,100),'Эпическая':(100,250),'Легендарная':(250,800),'Мифическая':(250,900),'Эксклюзивная':(300,1200)}
    cand=[]
    for it in market:
        card=cmap.get(it.get('card_id'),{}); lo,hi=limits.get(card.get('rarity'),(20,300)); price=int(it.get('price',0))
        if lo<=price<=hi: cand.append(it)
    if not cand: return
    it=random.choice(cand); market=[m for m in market if m.get('id')!=it.get('id')]; save_data(MARKET_FILE,market); update_coins(it['seller_id'],int(it['price']))
    log_security('bot_market_buy',it.get('seller_id'),f"lot {it.get('id')} price {it.get('price')}")
    try: await context.bot.send_message(ADMIN_ID,f"🤖 Бот выкупил лот #{it.get('id')} за {it.get('price')} монет у {it.get('seller_id')}")
    except Exception: pass

def _profile_font(size:int, bold:bool=False):
    candidates = [
        '/usr/share/fonts/google-noto/NotoSans-Bold.ttf' if bold else '/usr/share/fonts/google-noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _draw_fit_text(draw, xy, text, font, fill, max_width):
    text = str(text)
    while len(text) > 3 and draw.textbbox((0,0), text, font=font)[2] > max_width:
        text = text[:-2]
    if text != str(text):
        text = text[:-1] + '…'
    draw.text(xy, text, font=font, fill=fill)

def build_profile_card(user_id:int, name:str):
    """Новый премиум-профиль: кастомный фон/рамка/значок + настоящая витрина с фото карт."""
    if not PIL_AVAILABLE:
        return None
    try:
        W, H = 1600, 1050
        users = load_data(USERS_FILE,{})
        u = users.get(str(user_id),{})
        st = u.get('stats',{})
        custom = _profile_custom(user_id) if '_profile_custom' in globals() else {}
        bg = PROFILE_BACKGROUNDS.get(custom.get('background', 'ice'), PROFILE_BACKGROUNDS['ice']) if 'PROFILE_BACKGROUNDS' in globals() else {'colors': ((7,12,24),(22,55,95)), 'emoji':'🧊'}
        fr = PROFILE_FRAMES.get(custom.get('frame', 'blue'), PROFILE_FRAMES['blue']) if 'PROFILE_FRAMES' in globals() else {'color': (75,155,255)}
        badge = PROFILE_BADGES.get(custom.get('badge', 'none'), PROFILE_BADGES['none']) if 'PROFILE_BADGES' in globals() else {'emoji':'▫️'}
        frame_col = tuple(fr.get('color', (75,155,255)))
        top_col, bot_col = bg.get('colors', ((7,12,24),(22,55,95)))

        def font(sz, bold=False): return _profile_font(int(sz), bold)
        f_name=font(64, True); f_title=font(36, True); f_big=font(42, True); f_mid=font(30, True); f_lab=font(24); f_small=font(21); f_tiny=font(18)
        img = Image.new('RGB', (W,H), top_col)
        d = ImageDraw.Draw(img)
        # cinematic gradient background
        for y in range(H):
            t=y/max(1,H-1)
            col=tuple(int(a+(b-a)*t) for a,b in zip(top_col, bot_col))
            d.line((0,y,W,y), fill=col)
        # subtle diagonal grid / ice lines
        for x in range(-W, W*2, 90):
            d.line((x,0,x+W,H), fill=tuple(min(255,c+28) for c in top_col), width=1)
        # dark overlay panels
        overlay = Image.new('RGBA',(W,H),(0,0,0,0)); od=ImageDraw.Draw(overlay)
        for pad,alpha in [(22,65),(34,45),(48,30)]:
            od.rounded_rectangle((pad,pad,W-pad,H-pad), radius=46, outline=(*frame_col,alpha), width=3)
        od.rounded_rectangle((48,48,W-48,H-48), radius=42, fill=(9,18,36,210), outline=(*frame_col,255), width=5)
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB'); d=ImageDraw.Draw(img)

        # helpers
        def text_w(txt, f):
            try: return d.textlength(str(txt), font=f)
            except Exception: return len(str(txt))*20
        def fit_text(x,y,txt,f,fill,maxw):
            txt=str(txt)
            while len(txt)>2 and text_w(txt,f)>maxw: txt=txt[:-2]+'…'
            d.text((x,y),txt,font=f,fill=fill)
        def center_text(box, txt, f, fill):
            x1,y1,x2,y2=box; bb=d.textbbox((0,0),str(txt),font=f); tw=bb[2]-bb[0]; th=bb[3]-bb[1]
            d.text((x1+(x2-x1-tw)/2,y1+(y2-y1-th)/2-2),str(txt),font=f,fill=fill)
        def panel(box, fill=(16,31,60,235), outline=None, radius=28, width=2):
            x1,y1,x2,y2=box; outline=outline or (*frame_col,190)
            layer=Image.new('RGBA',(W,H),(0,0,0,0)); ld=ImageDraw.Draw(layer)
            ld.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
            # top highlight
            ld.rounded_rectangle((x1+8,y1+8,x2-8,y1+45), radius=radius//2, fill=(255,255,255,18))
            return Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')

        # header
        img2=panel((82,78,W-82,252), fill=(22,48,88,230), radius=34, width=3); img.paste(img2); d=ImageDraw.Draw(img)
        d.ellipse((122,112,218,208), fill=frame_col, outline=(235,248,255), width=4)
        initials=(name or 'U')[:1].upper(); center_text((122,112,218,208), initials, font(54,True), (8,18,35))
        fit_text(250,105,name,f_name,(248,252,255),760)
        title = active_title(user_id)[1] if 'active_title' in globals() else '🆕 Новичок'
        fit_text(252,178,f"{badge.get('emoji','▫️')} {title}",f_title,(255,222,92),760)
        elo=get_rating_elo(user_id); rank=get_rating_rank(elo)
        img2=panel((1195,108,1438,218), fill=(10,20,38,235), outline=(255,222,92,230), radius=24, width=3); img.paste(img2); d=ImageDraw.Draw(img)
        d.text((1230,126),'⭐ Рейтинг',font=f_lab,fill=(180,205,235)); d.text((1230,158),str(elo),font=f_big,fill=(255,255,255))

        # stats left 2 columns
        coins=get_coins(user_id); normal=len(u.get('cards',[])); mutated=len(u.get('mutated_cards',[])); seen=len(u.get('seen_cards',[])); total=len(load_data(CARDS_FILE, []))
        matches=int(st.get('rating_matches',0)); wins=int(st.get('rating_wins',0)); wr=round(wins/max(1,matches)*100,1)
        stats=[('💰 Баланс',_fmt_coins(coins)),('🃏 Карты',f'{normal} + 🧬 {mutated}'),('📚 Уникальные',f'{seen}/{total}'),('🏒 Матчи',str(matches)),('🏆 Победы',str(wins)),('📈 Винрейт',f'{wr}%'),('⚔️ Дуэли',f"{st.get('duel_wins',0)} побед"),('🛠 Крафты',f"{st.get('craft_success',0)} успешных")]
        x0,y0=82,288; cw,ch,gap=350,118,24
        for i,(lab,val) in enumerate(stats):
            x=x0+(i%2)*(cw+gap); y=y0+(i//2)*(ch+gap)
            img2=panel((x,y,x+cw,y+ch), fill=(16,31,60,225), radius=22, width=2); img.paste(img2); d=ImageDraw.Draw(img)
            fit_text(x+24,y+18,lab,f_lab,(177,202,232),cw-48)
            fit_text(x+24,y+57,val,f_mid,(255,255,255),cw-48)

        # showcase section right
        sx,sy,sw,sh=855,288,663,555
        img2=panel((sx,sy,sx+sw,sy+sh), fill=(13,27,54,230), radius=30, width=3); img.paste(img2); d=ImageDraw.Draw(img)
        d.text((sx+30,sy+24),'⭐ ВИТРИНА КАРТ',font=f_mid,fill=(255,245,210))
        d.text((sx+30,sy+60),'любимые карты игрока',font=f_small,fill=(170,195,225))
        cards_all=load_data(CARDS_FILE, []); cmap={int(c.get('id')):c for c in cards_all if 'id' in c}
        showcase=[int(x) for x in custom.get('showcase',[])[:3] if str(x).isdigit()]
        if not showcase:
            # fallback: 3 strongest/first available cards so profile never looks empty
            owned=list(dict.fromkeys(u.get('cards',[])))[:3]
            showcase=[int(x) for x in owned if int(x) in cmap][:3]
        card_boxes=[(sx+28, sy+108, sx+215, sy+488),(sx+238, sy+108, sx+425, sy+488),(sx+448, sy+108, sx+635, sy+488)]
        rarity_colors={'Обычная':(150,165,185),'Редкая':(80,160,255),'Эпическая':(185,95,255),'Легендарная':(255,205,72),'Мифическая':(120,240,255),'Эксклюзивная':(255,105,190)}
        for idx,box in enumerate(card_boxes):
            x1,y1,x2,y2=box
            cid=showcase[idx] if idx < len(showcase) else None
            card=cmap.get(cid,{}) if cid else {}
            rarity=str(card.get('rarity',''))
            rc=rarity_colors.get(rarity, frame_col)
            img2=panel(box, fill=(10,20,40,235), outline=(*rc,230), radius=22, width=3); img.paste(img2); d=ImageDraw.Draw(img)
            photo_box=(x1+13,y1+14,x2-13,y1+220)
            if card and card.get('image'):
                path=os.path.join(CARDS_IMAGE_DIR, card.get('image',''))
                try:
                    ph=Image.open(path).convert('RGB')
                    ph=ImageOps.fit(ph,(photo_box[2]-photo_box[0],photo_box[3]-photo_box[1]),centering=(0.5,0.25))
                    mask=Image.new('L',ph.size,0); md=ImageDraw.Draw(mask); md.rounded_rectangle((0,0,ph.size[0],ph.size[1]),radius=16,fill=255)
                    img.paste(ph,photo_box[:2],mask)
                except Exception:
                    d.rounded_rectangle(photo_box,radius=16,fill=(28,42,72)); center_text(photo_box,'NO IMG',f_lab,(170,190,220))
            else:
                d.rounded_rectangle(photo_box,radius=16,fill=(28,42,72)); center_text(photo_box,'ПУСТО',f_lab,(170,190,220))
            if card:
                fit_text(x1+16,y1+248,card.get('name','?'),font(22,True),(255,255,255),x2-x1-32)
                fit_text(x1+16,y1+282,rarity,font(18),rc,x2-x1-32)
                pwr=get_card_power(card) if 'get_card_power' in globals() else 0
                d.rounded_rectangle((x1+16,y2-58,x2-16,y2-18),radius=13,fill=(0,0,0,90),outline=(*rc,180),width=1)
                center_text((x1+16,y2-58,x2-16,y2-18),f'СИЛА {pwr}',font(20,True),(255,255,255))

        # footer strip
        img2=panel((82,880,W-82,970), fill=(10,22,42,235), radius=24, width=2); img.paste(img2); d=ImageDraw.Draw(img)
        style_line=f"{bg.get('emoji','')} {bg.get('name','Фон')}  •  {fr.get('emoji','')} {fr.get('name','Рамка')}  •  {rank[1]} {rank[2]}"
        fit_text(118,900,style_line,f_lab,(215,235,255),920)
        fit_text(118,934,'/profile_custom • /cosmetic_shop • /my_cosmetics • /quests',f_small,(170,195,225),1100)
        # watermark
        d.text((W-310,925),'Хоккейные карточки',font=font(28,True),fill=(*frame_col,))
        out=io.BytesIO(); img.save(out,'PNG',quality=95); out.seek(0); return out
    except Exception as e:
        logger.warning(f'profile card error: {e}')
        return None

# ============================ ПРОФИЛЬ ============================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    users = load_data(USERS_FILE, {})
    u = users.get(str(user.id), {})
    st = u.get("stats", {})
    cards = load_data(CARDS_FILE, [])
    normal_cards = u.get("cards", [])
    mutated_cards = u.get("mutated_cards", [])
    seen = u.get("seen_cards", [])
    title = active_title(user.id)[1] if 'active_title' in globals() else "🆕 Новичок"
    trophy_pts = get_trophy_points(user.id) if 'get_trophy_points' in globals() else 0
    elo = get_rating_elo(user.id)
    rank = get_rating_rank(elo)
    matches = int(st.get("rating_matches", 0))
    wins = int(st.get("rating_wins", 0))
    wr = round(wins / max(1, matches) * 100, 1)
    msg = (
        f"👤 <b>Профиль игрока</b>\n\n"
        f"🏷 <b>Титул:</b> {html.escape(title)}\n"
        f"🏆 <b>Трофейных очков:</b> {trophy_pts}\n"
        f"⭐ <b>Рейтинг:</b> {elo} — {rank[1]} {rank[2]}\n"
        f"💰 <b>Баланс:</b> {get_coins(user.id)} монет\n"
        f"🃏 <b>Карты:</b> обычных {len(normal_cards)}, мутированных {len(mutated_cards)}\n"
        f"📊 <b>Уникальных открыто:</b> {len(seen)}/{len(cards)}\n\n"
        f"🏒 <b>Рейтинг-матчи:</b> {matches}, побед {wins}, винрейт {wr}%\n"
        f"⚔️ <b>Дуэли:</b> {st.get('duel_played',0)}, побед {st.get('duel_wins',0)}\n"
        f"🛠 <b>Крафты:</b> {st.get('craft_attempts',0)}, успешных {st.get('craft_success',0)}\n"
        f"🏪 <b>Маркет:</b> операций {st.get('market_ops',0)}, продаж {st.get('market_sales',0)}\n"
        f"💼 <b>Работа:</b> {st.get('work_count',0)} раз\n\n"
        f"🏷 Титулы: /titles\n📋 Задания: /quests\n🎯 Гарант: /pity\n🏥 Лазарет: /injuries"
    )
    try:
        img = build_profile_card(user.id, user.first_name or f"Игрок {user.id}") if 'build_profile_card' in globals() else None
        if img:
            await update.message.reply_photo(photo=img, caption=msg, parse_mode="HTML")
            return
    except Exception as e:
        logger.warning(f"Не удалось построить картинку профиля: {e}")
    await update.message.reply_text(msg, parse_mode="HTML")

# ============================ ТРЕЙД СИСТЕМА ============================
TRADE_TTL_SECONDS = 5 * 60
TRADE_MAX_CARDS = 10

def _next_trade_id() -> int:
    trades = load_data(TRADES_FILE, [])
    return max((t.get("id", 0) for t in trades), default=0) + 1

def _get_trade(trade_id: int):
    return next((t for t in load_data(TRADES_FILE, []) if t.get("id") == trade_id), None)

def _save_trades(trades: list) -> None:
    save_data(TRADES_FILE, trades)

def _trade_is_expired(trade: dict) -> bool:
    return time.time() - trade.get("created", time.time()) > TRADE_TTL_SECONDS

def _cleanup_expired_trades() -> int:
    trades = load_data(TRADES_FILE, [])
    active, removed = [], 0
    for t in trades:
        if t.get("status") in ("pending", "counter", "confirm") and _trade_is_expired(t):
            removed += 1
            continue
        active.append(t)
    if removed:
        save_data(TRADES_FILE, active)
    return removed

def _parse_trade_card_tokens(text: str):
    raw = text.replace(",", " ").replace(";", " ").split()
    if not raw:
        return None, "пустой список"
    if len(raw) > TRADE_MAX_CARDS:
        return None, f"можно указать максимум {TRADE_MAX_CARDS} карточек"
    result = []
    seen_mut = set()
    for tok in raw:
        kind, val = _parse_sell_target(tok) if '_parse_sell_target' in globals() else ('normal', tok)
        if kind == 'mutated':
            mid = str(val)
            if mid in seen_mut:
                return None, f"мутированная карта {tok} указана дважды"
            seen_mut.add(mid)
            result.append({"type": "mutated", "instance_id": mid})
        else:
            try:
                cid = int(val)
            except Exception:
                return None, f"неверный ID: {tok}"
            result.append({"type": "normal", "card_id": cid})
    return result, None

def _trade_item_key(item: dict):
    return f"m:{item.get('instance_id')}" if item.get("type") == "mutated" else f"n:{item.get('card_id')}"

def _trade_cards_available(user_id: int, items: list):
    users = load_data(USERS_FILE, {})
    u = users.get(str(user_id), {})
    normal_counts = Counter(u.get("cards", []))
    need_counts = Counter()
    for item in items:
        if item.get("type") == "mutated":
            mid = item.get("instance_id")
            if not _get_mutation_instance(user_id, mid):
                return False, f"мутированная карта M-ID {mid} недоступна"
            ok, reason = _can_sell_mutated_card(user_id, mid) if '_can_sell_mutated_card' in globals() else (True, '')
            if not ok:
                return False, reason
        else:
            cid = int(item.get("card_id"))
            need_counts[cid] += 1
    for cid, cnt in need_counts.items():
        if normal_counts.get(cid, 0) < cnt:
            return False, f"обычной карты ID {cid} не хватает в нужном количестве"
        ok, reason = _can_sell_normal_card(user_id, cid) if '_can_sell_normal_card' in globals() else (True, '')
        if not ok and normal_counts.get(cid, 0) <= cnt:
            return False, reason
    return True, ""

def _trade_item_name(user_id: int, item: dict, card_map: dict):
    if item.get("type") == "mutated":
        inst = _get_mutation_instance(user_id, item.get("instance_id"))
        if not inst:
            return f"M-ID {item.get('instance_id')}"
        card = card_map.get(inst.get("card_id"), {})
        meta = _get_mutation_meta(inst.get("mutation")) or {}
        return f"{card.get('name', 'Карта')} [{meta.get('label', 'Мутация')}] M-ID {inst.get('instance_id')}"
    card = card_map.get(int(item.get("card_id")), {})
    return f"{card.get('name', 'Карта')} ID {item.get('card_id')}"

def _trade_items_text(user_id: int, items: list, card_map: dict):
    if not items:
        return "—"
    return "\n".join(f"• {html.escape(_trade_item_name(user_id, it, card_map))}" for it in items)

def _trade_remove_items(user_id: int, items: list):
    removed = []
    for item in items:
        if item.get("type") == "mutated":
            inst = _get_mutation_instance(user_id, item.get("instance_id"))
            if not inst:
                for old in reversed(removed): _trade_add_item(user_id, old)
                return False
            if not remove_mutated_card_instance(user_id, item.get("instance_id")):
                for old in reversed(removed): _trade_add_item(user_id, old)
                return False
            removed.append({"type":"mutated_instance", "instance": inst})
        else:
            cid = int(item.get("card_id"))
            if 'remove_one_normal_card' in globals(): ok = remove_one_normal_card(user_id, cid)
            else: ok = remove_one_card(user_id, cid)
            if not ok:
                for old in reversed(removed): _trade_add_item(user_id, old)
                return False
            removed.append({"type":"normal", "card_id": cid})
    return removed

def _trade_add_item(user_id: int, item: dict):
    if item.get("type") == "mutated_instance":
        add_mutated_card_instance(user_id, item.get("instance"))
    elif item.get("type") == "mutated":
        inst = item.get("instance") or _get_mutation_instance(user_id, item.get("instance_id"))
        if inst: add_mutated_card_instance(user_id, inst)
    else:
        add_one_card(user_id, int(item.get("card_id")))

def _trade_give_removed_items(user_id: int, removed: list):
    for item in removed:
        _trade_add_item(user_id, item)

async def trade_offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте."); return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text()); return
    _cleanup_expired_trades()
    if len(context.args) < 2:
        await update.message.reply_text("ℹ️ Использование: /trade <user_id> <card_id... до 10>\nПример: /trade 123456 1 2 3 m777_mut")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный user_id."); return
    offered, err = _parse_trade_card_tokens(" ".join(context.args[1:]))
    if err:
        await update.message.reply_text(f"❌ {err}"); return
    if target_id == user.id:
        await update.message.reply_text("❌ Нельзя предложить обмен самому себе."); return
    users = load_data(USERS_FILE, {})
    if str(target_id) not in users:
        await update.message.reply_text("❌ Игрок не найден в базе бота."); return
    ok, reason = _trade_cards_available(user.id, offered)
    if not ok:
        await update.message.reply_text(f"❌ Карты недоступны для трейда: {reason}"); return
    trades = load_data(TRADES_FILE, [])
    active = [t for t in trades if t.get("status") in ("pending", "counter", "confirm") and user.id in (t.get("from_user"), t.get("to_user"))]
    if active:
        await update.message.reply_text("❌ У вас уже есть активный обмен. Завершите или отмените его через /cancel_trade."); return
    trade_id = _next_trade_id()
    trade = {"id": trade_id, "from_user": user.id, "to_user": target_id, "from_cards": offered, "to_cards": [], "status":"pending", "created": time.time()}
    trades.append(trade); _save_trades(trades)
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    text = _trade_items_text(user.id, offered, card_map)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Принять и выбрать свои карты", callback_data=f"trade_accept_{trade_id}")],[InlineKeyboardButton("❌ Отклонить", callback_data=f"trade_decline_{trade_id}")]])
    await update.message.reply_text(f"🔄 Обмен #{trade_id} отправлен игроку {target_id}.\nВы предлагаете:\n{text}", parse_mode="HTML")
    try:
        await context.bot.send_message(target_id, f"🔄 <b>Предложение обмена #{trade_id}</b>\n\nОт: @{html.escape(user.username or str(user.id))}\n\nВам предлагают:\n{text}\n\nМожно отдать от 1 до {TRADE_MAX_CARDS} карточек.", reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось уведомить получателя обмена: {e}")

async def cancel_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    _cleanup_expired_trades()
    trades = load_data(TRADES_FILE, [])
    active = [t for t in trades if t.get("status") in ("pending", "counter", "confirm") and user.id in (t.get("from_user"), t.get("to_user"))]
    if not active:
        await update.message.reply_text("ℹ️ У вас нет активного обмена."); return
    trade = active[0]
    _save_trades([t for t in trades if t.get("id") != trade.get("id")])
    await update.message.reply_text(f"❌ Обмен #{trade.get('id')} отменён.")
    other = trade.get("to_user") if user.id == trade.get("from_user") else trade.get("from_user")
    try: await context.bot.send_message(other, f"ℹ️ Обмен #{trade.get('id')} отменён второй стороной.")
    except Exception: pass

async def trade_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    _cleanup_expired_trades()
    if data.startswith("trade_decline_"):
        trade_id = int(data.split("_")[2]); trade = _get_trade(trade_id)
        if not trade or trade.get("status") not in ("pending", "counter", "confirm"):
            await query.edit_message_text("❌ Обмен уже недействителен."); return
        if user_id not in (trade.get("from_user"), trade.get("to_user")):
            await query.edit_message_text("❌ Это не ваш обмен."); return
        _save_trades([t for t in load_data(TRADES_FILE, []) if t.get("id") != trade_id])
        await query.edit_message_text("❌ Обмен отменён.")
        other = trade.get("to_user") if user_id == trade.get("from_user") else trade.get("from_user")
        try: await context.bot.send_message(other, "ℹ️ Обмен был отменён второй стороной.")
        except Exception: pass
        return
    if data.startswith("trade_accept_"):
        trade_id = int(data.split("_")[2]); trade = _get_trade(trade_id)
        if not trade or trade.get("status") != "pending":
            await query.edit_message_text("❌ Обмен уже недействителен."); return
        if _trade_is_expired(trade):
            _cleanup_expired_trades(); await query.edit_message_text("⌛ Обмен истёк — прошло больше 5 минут."); return
        if user_id != trade.get("to_user"):
            await query.edit_message_text("❌ Это предложение не для вас."); return
        trade["status"] = "counter"
        trades = load_data(TRADES_FILE, [])
        for i,t in enumerate(trades):
            if t.get("id") == trade_id: trades[i]=trade; break
        _save_trades(trades)
        context.user_data.clear(); context.user_data["trade_counter_id"] = trade_id
        await query.edit_message_text(f"✅ Обмен #{trade_id} принят.\n\nОтправьте ID ваших карточек через пробел или запятую, максимум {TRADE_MAX_CARDS}.\nПример: <code>5 9 12 m777_mut</code>", parse_mode="HTML")
        return
    if data.startswith("trade_confirm_"):
        trade_id = int(data.split("_")[2]); trade = _get_trade(trade_id)
        if not trade or trade.get("status") != "confirm":
            await query.edit_message_text("❌ Обмен уже недействителен."); return
        if _trade_is_expired(trade):
            _cleanup_expired_trades(); await query.edit_message_text("⌛ Обмен истёк — прошло больше 5 минут."); return
        if user_id not in (trade.get("from_user"), trade.get("to_user")):
            await query.edit_message_text("❌ Это не ваш обмен."); return
        trade.setdefault("confirmed", [])
        if user_id in trade["confirmed"]:
            await query.edit_message_text("✅ Вы уже подтвердили этот обмен."); return
        # финальная проверка до подтверждения
        ok1, r1 = _trade_cards_available(trade["from_user"], trade.get("from_cards", []))
        ok2, r2 = _trade_cards_available(trade["to_user"], trade.get("to_cards", []))
        if not ok1 or not ok2:
            _save_trades([t for t in load_data(TRADES_FILE, []) if t.get("id") != trade_id])
            await query.edit_message_text(f"❌ Обмен отменён: карты уже недоступны. {r1 or r2}")
            return
        trade["confirmed"].append(user_id)
        trades = load_data(TRADES_FILE, [])
        for i,t in enumerate(trades):
            if t.get("id") == trade_id: trades[i]=trade; break
        _save_trades(trades)
        if len(trade["confirmed"]) < 2:
            await query.edit_message_text("✅ Вы подтвердили обмен. Ждём второго игрока...")
            other = trade["to_user"] if user_id == trade["from_user"] else trade["from_user"]
            try: await context.bot.send_message(other, f"✅ Вторая сторона подтвердила обмен #{trade_id}. Подтвердите его и вы.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Подтвердить обмен", callback_data=f"trade_confirm_{trade_id}"), InlineKeyboardButton("❌ Отмена", callback_data=f"trade_decline_{trade_id}")]]))
            except Exception: pass
            return
        # execute atomically with rollback
        rem_from = _trade_remove_items(trade["from_user"], trade.get("from_cards", []))
        if not rem_from:
            _save_trades([t for t in trades if t.get("id") != trade_id]); await query.edit_message_text("❌ Обмен не удался — карты отправителя недоступны."); return
        rem_to = _trade_remove_items(trade["to_user"], trade.get("to_cards", []))
        if not rem_to:
            _trade_give_removed_items(trade["from_user"], rem_from)
            _save_trades([t for t in trades if t.get("id") != trade_id]); await query.edit_message_text("❌ Обмен не удался — карты получателя недоступны."); return
        _trade_give_removed_items(trade["from_user"], rem_to)
        _trade_give_removed_items(trade["to_user"], rem_from)
        _save_trades([t for t in load_data(TRADES_FILE, []) if t.get("id") != trade_id])
        card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
        msg_a = f"🎉 <b>Обмен #{trade_id} завершён!</b>\n\nВы отдали:\n{_trade_items_text(trade['from_user'], trade.get('from_cards', []), card_map)}\n\nВы получили:\n{_trade_items_text(trade['to_user'], trade.get('to_cards', []), card_map)}"
        msg_b = f"🎉 <b>Обмен #{trade_id} завершён!</b>\n\nВы отдали:\n{_trade_items_text(trade['to_user'], trade.get('to_cards', []), card_map)}\n\nВы получили:\n{_trade_items_text(trade['from_user'], trade.get('from_cards', []), card_map)}"
        await query.edit_message_text(msg_a if user_id == trade['from_user'] else msg_b, parse_mode="HTML")
        other = trade["to_user"] if user_id == trade["from_user"] else trade["from_user"]
        try: await context.bot.send_message(other, msg_b if other == trade['to_user'] else msg_a, parse_mode="HTML")
        except Exception: pass
        try: inc_stat(trade['from_user'],'trade_count',1); inc_stat(trade['to_user'],'trade_count',1); log_action(trade['from_user'],'trade_done',str(trade_id)); log_action(trade['to_user'],'trade_done',str(trade_id))
        except Exception: pass

async def trade_counter_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("bet_state") == "awaiting_amount": return
    trade_id = context.user_data.get("trade_counter_id")
    if not trade_id: return
    user = update.effective_user
    trade = _get_trade(trade_id)
    if not trade or trade.get("status") != "counter" or user.id != trade.get("to_user"):
        context.user_data.pop("trade_counter_id", None); return
    if _trade_is_expired(trade):
        _cleanup_expired_trades(); context.user_data.pop("trade_counter_id", None); await update.message.reply_text("⌛ Обмен истёк — прошло больше 5 минут."); return
    items, err = _parse_trade_card_tokens(update.message.text.strip())
    if err:
        await update.message.reply_text(f"❌ {err}"); return
    ok, reason = _trade_cards_available(user.id, items)
    if not ok:
        await update.message.reply_text(f"❌ Карты недоступны для трейда: {reason}"); return
    trade["to_cards"] = items; trade["status"] = "confirm"; trade["confirmed"] = []
    trades = load_data(TRADES_FILE, [])
    for i,t in enumerate(trades):
        if t.get("id") == trade_id: trades[i]=trade; break
    _save_trades(trades); context.user_data.pop("trade_counter_id", None)
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    summary = f"🔄 <b>Обмен #{trade_id}</b>\n\nИгрок 1 отдаёт:\n{_trade_items_text(trade['from_user'], trade.get('from_cards', []), card_map)}\n\nИгрок 2 отдаёт:\n{_trade_items_text(trade['to_user'], trade.get('to_cards', []), card_map)}\n\n⚠️ Проверьте список внимательно. После двух подтверждений обмен выполнится."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Подтвердить обмен", callback_data=f"trade_confirm_{trade_id}"), InlineKeyboardButton("❌ Отмена", callback_data=f"trade_decline_{trade_id}")]])
    await update.message.reply_text("✅ Ваш список карт принят. Отправил подтверждение обеим сторонам.")
    for uid in (trade["from_user"], trade["to_user"]):
        try: await context.bot.send_message(uid, summary, reply_markup=kb, parse_mode="HTML")
        except Exception as e: logger.error(f"Не удалось отправить подтверждение обмена {uid}: {e}")

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
    if price > MARKET_MAX_PRICE:
        await update.message.reply_text(f"❌ Лимит цены одного лота: {_fmt_coins(MARKET_MAX_PRICE)} монет.")
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
    if not remove_one_normal_card(user.id, card_id):
        await update.message.reply_text("❌ Не удалось снять обычную карточку с коллекции.")
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
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
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
    if is_banned(buyer_id):
        await query.edit_message_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(buyer_id, context):
        await query.edit_message_text(subscription_required_text())
        return
    market = load_data(MARKET_FILE, [])
    item = next((m for m in market if m["id"] == listing_id), None)
    if not item:
        await query.edit_message_text("❌ Объявление уже недоступно.")
        return
    if item["seller_id"] == buyer_id:
        await query.edit_message_text("❌ Нельзя купить свою карточку.")
        return
    if item.get("target_buyer_id") and int(item.get("target_buyer_id")) != int(buyer_id):
        await query.edit_message_text("❌ Это личное предложение продажи не для вас.")
        return
    if get_coins(buyer_id) < item["price"]:
        await query.edit_message_text("❌ Недостаточно монет!")
        return
    if item.get("_processing"):
        await query.edit_message_text("⌛ Покупка уже обрабатывается, откройте маркет заново.")
        return
    item["_processing"] = buyer_id
    save_data(MARKET_FILE, market)
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

def get_work_reward_range(rarity_name: str) -> tuple:
    """Диапазон награды за работу с учётом шанса выпадения редкости.
    Раньше редкости, добавленные админом, всегда получали минимальную награду
    (10-22). Теперь заработок определяется реальным шансом выпадения карты:
    чем реже редкость, тем выше профит (ступени привязаны к стандартным)."""
    if rarity_name in WORK_REWARDS:
        return WORK_REWARDS[rarity_name]
    chance = get_rarity_drop_chance(rarity_name)
    if chance <= 0:
        # Редкость вообще не выпадает (как Эксклюзивная) — высший диапазон
        return WORK_REWARDS["Эксклюзивная"]
    if chance >= 0.45:
        return WORK_REWARDS["Обычная"]
    if chance >= 0.25:
        return WORK_REWARDS["Редкая"]
    if chance >= 0.12:
        return WORK_REWARDS["Эпическая"]
    if chance >= 0.06:
        return WORK_REWARDS["Мифическая"]
    if chance >= 0.02:
        return WORK_REWARDS["Легендарная"]
    return WORK_REWARDS["Эксклюзивная"]

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
    # Бафф-карта сокращает кулдаун работы, но не сильнее чем на 30%
    work_cooldown = WORK_COOLDOWN_SECONDS * max(1.0 - WORK_MAX_COOLDOWN_REDUCTION, get_cooldown_multiplier(user.id))
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
    reward_range = get_work_reward_range(card["rarity"])
    reward = random.randint(*reward_range)
    # Нерф: на работе действует только ПОЛОВИНА монетного баффа (карта + клан)
    # и суммарно не больше +25%. Плюс жёсткий потолок награды.
    work_bonus = min(WORK_BUFF_BONUS_CAP, max(0.0, (get_total_coin_multiplier(user.id) - 1.0) * 0.5))
    reward = min(WORK_REWARD_HARD_CAP, int(reward * (1.0 + work_bonus)))
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
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'work_count', 1))
    log_action(user.id, 'work_start', card.get('name',''))
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
            "⚡ <b>Буст выпадения</b>\n\nВведите редкость или напишите <b>Мутация</b> для буста шанса на мутированные карты:",
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
                f"Увеличен шанс выпадения <b>{html.escape(rarity)}</b>!\n"
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
            await update.message.reply_text("Введите редкость или Мутация:")
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
                "chat_id": EVENTS_CHANNEL_ID,
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
                "poll_chat_id": EVENTS_CHANNEL_ID,
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
            # Промокод после голосования доступен всем пользователям бота,
            # но каждый пользователь может активировать его только один раз.
            # Общего лимита по количеству людей нет.
            "max_uses": 0,
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
            EVENTS_CHANNEL_ID,
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
    try:
        await bot_market_buy_cycle(context)
    except Exception as e:
        logger.error(f"bot_market_buy_cycle: {e}")
    try:
        if 'cosmetic_shop_refresh_cycle' in globals():
            await cosmetic_shop_refresh_cycle(context)
    except Exception as e:
        logger.error(f"cosmetic_shop_refresh_cycle: {e}")
    # Заодно чистим истёкшие трейды: если обмен не приняли/не подтвердили за 5 минут,
    # он исчезает сам, без ожидания нового /trade или нажатия кнопок.
    try:
        _cleanup_expired_trades()
    except Exception:
        pass
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
                    await post_to_channel(
                        context,
                        f"⚡ <b>СОБЫТИЕ НАЧАЛОСЬ!</b>\n\n"
                        f"Увеличен шанс выпадения <b>{html.escape(event['rarity'])}</b>!\n"
                        f"Множитель: x{event.get('multiplier', 2)}\n"
                        f"⏳ На {mins} минут!",
                    )
                except Exception:
                    pass
        if event.get("status") == "active" and event.get("type") == "scheduled_boost":
            if now >= event.get("end_at", 0):
                event["status"] = "completed"
                changed = True
                try:
                    await post_to_channel(
                        context,
                        f"⏹ Буст <b>{html.escape(event['rarity'])}</b> завершён!",
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
    now_ts = time.time()
    _work_processed = 0
    for uid, udata in list(users.items()):
        work = (udata or {}).get("working_card")
        if not work or now_ts < work.get("finish_at", 0):
            continue
        try:
            await _complete_work_if_ready(int(uid), context)
            _work_processed += 1
            # Отдаём управление событийному циклу чтобы бот не «тупил»
            if _work_processed % 3 == 0:
                await asyncio.sleep(0)
        except Exception:
            pass
    # Завершение розыгрышей (по времени или по числу участников)
    try:
        giveaways = load_data(GIVEAWAYS_FILE, [])
        gw_changed = False
        for gw in giveaways:
            if gw.get("status") != "active":
                continue
            by_time = gw.get("end_type") == "time" and now_ts >= (gw.get("end_at") or 0)
            by_count = gw.get("end_type") == "participants" and len(gw.get("participants", [])) >= gw.get("end_value", 0)
            if by_time or by_count:
                await _finish_giveaway(gw, context)
                gw_changed = True
        if gw_changed:
            save_data(GIVEAWAYS_FILE, giveaways)
    except Exception as e:
        logger.error(f"Ошибка завершения розыгрышей: {e}")




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
    """Запускает фоновый воркер + добиваем просроченные розыгрыши сразу после старта."""
    application.bot_data["mc_loop"] = asyncio.get_running_loop()
    application.create_task(_event_worker(application))
    # Если бот перезапустился через /update, розыгрыши которые уже истекли — подводимся сразу
    async def _startup_giveaway_check():
        await asyncio.sleep(5)  # ждём пока Telegram-соединение установится
        try:
            giveaways = load_data(GIVEAWAYS_FILE, [])
            now = time.time()
            changed = False
            ctx = CallbackContext(application)
            for gw in giveaways:
                if gw.get("status") != "active":
                    continue
                by_time = gw.get("end_type") == "time" and gw.get("end_at") and now >= gw["end_at"]
                by_count = (gw.get("end_type") == "participants" and
                            len(gw.get("participants", [])) >= gw.get("end_value", 0))
                if by_time or by_count:
                    await _finish_giveaway(gw, ctx)
                    changed = True
            if changed:
                save_data(GIVEAWAYS_FILE, giveaways)
                logger.info(f"Startup: добиты просроченные розыгрыши.")
        except Exception as e:
            logger.error(f"Startup giveaway check error: {e}")
    application.create_task(_startup_giveaway_check())

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
        data["rating_stats"] = {"wins": 0, "losses": 0, "draws": 0}
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
    # Начисляем трофейные очки за топ-10
    trophy_pts_map = {1: 10, 2: 5, 3: 3}
    all_top10 = leaders[:10]
    for _rank_i, (_uid, _elo) in enumerate(all_top10, start=1):
        _pts = trophy_pts_map.get(_rank_i, 1)
        _old_pts = get_trophy_points(_uid)
        _new_pts = add_trophy_points(_uid, _pts)
        # Проверяем смену звания
        def _t(p):
            for thr, en, ru, em in TITLES:
                if p >= thr:
                    return en, ru, em
            return "Average", "Обыватель", "👥"
        _old_t = _t(_old_pts)
        _new_t = _t(_new_pts)
        if _new_t[0] != _old_t[0]:
            try:
                await context.bot.send_message(
                    _uid,
                    f"🏆 <b>Новое звание!</b>\n\n"
                    f"{_new_t[2]} <b>{_new_t[0]}</b> — {_new_t[1]}\n"
                    f"Трофейных очков: {_new_pts}\n\n"
                    f"Заработано за топ-{_rank_i} в сезоне #{season.get('number')}!",
                    parse_mode="HTML",
                )
            except Exception:
                pass
    season["active"] = False
    season["ended_at"] = time.time()
    save_data(SEASON_FILE, season)
    await post_to_channel(context, "\n".join(result_lines), notification_category="giveaways")
    await update.message.reply_text("✅ Сезон завершён, призы выданы!")

# ============================ РОЗЫГРЫШИ (АДМИН) ============================
GIVEAWAYS_FILE = "giveaways.json"
GIVEAWAY_WINNERS, GIVEAWAY_PRIZES, GIVEAWAY_END = range(110, 113)

def _prize_label(prize: dict, card_map=None) -> str:
    """Человекочитаемое описание приза."""
    if prize.get("type") == "coins":
        return f"{prize['amount']} монет"
    if prize.get("type") == "card":
        if card_map is None:
            card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
        card = card_map.get(prize["card_id"], {})
        name = card.get("name", f"ID {prize['card_id']}")
        rarity = card.get("rarity", "")
        return f"карта «{name}»" + (f" ({rarity})" if rarity else "")
    if prize.get("type") == "reset":
        return "сброс таймеров (карточка и работа)"
    return "приз"

def _gw_place(i: int) -> str:
    return f"{['🥇', '🥈', '🥉'][i]} {i + 1} место" if i < 3 else f"🏅 {i + 1} место"

def _gw_display(p: dict) -> str:
    if p.get("username"):
        return f"@{p['username']}"
    return p.get("first_name") or f"ID {p.get('id')}"

async def giveaway_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return ConversationHandler.END
    context.user_data["new_giveaway"] = {}
    await update.message.reply_text(
        "🎉 <b>Создание розыгрыша</b>\n\nСколько будет призовых мест? (от 1 до 10)\n\n/cancel — отмена",
        parse_mode="HTML",
    )
    return GIVEAWAY_WINNERS

async def giveaway_winners_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        n = int(update.message.text.strip())
        if not 1 <= n <= 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите число от 1 до 10.")
        return GIVEAWAY_WINNERS
    context.user_data["new_giveaway"]["winners_count"] = n
    await update.message.reply_text(
        f"🏆 Мест: {n}.\n\nТеперь отправьте призы — по одной строке на место (сверху вниз, всего {n}).\n"
        "Форматы:\n"
        "• монеты 200\n"
        "• карта 15 (ID карточки)\n"
        "• сброс (сброс таймеров карточки и работы)\n\n"
        "Пример:\nкарта 15\nмонеты 200\nсброс"
    )
    return GIVEAWAY_PRIZES

def _parse_prize_line(line: str, cards_db: list):
    parts = line.strip().lower().split()
    if not parts:
        return None
    if parts[0].startswith("монет"):
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            return None
        return {"type": "coins", "amount": int(parts[1])}
    if parts[0].startswith("карт"):
        if len(parts) < 2 or not parts[1].isdigit():
            return None
        cid = int(parts[1])
        if not any(c["id"] == cid for c in cards_db):
            return None
        return {"type": "card", "card_id": cid}
    if parts[0].startswith("сброс"):
        return {"type": "reset"}
    return None

async def giveaway_prizes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    g = context.user_data.get("new_giveaway", {})
    n = g.get("winners_count", 0)
    lines = [l for l in update.message.text.splitlines() if l.strip()]
    if len(lines) != n:
        await update.message.reply_text(f"❌ Нужно ровно {n} строк(и) с призами, получено {len(lines)}. Попробуйте ещё раз.")
        return GIVEAWAY_PRIZES
    cards_db = load_data(CARDS_FILE, [])
    prizes = []
    for i, line in enumerate(lines, start=1):
        prize = _parse_prize_line(line, cards_db)
        if prize is None:
            await update.message.reply_text(
                f"❌ Строка {i} («{line.strip()}») не распознана или карточка не найдена.\n"
                "Форматы: «монеты 200», «карта 15», «сброс». Отправьте все призы заново."
            )
            return GIVEAWAY_PRIZES
        prizes.append(prize)
    g["prizes"] = prizes
    await update.message.reply_text(
        "⏰ Когда подводить итоги?\n\n"
        "• участники 20 — как только наберётся 20 участников\n"
        "• время 2:30 — через 2 часа 30 минут\n\n"
        "Отправьте одно из условий."
    )
    return GIVEAWAY_END

async def giveaway_end_condition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    g = context.user_data.get("new_giveaway", {})
    parts = update.message.text.strip().lower().split()
    end_type = None
    end_value = 0
    end_at = None
    if parts and parts[0].startswith("участник") and len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) > 0:
        end_type = "participants"
        end_value = int(parts[1])
    elif parts and parts[0].startswith("врем") and len(parts) >= 2 and ":" in parts[1]:
        hh, _, mm = parts[1].partition(":")
        if hh.isdigit() and mm.isdigit() and int(hh) * 60 + int(mm) > 0:
            end_type = "time"
            end_value = int(hh) * 60 + int(mm)
            end_at = time.time() + end_value * 60
    if end_type is None:
        await update.message.reply_text("❌ Не понял условие. Примеры: «участники 20» или «время 2:30».")
        return GIVEAWAY_END
    giveaways = load_data(GIVEAWAYS_FILE, [])
    gid = max([x.get("id", 0) for x in giveaways], default=0) + 1
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    prize_lines = [f"{_gw_place(i)} — {html.escape(_prize_label(p, card_map))}" for i, p in enumerate(g["prizes"])]
    if end_type == "participants":
        cond_text = f"👥 Итоги — как только наберётся {end_value} участник(ов)."
    else:
        rem = int(end_at - time.time())
        _rh, _rm = divmod(max(rem, 0) // 60, 60)
        rel_str = (f"{_rh}ч {_rm}мин" if _rh else f"{_rm}мин")
        cond_text = f"⏰ Итоги через: {rel_str} ({time.strftime('%d.%m %H:%M', time.localtime(end_at))})"
    announce = (
        "🎉 <b>РОЗЫГРЫШ ОТ Хоккейные карточки!</b>\n\n"
        "🏆 <b>Призы:</b>\n" + "\n".join(prize_lines) + "\n\n"
        f"{cond_text}\n\n"
        "Нажмите кнопку ниже, чтобы участвовать!"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 Участвовать (0)", callback_data=f"gw_join_{gid}")]])
    try:
        msg = await context.bot.send_message(EVENTS_CHANNEL_ID, announce, parse_mode="HTML", reply_markup=keyboard)
        await notify_users_in_dm(context, f"🎉 В телеграм-канале Хоккейные карточки запущен розыгрыш!\n\nУчаствовать здесь: {EVENTS_CHANNEL_LINK}", parse_mode="HTML", category="giveaways")
    except Exception as e:
        logger.error(f"Не удалось опубликовать розыгрыш: {e}")
        await update.message.reply_text("❌ Не удалось опубликовать розыгрыш в канал. Проверьте права бота в канале.")
        context.user_data.pop("new_giveaway", None)
        return ConversationHandler.END
    giveaways.append({
        "id": gid,
        "status": "active",
        "prizes": g["prizes"],
        "winners_count": g["winners_count"],
        "end_type": end_type,
        "end_value": end_value,
        "end_at": end_at,
        "participants": [],
        "created_at": time.time(),
        "channel_message_id": msg.message_id,
    })
    save_data(GIVEAWAYS_FILE, giveaways)
    await update.message.reply_text(f"✅ Розыгрыш #{gid} опубликован в канале! Итоги будут подведены автоматически.")
    context.user_data.pop("new_giveaway", None)
    return ConversationHandler.END

async def giveaway_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    try:
        gid = int(query.data.split("_")[-1])
    except ValueError:
        await query.answer()
        return
    if is_banned(user.id):
        await query.answer("❌ Вы заблокированы в этом боте.", show_alert=True)
        return
    giveaways = load_data(GIVEAWAYS_FILE, [])
    gw = next((x for x in giveaways if x.get("id") == gid), None)
    if not gw or gw.get("status") != "active":
        await query.answer("⏹ Этот розыгрыш уже завершён.", show_alert=True)
        return
    if any(p.get("id") == user.id for p in gw.get("participants", [])):
        await query.answer("✅ Вы уже участвуете в этом розыгрыше!", show_alert=True)
        return
    gw.setdefault("participants", []).append({"id": user.id, "username": user.username, "first_name": user.first_name})
    await query.answer("🎉 Вы участвуете в розыгрыше! Удачи!", show_alert=True)
    # Обновляем счётчик на кнопке
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton(f"🎉 Участвовать ({len(gw['participants'])})", callback_data=f"gw_join_{gid}")]])
        )
    except Exception:
        pass
    # Достигнуто нужное число участников — сразу подводим итоги
    if gw.get("end_type") == "participants" and len(gw["participants"]) >= gw.get("end_value", 0):
        await _finish_giveaway(gw, context)
    save_data(GIVEAWAYS_FILE, giveaways)

async def _finish_giveaway(gw: dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подводит итоги: выдаёт призы, публикует результаты в канал,
    шлёт лог админу и ЛС победителям. Сохранение файла — на вызывающей стороне."""
    gw["status"] = "finished"
    gw["finished_at"] = time.time()
    participants = gw.get("participants", [])
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    if not participants:
        gw["winners"] = []
        try:
            await post_to_channel(context, f"🎭 Розыгрыш #{gw['id']} завершён: участников не было, призы не разыграны.", notification_category="giveaways")
        except Exception:
            pass
        try:
            await context.bot.send_message(ADMIN_ID, f"🎁 Розыгрыш #{gw['id']} завершён без участников.")
        except Exception:
            pass
        return
    count = min(gw.get("winners_count", 1), len(participants))
    winners = random.sample(participants, count)
    result_lines = [f"🎉 <b>ИТОГИ РОЗЫГРЫША #{gw['id']} • Хоккейные карточки</b>\n"]
    log_lines = []
    gw["winners"] = []
    for i, winner in enumerate(winners):
        prize = gw["prizes"][i]
        label = _prize_label(prize, card_map)
        # Выдаём приз автоматически
        try:
            if prize["type"] == "coins":
                update_coins(winner["id"], prize["amount"])
            elif prize["type"] == "card":
                add_one_card(winner["id"], prize["card_id"])
            elif prize["type"] == "reset":
                users = load_data(USERS_FILE, {})
                udata = users.get(str(winner["id"]), {})
                udata["last_drop"] = 0
                udata["last_work"] = 0
                users[str(winner["id"])] = udata
                save_data(USERS_FILE, users)
        except Exception as e:
            logger.error(f"Не удалось выдать приз победителю {winner.get('id')}: {e}")
        name = _gw_display(winner)
        result_lines.append(f"{_gw_place(i)}: {html.escape(name)} — {html.escape(label)}")
        log_lines.append(f"{i + 1} место: {name} (ID {winner.get('id')}) — {label}")
        gw["winners"].append({"id": winner.get("id"), "prize": prize})
        # Уведомляем победителя в ЛС
        try:
            await context.bot.send_message(
                winner["id"],
                f"🎉 <b>Поздравляем!</b> Вы победили в розыгрыше #{gw['id']} ({_gw_place(i)})!\n"
                f"🎁 Ваш приз: <b>{html.escape(label)}</b>\nПриз уже начислен!",
                parse_mode="HTML",
            )
        except Exception:
            pass
    result_lines.append(f"\n👥 Участников: {len(participants)}. Спасибо всем за участие!")
    try:
        await post_to_channel(context, "\n".join(result_lines), notification_category="giveaways")
    except Exception as e:
        logger.error(f"Не удалось опубликовать итоги розыгрыша: {e}")
    # Лог админу: призы выданы ботом
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🎁 <b>Розыгрыш #{gw['id']}</b> завершён, бот автоматически выдал призы:\n" + html.escape("\n".join(log_lines)),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Не удалось отправить лог о розыгрыше администратору: {e}")

async def giveaways_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
    # При просмотре — также добиваем просроченные старые розыгрыши
    _gws_all = load_data(GIVEAWAYS_FILE, [])
    _gw_now = time.time()
    _gw_changed = False
    for _gw in _gws_all:
        if _gw.get("status") != "active": continue
        if _gw.get("end_type") == "time" and _gw.get("end_at") and _gw_now >= _gw["end_at"]:
            await _finish_giveaway(_gw, context)
            _gw_changed = True
    if _gw_changed:
        save_data(GIVEAWAYS_FILE, _gws_all)
    active = [g for g in _gws_all if g.get("status") == "active"]
    if not active:
        await update.message.reply_text("📭 Активных розыгрышей нет. Создать: /giveaway")
        return
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    lines = []
    for g in active:
        if g.get("end_type") == "participants":
            cond = f"итоги при {g.get('end_value')} участниках"
        else:
            _ea = g.get('end_at') or 0
            _rem = int(_ea - time.time())
            if _rem > 0:
                _rh, _rm = divmod(_rem // 60, 60)
                cond = f"итоги через {_rh}ч {_rm}мин" if _rh else f"итоги через {_rm}мин"
            else:
                cond = f"итоги {time.strftime('%d.%m %H:%M', time.localtime(_ea))} (просрочен)"
        prizes = ", ".join(_prize_label(p, card_map) for p in g.get("prizes", []))
        lines.append(f"🎉 #{g['id']} — участников: {len(g.get('participants', []))}, {cond}\n   Призы: {prizes}")
    await update.message.reply_text("🎁 <b>Активные розыгрыши:</b>\n\n" + html.escape("\n\n".join(lines)), parse_mode="HTML")

# ============================ САМООБНОВЛЕНИЕ БОТА (/update) ============================
UPDATE_TOKEN, UPDATE_FILE = range(120, 122)
BOT_BACKUP_FILE = "bot_backup.py"

async def update_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return ConversationHandler.END
    await update.message.reply_text(
        "🔄 <b>Обновление бота</b>\n\n"
        "Шаг 1/2. Какой токен использовать после перезапуска?\n"
        "• отправьте новый токен, или\n"
        "• напишите «оставить» — останется текущий.\n\n"
        "/cancel — отмена",
        parse_mode="HTML",
    )
    return UPDATE_TOKEN

async def update_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() in ("оставить", "текущий", "оставь"):
        context.user_data.pop("pending_token", None)
        await update.message.reply_text("🔑 Оставляю текущий токен.\n\nШаг 2/2. Отправьте новый файл bot.py документом.")
        return UPDATE_FILE
    if ":" not in text or len(text) < 20 or " " in text:
        await update.message.reply_text("❌ Это не похоже на токен бота (формат 123456789:AbCdEf...). Отправьте токен или напишите «оставить».")
        return UPDATE_TOKEN
    context.user_data["pending_token"] = text
    await update.message.reply_text("🔑 Токен принят — применится после перезапуска.\n\nШаг 2/2. Отправьте новый файл bot.py документом.")
    return UPDATE_FILE

async def update_bot_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc = update.message.document
    if not doc or not (doc.file_name or "").endswith(".py"):
        await update.message.reply_text("❌ Отправьте файл с расширением .py именно документом.")
        return UPDATE_FILE
    await update.message.reply_text("📥 Скачиваю и проверяю файл...")
    current_path = os.path.abspath(__file__)
    new_path = os.path.join(os.path.dirname(current_path), "bot_new.py")
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(new_path)
        with open(new_path, encoding="utf-8") as f:
            source = f.read()
        # Проверка синтаксиса: битый файл не будет установлен
        compile(source, "bot.py", "exec")
        if "def main" not in source or "run_polling" not in source:
            raise ValueError("это не похоже на файл бота (нет main/run_polling)")
    except SyntaxError as e:
        await update.message.reply_text(
            f"❌ В новом файле синтаксическая ошибка (строка {e.lineno}): {e.msg}\n"
            "Обновление отменено — бот продолжает работать на старой версии."
        )
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось принять файл: {e}\nОбновление отменено.")
        return ConversationHandler.END
    # Резервная копия текущей версии — для отката, если что-то пойдёт не так
    try:
        with open(current_path, encoding="utf-8") as f:
            old_source = f.read()
        with open(BOT_BACKUP_FILE, "w", encoding="utf-8") as f:
            f.write(old_source)
    except Exception:
        pass
    # Новый токен (если админ его задал) — подхватится из файла после рестарта
    pending_token = context.user_data.pop("pending_token", None)
    if pending_token:
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(pending_token)
        except Exception:
            pass
    # Анонс в канал перед перезапуском
    try:
        await post_to_channel(context, "🔄 ОБНОВЛЕНИЕ Хоккейные карточки!\nБот перезапускается с новой версией и вернётся через минуту. Спасибо за ожидание! 🏒", mirror_dm=False)
    except Exception:
        pass
    # Подменяем файл и перезапускаемся
    try:
        with open(current_path, "w", encoding="utf-8") as f:
            f.write(source)
        os.remove(new_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось заменить файл: {e}")
        return ConversationHandler.END
    await update.message.reply_text(
        "✅ Файл заменён, резервная копия сохранена в bot_backup.py.\n"
        "🔄 Перезапускаюсь... Проверьте меня через ~30 секунд командой /start."
    )
    logger.info("САМООБНОВЛЕНИЕ: перезапуск бота по команде администратора")
    await asyncio.sleep(1)
    # Запускаем отдельный процесс-помощник: он ждёт 3 секунды, пока старый бот
    # полностью умрёт и отпустит соединение с Telegram, и запускает новую версию
    # тем же интерпретатором (реальная среда сохраняется) из папки бота.
    helper = (
        "import time, os, sys, subprocess\n"
        "time.sleep(3)\n"
        "os.chdir(os.path.dirname(os.path.abspath(sys.argv[2])))\n"
        "subprocess.call([sys.argv[1], sys.argv[2]])\n"
    )
    popen_kwargs = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    else:
        popen_kwargs["creationflags"] = 0x00000010  # CREATE_NEW_CONSOLE (Windows)
    subprocess.Popen(
        [sys.executable, "-c", helper, sys.executable, current_path],
        cwd=os.path.dirname(current_path),
        stdin=subprocess.DEVNULL,
        **popen_kwargs,
    )
    # Немедленно завершаем старый процесс, чтобы два бота с одним токеном
    # не конфликтовали за Telegram (ошибка 409 Conflict).
    os._exit(0)
    return ConversationHandler.END

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
    await post_to_channel(context, f"🏒 <b>Новый матч для ставок!</b>\n\n<b>{html.escape(team1)} — {html.escape(team2)}</b>\n⏳ Приём ставок до: <b>{deadline.strftime('%d.%m.%Y %H:%M')}</b> ({hours:g} ч.)\n🎯 Сделать ставку: /bet", notification_category="matches")
    # Лог админу, если матч создал модератор
    await log_moderator_action(context, update.effective_user.id,
                               f"Создал матч #{new_id}: {team1} — {team2} (приём ставок {hours:g} ч.)")

async def finish_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна администратору и модераторам!")
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
    # Лог админу, если матч завершил модератор (раньше лог не отправлялся — баг)
    await log_moderator_action(
        context, update.effective_user.id,
        f"Завершил матч #{event['id']}: {event['team1']} — {event['team2']} со счётом {score}. "
        f"Ставок: выигрышных {total_wins}, проигрышных {total_loses}."
    )

# Инлайн-меню для ставок
async def bet_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
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

def _is_betting_open(event: dict) -> bool:
    """Единая проверка: матч активен и дедлайн приёма ставок ещё не прошёл."""
    return bool(event and event.get("status") == "active" and time.time() < float(event.get("deadline", 0) or 0))


async def bet_match_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    match_id = int(data.split("_")[2])
    events = load_data(EVENTS_FILE, [])
    event = next((e for e in events if e["id"] == match_id), None)
    if not event:
        context.user_data.pop("bet_match_id", None)
        await query.edit_message_text("❌ Матч не найден.")
        return
    if not _is_betting_open(event):
        for key in ("bet_state", "bet_match_id", "bet_outcome_id"):
            context.user_data.pop(key, None)
        await query.edit_message_text("❌ Приём ставок на этот матч уже закрыт.")
        return
    context.user_data["bet_match_id"] = match_id
    if not event["outcomes"]:
        await query.edit_message_text("❌ Для этого матча нет исходов.")
        return
    keyboard = []
    for o in event["outcomes"]:
        keyboard.append([InlineKeyboardButton(f"{o['label']} (коэф {o['coefficient']})", callback_data=f"bet_outcome_{match_id}_{o['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    deadline_text = datetime.fromtimestamp(event.get("deadline", 0)).strftime('%d.%m %H:%M')
    await query.edit_message_text(
        f"Выберите исход для матча {event['team1']} - {event['team2']}:\n"
        f"⏳ Приём ставок до: {deadline_text}",
        reply_markup=reply_markup,
    )

async def bet_outcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split("_")
    match_id = int(parts[2])
    outcome_id = int(parts[3])
    events = load_data(EVENTS_FILE, [])
    event = next((e for e in events if e["id"] == match_id), None)
    if not event:
        for key in ("bet_state", "bet_match_id", "bet_outcome_id"):
            context.user_data.pop(key, None)
        await query.edit_message_text("❌ Матч не найден.")
        return
    if not _is_betting_open(event):
        for key in ("bet_state", "bet_match_id", "bet_outcome_id"):
            context.user_data.pop(key, None)
        await query.edit_message_text("❌ Приём ставок на этот матч уже закрыт.")
        return
    outcome = next((o for o in event.get("outcomes", []) if o["id"] == outcome_id), None)
    if not outcome:
        for key in ("bet_state", "bet_match_id", "bet_outcome_id"):
            context.user_data.pop(key, None)
        await query.edit_message_text("❌ Исход не найден.")
        return
    context.user_data.clear()
    context.user_data["bet_outcome_id"] = outcome_id
    context.user_data["bet_match_id"] = match_id
    context.user_data["bet_state"] = "awaiting_amount"
    await query.edit_message_text(
        f"Исход выбран: {outcome['label']} (коэф {outcome['coefficient']}).\n"
        "Введите сумму ставки (в монетах):"
    )

async def bet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("bet_state") != "awaiting_amount":
        return
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
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
    if not _is_betting_open(event):
        for key in ("bet_state", "bet_match_id", "bet_outcome_id"):
            context.user_data.pop(key, None)
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
        await update.message.reply_text(subscription_required_text())
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
    await _reply_long_html(update.message, message)

# ============================ РЕЙТИНГОВЫЙ РЕЖИМ ============================

async def rating_team_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return ConversationHandler.END
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return ConversationHandler.END
    available = get_available_card_ids(user.id)
    mutated = _get_user_mutated_cards(user.id) if '_get_user_mutated_cards' in globals() else []
    if len(available) + len(mutated) < 6:
        await update.message.reply_text(
            "❌ Для состава КХЛ нужно минимум 6 доступных карточек в коллекции: 1 вратарь и 5 полевых. Получите больше карточек через /get_card."
        )
        return ConversationHandler.END
    context.user_data.clear()
    total_available = len(available) + len(mutated)
    await update.message.reply_text(
        f"🏒 <b>Сбор рейтинговой команды</b>\n\n"
        f"Доступно карт для выбора: <b>{total_available}</b>.\n"
        f"Чтобы не ломать Telegram при большой коллекции, полный список здесь не отправляю.\n"
        f"Откройте /my_cards и скопируйте нужные ID.\n\n"
        f"🥅 Введите ID карточки для <b>ВРАТАРЯ</b>.\n"
        f"Для мутированной карты используйте формат <code>mINSTANCE_ID</code> из /my_cards.",
        parse_mode="HTML",
    )
    return RATING_TEAM_GK


async def rating_team_gk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    try:
        gk_ref = _parse_team_card_input(user.id, update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Укажите обычный ID карты или mINSTANCE_ID для мутированной карты.")
        return RATING_TEAM_GK
    context.user_data["rating_gk"] = gk_ref
    await update.message.reply_text(
        "⚔️ Теперь введите 5 карт для полевых игроков через запятую: 2 защитника и 3 нападающих. Можно смешивать обычные ID и мутированные mINSTANCE_ID.\n"
        "Пример: 2, m123456_777, 7, 12, 15"
    )
    return RATING_TEAM_FIELD


async def rating_team_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    raw = update.message.text.strip()
    parts = [x.strip() for x in raw.split(",") if x.strip()]
    if len(parts) != 5:
        await update.message.reply_text("❌ Нужно указать ровно 5 полевых карт через запятую: 2 защитника и 3 нападающих.")
        return RATING_TEAM_FIELD
    try:
        field_refs = [_parse_team_card_input(user.id, part) for part in parts]
    except Exception:
        await update.message.reply_text("❌ Используйте обычные ID или mINSTANCE_ID, например: 2, m123456_777, 7")
        return RATING_TEAM_FIELD
    gk_ref = context.user_data.get("rating_gk")
    all_refs = [gk_ref] + field_refs
    if len({str(x) for x in all_refs}) != 6:
        await update.message.reply_text("❌ Вратарь и все 5 полевых должны быть разными экземплярами. Попробуйте снова.")
        return RATING_TEAM_FIELD
    context.user_data["rating_field"] = field_refs
    await update.message.reply_text(
        "🧠 Теперь введите ID отдельной отдельной карточки-ТРЕНЕРА (обычный ID или mINSTANCE_ID, если тренер мутированный).\n"
        "Чем реже карта тренера, тем сильнее бафф его тактики.\n\n"
        "Или напишите «пропустить», чтобы собрать команду без тренера. Тренер — редкая отдельная карточка и может докупаться через магазинные паки."
    )
    return RATING_TEAM_COACH


async def rating_team_coach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    raw_text = update.message.text.strip()
    if raw_text.lower() in ("пропустить", "скип", "skip", "нет"):
        context.user_data["rating_coach"] = None
        context.user_data["rating_tactic"] = "balanced"
        await update.message.reply_text(
            "🧠 Команда сохранится без тренера — тактика будет недоступна до покупки/получения отдельной тренерской карточки.\n\n"
            "🏒 Придумайте НАЗВАНИЕ вашей команды (от 2 до 20 символов):"
        )
        return RATING_TEAM_NAME
    try:
        coach_ref = _parse_team_card_input(user.id, raw_text)
    except Exception:
        await update.message.reply_text("❌ Введите обычный ID отдельной карточки-тренера или mINSTANCE_ID, либо «пропустить».")
        return RATING_TEAM_COACH
    used = [context.user_data.get("rating_gk")] + list(context.user_data.get("rating_field", []))
    if str(coach_ref) in {str(x) for x in used}:
        await update.message.reply_text("❌ Тренер не может совпадать с картами состава. Выберите другую карту.")
        return RATING_TEAM_COACH
    context.user_data["rating_coach"] = coach_ref
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    card = _team_ref_card(user.id, coach_ref, card_map)
    bonus = round(get_coach_bonus(card.get("rarity", "")) * 100) if card else 3
    coach_name = _team_ref_name(user.id, coach_ref, card_map, html_safe=False)
    await update.message.reply_text(
        f"🧠 Тренер: {coach_name} ({card.get('rarity', '—') if card else '—'})\n"
        f"💪 Сила баффа тактики: {bonus}%\n\n"
        "Выберите ТАКТИКУ команды:\n\n"
        f"1️⃣ ⚔️ Нападение — +{bonus}% к шансу забить, но +{round(bonus * 0.8)}% к шансу пропустить\n"
        f"2️⃣ 🚌 Автобус — -{bonus}% к шансу пропустить, но -{round(bonus * 0.7)}% к шансу забить\n"
        f"3️⃣ ⚖️ Сбалансировано — +{round(bonus * 0.35)}% к шансу забить и -{round(bonus * 0.35)}% к шансу пропустить\n\n"
        "Отправьте цифру 1, 2 или 3."
    )
    return RATING_TEAM_TACTIC


async def rating_team_tactic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mapping = {"1": "attack", "2": "bus", "3": "balanced"}
    tactic = mapping.get(update.message.text.strip())
    if not tactic:
        await update.message.reply_text("❌ Отправьте 1 (нападение), 2 (автобус) или 3 (сбалансировано).")
        return RATING_TEAM_TACTIC
    context.user_data["rating_tactic"] = tactic
    await update.message.reply_text(
        f"✅ Тактика выбрана: {TACTIC_LABELS[tactic]}\n\n"
        "🏒 Придумайте НАЗВАНИЕ вашей команды (от 2 до 20 символов).\n"
        "Оно будет отображаться в матчах и на картинке состава!"
    )
    return RATING_TEAM_NAME

async def rating_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    team_name = update.message.text.strip()
    if len(team_name) < 3 or len(team_name) > 24:
        await update.message.reply_text("❌ Название команды должно быть от 3 до 24 символов. Попробуйте снова.")
        return RATING_TEAM_NAME
    gk_ref = context.user_data.get("rating_gk")
    field_refs = context.user_data.get("rating_field", [])
    coach_ref = context.user_data.get("rating_coach")
    tactic = context.user_data.get("rating_tactic", "balanced")
    set_rating_team(user.id, gk_ref, field_refs, coach_ref, tactic, team_name)
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    lines = [f"🥅 Вратарь: {_team_ref_name(user.id, gk_ref, card_map, html_safe=False)}"]
    for ref in field_refs:
        lines.append(f"⚔️ Полевой игрок: {_team_ref_name(user.id, ref, card_map, html_safe=False)}")
    if coach_ref:
        ccard = _team_ref_card(user.id, coach_ref, card_map)
        bonus = round(get_coach_bonus(ccard.get('rarity', '')) * 100) if ccard else 3
        lines.append(f"🧠 Тренер: {_team_ref_name(user.id, coach_ref, card_map, html_safe=False)} — {TACTIC_LABELS.get(tactic)} (бафф {bonus}%)")
    await update.message.reply_text(
        f"✅ Команда «{team_name}» сохранена!\n\n" + "\n".join(lines) +
        "\n\nТеперь используйте /find_match, чтобы найти соперника, и /rating, чтобы посмотреть состав."
    )
    for key in ("rating_gk", "rating_field", "rating_coach", "rating_tactic"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def cancel_rating_team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Составление команды отменено.")
    for key in ("rating_gk", "rating_field", "rating_coach", "rating_tactic"):
        context.user_data.pop(key, None)
    return ConversationHandler.END

def _load_team_font(size: int):
    """Шрифт с кириллицей. DroidSans-Bold -> NotoSans -> fallback."""
    _size = max(8, int(size))
    for path in (
        "/usr/share/fonts/google-droid-sans-fonts/DroidSans-Bold.ttf",
        "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "arialbd.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, _size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(_size)
    except Exception:
        return ImageFont.load_default()

def _draw_vertical_gradient(img, top_color, bottom_color):
    """Вертикальный градиент фона (1px колонка, растянутая на всю ширину)."""
    w, h = img.size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top_color, bottom_color)))
    img.paste(col.resize((w, h)))

def _short_card_name(name: str, max_len: int = 14) -> str:
    """Умное обрезание длинного имени карточки. Убирает скобки если длинно."""
    if len(name) <= max_len:
        return name
    # Пробуем убрать часть в скобках: "Нокс (Сборная России)" → "Нокс"
    import re as _re
    short = _re.sub(r'\s*\([^)]*\)', '', name).strip()
    if short and len(short) <= max_len:
        return short
    # Просто обрезаем
    return name[:max_len - 1] + '…'



# ==========================================================================
# HUD HELPERS — arena background, glassmorphism, glow text
# ═══════════════════════════════════════════════════════════════════════

def _arena_bg_2k(W: int = 2048, H: int = 2048):
    """Тёмный ледовый стадион 2048×2048: прожекторы, лёд, частицы, трибуны."""
    img = Image.new('RGBA', (W, H), (4, 8, 20, 255))
    draw = ImageDraw.Draw(img)
    # Вертикальный градиент
    step = 6
    for y in range(0, H, step):
        t = y / H
        f = max(0.0, 0.55 - abs(t - 0.38) * 1.6)
        r2 = int(4 + 14 * f); g2 = int(8 + 26 * f); b2 = int(20 + 55 * f)
        draw.rectangle([(0, y), (W, min(H, y + step))], fill=(r2, g2, b2, 255))
    # Прожекторы
    spot = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spot)
    beams = [(W//2,560,22),(W//4,330,13),(W*3//4,330,13),
             (W//8,185,8),(W*7//8,185,8),(W*3//8,250,9),(W*5//8,250,9)]
    for bx, sp, inten in beams:
        pts = [(bx-65,0),(bx+65,0),(bx+sp,int(H*0.68)),(bx-sp,int(H*0.68))]
        sd.polygon(pts, fill=(55, 135, 255, inten))
    img = Image.alpha_composite(img, spot)
    # Ледовое поле
    ice_y = int(H * 0.68)
    ice = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    id_ = ImageDraw.Draw(ice)
    for y in range(ice_y, H, 4):
        t2 = (y - ice_y) / (H - ice_y)
        c = int(8 + 32 * t2)
        id_.rectangle([(0, y), (W, y + 3)], fill=(c, c + 12, c + 32, 190 + int(65 * t2)))
    ry = ice_y + 80
    id_.line([(int(W*0.12), ry), (int(W*0.88), ry)], fill=(22,58,145,120), width=10)
    id_.line([(int(W*0.12), ry+16), (int(W*0.88), ry+16)], fill=(22,58,145,50), width=4)
    ccx, ccy = W//2, ice_y + 230
    id_.ellipse([ccx-280, ccy-110, ccx+280, ccy+110], outline=(22,55,140,130), width=12)
    id_.ellipse([ccx-55, ccy-55, ccx+55, ccy+55], fill=(22,55,140,60))
    id_.rectangle([W//2-140, ice_y+28, W//2+140, ice_y+80],
                  fill=(18,42,110,60), outline=(22,58,145,100), width=6)
    img = Image.alpha_composite(img, ice)
    # Частицы льда / снег
    part = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(part)
    import random as _rand
    rng = _rand.Random(42)
    for _ in range(600):
        px=rng.randint(0,W); py=rng.randint(0,ice_y)
        s=rng.randint(1,5); b3=rng.randint(140,255); a3=rng.randint(18,90)
        pd.ellipse([px-s,py-s,px+s,py+s], fill=(b3,b3+25,255,a3))
    for _ in range(100):
        px=rng.randint(0,W); py=rng.randint(0,int(H*0.42))
        s=rng.randint(4,10)
        pd.ellipse([px-s,py-s,px+s,py+s], fill=(180,220,255,rng.randint(12,40)))
    img = Image.alpha_composite(img, part)
    # Полосы трибун (сверху)
    trib = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(trib)
    for y in range(0, int(H*0.22), 12):
        a4 = int(22 - 16 * (y / (H*0.22)))
        td.line([(0, y), (W, y)], fill=(30,55,110,max(0,a4)), width=4)
    img = Image.alpha_composite(img, trib)
    # Неоновые горизонтальные линии
    neon = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neon)
    for ly, alpha5 in [(int(H*0.20), 38), (int(H*0.78), 38), (int(H*0.205), 18), (int(H*0.785), 18)]:
        nd.line([(int(W*0.05), ly), (int(W*0.95), ly)], fill=(0,185,255,alpha5), width=3)
    img = Image.alpha_composite(img, neon)
    # Финальное затемнение ~70%
    dark = Image.new('RGBA', (W, H), (0, 0, 5, 178))
    img = Image.alpha_composite(img, dark)
    return img.convert('RGB')


def _hud_glass(img_rgb, x1, y1, x2, y2, radius=28,
               fill=(10, 22, 60, 190), border=(45, 125, 240, 230),
               border_w=3, glow=(0, 160, 255)):
    """Glassmorphism панель с неоновым свечением. Возвращает RGB."""
    W2, H2 = img_rgb.size
    ovl = Image.new('RGBA', (W2, H2), (0, 0, 0, 0))
    od = ImageDraw.Draw(ovl)
    for g in range(14, 0, -3):
        gc = (*glow, int(48 * (14 - g + 1) / 14))
        try:
            od.rounded_rectangle([x1-g, y1-g, x2+g, y2+g],
                                 radius=radius + g // 2, outline=gc, width=2)
        except Exception:
            od.rectangle([x1-g, y1-g, x2+g, y2+g], outline=gc, width=2)
    try:
        od.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)
    except Exception:
        od.rectangle([x1, y1, x2, y2], fill=fill)
    try:
        od.rounded_rectangle([x1+6, y1+6, x2-6, y1+55], radius=radius, fill=(255,255,255,18))
    except Exception:
        pass
    bdr = (*border[:3], border[3] if len(border) > 3 else 230)
    try:
        od.rounded_rectangle([x1, y1, x2, y2], radius=radius, outline=bdr, width=border_w)
    except Exception:
        od.rectangle([x1, y1, x2, y2], outline=bdr, width=border_w)
    return Image.alpha_composite(img_rgb.convert('RGBA'), ovl).convert('RGB')


def _glow_ctext(img_rgb, text, cx, y, font, fill, glow_col=(0, 200, 255), glow_r=22):
    """Текст по центру cx с Gaussian-свечением. Возвращает (RGB, x)."""
    W2, H2 = img_rgb.size
    gl = Image.new('RGBA', (W2, H2), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    try:
        tw = gd.textlength(text, font=font)
    except Exception:
        tw = len(text) * max(getattr(font, 'size', 20), 20)
    x = cx - tw / 2
    gd.text((x, y), text, font=font, fill=(*glow_col, 255))
    gl = gl.filter(ImageFilter.GaussianBlur(radius=glow_r))
    result = Image.alpha_composite(img_rgb.convert('RGBA'), gl)
    rd = ImageDraw.Draw(result)
    rd.text((x, y), text, font=font, fill=fill)
    return result.convert('RGB'), x


def _hud_cx(draw, text, cx, y, font, fill):
    """Текст по центру cx на существующем draw."""
    try:
        tw = draw.textlength(text, font=font)
    except Exception:
        tw = len(text) * 18
    draw.text((cx - tw / 2, y), text, font=font, fill=fill)
    return tw


def _card_substats(ovr: int, rarity: str) -> dict:
    """Генерирует субстаты карточки из OVR + редкости (стабильно)."""
    import random as _rand2
    rng2 = _rand2.Random(ovr * 7 + hash(str(rarity)) % 997)
    def _s(off=0):
        return max(30, min(99, int(ovr + off + rng2.randint(-12, 12))))
    r3 = str(rarity).lower()
    if 'myth' in r3:   return {'ATK':_s(6),'DEF':_s(4),'SPD':_s(5),'STR':_s(3),'SHT':_s(7),'END':_s(3)}
    if 'legend' in r3: return {'ATK':_s(4),'DEF':_s(3),'SPD':_s(4),'STR':_s(2),'SHT':_s(5),'END':_s(2)}
    if 'epic' in r3:   return {'ATK':_s(2),'DEF':_s(1),'SPD':_s(2),'STR':_s(0),'SHT':_s(3),'END':_s(1)}
    if 'rare' in r3:   return {'ATK':_s(0),'DEF':_s(-1),'SPD':_s(1),'STR':_s(-1),'SHT':_s(1),'END':_s(0)}
    return {'ATK':_s(-3),'DEF':_s(-2),'SPD':_s(-3),'STR':_s(-4),'SHT':_s(-2),'END':_s(-3)}


def _rarity_glow_col(rarity: str) -> tuple:
    r4 = str(rarity).lower()
    if 'myth' in r4:   return (255, 70, 0)
    if 'legend' in r4: return (255, 195, 0)
    if 'epic' in r4:   return (165, 50, 255)
    if 'rare' in r4:   return (30, 120, 255)
    return (110, 130, 155)





def build_rating_team_image(user_id: int):
    """Премиальный постер состава /rating: арена, карточки, неон, читаемые статы."""
    if not PIL_AVAILABLE:
        return None
    team = get_rating_team(user_id)
    if not team:
        return None
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    gk_ref = team.get("gk")
    field_refs = list(team.get("field", []))[:4]
    coach_ref = team.get("coach")

    W, H = 1800, 2200
    img = _arena_bg_2k(W, H).convert('RGB')
    draw = ImageDraw.Draw(img)

    def F(sz): return _load_team_font(sz)
    def tw(text, font):
        try: return draw.textlength(str(text), font=font)
        except Exception: return len(str(text)) * sz * .55
    def center(text, cx, y, font, fill):
        try: w = draw.textlength(str(text), font=font)
        except Exception: w = len(str(text))*font.size*.55
        draw.text((cx-w/2, y), str(text), font=font, fill=fill)
    def fit(text, max_w, size, min_size=18):
        for sz in range(size, min_size-1, -2):
            f=F(sz)
            try: w=draw.textlength(str(text), font=f)
            except Exception: w=len(str(text))*sz*.55
            if w <= max_w: return f
        return F(min_size)
    def trim(text, font, max_w):
        text=str(text or '?')
        try:
            if draw.textlength(text,font=font)<=max_w: return text
        except Exception: pass
        while len(text)>2:
            text=text[:-1]
            cand=text.rstrip()+'…'
            try:
                if draw.textlength(cand,font=font)<=max_w: return cand
            except Exception: return cand
        return text[:1]+'…'

    # Header
    img = _hud_glass(img, 70, 55, W-70, 300, radius=42, fill=(8,18,45,215), border=(85,145,255,240), glow=(0,165,255))
    draw = ImageDraw.Draw(img)
    team_name = (team.get('name') or 'МОЯ КОМАНДА').upper()
    center('Хоккейные карточки  •  RATING LINEUP', W//2, 82, F(34), (88,220,255))
    center(trim(team_name, fit(team_name, W-220, 92, 40), W-220), W//2, 122, fit(team_name, W-220, 92, 40), (250,253,255))
    center('ледовая пятёрка готова к матчу', W//2, 230, F(28), (170,185,215))

    elo = get_rating_elo(user_id)
    _, rank_emoji, rank_name = get_rating_rank(elo)
    refs = [r for r in [gk_ref] + field_refs if r is not None]
    powers = [_team_ref_power(user_id, r, card_map) for r in refs]
    avg = round(sum(powers)/len(powers)) if powers else 0
    strength = int(_team_strength(team, card_map, user_id))
    stats=[(f'{rank_emoji} {rank_name}','РАНГ'),(str(elo),'ELO'),(str(avg),'AVG OVR'),(str(strength),'СИЛА')]
    x=95; y=335; gap=24; sw=(W-190-gap*3)//4
    for val,label in stats:
        img=_hud_glass(img,x,y,x+sw,y+118,radius=26,fill=(12,24,55,205),border=(72,130,235,220),border_w=2,glow=(40,170,255))
        draw=ImageDraw.Draw(img)
        center(trim(val, fit(val, sw-28, 42, 20), sw-28), x+sw//2, y+18, fit(val, sw-28, 42, 20), (255,255,255))
        center(label, x+sw//2, y+70, F(22), (158,174,205))
        x+=sw+gap

    def rarity_color(card, meta=None):
        if meta: return tuple(meta.get('color',(120,220,255)))
        r=str((card or {}).get('rarity','')).lower()
        if 'экск' in r: return (255,80,180)
        if 'леген' in r: return (255,205,70)
        if 'блещ' in r: return (105,235,255)
        if 'эпич' in r: return (180,95,255)
        if 'редк' in r: return (82,160,255)
        return (150,165,190)

    def card_block(ref, box, role):
        nonlocal img, draw
        x1,y1,x2,y2=box; cw=x2-x1; ch=y2-y1
        card=_team_ref_card(user_id, ref, card_map) or {}
        mut=_team_ref_mutation_instance(user_id, ref)
        meta=_get_mutation_meta(mut.get('mutation')) if mut else None
        col=rarity_color(card, meta)
        img=_hud_glass(img,x1,y1,x2,y2,radius=34,fill=(9,18,42,225),border=(*col,240),border_w=3,glow=col)
        draw=ImageDraw.Draw(img)
        art=(x1+18,y1+18,x2-18,y1+int(ch*.57))
        fn=str(card.get('image','')); fp=os.path.join(CARDS_IMAGE_DIR,fn)
        if fn and os.path.exists(fp):
            try:
                photo=Image.open(fp).convert('RGBA')
                photo=ImageOps.fit(photo,(art[2]-art[0],art[3]-art[1]),centering=(0.5,0.32))
                mask=Image.new('L',photo.size,0); md=ImageDraw.Draw(mask); md.rounded_rectangle((0,0,*photo.size),radius=22,fill=255)
                img.paste(photo,(art[0],art[1]),mask)
                if meta:
                    frame=Image.open(meta['frame_path']).convert('RGBA').resize(photo.size)
                    img.paste(frame,(art[0],art[1]),frame)
            except Exception:
                draw.rounded_rectangle(art,radius=22,fill=(26,39,75))
        else:
            draw.rounded_rectangle(art,radius=22,fill=(26,39,75)); center('NO IMAGE',(x1+x2)//2,y1+120,F(28),(170,185,215))
        draw.rectangle((x1+18, art[3]-8, x2-18, art[3]+4), fill=col)
        name=_team_ref_name(user_id, ref, card_map, html_safe=False)
        nf=fit(name,cw-42,34,16); center(trim(name,nf,cw-42),(x1+x2)//2,art[3]+28,nf,(255,255,255))
        power=_team_ref_power(user_id,ref,card_map)
        ovr='COACH' if role=='ТРЕНЕР' else f'OVR {power}'
        center(ovr,(x1+x2)//2,art[3]+78,F(48 if role!='ТРЕНЕР' else 42),(92,220,255) if role!='ТРЕНЕР' else (255,205,70))
        rarity=str(card.get('rarity','Обычная')).upper()
        if meta: rarity += ' • ' + str(meta.get('label','МУТАЦИЯ')).upper()
        center(trim(f'{role} • {rarity}', fit(f'{role} • {rarity}', cw-42, 20, 12), cw-42),(x1+x2)//2,y2-42,fit(f'{role} • {rarity}', cw-42, 20, 12),col)

    card_w, card_h = 500, 440
    positions=[(650,500,1150,940),(120,790,620,1230),(1180,790,1680,1230),(650,1085,1150,1525)]
    for ref,box in zip(field_refs,positions): card_block(ref,box,'ПОЛЕВОЙ')
    if gk_ref: card_block(gk_ref,(120,1580,820,2070),'ВРАТАРЬ')
    if coach_ref: card_block(coach_ref,(980,1580,1680,2070),'ТРЕНЕР')

    img=_hud_glass(img,120,2090,W-120,2170,radius=26,fill=(10,22,50,220),border=(85,145,255,220),border_w=2,glow=(0,160,255))
    draw=ImageDraw.Draw(img)
    tactic=TACTIC_PLAIN.get(team.get('tactic','balanced'),'Баланс')
    coach_name=_team_ref_name(user_id, coach_ref, card_map, html_safe=False) if coach_ref else 'без тренера'
    footer=f'Тренер: {coach_name}  •  Тактика: {tactic}'
    center(trim(footer, fit(footer,W-300,30,16), W-300), W//2, 2114, fit(footer,W-300,30,16), (245,247,252))
    out=io.BytesIO(); img.save(out,'PNG'); out.seek(0); return out


async def rating_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    elo = get_rating_elo(user.id)
    team = get_rating_team(user.id)
    if not team:
        await update.message.reply_text(
            f"⭐ Ваш рейтинг: {elo}\n{get_rating_rank(elo)[1]} Ранг: {get_rating_rank(elo)[2]}\n\n❌ У вас ещё нет состава. Используйте /rating_team, чтобы его создать."
        )
        return
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    upgrades = load_data(USERS_FILE, {}).get(str(user.id), {}).get("card_upgrades", {})
    def _member_line(icon, role, card_ref):
        card = _team_ref_card(user.id, card_ref, card_map)
        cid = int(card.get('id', -1)) if card else -1
        lvl = int(upgrades.get(str(cid), 0)) if cid >= 0 else 0
        lvl_text = f" ⭐ур.{lvl}" if lvl > 0 else ""
        return f"{icon} {role}: {_team_ref_name(user.id, card_ref, card_map, html_safe=False)} — сила {_team_ref_power(user.id, card_ref, card_map)}{lvl_text}"
    lines = [_member_line("🥅", "Вратарь", team["gk"])]
    for ref in team["field"]:
        lines.append(_member_line("⚔️", "Полевой", ref))
    coach_ref = team.get("coach")
    if coach_ref:
        ccard = _team_ref_card(user.id, coach_ref, card_map)
        cname = _team_ref_name(user.id, coach_ref, card_map, html_safe=False)
        cbonus = round(get_coach_bonus(ccard.get("rarity", "")) * 100) if ccard else 3
        ctactic = TACTIC_LABELS.get(team.get("tactic", "balanced"), "⚖️ Сбалансировано")
        lines.append(f"🧠 Тренер: {cname} - {ctactic} (бафф {cbonus}%)")
    strength = int(_team_strength(team, card_map, user.id))
    team_name = team.get("name")
    header = f"🏒 Команда: «{team_name}»\n" if team_name else ""
    _, rank_emoji, rank_name = get_rating_rank(elo)
    caption = header + f"⭐ Ваш рейтинг: {elo}\n{rank_emoji} Ранг: {rank_name}\n💪 Сила состава: {strength}\n\n" + "\n".join(lines)
    photo = None
    try:
        photo = build_rating_team_image(user.id)
    except Exception as e:
        logger.warning(f"Не удалось построить картинку состава: {e}")
    if photo:
        await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text(caption)


def _team_strength(team: dict, card_map: dict, owner_id=None) -> float:
    """Сила состава. Для мутированных карт учитывается бонус именно выбранного экземпляра."""
    def _power(card_ref):
        return _team_ref_power(owner_id, card_ref, card_map)
    gk_ref = team.get('gk')
    return _power(gk_ref) * 1.5 + sum(_power(ref) for ref in team.get('field', []))


async def _get_display_name(context: ContextTypes.DEFAULT_TYPE, user_id) -> str:
    if user_id is None:
        return "Бот-соперник"
    try:
        chat = await context.bot.get_chat(user_id)
        return f"@{chat.username}" if chat.username else f"Игрок {user_id}"
    except Exception:
        return f"Игрок {user_id}"

BOT_TEAM_NAMES = [
    "Ледяные Волки", "Стальные Акулы", "Полярные Медведи", "Снежные Барсы",
    "Северные Ястребы", "Гром Арены", "Красная Машина", "Ночные Пантеры",
]

def _generate_bot_team() -> dict:
    all_cards = load_data(CARDS_FILE, [])
    bot_name = random.choice(BOT_TEAM_NAMES)
    if len(all_cards) < 5:
        # На случай очень маленькой базы карточек - дублировать нельзя, но и падать не надо
        ids = [c["id"] for c in all_cards]
        while len(ids) < 4:
            ids.append(ids[0] if ids else 1)
        return {"gk": ids[0], "field": ids[1:4], "name": bot_name}
    chosen = random.sample(all_cards, 5)
    return {
        "gk": chosen[0]["id"],
        "field": [c["id"] for c in chosen[1:4]],
        "coach": chosen[4]["id"],
        "tactic": random.choice(["attack", "bus", "balanced"]),
        "name": bot_name,
    }

HIT_EVENTS = [
    "🖥 {player} ({team}) бросает в упор... НЕ РЕГНУЛО! Сервер не засчитал бросок!",
    "🌀 ФЛИНГ! Шайбу от {player} ({team}) отменяют после видеопросмотра — аномальная физика!",
    "📶 Лаг-гол от {player} ({team})? Судья идёт смотреть повтор... взятие ворот ОТМЕНЕНО!",
    "🧤 ЛАГ-СЕЙВ! Шайба телепортируется прямо в ловушку {gk} — скамейка {team} в шоке!",
    "💥 {player} ({team}) впечатывает соперника в борт — хит зарегистрирован сервером!",
    "🥊 {player} ({team}) получает 2 минуты за неспортивное поведение в чате!",
    "⚠️ У {player} ({team}) скакнул пинг до 900 — техническое предупреждение от судьи!",
    "🪑 {player} ({team}) ловит АФК посреди атаки — стопроцентный момент упущен!",
    "🔌 {player} ({team}) вылетает с сервера в решающий момент! Ждём реконнект...",
    "🕳 Шайба застревает в текстурах борта — вбрасывание в зоне {team}.",
    "🚫 Видеопросмотр: блокировка вратаря! Момент {player} ({team}) отменён.",
    "💺 {player} ({team}) флингует соперника через борт — 2+2 за грубость!",
    "🛰 Сервер лагнул — шайба у {player} ({team}) телепортируется в ловушку {gk}!",
    "⏱ {player} ({team}) пассивно катает шайбу — 2 минуты за задержку игры!",
    "🧱 {gk} стоит как каменная стена — бросок {player} намертво в ловушке!",
    "🦵 Подсечка! {player} ({team}) отправляется на скамейку штрафников.",
    "📺 Тренер {team} требует видеопросмотр... судьи подтверждают: гола НЕ БЫЛО!",
    "🎮 {player} ({team}) крутит финт с разворотом на 360°, но {gk} не ведётся!",
    "🏒 {player} ({team}) ломает клюшку об штангу — модель улетает за борт!",
    "⚡ Контратака {team}! {player} выходит 1 на 0, но {gk} читает буллит!",
    "🌪 {player} ({team}) закручивает шайбу из-за ворот — впритирку мимо девятки!",
    "🚧 Защитник ложится под бросок {player} ({team}) — шайба заблокирована!",
    "🎯 {player} ({team}) попадает в перекладину — DING на всю арену!",
    "🧲 {gk} магнитом снимает шайбу с ленточки после броска {player}!",
    "🥋 Жёсткая возня на пятаке — {player} ({team}) остаётся без шайбы!",
    "📉 Большинство не реализовано: {player} ({team}) мажет с пятака!",
    "🏒 {player} ({team}) выигрывает вбрасывание и создаёт момент у ворот {gk}!",
    "🎣 Финт {player} ({team}) не проходит — {gk} хладнокровен как бот (но не бот, это запрещено регламентом)!",
]
GOAL_EVENTS = [
    "🚨 ГОЛ! {player} ({team}) зажигает лампу — сервер ЗАРЕГАЛ бросок!",
    "⚡ {player} ({team}) щёлкает с синей — {gk} даже не дёрнулся! ГОЛ!",
    "🎯 Снайперский выстрел в девятку — {player} ({team}) забивает!",
    "🌀 ФЛИНГ-ГОЛ?! Судьи на видеопросмотре... ГОЛ ЗАСЧИТАН! {player} ({team}) ликует!",
    "📶 {gk} лагнул на долю секунды — {player} ({team}) наказывает мгновенно!",
    "🧠 Хитрющий буллит-финт: {player} ({team}) укладывает {gk} на лёд и заносит!",
    "🚀 {player} ({team}) разгоняется через всю площадку и прошивает {gk}!",
    "🥅 Добивание на пятаке — {player} ({team}) первым успевает на отскок!",
    "💫 Комбинация в одно касание — {player} ({team}) замыкает прострел!",
    "🪄 Лакросс-гол! {player} ({team}) поднимает шайбу на крюк и кладёт {gk} за шиворот!",
    "🎇 {player} ({team}) заносит шайбу вместе с {gk} — видеопросмотр подтверждает: ГОЛ!",
    "💣 Пушка от {player} ({team}) — шайба рвёт сетку, {gk} без шансов!",
    "🏹 {player} ({team}) бросает из-под защитника — {gk} закрыт, ГОЛ!",
    "🧊 {player} ({team}) выигрывает вбрасывание и забивает за две секунды!",
    "🌟 Соло-проход! {player} ({team}) обыгрывает всех и расписывается в воротах {gk}!",
    "🎆 {player} ({team}) хладнокровно кладёт в дальний угол — {gk} только разводит руками!",
    "🔥 {player} ({team}) добивает после лаг-сейва — на этот раз шайба РЕГНУЛАСЬ!",
]
NEUTRAL_EVENTS = [
    "🧊 Пауза: сервер пересчитывает физику льда.",
    "📶 У пары игроков подскочил пинг — судья ждёт стабилизации соединения.",
    "🗣 Тренер {team} берёт 30-секундный тайм-аут для перестроения.",
    "📺 Судьи разбирают спорный момент на видеоповторе — трибуны замерли.",
    "🪨 КАМЕННАЯ ШАЙБА! Судья останавливает игру и меняет игровой снаряд.",
    "📢 Диктор объявляет статистику бросков по воротам.",
    "🎶 Диджей арены врубает фонк — трибуны заводятся!",
    "🔄 {team} меняет пятёрку на лету.",
    "🩹 {player} ({team}) отряхивается после жёсткого хита и возвращается в игру.",
    "🖥 Офис лиги проверяет FFlags у игроков — всё чисто, играем дальше!",
    "🍿 Болельщики {team} спамят кричалки в чате арены!",
    "🎥 Оператор ловит крупный план {player} ({team}) для повтора на табло.",
    "⏸ Короткая пауза: игрок {team} перезаходит на сервер.",
    "🥶 Заливочная машина выезжает на лёд — 30 секунд перерыва.",
    "🎙 Комментатор отмечает бешеный темп сегодняшнего матча!",
    "📝 Статистики фиксируют очередной хит от {player} ({team}).",
    "🧤 {player} ({team}) меняет сломанную клюшку у скамейки запасных.",
]

def _pick_field_player(team: dict, card_map: dict, owner_id=None):
    """Выбирает полевого игрока с учётом силы и поддержкой мутированных экземпляров."""
    field_refs = list(team.get("field", []))
    weights = [max(1, _team_ref_power(owner_id, ref, card_map) if owner_id is not None else get_card_power(_team_ref_card(owner_id, ref, card_map))) for ref in field_refs]
    return random.choices(field_refs, weights=weights, k=1)[0]


def _card_name(card_ref, card_map: dict, owner_id=None, html_safe: bool = True) -> str:
    return _team_ref_name(owner_id, card_ref, card_map, html_safe=html_safe)


def _generate_period_events(team_a: dict, team_b: dict, card_map: dict, name_a: str, name_b: str, p_a: float, tempo: float = 1.0):
    """Генерирует события одного периода. Возвращает (events_text_list, goals_a, goals_b).

    tempo - "характер матча", выбирается случайно один раз на матч: в "закрытых"
    матчах голов мало, в "перестрелках" - много. Вместе со случайным числом
    событий и влиянием вратаря это даёт разные счета даже у одних и тех же соперников."""
    events = []
    goals_a = 0
    goals_b = 0
    num_events = random.randint(3, 8)
    for _ in range(num_events):
        acting_a = random.random() < p_a
        acting_team = team_a if acting_a else team_b
        defending_team = team_b if acting_a else team_a
        team_name = name_a if acting_a else name_b
        player_name = _card_name(_pick_field_player(acting_team, card_map), card_map)
        gk_name = _card_name(defending_team["gk"], card_map)

        # Шанс гола зависит от темпа матча и силы вратаря обороняющихся:
        # топовый вратарь заметно чаще спасает свою команду.
        gk_power = get_card_power(card_map.get(defending_team["gk"], {}))
        gk_factor = 1.25 - min(1.15, gk_power / 110.0) * 0.5
        goal_chance = max(0.06, min(0.5, 0.24 * tempo * gk_factor))

        roll = random.random()
        if roll < goal_chance:
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

# (Старая версия _simulate_match удалена: её всё равно переопределяла новая версия
# с важными событиями и минутами голов, объявленная ниже в файле.)

FIND_MATCH_COOLDOWN = 30  # секунд между запусками поиска (антиспам)
FIND_MATCH_TIMEOUT = 90   # секунд до отмены поиска

async def _search_timeout_cancel(context: ContextTypes.DEFAULT_TYPE, user_id: int, wait_seconds: int = FIND_MATCH_TIMEOUT):
    """Если за отведённое время соперник того же ранга не найден — поиск отменяется."""
    await asyncio.sleep(wait_seconds)
    queue = context.bot_data.setdefault("rating_queue", [])
    entry = next((q for q in queue if q["user_id"] == user_id), None)
    if not entry:
        return  # уже нашли соперника
    queue.remove(entry)
    try:
        await context.bot.send_message(
            user_id,
            "😔 <b>Поиск отменён.</b>\n\n"
            "За 90 секунд не нашлось соперника вашего ранга.\n"
            "Попробуйте позже — возможно, игроки вашего уровня сейчас офлайн: /find_match",
            parse_mode="HTML",
        )
    except Exception:
        pass

async def find_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    if not get_rating_team(user.id):
        await update.message.reply_text("❌ У вас нет состава. Сначала используйте /rating_team.")
        return
    ok_team, team_reason = validate_rating_team(user.id)
    if not ok_team:
        await update.message.reply_text(f"❌ Ваш состав устарел: {team_reason}. Пересоберите его через /rating_team.")
        return
    inj = team_injury(user.id)
    if inj:
        left=int((inj.get('until',0)-time.time())//60)+1
        await update.message.reply_text(f"🏥 Карта в составе травмирована: {inj.get('name','карта')}. Осталось {left} мин.")
        return

    queue = context.bot_data.setdefault("rating_queue", [])
    active_matches = context.bot_data.setdefault("active_matches", set())

    # Блок: уже идёт матч
    if user.id in active_matches:
        await update.message.reply_text("⚽ У вас уже идёт матч! Дождитесь его окончания, затем ищите снова.")
        return

    # Антиспам №1: уже в поиске — повторный запуск запрещён
    if any(q["user_id"] == user.id for q in queue):
        await update.message.reply_text("⏳ Вы уже ищете соперника. Дождитесь результата поиска.")
        return

    # Антиспам №2: кулдаун между запусками поиска
    cooldowns = context.bot_data.setdefault("find_match_cooldowns", {})
    now = time.time()
    elapsed = now - cooldowns.get(user.id, 0)
    if elapsed < FIND_MATCH_COOLDOWN:
        wait_left = int(FIND_MATCH_COOLDOWN - elapsed) + 1
        await update.message.reply_text(f"🕒 Не так быстро! Повторный поиск будет доступен через {wait_left} сек.")
        return
    cooldowns[user.id] = now

    my_elo = get_rating_elo(user.id)
    my_rank, rank_emoji, rank_name = get_rating_rank(my_elo)

    # Подбираем соперника ТОЛЬКО своего ранга
    opponent_entry = next((q for q in queue if q.get("rank") == my_rank), None)
    if opponent_entry:
        queue.remove(opponent_entry)
        await update.message.reply_text(f"⚔️ Соперник найден! Ранг: {rank_emoji} {rank_name}. Матч начинается прямо сейчас...")
        try:
            await context.bot.send_message(opponent_entry["user_id"], f"⚔️ Соперник найден! Ранг: {rank_emoji} {rank_name}. Матч начинается прямо сейчас...")
        except Exception:
            pass
        # Определяем чат для результата: если оба игрока вызывали из одного чата — используем его
        curr_chat = update.effective_chat.id if update.effective_chat and update.effective_chat.id != user.id else None
        opp_chat  = opponent_entry.get("chat_id")
        result_chat = curr_chat if curr_chat == opp_chat and curr_chat else (curr_chat or opp_chat)
        asyncio.create_task(_simulate_match(context, user.id, opponent_entry["user_id"], result_chat_id=result_chat))
    else:
        chat_id_of_call = update.effective_chat.id if update.effective_chat and update.effective_chat.id != user.id else None
        queue.append({"user_id": user.id, "joined": now, "rank": my_rank, "chat_id": chat_id_of_call})
        await update.message.reply_text(
            f"🔍 Ищем соперника вашего ранга: {rank_emoji} <b>{rank_name}</b> (рейтинг {my_elo})...\n\n"
            "⚖️ Подбираются только игроки того же ранга.\n"
            "⏳ Если за 90 секунд никто не найдётся — поиск отменится.",
            parse_mode="HTML",
        )
        asyncio.create_task(_search_timeout_cancel(context, user.id, FIND_MATCH_TIMEOUT))

# ============================ КОМАНДА /id ============================
async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает ваш Telegram ID или ищет ID игрока по @юзернейму (или юзернейм по ID)."""
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    args = context.args or []
    if not args:
        uname = f"@{user.username}" if user.username else "не задан"
        await update.message.reply_text(
            "🪪 <b>Ваши данные</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Юзернейм: {uname}\n\n"
            "💡 Узнать чей-то ID: <code>/id @юзернейм</code>",
            parse_mode="HTML",
        )
        return
    query = args[0].lstrip("@").strip()
    if not query:
        await update.message.reply_text("❌ Укажите юзернейм: /id @юзернейм")
        return
    users = load_data(USERS_FILE, {})
    # Если передали число — ищем юзернейм по ID
    if query.isdigit():
        target = users.get(query)
        if target is not None:
            uname = target.get("username")
            uname_text = f"@{uname}" if uname else "юзернейм не сохранён"
            await update.message.reply_text(
                f"🪪 Игрок с ID <code>{query}</code>: {uname_text}",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("❌ Игрок с таким ID не найден в базе бота.")
        return
    # Иначе ищем ID по юзернейму
    q_lower = query.lower()
    for uid, data in users.items():
        if (data.get("username") or "").lower() == q_lower:
            await update.message.reply_text(
                f"🪪 @{data.get('username')} — ID: <code>{uid}</code>",
                parse_mode="HTML",
            )
            return
    await update.message.reply_text(
        f"❌ Игрок @{html.escape(query)} не найден.\n"
        "ID можно узнать только у тех, кто хотя бы раз запускал бота."
    )

# ============================ ДУЭЛИ 1 НА 1 ============================
DUEL_MIN_BET = 10
DUEL_MAX_BET = 500
DUEL_COMMISSION = 0.10  # 10% банка сгорает (слив монет из экономики)
DUEL_EXPIRE_SECONDS = 300

def _duel_power(user_id: int):
    """Вспомогательная выборка топ-3 карточек для отображения в дуэли.
    Возвращает суммарную силу и подписи карточек, но на шанс победы это не влияет."""
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    card_ids = list(user_data.get("cards", [])) + list(get_locked_card_ids(user_id))
    if not card_ids:
        return 0, []
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    owned = [card_map[cid] for cid in set(card_ids) if cid in card_map]
    if not owned:
        return 0, []
    # Учитываем прокачку карт (/upgrade_card)
    def _p(c):
        return get_player_card_power(user_id, c["id"], card_map)
    owned.sort(key=_p, reverse=True)
    top = owned[:3]
    power = sum(_p(c) for c in top)
    labels = [html.escape(c['name']) for c in top]
    return power, labels

async def duel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Использование: /duel <ставка>\n"
            "🎲 Дуэль: победитель определяется честным рандомом 50/50.\n"
            f"💰 Ставка: от {DUEL_MIN_BET} до {DUEL_MAX_BET} монет. Комиссия с банка: {int(DUEL_COMMISSION * 100)}%."
        )
        return
    mode = context.args[1].lower() if len(context.args)>1 else "random"
    if mode not in ("random","bestof3","coin"): mode="random"
    try:
        bet = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Ставка должна быть числом.")
        return
    if bet < DUEL_MIN_BET or bet > DUEL_MAX_BET:
        await update.message.reply_text(f"❌ Ставка должна быть от {DUEL_MIN_BET} до {DUEL_MAX_BET} монет.")
        return
    if get_coins(user.id) < bet:
        await update.message.reply_text(f"❌ Недостаточно монет. У вас: {_fmt_coins(get_coins(user.id))}.")
        return
    power, _labels = _duel_power(user.id)
    if power <= 0:
        await update.message.reply_text("❌ У вас нет карточек для дуэли. Сначала получите карточки.")
        return

    duels = context.bot_data.setdefault("duels", {})
    duel_id = str(int(time.time() * 1000))
    duels[duel_id] = {
        "challenger": user.id,
        "challenger_name": user.first_name or f"Игрок {user.id}",
        "bet": bet,
        "mode": mode,
        "created": time.time(),
    }
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Принять дуэль", callback_data=f"duel_accept_{duel_id}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"duel_cancel_{duel_id}")],
    ])
    await update.message.reply_text(
        f"⚔️ <b>{html.escape(user.first_name or 'Игрок')} бросает вызов на дуэль на монеты!</b>\n\n"
        f"💰 Ставка: <b>{_fmt_coins(bet)}</b> монет с каждого\n"
        f"🎲 Победитель определяется честным рандомом 50/50\n"
        f"🏆 Победитель забирает банк (комиссия {int(DUEL_COMMISSION * 100)}%)\n\n"
        f"⏳ Вызов действует {DUEL_EXPIRE_SECONDS // 60} минут.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def duel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    duels = context.bot_data.setdefault("duels", {})

    if data.startswith("duel_cancel_"):
        duel_id = data[len("duel_cancel_"):]
        duel = duels.get(duel_id)
        if not duel:
            await query.answer("Дуэль уже неактуальна.", show_alert=True)
            return
        if query.from_user.id != duel["challenger"]:
            await query.answer("Отменить вызов может только его автор.", show_alert=True)
            return
        duels.pop(duel_id, None)
        await query.answer()
        try:
            await query.edit_message_text("❌ Дуэль отменена.")
        except Exception:
            pass
        return

    if not data.startswith("duel_accept_"):
        await query.answer()
        return

    duel_id = data[len("duel_accept_"):]
    duel = duels.get(duel_id)
    if not duel:
        await query.answer("Дуэль уже неактуальна.", show_alert=True)
        return
    acceptor = query.from_user
    challenger_id = duel["challenger"]
    bet = duel["bet"]
    mode = duel.get("mode","random")
    if acceptor.id == challenger_id:
        await query.answer("Нельзя принять собственный вызов.", show_alert=True)
        return
    if is_banned(acceptor.id):
        await query.answer("Вы заблокированы в этом боте.", show_alert=True)
        return
    if time.time() - duel["created"] > DUEL_EXPIRE_SECONDS:
        duels.pop(duel_id, None)
        await query.answer("Вызов истёк.", show_alert=True)
        try:
            await query.edit_message_text("⌛ Дуэль истекла - никто не принял вызов.")
        except Exception:
            pass
        return
    if get_coins(acceptor.id) < bet:
        await query.answer(f"Недостаточно монет: нужно {bet}.", show_alert=True)
        return
    if get_coins(challenger_id) < bet:
        duels.pop(duel_id, None)
        await query.answer("У автора вызова уже не хватает монет - дуэль отменена.", show_alert=True)
        try:
            await query.edit_message_text("❌ Дуэль отменена: у автора вызова не хватает монет.")
        except Exception:
            pass
        return
    power_b, cards_b = _duel_power(acceptor.id)
    if power_b <= 0:
        await query.answer("У вас нет карточек для дуэли.", show_alert=True)
        return

    # Снимаем дуэль из списка до расчётов (защита от двойного клика)
    duels.pop(duel_id, None)
    await query.answer()

    power_a, cards_a = _duel_power(challenger_id)
    update_coins(challenger_id, -bet)
    update_coins(acceptor.id, -bet)

    name_a = html.escape(duel.get("challenger_name") or f"Игрок {challenger_id}")
    name_b = html.escape(acceptor.first_name or f"Игрок {acceptor.id}")

    try:
        await query.edit_message_text(
            f"⚔️ <b>{name_a} 🆚 {name_b}</b>\n\n⏳ Определяем победителя...",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await asyncio.sleep(2)

    # Дуэль: строго 50/50, карточки не дают преимуществ
    challenger_wins = random.random() < 0.5
    winner_id = challenger_id if challenger_wins else acceptor.id
    winner_name = name_a if challenger_wins else name_b

    pot = bet * 2
    commission = int(pot * DUEL_COMMISSION)
    win_amount = pot - commission
    update_coins(winner_id, win_amount)
    # квесты и статистика дуэлей
    try:
        r1 = inc_stat(challenger_id, 'duel_played', 1)
        r2 = inc_stat(acceptor.id, 'duel_played', 1)
        r3 = inc_stat(winner_id, 'duel_wins', 1)
        await _notify_quest_rewards(context, challenger_id, r1)
        await _notify_quest_rewards(context, acceptor.id, r2)
        await _notify_quest_rewards(context, winner_id, r3)
    except Exception as _qe:
        logger.warning(f'quest duel stat error: {_qe}')

    result_text = (
        f"⚔️ <b>Дуэль: {name_a} 🆚 {name_b}</b>\n\n"
        f"🏆 <b>Победитель: {winner_name}!</b>\n"
        f"💰 Выигрыш: <b>{_fmt_coins(win_amount)}</b> монет (банк {_fmt_coins(pot)}, комиссия {_fmt_coins(commission)})"
    )
    try:
        await query.edit_message_text(result_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить результат дуэли: {e}")

# ============================ СИСТЕМА КЛАНОВ ============================
async def create_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
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
        await update.message.reply_text(subscription_required_text())
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
        f"⬆️ Прокачка баффа: ур. {upgrade_lvl}/10",
        (f"💰 До следующего улучшения: {_fmt_coins(CLAN_UPGRADE_COSTS.get(upgrade_lvl + 1))} монет в казне" if CLAN_UPGRADE_COSTS.get(upgrade_lvl + 1) else "🏁 Достигнут максимальный уровень клана (10)"),
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
            {"id": 1, "name": "Тумба", "rarity": "Легендарная", "image": "tumba.png", "description": "x2 Чемпион Хоккейные карточки"},
            {"id": 2, "name": "Тимахез", "rarity": "Редкая", "image": "tima.png", "description": "Тимакез дота 2"},
            {"id": 3, "name": "Казума", "rarity": "Эпическая", "image": "kazuma.png", "description": "Алкаш"},
            {"id": 4, "name": "Китаец", "rarity": "Обычная", "image": "kitaec.png", "description": "Узкоглазый"}
        ])

    # Создаём файлы, если их нет
    for f in [USERS_FILE, BLACKLIST_FILE, MODERATORS_FILE, COINS_FILE, SHOP_FILE, PROMOCODES_FILE, EVENTS_FILE, BETS_FILE, CLANS_FILE, ISSUED_PROMO_CODES_FILE, REFERRALS_FILE, GIVEAWAYS_FILE]:
        if not os.path.exists(f):
            if f in [BLACKLIST_FILE, MODERATORS_FILE, SHOP_FILE, EVENTS_FILE, BETS_FILE, CLANS_FILE, GIVEAWAYS_FILE]:
                save_data(f, [])
            else:
                save_data(f, {})

    if not os.path.exists(COSMETIC_SHOP_FILE):
        save_data(COSMETIC_SHOP_FILE, {})
    if not os.path.exists(REPORTS_FILE):
        save_data(REPORTS_FILE, [])

    # Инициализация редкостей
    if not os.path.exists(RARITIES_FILE):
        save_data(RARITIES_FILE, [
            {"name": "Легендарная", "emoji": "🔥", "droppable": True},
            {"name": "Мифическая", "emoji": "🧠", "droppable": True},
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
                {"name": "Мифическая", "emoji": "🧠", "droppable": True},
                {"name": "Эпическая", "emoji": "💎", "droppable": True},
                {"name": "Редкая", "emoji": "✨", "droppable": True},
                {"name": "Обычная", "emoji": "🃏", "droppable": True},
                {"name": "Эксклюзивная", "emoji": "😎", "droppable": False}
            ]
            save_data(RARITIES_FILE, default_rarities)
            logger.warning("Файл редкостей был пуст или не содержал выпадаемых – пересоздан.")

    application = Application.builder().token(TOKEN).post_init(_post_init).build()
    application.add_error_handler(global_error_handler)

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
            CommandHandler("giveaway", giveaway_start),
            CommandHandler("update", update_bot_start),
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
            RATING_TEAM_COACH: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_coach)],
            RATING_TEAM_TACTIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_tactic)],
            RATING_TEAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_team_name)],
            PROMO_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_name)],
            PROMO_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_type)],
            PROMO_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_value)],
            PROMO_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_uses)],
            PROMO_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_duration)],
            SEASON_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_number)],
            SEASON_PRIZE_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_prize_1)],
            SEASON_PRIZE_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_prize_2)],
            SEASON_PRIZE_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, season_prize_3)],
            GIVEAWAY_WINNERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, giveaway_winners_count)],
            GIVEAWAY_PRIZES: [MessageHandler(filters.TEXT & ~filters.COMMAND, giveaway_prizes)],
            GIVEAWAY_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, giveaway_end_condition)],
            UPDATE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_bot_token)],
            UPDATE_FILE: [MessageHandler(filters.Document.ALL, update_bot_file)],
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
    application.add_handler(CommandHandler("offer_sell", offer_sell))
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
    application.add_handler(CommandHandler("profile_custom", profile_custom_cmd))
    application.add_handler(CommandHandler("profile_bg", profile_bg_cmd))
    application.add_handler(CommandHandler("profile_frame", profile_frame_cmd))
    application.add_handler(CommandHandler("profile_badge", profile_badge_cmd))
    application.add_handler(CommandHandler("profile_showcase", profile_showcase_cmd))
    application.add_handler(CommandHandler("cosmetic_shop", cosmetic_shop_cmd))
    application.add_handler(CommandHandler("buy_cosmetic", buy_cosmetic_cmd))
    application.add_handler(CommandHandler("my_cosmetics", my_cosmetics_cmd))
    application.add_handler(CommandHandler("titles", titles_cmd))
    application.add_handler(CommandHandler("quests", quests_cmd))
    application.add_handler(CommandHandler("pity", pity_cmd))
    application.add_handler(CommandHandler("injuries", injuries_cmd))
    application.add_handler(CommandHandler("notifications", notifications_cmd))
    application.add_handler(CommandHandler("create_match", create_match))
    application.add_handler(CommandHandler("finish_match", finish_match))
    application.add_handler(CommandHandler("my_bets", my_bets))
    application.add_handler(CommandHandler("view_matches", view_matches))
    application.add_handler(CommandHandler("ref", referral_info))
    application.add_handler(CommandHandler("upgrade_card", upgrade_card))
    application.add_handler(CommandHandler("find_match", find_match))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("duel", duel_start))
    application.add_handler(CommandHandler("cancel_trade", cancel_trade))
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
    application.add_handler(CommandHandler("history", history_cmd))
    application.add_handler(CommandHandler("security", security_cmd))
    application.add_handler(CommandHandler("report", report_cmd))
    application.add_handler(CommandHandler("reply_report", reply_report_cmd))
    application.add_handler(CommandHandler("admin", admin_commands_list))
    application.add_handler(CommandHandler("giveaways", giveaways_list))

    # CallbackQueryHandler'ы
    application.add_handler(CallbackQueryHandler(admin_shop_type, pattern=r"^(reset|pack)"))
    application.add_handler(CallbackQueryHandler(set_buff_buttons, pattern=r"^(confirm_set_buff_|cancel_set_buff)"))
    application.add_handler(CallbackQueryHandler(upgrade_buff_buttons, pattern=r"^(confirm_upgrade_buff|cancel_upgrade_buff)"))
    application.add_handler(CallbackQueryHandler(bet_match_callback, pattern=r"^bet_match_"))
    application.add_handler(CallbackQueryHandler(duel_callback, pattern=r"^duel_"))
    application.add_handler(CallbackQueryHandler(bet_outcome_callback, pattern=r"^bet_outcome_"))
    application.add_handler(CallbackQueryHandler(trade_callbacks, pattern=r"^trade_"))
    application.add_handler(CallbackQueryHandler(market_buy_callback, pattern=r"^market_buy_"))
    application.add_handler(CallbackQueryHandler(market_page_callback, pattern=r"^market_page_"))
    application.add_handler(CallbackQueryHandler(events_callbacks, pattern=r"^evt_"))
    application.add_handler(CallbackQueryHandler(giveaway_join_callback, pattern=r"^gw_join_"))

    # Обработка обновлений голосований (ручная/автоматическая остановка)
    application.add_handler(PollHandler(poll_update_handler))

    # Кнопки красивой клавиатуры (точное совпадение текста кнопки)
    # Хэндлер бонусного чата — должен стоять выше остальных
    application.add_handler(MessageHandler(filters.ALL & filters.Chat(BONUS_CHAT_ID), handle_chat_activity), group=1)
    application.add_handler(MessageHandler(filters.Text(ALL_KEYBOARD_BUTTONS), keyboard_button_handler))

    # MessageHandler для текстового ввода (ставки, обмен, события)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    # Проверка подписки (обрабатывает оставшиеся сообщения)
    application.add_handler(MessageHandler(filters.ALL, check_subscription))

    # Явно запрашиваем все типы апдейтов, чтобы гарантированно получать Poll-апдейты.
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, close_loop=False)


# ============================ ОБНОВЛЕНИЕ ЭКОНОМИКИ / РЕЙТИНГА 2026 ============================

def _json_contains_user(value, uid: str) -> bool:
    if isinstance(value, dict):
        return any(str(k) == uid or _json_contains_user(v, uid) for k, v in value.items())
    if isinstance(value, list):
        return any(_json_contains_user(v, uid) for v in value)
    return str(value) == uid

def _is_pristine_user(user_id: int) -> bool:
    """Игрок считается новым только если его ID отсутствует во всех игровых хранилищах."""
    uid = str(user_id)
    for filename in (USERS_FILE, COINS_FILE, BETS_FILE, MARKET_FILE, TRADES_FILE, CLANS_FILE, BLACKLIST_FILE, REFERRALS_FILE):
        if _json_contains_user(load_data(filename, {} if filename not in (BETS_FILE, MARKET_FILE, TRADES_FILE, CLANS_FILE, BLACKLIST_FILE) else []), uid):
            return False
    return True

def _referral_link(user_id: int) -> str:
    # Username определяется Telegram автоматически из deep-link в BotFather.
    username = os.environ.get('BOT_USERNAME', 'YOUR_BOT_USERNAME').lstrip('@')
    return "https://t.me/" + username + f"?start=ref_{user_id}"

async def finalize_referral_after_first_card(user, context):
    """Выплата строго один раз после первой сохранённой карточки нового игрока."""
    refs = load_data(REFERRALS_FILE, {})
    row = refs.get(str(user.id))
    if not row or row.get('status') != 'pending' or row.get('rewarded'):
        return
    inviter = row.get('inviter_id')
    # Telegram не предоставляет возраст аккаунта. Поэтому доступны и применяются
    # надёжные серверные признаки: новый ID во всех JSON, не self-ref, не bot,
    # подписка (проверена до /get_card), живая карточка и одноразовый журнал.
    valid = (isinstance(inviter, int) and inviter != user.id and not user.is_bot and
             bool(user.first_name or user.username) and str(inviter) in load_data(USERS_FILE, {}))
    row['first_card_at'] = time.time()
    if valid:
        update_coins(inviter, REFERRAL_REWARD)
        row.update({'status':'rewarded','rewarded':True,'rewarded_at':time.time()})
        try: await context.bot.send_message(inviter, f"🎉 Друг выполнил условия реферала. Вам начислено {REFERRAL_REWARD} монет!")
        except Exception: pass
    else:
        row['status'] = 'rejected'
    refs[str(user.id)] = row
    save_data(REFERRALS_FILE, refs)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте."); return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text() + "\nЗатем повторите /start."); return
    pristine = _is_pristine_user(user.id)
    users = load_data(USERS_FILE, {})
    if pristine:
        users[str(user.id)] = {"cards": [], "last_drop": 0, "username": user.username, "casino_streak": 0, "coin_streak": 0, "seen_cards": [], "joined_at": time.time()}
        save_data(USERS_FILE, users)
        coins=load_data(COINS_FILE,{ }); coins.setdefault(str(user.id),0); save_data(COINS_FILE,coins)
        if not is_admin(user.id) and not is_moderator(user.id):
            try:
                await context.bot.send_message(ADMIN_ID, f"Новый пользователь: @{user.username} | ID: {user.id}")
            except Exception as e:
                logger.error(f"Не удалось уведомить администратора о новом пользователе: {e}")
        payload = context.args[0] if context.args else ''
        if payload.startswith('ref_'):
            try: inviter=int(payload[4:])
            except ValueError: inviter=None
            if inviter and inviter != user.id and str(inviter) in users:
                refs=load_data(REFERRALS_FILE,{})
                if str(user.id) not in refs:
                    refs[str(user.id)]={"inviter_id":inviter,"joined_at":time.time(),"status":"pending","rewarded":False,"first_card_at":None}
                    save_data(REFERRALS_FILE,refs)
    else:
        # Бэкфилл полей для старых аккаунтов (как в старой версии /start)
        user_data = users.get(str(user.id))
        if user_data is not None:
            user_data.setdefault("casino_streak", 0)
            user_data.setdefault("coin_streak", 0)
            user_data.setdefault("seen_cards", [])
            user_data.setdefault("username", user.username)
            users[str(user.id)] = user_data
            save_data(USERS_FILE, users)

    # Меню в классическом стиле: у обычных игроков — свои команды,
    # у администратора и модераторов — дополнительно свой набор.
    # ВАЖНО: тексты команд содержат плейсхолдеры вида "card_id" в угловых скобках.
    # При parse_mode="HTML" Telegram пытается разобрать их как теги и падает,
    # поэтому текст экранируем через html.escape(), а настоящие теги <b> добавляем уже поверх.
    if is_admin(user.id):
        # Админ видит в /start только обычные команды.
        # Полный список админских команд вынесен в отдельную команду /admin.
        await update.message.reply_text(
            "👑 Вы администратор.\n"
            "📋 Полный список админских команд: /admin\n\n"
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
        # Обычный игрок видит ТОЛЬКО игровые команды (никакого управления ставками).
        # В личке сразу включаем удобную клавиатуру с командами.
        kb = get_main_keyboard() if update.effective_chat.type == "private" else None
        await update.message.reply_text(
            "🎮 Добро пожаловать в Хоккейные карточки!\n\n" + USER_COMMANDS_TEXT,
            reply_markup=kb
        )

async def admin_commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /admin — полный список админских команд (модератору — его список)."""
    user = update.effective_user
    if is_admin(user.id):
        await update.message.reply_text(
            "👑 <b>Админские команды:</b>\n\n" + html.escape(ADMIN_ONLY_COMMANDS_TEXT),
            parse_mode="HTML"
        )
    elif is_moderator(user.id):
        await update.message.reply_text(
            "🛡 <b>Модераторские команды:</b>\n\n" + html.escape(MODERATOR_ONLY_COMMANDS_TEXT),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")

async def referral_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user=update.effective_user; refs=load_data(REFERRALS_FILE,{})
    try:
        bot_username = (await context.bot.get_me()).username
    except Exception:
        bot_username = os.environ.get('BOT_USERNAME', 'YOUR_BOT_USERNAME')
    link = 'https://t.me/' + str(bot_username).lstrip('@') + f'?start=ref_{user.id}'
    mine=[r for r in refs.values() if r.get('inviter_id')==user.id]
    rewarded=sum(1 for r in mine if r.get('status')=='rewarded')
    pending=sum(1 for r in mine if r.get('status') in ('pending','waiting_validation'))
    await update.message.reply_text(
        f"🔗 <b>Реферальная программа</b>\n\nВаша ссылка:\n<code>{html.escape(link)}</code>\n\n"
        f"👥 Приглашено: {len(mine)}\n✅ Подтверждено: {rewarded}\n⏳ На проверке: {pending}\n🎁 Получено: {rewarded * REFERRAL_REWARD} монет\n\n"
        "Бонус 50 монет начисляется только один раз после: новый ID отсутствовал во всех игровых JSON, приглашение не от себя, аккаунт не бот, есть профиль, игрок подписан на канал и получил первую карту. Повторные выплаты блокируются журналом рефералов.", parse_mode='HTML')

async def view_matches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text('❌ Только для администратора и модераторовв.'); return
    events=load_data(EVENTS_FILE,[]); now=time.time()
    if not events: await update.message.reply_text('📭 Матчей для ставок нет.'); return
    lines=['🏒 <b>Матчи для ставок</b>\n']
    for e in sorted(events,key=lambda x:x.get('id',0),reverse=True)[:30]:
        state='🟢 открыт' if e.get('status')=='active' and e.get('deadline',0)>now else ('⌛ приём закрыт' if e.get('status')=='active' else '🏁 завершён')
        deadline=datetime.fromtimestamp(e.get('deadline',0)).strftime('%d.%m %H:%M')
        lines.append(f"#{e['id']} {html.escape(e['team1'])} — {html.escape(e['team2'])}: {state}; до {deadline}; счёт: {e.get('score') or '—'}")
    await update.message.reply_text('\n'.join(lines),parse_mode='HTML')

def get_player_card_power(user_id:int, card_id:int, card_map:dict)->int:
    card=card_map.get(card_id,{})
    base=get_card_power(card)
    # Потолок тоже зависит от шанса редкости, чтобы кастомные редкости работали честно.
    cap=min(140, base+35)
    level=load_data(USERS_FILE,{}).get(str(user_id),{}).get('card_upgrades',{}).get(str(card_id),0)
    return min(cap, base+max(0,int(level))*2)

async def upgrade_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user=update.effective_user
    if is_banned(user.id):
        await update.message.reply_text('❌ Вы заблокированы в этом боте.'); return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text()); return
    if not context.args:
        await update.message.reply_text(
            'ℹ️ <b>Прокачка карт</b>\n'
            'Использование: /upgrade_card ID_карточки\n\n'
            'Слияние с дубликатами: тратится N дубликатов (N = следующий уровень), '
            'карта остаётся той же (тот же ID), но получает +2 силы за уровень до потолка своей редкости.\n'
            'Уровень виден в /my_cards, /card_info, /rating и учитывается в рейтинговых матчах и дуэлях.',
            parse_mode='HTML'
        )
        return
    try: cid=int(context.args[0])
    except ValueError: await update.message.reply_text('❌ Укажите числовой ID.'); return
    users=load_data(USERS_FILE,{}); data=users.get(str(user.id),{}); cards=data.get('cards',[]); db={c['id']:c for c in load_data(CARDS_FILE,[])}; card=db.get(cid)
    if not card: await update.message.reply_text('❌ Карточка не найдена.'); return
    if cid not in cards:
        await update.message.reply_text('❌ У вас нет этой карточки в коллекции!'); return
    level=int(data.get('card_upgrades',{}).get(str(cid),0)); base=get_card_power(card); cap=get_card_rating_cap(card)
    if base+level*2>=cap:
        await update.message.reply_text(f"✅ «{card['name']}» уже прокачана до максимума своей редкости (сила {min(cap, base + level * 2)}, потолок {cap})."); return
    cost=level+1
    have=cards.count(cid)
    if have<cost+1:
        await update.message.reply_text(
            f"❌ Для уровня {level + 1} нужны основная карта + {cost} дубликат(а) для слияния.\n"
            f"У вас сейчас копий: {have}. Не хватает: {cost + 1 - have}.\n"
            f"ℹ️ Копии на маркете или на работе не считаются."
        ); return
    # Слияние: удаляем ровно cost дубликатов, основная карта (тот же ID) остаётся.
    # Уровень хранится отдельно в card_upgrades — размножение карт невозможно.
    for _ in range(cost): cards.remove(cid)
    data['cards']=cards; data.setdefault('card_upgrades',{})[str(cid)]=level+1; users[str(user.id)]=data; save_data(USERS_FILE,users)
    new_power=min(cap,base+(level+1)*2)
    await update.message.reply_text(
        f"⬆️ <b>{html.escape(card['name'])}</b> улучшена до уровня <b>{level + 1}</b>!\n"
        f"💪 Сила: {min(cap, base + level * 2)} → <b>{new_power}</b> (потолок редкости: {cap})\n"
        f"🎴 Потрачено дубликатов: {cost}\n\n"
        f"Прокачка видна в /my_cards, /card_info, /rating и учитывается в рейтинговых матчах и дуэлях.",
        parse_mode='HTML'
    )



def build_match_result_image(name_a, name_b, goals_a, goals_b, periods,
                             scorers=None, coaches=None, stats=None,
                             elo_old=None, elo_new=None, won=None):
    """Премиальная финальная сирена: крупный табло-постер, MVP, голы и статистика."""
    if not PIL_AVAILABLE:
        return None
    scorers=scorers or []; stats=stats or []
    W,H=1800,2200
    img=_arena_bg_2k(W,H).convert('RGB')
    draw=ImageDraw.Draw(img)
    def F(sz): return _load_team_font(sz)
    def wtxt(t,f):
        try: return draw.textlength(str(t),font=f)
        except Exception: return len(str(t))*getattr(f,'size',24)*.55
    def center(t,cx,y,f,fill): draw.text((cx-wtxt(t,f)/2,y),str(t),font=f,fill=fill)
    def fit(t,maxw,sz,minsz=16):
        for s2 in range(sz,minsz-1,-2):
            f=F(s2)
            if wtxt(t,f)<=maxw: return f
        return F(minsz)
    def trim(t,f,maxw):
        t=str(t or '?').replace('@','').strip() or '?'
        if wtxt(t,f)<=maxw: return t
        while len(t)>2:
            t=t[:-1]; c=t.rstrip()+'…'
            if wtxt(c,f)<=maxw: return c
        return t[:1]+'…'
    def clean(t): return str(t or '?').replace('@','').strip() or '?'
    a,b=clean(name_a),clean(name_b)
    win_name = b if goals_b>goals_a else (a if goals_a>goals_b else 'НИЧЬЯ')

    img=_hud_glass(img,70,55,W-70,295,radius=44,fill=(8,18,45,220),border=(85,145,255,245),glow=(0,165,255))
    draw=ImageDraw.Draw(img)
    center('РЕЙТИНГОВЫЙ МАТЧ',W//2,82,F(38),(170,185,215))
    center('ФИНАЛЬНАЯ СИРЕНА',W//2,124,F(84),(255,255,255))
    center('Хоккейные карточки',W//2,218,F(30),(88,220,255))

    img=_hud_glass(img,95,335,W-95,760,radius=42,fill=(10,20,48,230),border=(80,135,245,240),glow=(0,160,255))
    draw=ImageDraw.Draw(img)
    lf=fit(a,520,50,22); rf=fit(b,520,50,22)
    center(trim(a,lf,520),380,380,lf,(255,255,255)); center(trim(b,rf,520),1420,380,rf,(255,255,255))
    center(str(goals_a),380,470,F(170),(255,255,255)); center(':',W//2,500,F(120),(160,176,205)); center(str(goals_b),1420,470,F(170),(255,255,255))
    res='НИЧЬЯ' if goals_a==goals_b else f'ПОБЕДА • {win_name}'
    center(trim(res,fit(res,W-260,54,24),W-260),W//2,665,fit(res,W-260,54,24),(255,205,70))

    y=800
    if elo_old is not None and elo_new is not None:
        delta=elo_new-elo_old; dtext=f'+{delta}' if delta>=0 else str(delta)
        img=_hud_glass(img,95,y,W-95,y+125,radius=28,fill=(12,25,55,220),border=(80,210,130,230) if delta>=0 else (255,100,110,230),glow=(80,210,130) if delta>=0 else (255,80,90))
        draw=ImageDraw.Draw(img)
        center(dtext,320,y+18,F(56),(95,235,130) if delta>=0 else (255,115,120)); center('ИЗМЕНЕНИЕ',320,y+78,F(22),(165,180,210))
        center(str(elo_new),W//2,y+18,F(56),(255,255,255)); center('ELO',W//2,y+78,F(22),(165,180,210))
        center('ПОБЕДА' if won else 'ПОРАЖЕНИЕ',1470,y+34,F(36),(255,205,70) if won else (255,115,120))
        y+=155
    period_line=[]; tags=['П1','П2','П3','ОТ','БУЛ']
    for i,p in enumerate(periods or []): period_line.append(str(p) if str(p).upper() in ('ОТ','БУЛ') else f'{tags[i] if i<len(tags) else "П"+str(i+1)} {p}')
    pl=' • '.join(period_line[:6]) or 'Периоды недоступны'
    img=_hud_glass(img,95,y,W-95,y+82,radius=24,fill=(12,25,55,220),border=(80,135,245,220),glow=(0,160,255)); draw=ImageDraw.Draw(img)
    center(trim(pl,fit(pl,W-250,32,16),W-250),W//2,y+22,fit(pl,W-250,32,16),(245,247,252)); y+=112

    if scorers:
        from collections import Counter
        best,cnt=Counter(s for _,s,_,_ in scorers).most_common(1)[0]
        mvp=f'ЛУЧШИЙ ИГРОК • {best} • {cnt} гол' + ('а' if 1<cnt<5 else '')
        img=_hud_glass(img,95,y,W-95,y+94,radius=24,fill=(38,30,12,220),border=(255,205,70,235),glow=(255,180,40)); draw=ImageDraw.Draw(img)
        center(trim(mvp,fit(mvp,W-250,36,18),W-250),W//2,y+26,fit(mvp,W-250,36,18),(255,215,90)); y+=124

    rows=[f"{int(m):02d}'  {clean(t)}  •  {s}  •  {sc}" for m,s,t,sc in scorers[:7]] or ['Голы не зафиксированы']
    h=90+len(rows)*44
    img=_hud_glass(img,95,y,W-95,y+h,radius=28,fill=(10,22,50,225),border=(80,135,245,225),glow=(0,160,255)); draw=ImageDraw.Draw(img)
    center('АВТОРЫ ГОЛОВ',W//2,y+22,F(34),(88,220,255))
    for i,r in enumerate(rows): center(trim(r,fit(r,W-260,25,14),W-260),W//2,y+72+i*44,fit(r,W-260,25,14),(245,247,252))
    y+=h+35

    if stats:
        img=_hud_glass(img,95,y,W-95,2035,radius=32,fill=(10,22,50,225),border=(80,135,245,225),glow=(0,160,255)); draw=ImageDraw.Draw(img)
        center('СТАТИСТИКА МАТЧА',W//2,y+24,F(38),(255,255,255))
        sy=y+92
        for i,item in enumerate(stats[:5]):
            try: label,va,vb=item[0],float(item[1]),float(item[2])
            except Exception: continue
            yy=sy+i*78; total=max(1,va+vb); left=int(520*va/total); right=int(520*vb/total)
            draw.text((145,yy),str(int(va) if va.is_integer() else va),font=F(26),fill=(255,255,255))
            draw.text((W-190,yy),str(int(vb) if vb.is_integer() else vb),font=F(26),fill=(255,255,255))
            center(str(label),W//2,yy,F(25),(170,185,215))
            draw.rounded_rectangle((260,yy+38,780,yy+51),radius=7,fill=(32,48,92)); draw.rounded_rectangle((1020,yy+38,1540,yy+51),radius=7,fill=(32,48,92))
            draw.rounded_rectangle((780-left,yy+38,780,yy+51),radius=7,fill=(78,210,255)); draw.rounded_rectangle((1020,yy+38,1020+right,yy+51),radius=7,fill=(255,112,126))
    img=_hud_glass(img,95,2070,W-95,2150,radius=24,fill=(12,25,55,220),border=(80,135,245,220),glow=(0,160,255)); draw=ImageDraw.Draw(img)
    center('Хоккейные карточки',W//2,2085,F(38),(255,205,70)); center('Every Card Matters',W//2,2125,F(22),(255,255,255))
    out=io.BytesIO(); img.save(out,'PNG'); out.seek(0); return out


async def _simulate_match(context: ContextTypes.DEFAULT_TYPE, user_a: int, user_b, result_chat_id=None):
    """Симуляция рейтингового матча. Вместо «глухой заглушки» со счётом периода
    игрокам отправляются важные события периода (голы с минутами, сэйвы, удаления).
    Прокачка карт (/upgrade_card) учитывается в силе составов."""
    # Помечаем игроков как занятых — нельзя начать второй матч
    _active = context.bot_data.setdefault("active_matches", set())
    _active.add(user_a)
    if user_b:
        _active.add(user_b)
    try:
     _sim_placeholder = None  # try-block открыт; finally снимет метку
    except Exception:
        pass
    team_a = get_rating_team(user_a)
    team_b = get_rating_team(user_b) if user_b else _generate_bot_team()
    card_map = {c['id']: c for c in load_data(CARDS_FILE, [])}
    sa = _team_strength(team_a, card_map, user_a)
    sb = _team_strength(team_b, card_map, user_b)
    ea = get_rating_elo(user_a)
    eb = get_rating_elo(user_b) if user_b else DEFAULT_RATING_ELO
    # РЕБАЛАНС: сила состава и ELO теперь чуть заметнее влияют на исход,
    # но апсеты всё ещё возможны. Рандом ослаблен, чтобы сильная команда
    # чаще подтверждала статус, а не выигрывала только из-за «формы дня».
    # Сила состава теперь влияет заметнее: каждые ~100 силы дают около 10% перевеса.
    # ELO оставлен как дополнительный фактор, а рандом уменьшен — апсеты возможны, но сильный состав чаще побеждает.
    strength_edge = (sa - sb) / 1000
    elo_edge = (ea - eb) / 3600
    form = random.uniform(-0.025, 0.025)
    p_a = max(.28, min(.72, .50 + strength_edge + elo_edge + form))
    # Тактики тренеров: (бонус к своему шансу забить, бонус к шансу соперника забить)
    atk_a, give_a = _team_tactic_mods(team_a, card_map)
    atk_b, give_b = _team_tactic_mods(team_b, card_map)
    name_a_raw = _team_title(team_a, await _get_display_name(context, user_a))
    name_b_raw = _team_title(team_b, await _get_display_name(context, user_b))
    na, nb = html.escape(name_a_raw), html.escape(name_b_raw)
    recipients = [user_a] + ([user_b] if user_b else [])

    async def send(uid, text):
        try:
            await context.bot.send_message(uid, text, parse_mode='HTML')
        except Exception:
            pass

    def raw_name(cid, owner_id=None):
        return _team_ref_name(owner_id, cid, card_map, html_safe=False)

    def _coach_info(team, plain=False):
        """Строка «Тренер — тактика (бафф N%)». plain=True — без эмодзи (для картинки)."""
        coach_id = (team or {}).get('coach')
        if not coach_id:
            return 'без тренера'
        card = _team_ref_card(user_a if team is team_a else user_b, coach_id, card_map)
        cname = _team_ref_name(user_a if team is team_a else user_b, coach_id, card_map, html_safe=False) if card else f'Тренер {coach_id}'
        bonus = round(get_coach_bonus(card.get('rarity', '')) * 100) if card else 3
        tactic = (team or {}).get('tactic', 'balanced')
        if plain:
            return f"{cname} ({TACTIC_PLAIN.get(tactic, 'Баланс')}, +{bonus}%)"
        return f"{cname} - {TACTIC_LABELS.get(tactic, '⚖️ Сбалансировано')} (бафф {bonus}%)"

    coach_a_text, coach_b_text = _coach_info(team_a), _coach_info(team_b)

    # Короткое имя команды для текста событий (без @username части)
    def _short_team(s: str) -> str:
        return re.sub(r'\s*\(@[^)]*\)', '', s).strip()
    short_na = html.escape(_short_team(name_a_raw))
    short_nb = html.escape(_short_team(name_b_raw))

    def _safe_power(owner_id, cid):
        try:
            if owner_id is not None:
                return int(_team_ref_power(owner_id, cid, card_map))
        except Exception:
            pass
        card = card_map.get(cid) or {}
        return int(get_card_power(card)) if card else 0

    def _lineup_text(team, owner_id):
        if not team:
            return 'Состав недоступен'
        lines = []
        gk_id = team.get('gk')
        if gk_id:
            lines.append(f"🥅 Вратарь: {_card_name(gk_id, card_map, owner_id)} - сила {_safe_power(owner_id, gk_id)}")
        for fid in team.get('field', []):
            lines.append(f"⚔️ Полевой игрок: {_card_name(fid, card_map, owner_id)} - сила {_safe_power(owner_id, fid)}")
        coach_id = team.get('coach')
        tactic = team.get('tactic', 'balanced')
        if coach_id:
            coach_card = _team_ref_card(owner_id, coach_id, card_map)
            bonus = round(get_coach_bonus(coach_card.get('rarity', '')) * 100) if coach_card else 3
            coach_name = _card_name(coach_id, card_map, owner_id)
            lines.append(f"🧠 Тренер: {coach_name} - {TACTIC_PLAIN.get(tactic, 'Баланс')} (бафф {bonus}%)")
        else:
            lines.append("🧠 Тренер: без тренера")
        return '\n'.join(lines)

    lineup_a = _lineup_text(team_a, user_a)
    lineup_b = _lineup_text(team_b, user_b)

    for uid in recipients:
        if uid == user_a:
            opponent_name, opponent_lineup = nb, lineup_b
            my_name, my_lineup = na, lineup_a
        else:
            opponent_name, opponent_lineup = na, lineup_a
            my_name, my_lineup = nb, lineup_b
        await send(
            uid,
            f'🏒 <b>Матч начался:</b> {na} 🆚 {nb}\n'
            f'💪 Сила составов: {int(sa)} 🆚 {int(sb)}\n\n'
            f'👀 <b>Состав соперника — {opponent_name}:</b>\n{opponent_lineup}\n\n'
            f'🧊 <b>Ваш состав — {my_name}:</b>\n{my_lineup}\n\n'
            f'🧠 <b>Тренеры:</b>\n▪️ {na}: {html.escape(coach_a_text)}\n▪️ {nb}: {html.escape(coach_b_text)}'
        )
    await asyncio.sleep(2.4)

    ga = gb = 0
    period_scores = []
    scorers = []  # (минута, имя игрока, команда, счёт после гола) — без HTML-экранирования

    def _goal_event(minute, side):
        """Оформляет гол: обновляет счёт, запоминает автора, возвращает строку события."""
        nonlocal ga, gb
        att_team, def_team = (team_a, team_b) if side == 'a' else (team_b, team_a)
        att_name = na if side == 'a' else nb
        pid = _pick_field_player(att_team, card_map, user_a if side == 'a' else user_b)
        if side == 'a':
            ga += 1
        else:
            gb += 1
        scorers.append((minute, raw_name(pid, user_a if side == 'a' else user_b), (name_a_raw if side == 'a' else name_b_raw).lstrip('@'), f'{ga}:{gb}'))
        _evt_team = short_na if side == 'a' else short_nb
        text = random.choice(GOAL_EVENTS).format(team=_evt_team, player=_card_name(pid, card_map, user_a if side == 'a' else user_b), gk=_card_name(def_team['gk'], card_map, user_b if side == 'a' else user_a))
        return f"⏱ {minute:02d}' — {text} <b>{ga}:{gb}</b>"

    # Малорезультативный хоккей: 0–2 гола на команду за период.
    for period in range(1, 4):
        # Камбек-механика: проигрывающая команда прибавляет (+5% к шансу
        # гола за каждый гол отставания), поэтому забивший первым
        # больше не выигрывает почти всегда — отыгрыши случаются регулярно.
        comeback = max(-0.10, min(0.10, (gb - ga) * 0.05))
        # Тактики тренеров: atk_x — свой бонус атаки, give_x — насколько команда «открывается» сопернику
        pa = 1 if random.random() < (.30 + (p_a - .5) * .30 + comeback + atk_a + give_b) else 0
        pb = 1 if random.random() < (.30 - (p_a - .5) * .30 - comeback + atk_b + give_a) else 0
        if random.random() < .10:
            pa += 1
        if random.random() < .10:
            pb += 1
        extra = random.randint(2, 3)  # важные события без гола (сэйвы, удаления, штанги)
        minutes = sorted(random.sample(range((period - 1) * 20 + 1, period * 20 + 1), pa + pb + extra))
        kinds = ['goal_a'] * pa + ['goal_b'] * pb + ['other'] * extra
        random.shuffle(kinds)
        lines = []
        for minute, kind in zip(minutes, kinds):
            if kind == 'goal_a':
                lines.append(_goal_event(minute, 'a'))
            elif kind == 'goal_b':
                lines.append(_goal_event(minute, 'b'))
            else:
                side = 'a' if random.random() < p_a else 'b'
                att_team, def_team = (team_a, team_b) if side == 'a' else (team_b, team_a)
                att_name = na if side == 'a' else nb
                pool = HIT_EVENTS if random.random() < .75 else NEUTRAL_EVENTS
                _evt_side_team = short_na if side == 'a' else short_nb
                text = random.choice(pool).format(
                    team=_evt_side_team,
                    player=_card_name(_pick_field_player(att_team, card_map, user_a if side == 'a' else user_b), card_map),
                    gk=_card_name(def_team['gk'], card_map),
                )
                lines.append(f"⏱ {minute:02d}' — {text}")
        period_scores.append(f'{pa}:{pb}')
        for uid in recipients:
            await send(uid, f'🏒 <b>Период {period}</b>\n' + '\n'.join(lines) + f'\n\n📊 Счёт после периода: <b>{ga}:{gb}</b>')
        await asyncio.sleep(3.0)

    finish_suffix = ''
    if ga == gb:
        # В хоккее матч не заканчивается ничьей: сначала овертайм,
        # а если в овертайме без гола — серия буллитов.
        period_scores.append('ОТ')
        ot_pa = max(.44, min(.56, p_a))
        ot_goal = random.random() < 0.58
        if ot_goal:
            ot_minute = 60 + random.randint(1, 5)
            line = _goal_event(ot_minute, 'a' if random.random() < ot_pa else 'b')
            finish_suffix = ' (ОТ)'
            for uid in recipients:
                await send(uid, f'🚨 <b>ОВЕРТАЙМ!</b>\n{line}')
            await asyncio.sleep(1.4)
        else:
            finish_suffix = ' (БУЛ)'
            period_scores.append('БУЛ')
            shootout_side = 'a' if random.random() < ot_pa else 'b'
            shootout_player = _card_name(_pick_field_player(team_a if shootout_side == 'a' else team_b, card_map), card_map)
            if shootout_side == 'a':
                ga += 1
                win_team = short_na
                lose_gk = _card_name(team_b['gk'], card_map)
            else:
                gb += 1
                win_team = short_nb
                lose_gk = _card_name(team_a['gk'], card_map)
            scorers.append((65, shootout_player, (name_a_raw if shootout_side == 'a' else name_b_raw).lstrip('@'), f'{ga}:{gb}'))
            shootout_text = f"🎯 <b>Серия буллитов!</b> {shootout_player} приносит победу команде {win_team}. Вратарь {lose_gk} не выручает. <b>{ga}:{gb}</b>"
            for uid in recipients:
                await send(uid, f'🥅 <b>ОВЕРТАЙМ БЕЗ ГОЛОВ.</b>\n{shootout_text}')
            await asyncio.sleep(1.8)

    ea = get_rating_elo(user_a)
    eb = get_rating_elo(user_b) if user_b else DEFAULT_RATING_ELO
    expected = 1 / (1 + 10 ** ((eb - ea) / 400))
    score = 1.0 if ga > gb else 0.0
    newa = round(ea + 24 * (score - expected))
    set_rating_elo(user_a, newa)
    newb = None
    if user_b:
        newb = round(eb + 24 * ((1 - score) - (1 - expected)))
        set_rating_elo(user_b, newb)
    add_rating_result(user_a, 'win' if ga > gb else 'loss')
    inc_stat(user_a,'rating_matches',1)
    if ga>gb: inc_stat(user_a,'rating_wins',1)
    if user_b:
        add_rating_result(user_b, 'win' if gb > ga else 'loss')
        inc_stat(user_b,'rating_matches',1)
        if gb>ga: inc_stat(user_b,'rating_wins',1)
    for _uid,_team in [(user_a,team_a),(user_b,team_b if user_b else None)]:
        if _uid and _team and random.random()<0.08:
            refs=[_team.get('gk')]+list(_team.get('field',[]))
            ref=random.choice([r for r in refs if r])
            name=_card_name(ref, card_map)
            data=load_data(INJURIES_FILE,{}) ; arr=data.setdefault(str(_uid),[])
            arr.append({'ref':ref,'name':name,'until':time.time()+random.randint(60,180)*60})
            save_data(INJURIES_FILE,data); log_action(_uid,'injury',name)
    # Контролируемая награда: только 35% шанс, меньше за победу над слабым составом.
    winner = user_a if ga > gb else user_b
    ws, ls = (sa, sb) if ga > gb else (sb, sa)
    reward = 0
    if winner and random.random() < .35:
        reward = 6 if ws > ls + 35 else (12 if ws >= ls - 35 else 18)
        update_coins(winner, reward)
    goals_text = '\n'.join(
        f"⏱ {m:02d}' — {html.escape(p)} ({html.escape(t)}) — {s}" for m, p, t, s in scorers
    ) or '—'
    # Статистика «как в реальном хоккее»: время в атаке, броски, броски в створ, хиты, удаления.
    sog_a, sog_b = ga + random.randint(14, 24), gb + random.randint(14, 24)
    shots_a, shots_b = sog_a + random.randint(7, 15), sog_b + random.randint(7, 15)
    hits_a, hits_b = random.randint(8, 24), random.randint(8, 24)
    pim_a, pim_b = 2 * random.randint(0, 4), 2 * random.randint(0, 4)
    atk_share = max(.35, min(.65, p_a + atk_a - atk_b + random.uniform(-.06, .06)))
    atk_total = random.randint(1100, 1500)
    atk_sec_a = int(atk_total * atk_share)
    atk_sec_b = atk_total - atk_sec_a
    stats_rows = [
        ('Время в атаке', f'{atk_sec_a // 60}:{atk_sec_a % 60:02d}', f'{atk_sec_b // 60}:{atk_sec_b % 60:02d}'),
        ('Броски', str(shots_a), str(shots_b)),
        ('Броски в створ', str(sog_a), str(sog_b)),
        ('Хиты', str(hits_a), str(hits_b)),
        ('Штрафные минуты', str(pim_a), str(pim_b)),
    ]
    stats_text = '\n'.join(f'▫️ {label}: <b>{va}</b> — <b>{vb}</b>' for label, va, vb in stats_rows)
    ot_mark = finish_suffix
    # Подготавливаем общие данные для картинки
    img_name_a = _short_team(name_a_raw) if team_a and team_a.get('name') else (name_a_raw.lstrip('@'))
    img_name_b = _short_team(name_b_raw) if team_b and team_b.get('name') else (name_b_raw.lstrip('@'))
    _img_kwargs = dict(
        scorers=scorers,
        coaches=(_coach_info(team_a, plain=True), _coach_info(team_b, plain=True)),
        stats=stats_rows,
    )
    for uid, old, new, won in [(user_a, ea, newa, ga > gb)] + ([(user_b, eb, newb, gb > ga)] if user_b else []):
        delta = new - old
        delta_str = f'+{delta}' if delta >= 0 else str(delta)
        cap = (
            f"{"🏆 ПОБЕДА!" if won else "😤 Поражение."} {na} <b>{ga}:{gb}</b>{ot_mark} {nb}\n"
            f"⭐ Рейтинг: {old} → <b>{new}</b> ({delta_str})"
            + (f'\n💰 Награда: +{reward}' if uid == winner and reward else '')
        )
        image = None
        try:
            image = build_match_result_image(
                img_name_a, img_name_b, ga, gb, period_scores,
                elo_old=old, elo_new=new, won=won,
                **_img_kwargs,
            )
        except Exception as _e:
            logger.warning(f'Не удалось построить картинку матча: {_e}')
        try:
            if image:
                await context.bot.send_photo(uid, photo=image, caption=cap, parse_mode='HTML')
            else:
                await context.bot.send_message(uid, cap, parse_mode='HTML')
        except Exception:
            try:
                await context.bot.send_message(uid, cap, parse_mode='HTML')
            except Exception:
                pass

    # Снимаем метку «в матче» — игроки снова могут искать
    _am = context.bot_data.setdefault("active_matches", set())
    _am.discard(user_a)
    if user_b:
        _am.discard(user_b)

    # Отправляем нейтральную картинку в чат (один раз, без ELO)
    if result_chat_id:
        try:
            chat_img = build_match_result_image(
                img_name_a, img_name_b, ga, gb, period_scores,
                **_img_kwargs,
            )
            _winner_name = html.escape(img_name_a if ga > gb else img_name_b)
            _score_line  = f"{html.escape(img_name_a)} {ga}:{gb} {html.escape(img_name_b)}{ot_mark}"
            chat_cap = "Хоккейные карточки\n" + _score_line + "\n🏆 Победа: " + _winner_name
            if chat_img:
                await context.bot.send_photo(result_chat_id, photo=chat_img, caption=chat_cap, parse_mode='HTML')
            else:
                await context.bot.send_message(result_chat_id, chat_cap, parse_mode='HTML')
        except Exception as _ce:
            logger.warning(f'Не удалось отправить результат в чат: {_ce}')


# ============================ FINAL STABILITY OVERRIDES ============================
FIND_MATCH_GLOBAL_TIMEOUT = 30
LOW_RATING_GLOBAL_SEARCH_MAX_ELO = 999


def _is_low_rating_global_candidate(elo: int) -> bool:
    return elo <= LOW_RATING_GLOBAL_SEARCH_MAX_ELO


def _queue_result_chat_id(current_chat_id, opponent_chat_id):
    curr_chat = current_chat_id if current_chat_id and current_chat_id > 0 else None
    opp_chat = opponent_chat_id if opponent_chat_id and opponent_chat_id > 0 else None
    return curr_chat if curr_chat == opp_chat and curr_chat else (curr_chat or opp_chat)


async def _start_ranked_match(context: ContextTypes.DEFAULT_TYPE, user_id: int, opponent_entry: dict, current_chat_id=None, match_label: str | None = None):
    queue = context.bot_data.setdefault("rating_queue", [])
    own_entry = next((q for q in queue if q.get("user_id") == user_id), None)
    if own_entry and own_entry in queue:
        queue.remove(own_entry)
    if opponent_entry in queue:
        queue.remove(opponent_entry)

    user_elo = get_rating_elo(user_id)
    opp_elo = get_rating_elo(opponent_entry["user_id"])
    user_rank_emoji, user_rank_name = get_rating_rank(user_elo)[1], get_rating_rank(user_elo)[2]
    opp_rank_emoji, opp_rank_name = get_rating_rank(opp_elo)[1], get_rating_rank(opp_elo)[2]
    intro = match_label or "⚔️ Соперник найден! Матч начинается прямо сейчас..."

    try:
        await context.bot.send_message(
            user_id,
            f"{intro}\nВаш ранг: {user_rank_emoji} {user_rank_name}\nРанг соперника: {opp_rank_emoji} {opp_rank_name}",
        )
    except Exception:
        pass
    try:
        await context.bot.send_message(
            opponent_entry["user_id"],
            f"{intro}\nВаш ранг: {opp_rank_emoji} {opp_rank_name}\nРанг соперника: {user_rank_emoji} {user_rank_name}",
        )
    except Exception:
        pass

    result_chat = _queue_result_chat_id(current_chat_id, opponent_entry.get("chat_id"))
    asyncio.create_task(_simulate_match(context, user_id, opponent_entry["user_id"], result_chat_id=result_chat))


async def _search_timeout_cancel(context: ContextTypes.DEFAULT_TYPE, user_id: int, wait_seconds: int = FIND_MATCH_TIMEOUT):
    await asyncio.sleep(wait_seconds)
    queue = context.bot_data.setdefault("rating_queue", [])
    entry = next((q for q in queue if q.get("user_id") == user_id), None)
    if not entry:
        return

    if entry.get("scope") == "rank":
        elo = int(entry.get("elo", get_rating_elo(user_id)))
        if _is_low_rating_global_candidate(elo):
            entry["scope"] = "global"
            entry["global_started"] = time.time()
            opponent_entry = next((q for q in queue if q.get("user_id") != user_id), None)
            if opponent_entry:
                await _start_ranked_match(
                    context,
                    user_id,
                    opponent_entry,
                    current_chat_id=entry.get("chat_id"),
                    match_label="🌍 Включён глобальный поиск. Соперник найден!"
                )
                return
            try:
                await context.bot.send_message(
                    user_id,
                    "🌍 <b>Локальный поиск завершён.</b>\n\n"
                    "За 90 секунд соперник вашего ранга не нашёлся.\n"
                    "Включаю глобальный поиск на 30 секунд — теперь ищем любого соперника.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            asyncio.create_task(_search_timeout_cancel(context, user_id, FIND_MATCH_GLOBAL_TIMEOUT))
            return

        if entry in queue:
            queue.remove(entry)
        try:
            await context.bot.send_message(
                user_id,
                "😔 <b>Поиск отменён.</b>\n\n"
                "За 90 секунд не нашлось соперника вашего ранга.\n"
                "Попробуйте позже: /find_match",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    if entry.get("scope") == "global":
        if entry in queue:
            queue.remove(entry)
        try:
            await context.bot.send_message(
                user_id,
                "😔 <b>Поиск отменён.</b>\n\n"
                "Глобальный поиск тоже никого не нашёл за 30 секунд.\n"
                "Попробуйте ещё раз позже: /find_match",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def find_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    if not get_rating_team(user.id):
        await update.message.reply_text("❌ У вас нет состава. Сначала используйте /rating_team.")
        return

    queue = context.bot_data.setdefault("rating_queue", [])
    active_matches = context.bot_data.setdefault("active_matches", set())
    if user.id in active_matches:
        await update.message.reply_text("⚽ У вас уже идёт матч! Дождитесь его окончания, затем ищите снова.")
        return
    if any(q.get("user_id") == user.id for q in queue):
        await update.message.reply_text("⏳ Вы уже ищете соперника. Дождитесь результата поиска.")
        return

    cooldowns = context.bot_data.setdefault("find_match_cooldowns", {})
    now = time.time()
    elapsed = now - cooldowns.get(user.id, 0)
    if elapsed < FIND_MATCH_COOLDOWN:
        wait_left = int(FIND_MATCH_COOLDOWN - elapsed) + 1
        await update.message.reply_text(f"🕒 Не так быстро! Повторный поиск будет доступен через {wait_left} сек.")
        return
    cooldowns[user.id] = now

    my_elo = get_rating_elo(user.id)
    my_rank, rank_emoji, rank_name = get_rating_rank(my_elo)
    current_chat_id = update.effective_chat.id if update.effective_chat and update.effective_chat.id != user.id else None

    global_entry = next((q for q in queue if q.get("user_id") != user.id and q.get("scope") == "global"), None)
    if global_entry:
        await update.message.reply_text("🌍 Найден соперник из глобального поиска. Матч начинается прямо сейчас...")
        await _start_ranked_match(context, user.id, global_entry, current_chat_id=current_chat_id)
        return

    opponent_entry = next((q for q in queue if q.get("user_id") != user.id and q.get("rank") == my_rank and q.get("scope") == "rank"), None)
    if opponent_entry:
        await update.message.reply_text(f"⚔️ Соперник найден! Ранг: {rank_emoji} {rank_name}. Матч начинается прямо сейчас...")
        await _start_ranked_match(context, user.id, opponent_entry, current_chat_id=current_chat_id)
        return

    queue.append({
        "user_id": user.id,
        "joined": now,
        "rank": my_rank,
        "elo": my_elo,
        "scope": "rank",
        "chat_id": current_chat_id,
    })
    extra = "\n🌍 Для низкого рейтинга после 90 секунд автоматически включится глобальный поиск ещё на 30 секунд." if _is_low_rating_global_candidate(my_elo) else ""
    await update.message.reply_text(
        f"🔍 Ищем соперника вашего ранга: {rank_emoji} <b>{rank_name}</b> (рейтинг {my_elo})...\n\n"
        "⚖️ Сначала ищем только игроков того же ранга.\n"
        "⏳ Локальный поиск длится 90 секунд." + extra,
        parse_mode="HTML",
    )
    asyncio.create_task(_search_timeout_cancel(context, user.id, FIND_MATCH_TIMEOUT))


async def _run_locked_action(context: ContextTypes.DEFAULT_TYPE, user_id: int, action_name: str, runner, busy_message: str, on_busy=None):
    locks = context.bot_data.setdefault("user_action_locks", set())
    key = (action_name, user_id)
    if key in locks:
        if on_busy is not None:
            await on_busy()
        return
    locks.add(key)
    try:
        return await runner()
    finally:
        locks.discard(key)


_original_get_card = get_card
async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_get_card(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Получение карточки уже обрабатывается. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "get_card", lambda: _original_get_card(update, context), "", on_busy=_busy)


_original_daily_claim = daily_claim
async def daily_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_daily_claim(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Ежедневная награда уже обрабатывается. Подождите пару секунд.")
    before_users = load_data(USERS_FILE, {})
    before_last = before_users.get(str(user.id), {}).get("last_daily", 0)
    await _run_locked_action(context, user.id, "daily_claim", lambda: _original_daily_claim(update, context), "", on_busy=_busy)
    after_users = load_data(USERS_FILE, {})
    after_last = after_users.get(str(user.id), {}).get("last_daily", 0)
    # Засчитываем квест только если /daily реально был получен, а не когда игрок упёрся в КД.
    if after_last and after_last != before_last:
        await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'daily_claims', 1))
        log_action(user.id, 'daily_claim', '')


_original_buy_item = buy_item
async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_buy_item(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Покупка уже обрабатывается. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "buy_item", lambda: _original_buy_item(update, context), "", on_busy=_busy)


_original_work_command = work_command
async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_work_command(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Команда /work уже обрабатывается. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "work_command", lambda: _original_work_command(update, context), "", on_busy=_busy)


_original_market_buy_callback = market_buy_callback
async def market_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user if query else None
    if not user:
        return await _original_market_buy_callback(update, context)
    async def _busy():
        try:
            await query.answer("Покупка уже обрабатывается", show_alert=True)
        except Exception:
            pass
    await _run_locked_action(context, user.id, "market_buy_callback", lambda: _original_market_buy_callback(update, context), "", on_busy=_busy)



# ============================ MUTATED CARDS SYSTEM ============================
MUTATION_DROP_CHANCE = 0.01
MUTATION_FRAMES_DIR = os.path.join(BASE_DIR, "mutation_frames")
MUTATIONS = {
    "gold": {
        "label": "Золотая",
        "chance": 18,
        "power_bonus": 8,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "gold.png"),
        "color": (255, 205, 72),
        "glow": (255, 241, 170),
        "emoji": "👑",
        "animation": [
            "🧬 Внутри карты что-то меняется...",
            "👑 Золотое свечение пробивается наружу...",
            "✨ МУТАЦИЯ: ЗОЛОТАЯ!",
        ],
    },
    "crystal": {
        "label": "Кристальная",
        "chance": 16,
        "power_bonus": 10,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "crystal.png"),
        "color": (106, 228, 255),
        "glow": (194, 248, 255),
        "emoji": "💎",
        "animation": [
            "🧬 Карта покрывается ледяным блеском...",
            "💎 По краям растут кристаллы...",
            "✨ МУТАЦИЯ: КРИСТАЛЬНАЯ!",
        ],
    },
    "shadow": {
        "label": "Теневая",
        "chance": 15,
        "power_bonus": 12,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "shadow.png"),
        "color": (121, 96, 255),
        "glow": (205, 195, 255),
        "emoji": "🌑",
        "animation": [
            "🧬 Свет вокруг карты резко тухнет...",
            "🌑 Карта растворяется в тени...",
            "✨ МУТАЦИЯ: ТЕНЕВАЯ!",
        ],
    },
    "plasma": {
        "label": "Плазменная",
        "chance": 14,
        "power_bonus": 14,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "plasma.png"),
        "color": (77, 255, 220),
        "glow": (180, 255, 239),
        "emoji": "⚡",
        "animation": [
            "🧬 Карту пробивают плазменные разряды...",
            "⚡ Сетка рамки заряжается током...",
            "✨ МУТАЦИЯ: ПЛАЗМЕННАЯ!",
        ],
    },
    "inferno": {
        "label": "Инфернальная",
        "chance": 12,
        "power_bonus": 16,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "inferno.png"),
        "color": (255, 102, 54),
        "glow": (255, 185, 155),
        "emoji": "🔥",
        "animation": [
            "🧬 Карту охватывает жар...",
            "🔥 Рамка превращается в пламя...",
            "✨ МУТАЦИЯ: ИНФЕРНАЛЬНАЯ!",
        ],
    },
    "void": {
        "label": "Бездна",
        "chance": 13,
        "power_bonus": 18,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "void.png"),
        "color": (46, 46, 46),
        "glow": (160, 84, 255),
        "emoji": "🕳",
        "animation": [
            "🧬 Вокруг карты искажается пространство...",
            "🕳 Края затягивает в бездну...",
            "✨ МУТАЦИЯ: БЕЗДНА!",
        ],
    },
    "celestial": {
        "label": "Небесная",
        "chance": 12,
        "power_bonus": 22,
        "frame_path": os.path.join(MUTATION_FRAMES_DIR, "celestial.png"),
        "color": (255, 220, 120),
        "glow": (255, 247, 210),
        "emoji": "🌠",
        "animation": [
            "🧬 Над картой вспыхивает звёздная пыль...",
            "🌠 Рамка становится небесной...",
            "✨ МУТАЦИЯ: НЕБЕСНАЯ!",
        ],
    },
}
MUTATION_MARKET_MULTIPLIER = 1.6
MUTATION_MARKET_BONUS_STEP = 12
TEAM_MUTATION_PREFIX = "m:"
MUTATION_EVENT_NAMES = {"мутация", "мутированная", "mutated", "mutation"}


def _normalize_mutation_token(raw: str) -> str:
    token = str(raw or '').strip()
    low = token.lower()
    if low.startswith('m-id:'):
        return token[5:].strip()
    if low.startswith('m_id:'):
        return token[5:].strip()
    if low.startswith('mut_'):
        return token[4:].strip()
    if low.startswith('m') and len(token) > 1:
        return token[1:].strip()
    return token


def _is_team_mutation_ref(value) -> bool:
    return isinstance(value, str) and value.startswith(TEAM_MUTATION_PREFIX)


def _make_team_mutation_ref(instance_id: str) -> str:
    return f"{TEAM_MUTATION_PREFIX}{instance_id}"


def _team_ref_card_id(card_ref):
    if _is_team_mutation_ref(card_ref):
        return None
    try:
        return int(card_ref)
    except Exception:
        return None


def _team_ref_mutation_instance(user_id, card_ref):
    if not _is_team_mutation_ref(card_ref) or user_id is None:
        return None
    instance_id = str(card_ref)[len(TEAM_MUTATION_PREFIX):]
    return _get_mutation_instance(user_id, instance_id)


def _team_ref_card(user_id, card_ref, card_map: dict):
    mutation = _team_ref_mutation_instance(user_id, card_ref)
    if mutation:
        return card_map.get(int(mutation.get('card_id', -1)), {})
    cid = _team_ref_card_id(card_ref)
    return card_map.get(cid, {}) if cid is not None else {}


def _team_ref_name(user_id, card_ref, card_map: dict, html_safe: bool = True) -> str:
    card = _team_ref_card(user_id, card_ref, card_map)
    if not card:
        raw = f"Игрок {card_ref}"
        return html.escape(raw) if html_safe else raw
    name = str(card.get('name', '?'))
    mutation = _team_ref_mutation_instance(user_id, card_ref)
    if mutation:
        meta = _get_mutation_meta(mutation.get('mutation')) or {}
        name = f"{name} [{meta.get('label', 'Мутация')}]"
    return html.escape(name) if html_safe else name


def _team_ref_power(user_id, card_ref, card_map: dict) -> int:
    mutation = _team_ref_mutation_instance(user_id, card_ref)
    if mutation:
        card_id = int(mutation.get('card_id', -1))
        card = card_map.get(card_id, {})
        base = get_card_power(card)
        cap = get_card_rating_cap(card)
        level = 0
        if user_id is not None:
            level = load_data(USERS_FILE, {}).get(str(user_id), {}).get('card_upgrades', {}).get(str(card_id), 0)
        return int(min(cap, base + max(0, int(level)) * 2) + _mutation_bonus_from_instance(mutation))
    cid = _team_ref_card_id(card_ref)
    if cid is None:
        return 0
    if user_id is not None:
        return int(get_player_card_power(user_id, cid, card_map))
    card = card_map.get(cid, {})
    return int(get_card_power(card)) if card else 0


def _parse_team_card_input(user_id: int, raw_text: str):
    raw = str(raw_text or '').strip()
    token = _normalize_mutation_token(raw)
    low = raw.lower()
    if low.startswith(('m', 'mut_')) or low.startswith('m-id:') or low.startswith('m_id:'):
        instance = _get_mutation_instance(user_id, token)
        if not instance:
            raise ValueError('mutated_not_found')
        return _make_team_mutation_ref(token)
    card_id = int(raw)
    if card_id not in get_available_card_ids(user_id):
        raise ValueError('card_not_found')
    return card_id


def _get_effective_mutation_drop_chance() -> float:
    chance = MUTATION_DROP_CHANCE
    for boost in get_active_drop_boosts():
        rarity = str(boost.get('rarity', '')).strip().lower()
        if rarity in MUTATION_EVENT_NAMES:
            try:
                chance *= float(boost.get('multiplier', 1))
            except Exception:
                pass
    return max(0.0, min(1.0, chance))


def _ensure_mutation_assets():
    if not PIL_AVAILABLE:
        return
    os.makedirs(MUTATION_FRAMES_DIR, exist_ok=True)
    for key, meta in MUTATIONS.items():
        path = meta["frame_path"]
        if os.path.exists(path):
            continue
        size = 512
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = meta["color"]
        glow = meta["glow"]
        for pad in range(10, 34, 6):
            alpha = max(28, 120 - pad * 2)
            d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=34, outline=(*glow, alpha), width=4)
        d.rounded_rectangle((34, 34, size - 34, size - 34), radius=28, outline=(*color, 255), width=8)
        d.rounded_rectangle((54, 54, size - 54, size - 54), radius=22, outline=(*glow, 190), width=3)
        # corners
        off = 52
        ln = 54
        for x0, y0, sx, sy in [
            (off, off, 1, 1),
            (size - off, off, -1, 1),
            (off, size - off, 1, -1),
            (size - off, size - off, -1, -1),
        ]:
            d.line((x0, y0, x0 + ln * sx, y0), fill=(*color, 255), width=10)
            d.line((x0, y0, x0, y0 + ln * sy), fill=(*color, 255), width=10)
        # particles
        rng = random.Random(sum(ord(c) for c in key) + 42)
        for _ in range(18):
            x = rng.randint(70, size - 70)
            y = rng.randint(70, size - 70)
            r = rng.randint(3, 9)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(*glow, rng.randint(120, 220)))
        img.save(path)


def _get_user_mutated_cards(user_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    cards = user_data.get("mutated_cards", [])
    if isinstance(cards, list):
        return cards
    return []


def _save_user_mutated_cards(user_id: int, mutated_cards):
    users = load_data(USERS_FILE, {})
    user_data = users.setdefault(str(user_id), {"cards": [], "last_drop": 0})
    user_data["mutated_cards"] = mutated_cards
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)


def _next_mutation_instance_id(user_id: int) -> str:
    return f"{user_id}_{int(time.time() * 1000)}_{random.randint(100, 999)}"


def _roll_mutation_key():
    keys = list(MUTATIONS.keys())
    weights = [MUTATIONS[k]["chance"] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


def _get_mutation_meta(mutation_key: str):
    return MUTATIONS.get(mutation_key or "")


def _get_mutation_instance(user_id: int, instance_id: str):
    for item in _get_user_mutated_cards(user_id):
        if str(item.get("instance_id")) == str(instance_id):
            return item
    return None


def add_mutated_card(user_id: int, card_id: int, mutation_key: str):
    mutated_cards = _get_user_mutated_cards(user_id)
    instance = {
        "instance_id": _next_mutation_instance_id(user_id),
        "card_id": int(card_id),
        "mutation": mutation_key,
        "created_at": time.time(),
    }
    mutated_cards.append(instance)
    _save_user_mutated_cards(user_id, mutated_cards)
    add_seen_card(user_id, int(card_id))
    return instance


def add_mutated_card_instance(user_id: int, instance: dict):
    mutated_cards = _get_user_mutated_cards(user_id)
    payload = dict(instance)
    payload["instance_id"] = payload.get("instance_id") or _next_mutation_instance_id(user_id)
    mutated_cards.append(payload)
    _save_user_mutated_cards(user_id, mutated_cards)
    add_seen_card(user_id, int(payload.get("card_id")))


def remove_mutated_card_instance(user_id: int, instance_id: str):
    mutated_cards = _get_user_mutated_cards(user_id)
    for idx, item in enumerate(mutated_cards):
        if str(item.get("instance_id")) == str(instance_id):
            return mutated_cards.pop(idx), mutated_cards
    return None, mutated_cards


def _mutation_bonus_from_instance(instance: dict) -> int:
    meta = _get_mutation_meta(instance.get("mutation")) if instance else None
    return int(meta.get("power_bonus", 0)) if meta else 0


def _best_mutation_for_card(user_id: int, card_id: int):
    matches = [m for m in _get_user_mutated_cards(user_id) if int(m.get("card_id", -1)) == int(card_id)]
    if not matches:
        return None
    matches.sort(key=lambda m: _mutation_bonus_from_instance(m), reverse=True)
    return matches[0]


def _format_mutation_name(mutation_key: str) -> str:
    meta = _get_mutation_meta(mutation_key)
    return meta.get("label", mutation_key) if meta else mutation_key


def _get_mutated_market_min_price(card: dict, mutation_key: str) -> int:
    rarity = card.get("rarity")
    base_min = MARKET_MIN_PRICES.get(rarity, 25)
    meta = _get_mutation_meta(mutation_key) or {}
    return int(base_min * MUTATION_MARKET_MULTIPLIER + int(meta.get("power_bonus", 0)) * MUTATION_MARKET_BONUS_STEP)


def get_available_card_ids(user_id: int) -> list:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    normal = list(user_data.get("cards", []))
    mutated = [int(item.get("card_id")) for item in user_data.get("mutated_cards", []) if item.get("card_id") is not None]
    return normal + mutated


def remove_one_card(user_id: int, card_id: int) -> bool:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    cards = list(user_data.get("cards", []))
    if card_id in cards:
        buff = user_data.get("buff_card")
        if buff and buff.get("card_id") == card_id and cards.count(card_id) <= 1:
            return False
        cards.remove(card_id)
        user_data["cards"] = cards
        users[str(user_id)] = user_data
        save_data(USERS_FILE, users)
        return True
    mutated_cards = list(user_data.get("mutated_cards", []))
    same = [m for m in mutated_cards if int(m.get("card_id", -1)) == int(card_id)]
    if not same:
        return False
    same.sort(key=lambda m: _mutation_bonus_from_instance(m))
    victim = same[0]
    mutated_cards = [m for m in mutated_cards if str(m.get("instance_id")) != str(victim.get("instance_id"))]
    user_data["mutated_cards"] = mutated_cards
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)
    return True


def _collect_user_inventory(user_id: int):
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    normal_cards = list(user_data.get("cards", []))
    mutated_cards = list(user_data.get("mutated_cards", []))
    return user_data, normal_cards, mutated_cards


async def show_collection_with_ids(user_id: int) -> str:
    user_data, normal_cards, mutated_cards = _collect_user_inventory(user_id)
    locked = get_locked_card_ids(user_id)
    if not normal_cards and not mutated_cards and not locked:
        return "📭 Ваша коллекция пуста!"
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    rarities = load_data(RARITIES_FILE, [])
    rarity_info = {r["name"]: r for r in rarities}
    def _collection_sort_key(rarity_name):
        info = rarity_info.get(rarity_name, {})
        droppable = info.get("droppable", rarity_name != "Эксклюзивная")
        chance = get_rarity_drop_chance(rarity_name)
        if chance <= 0:
            chance = 1.0
        return (0 if not droppable else 1, chance, rarity_name)

    message = "🃏 <b>Ваша коллекция карточек</b>\n\n"
    if normal_cards:
        card_counts = Counter(normal_cards)
        grouped = {}
        for cid, count in card_counts.items():
            card = card_map.get(cid)
            if not card:
                continue
            grouped.setdefault(card.get("rarity", "Обычная"), []).append((card, count))
        message += "📦 <b>Обычные</b>\n"
        for rarity in sorted(grouped.keys(), key=_collection_sort_key):
            cards_in_rarity = grouped[rarity]
            count_in_rarity = sum(count for _, count in cards_in_rarity)
            emoji = get_rarity_emoji(rarity)
            message += f"{emoji} <b>{html.escape(rarity)}</b> ({count_in_rarity}):\n"
            for card, count in sorted(cards_in_rarity, key=lambda x: x[0]['id']):
                lvl = int(user_data.get("card_upgrades", {}).get(str(card["id"]), 0))
                lvl_text = f" ⭐ур.{lvl}" if lvl > 0 else ""
                count_text = f" (x{count})" if count > 1 else ""
                message += f"   • {html.escape(card['name'])}{lvl_text}{count_text} [ID: {card['id']}]\n"
            message += "\n"
    if mutated_cards:
        message += "🧬 <b>Мутированные</b>\n"
        by_rarity = {}
        for item in mutated_cards:
            card = card_map.get(int(item.get("card_id", -1)))
            if not card:
                continue
            by_rarity.setdefault(card.get("rarity", "Обычная"), []).append((card, item))
        for rarity in sorted(by_rarity.keys(), key=_collection_sort_key):
            emoji = get_rarity_emoji(rarity)
            message += f"{emoji} <b>{html.escape(rarity)}</b> ({len(by_rarity[rarity])}):\n"
            for card, item in sorted(by_rarity[rarity], key=lambda x: (x[0]['id'], str(x[1].get('instance_id')))):
                meta = _get_mutation_meta(item.get("mutation")) or {}
                lvl = int(user_data.get("card_upgrades", {}).get(str(card["id"]), 0))
                lvl_text = f" ⭐ур.{lvl}" if lvl > 0 else ""
                message += (
                    f"   • {html.escape(card['name'])}{lvl_text} — {meta.get('emoji', '🧬')} "
                    f"<b>{html.escape(meta.get('label', 'Мутация'))}</b> (+{meta.get('power_bonus', 0)}) "
                    f"[M-ID: {html.escape(str(item.get('instance_id')))} | ID: {card['id']}]\n"
                )
            message += "\n"
    if locked:
        locked_counts = Counter(locked)
        message += f"🔒 <b>Недоступны</b> ({len(locked)} — на маркете или в работе):\n"
        for cid in sorted(locked_counts):
            cname = card_map.get(cid, {}).get("name", f"ID {cid}")
            count = locked_counts[cid]
            count_text = f" (x{count})" if count > 1 else ""
            message += f"   • {html.escape(cname)}{count_text} [ID: {cid}]\n"
        message += "\n"
    message += (
        f"📚 <b>Обычных: {len(normal_cards)}</b>\n"
        f"🧬 <b>Мутированных: {len(mutated_cards)}</b>\n"
        f"💡 Мутированный лот на маркете: <code>/sell mINSTANCE_ID цена</code>"
    )
    return message


def get_framed_card_photo(card: dict, mutation_instance: dict | None = None):
    if not PIL_AVAILABLE:
        return None
    src_path = os.path.join(CARDS_IMAGE_DIR, card.get("image", ""))
    if not os.path.exists(src_path):
        return None
    try:
        os.makedirs(FRAMED_CARDS_DIR, exist_ok=True)
        _ensure_mutation_assets()
        mutation_key = mutation_instance.get("mutation") if mutation_instance else ""
        mutation_meta = _get_mutation_meta(mutation_key) if mutation_key else None
        mtime = int(os.path.getmtime(src_path))
        cache_key = f"{card['id']}_{card.get('rarity','')}_{mtime}_{mutation_key or 'normal'}.png"
        cache_key = re.sub(r'[^A-Za-z0-9_.-]+', '_', cache_key)
        cache_path = os.path.join(FRAMED_CARDS_DIR, cache_key)
        if os.path.exists(cache_path):
            return open(cache_path, "rb")
        img = Image.open(src_path).convert("RGBA")
        img = ImageOps.fit(img, (512, 512), centering=(0.5, 0.35))
        canvas = Image.new("RGBA", (512, 640), (8, 12, 24, 255))
        main, light = _rarity_frame_colors(card.get("rarity", "Обычная"))
        d = ImageDraw.Draw(canvas)
        for y in range(0, 640, 8):
            d.line((0, y, 512, y), fill=(10, 16, 32 + (y % 16), 255), width=1)
        canvas.alpha_composite(img, (0, 0))
        for g in range(22, 0, -4):
            d.rounded_rectangle((14-g, 14-g, 512-14+g, 512-14+g), radius=28, outline=(*light, max(18, 85 - g * 2)), width=2)
        d.rounded_rectangle((18, 18, 494, 494), radius=24, outline=(*main, 255), width=8)
        d.rounded_rectangle((28, 28, 484, 484), radius=18, outline=(*light, 210), width=3)
        name_font = _load_team_font(30)
        small_font = _load_team_font(22)
        try:
            tw = d.textlength(card.get("name", "?"), font=name_font)
        except Exception:
            tw = len(card.get("name", "?")) * 15
        name = str(card.get("name", "?"))
        while tw > 470 and len(name) > 3:
            name = name[:-1].rstrip() + '…'
            tw = d.textlength(name, font=name_font)
        d.text(((512 - tw) / 2, 528), name, font=name_font, fill=(245, 247, 252, 255))
        rarity_line = f"{get_rarity_emoji(card.get('rarity', ''))} {card.get('rarity', 'Обычная')}"
        rt = d.textlength(rarity_line, font=small_font)
        d.text(((512 - rt) / 2, 568), rarity_line, font=small_font, fill=(*light, 255))
        if mutation_meta:
            frame = Image.open(mutation_meta["frame_path"]).convert("RGBA")
            frame = frame.resize((512, 512))
            canvas.alpha_composite(frame, (0, 0))
            bonus_line = f"{mutation_meta['emoji']} Мутация: {mutation_meta['label']}  +{mutation_meta['power_bonus']}"
            mt_font = _load_team_font(24)
            mtw = d.textlength(bonus_line, font=mt_font)
            d.rounded_rectangle((28, 600, 484, 632), radius=12, fill=(18, 24, 44, 220), outline=(*mutation_meta['color'], 255), width=2)
            d.text(((512 - mtw) / 2, 605), bonus_line, font=mt_font, fill=(*mutation_meta['glow'], 255))
        canvas.convert("RGB").save(cache_path)
        return open(cache_path, "rb")
    except Exception as e:
        logger.error(f"Не удалось построить framed card photo: {e}")
        return None


def _build_mutation_reveal_animation(card: dict, mutation_instance: dict):
    if not PIL_AVAILABLE:
        return None
    try:
        _ensure_mutation_assets()
        meta = _get_mutation_meta(mutation_instance.get("mutation"))
        if not meta:
            return None
        src_path = os.path.join(CARDS_IMAGE_DIR, card.get("image", ""))
        if not os.path.exists(src_path):
            return None
        base = Image.open(src_path).convert("RGBA")
        base = ImageOps.fit(base, (420, 420), centering=(0.5, 0.35))
        frame = Image.open(meta["frame_path"]).convert("RGBA").resize((420, 420))
        frames = []
        title_font = _load_team_font(36)
        small_font = _load_team_font(24)
        for idx, alpha in enumerate((60, 100, 145, 190, 235, 255)):
            canvas = Image.new("RGBA", (640, 640), (10, 12, 20, 255))
            d = ImageDraw.Draw(canvas)
            for y in range(0, 640, 10):
                d.line((0, y, 640, y), fill=(12, 18, 34, 255), width=1)
            glow = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.ellipse((120, 110, 520, 510), fill=(*meta["glow"], min(180, alpha)))
            glow = glow.filter(ImageFilter.GaussianBlur(radius=32))
            canvas = Image.alpha_composite(canvas, glow)
            canvas.alpha_composite(base, (110, 80))
            animated_frame = frame.copy()
            if alpha < 255:
                animated_frame.putalpha(animated_frame.getchannel('A').point(lambda p: int(p * alpha / 255)))
            canvas.alpha_composite(animated_frame, (110, 80))
            line1 = f"{meta['emoji']} МУТАЦИЯ"
            line2 = meta["label"].upper()
            line3 = f"+{meta['power_bonus']} к силе"
            w1 = d.textlength(line1, font=title_font)
            w2 = d.textlength(line2, font=title_font)
            w3 = d.textlength(line3, font=small_font)
            d.text(((640 - w1) / 2, 22), line1, font=title_font, fill=(*meta["glow"], 255))
            d.text(((640 - w2) / 2, 500), line2, font=title_font, fill=(245, 247, 252, 255))
            d.text(((640 - w3) / 2, 548), line3, font=small_font, fill=(*meta["color"], 255))
            frames.append(canvas.convert("P", palette=Image.ADAPTIVE))
        bio = io.BytesIO()
        bio.name = f"mutation_{mutation_instance.get('mutation','card')}.gif"
        frames[0].save(bio, format="GIF", save_all=True, append_images=frames[1:], duration=130, loop=0)
        bio.seek(0)
        return bio
    except Exception as e:
        logger.error(f"Не удалось построить GIF мутации: {e}")
        return None


def get_player_card_power(user_id:int, card_id:int, card_map:dict)->int:
    card = card_map.get(card_id,{})
    base = get_card_power(card)
    cap = get_card_rating_cap(card)
    level = load_data(USERS_FILE,{}).get(str(user_id),{}).get('card_upgrades',{}).get(str(card_id),0)
    total = min(cap, base + max(0,int(level))*2)
    mutation = _best_mutation_for_card(user_id, card_id)
    if mutation:
        total += _mutation_bonus_from_instance(mutation)
    return total


async def card_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /card_info <ID карточки или mINSTANCE_ID>")
        return
    raw = context.args[0].strip()
    target_mutation = None
    try:
        if raw.lower().startswith('m') and raw[1:]:
            target_mutation = _get_mutation_instance(user.id, raw[1:])
            if not target_mutation:
                raise ValueError
            card_id = int(target_mutation.get('card_id'))
        else:
            card_id = int(raw)
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте ID карточки или mINSTANCE_ID.")
        return
    if card_id not in get_available_card_ids(user.id):
        await update.message.reply_text("❌ У вас нет этой карточки в коллекции!")
        return
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена в базе данных!")
        return
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    emoji = get_rarity_emoji(card["rarity"])
    caption = (
        f"🃏 <b>Информация о карточке</b>\n\n"
        f"🏷 <b>Название</b>: {html.escape(card['name'])}\n"
        f"{emoji} <b>Редкость</b>: {html.escape(card['rarity'])}\n"
    )
    if "description" in card:
        caption += f"📝 <b>Описание</b>: {html.escape(card['description'])}\n"
    normal_count = list(user_data.get("cards", [])).count(card_id)
    mutated_items = [m for m in user_data.get("mutated_cards", []) if int(m.get("card_id", -1)) == int(card_id)]
    caption += f"📦 <b>Обычных копий</b>: {normal_count}\n"
    caption += f"🧬 <b>Мутированных копий</b>: {len(mutated_items)}\n"
    card_map = {c["id"]: c for c in cards}
    lvl = int(user_data.get("card_upgrades", {}).get(str(card_id), 0))
    caption += f"💪 <b>Сила</b>: {get_player_card_power(user.id, card_id, card_map)}"
    if lvl > 0:
        caption += f" (⭐ ур. {lvl})"
    caption += "\n"
    if target_mutation:
        meta = _get_mutation_meta(target_mutation.get("mutation")) or {}
        caption += (
            f"🧬 <b>Выбранная мутация</b>: {meta.get('label', 'Мутация')}\n"
            f"⚡ <b>Бонус силы</b>: +{meta.get('power_bonus', 0)}\n"
            f"🆔 <b>M-ID</b>: {html.escape(str(target_mutation.get('instance_id')))}\n"
        )
    elif mutated_items:
        caption += "🧬 <b>Мутации у этой карточки</b>:\n"
        for item in mutated_items[:5]:
            meta = _get_mutation_meta(item.get("mutation")) or {}
            caption += f"   • {meta.get('emoji', '🧬')} {meta.get('label', 'Мутация')} (+{meta.get('power_bonus', 0)}) [m{item.get('instance_id')}]\n"
    photo = get_framed_card_photo(card, target_mutation)
    if photo:
        await update.message.reply_photo(photo=photo, caption=caption, parse_mode="HTML")
    else:
        await update.message.reply_text(caption, parse_mode="HTML")


async def _get_card_with_mutation_core(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    current_time = time.time()
    last_drop = user_data.get("last_drop", 0)
    base_cooldown = 6 * 3600
    # Для главного админа отключаем кулдаун /get_card — удобно для тестов дропов и мутаций.
    if user.id == ADMIN_ID:
        time_left = 0
    else:
        cooldown_multiplier = get_cooldown_multiplier(user.id)
        effective_cooldown = base_cooldown * cooldown_multiplier
        time_left = effective_cooldown - (current_time - last_drop)
    if time_left > 0:
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        time_text = f"{hours} час(ов) и {minutes} минут(ы)" if hours > 0 else f"{minutes} минут(ы)"
        await update.message.reply_text(f"⏳ Следующую карточку можно получить через: {time_text}")
        return
    rarities = load_data(RARITIES_FILE, [])
    if not rarities:
        default_rarities = [
            {"name": "Легендарная", "emoji": "🔥", "droppable": True},
            {"name": "Мифическая", "emoji": "🧠", "droppable": True},
            {"name": "Эпическая", "emoji": "💎", "droppable": True},
            {"name": "Редкая", "emoji": "✨", "droppable": True},
            {"name": "Обычная", "emoji": "🃏", "droppable": True},
            {"name": "Эксклюзивная", "emoji": "😎", "droppable": False}
        ]
        save_data(RARITIES_FILE, default_rarities)
        rarities = default_rarities
    droppable_rarities = [r["name"] for r in rarities if r.get("droppable", True)]
    all_cards = load_data(CARDS_FILE, [])
    cards = [c for c in all_cards if c["rarity"] in droppable_rarities] or all_cards
    if not cards:
        await update.message.reply_text("⚠️ В базе нет ни одной карточки! Обратитесь к администратору.")
        return
    rarity_chances = get_drop_weights()
    rarities_list = list(rarity_chances.keys())
    if not rarities_list:
        await update.message.reply_text("⚠️ Нет выпадаемых редкостей! Обратитесь к администратору.")
        return
    weights = [rarity_chances[r] for r in rarities_list]
    chosen_rarity = random.choices(rarities_list, weights=weights, k=1)[0]
    rarity_cards = [c for c in cards if c["rarity"] == chosen_rarity]
    if not rarity_cards:
        rarity_cards = cards
    card = random.choice(rarity_cards)

    is_mutated = random.random() < _get_effective_mutation_drop_chance()
    mutation_instance = None
    if is_mutated:
        mutation_key = _roll_mutation_key()
        mutation_instance = add_mutated_card(user.id, card["id"], mutation_key)
    else:
        if "cards" not in user_data:
            user_data["cards"] = []
        user_data["cards"].append(card["id"])
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        add_seen_card(user.id, card["id"])

    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    user_data["last_drop"] = current_time
    users[str(user.id)] = user_data
    save_data(USERS_FILE, users)
    await finalize_referral_after_first_card(user, context)

    base_coins = random.randint(10, 50)
    coin_multiplier = get_total_coin_multiplier(user.id)
    coins_earned = int(base_coins * coin_multiplier)
    new_balance = update_coins(user.id, coins_earned)
    normal_count = list(user_data.get("cards", [])).count(card["id"])
    mutated_count = len([m for m in user_data.get("mutated_cards", []) if int(m.get("card_id", -1)) == int(card["id"])])

    caption = (
        f"🎉 Вы получили карточку!\n\n"
        f"🏷 Название: {card['name']}\n"
        f"⭐ Редкость: {card['rarity']}\n"
    )
    if mutation_instance:
        meta = _get_mutation_meta(mutation_instance.get("mutation")) or {}
        caption += (
            f"🧬 Мутация: {meta.get('label', 'Мутация')}\n"
            f"⚡ Бонус силы: +{meta.get('power_bonus', 0)}\n"
            f"🆔 M-ID: {mutation_instance.get('instance_id')}\n"
            f"📦 Мутированных копий этой карты: {mutated_count}\n"
        )
    else:
        count_text = f" (x{normal_count})" if normal_count > 1 else ""
        caption = caption.replace(card['name'], f"{card['name']}{count_text}", 1)
    if "description" in card:
        caption += f"📝 Описание: {card['description']}\n"
    caption += (
        f"💰 Получено монет: +{coins_earned}\n"
        f"💰 Ваш баланс: {new_balance}\n\n"
        f"📚 Обычных: {len(user_data.get('cards', []))} | Мутированных: {len(user_data.get('mutated_cards', []))}"
    )

    rarity_animations = {
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
            "🔥 Она СИЯЕТ золотом...",
            "✨ 🎇 ЛЕГЕНДА! Открываем!",
        ],
        "Мифическая": [
            "🃏 Тянем карточку из колоды...",
            "🧠 ⚡ Карта искрит идеями...",
            "🧠 💡 Она блещет умом...",
            "🧠 🎓 Гениально! Открываем!",
        ],
        "Мифическая": [
            "🃏 Тянем карточку из колоды...",
            "🃏 🌫 Колоду окутывает туман...",
            "😳 ⚡ Карта из древних МИФОВ...",
            "😳 🌌 Она светится магией...",
            "😳 🔮 МИФИЧЕСКАЯ! Открываем!",
        ],
        "Сверхредкая": [
            "🃏 Тянем карточку из колоды...",
            "🕶 Карта в тёмных очках...",
            "🕶 😏 Сверхредкая! Открываем!",
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
    try:
        if mutation_instance:
            meta = _get_mutation_meta(mutation_instance.get("mutation")) or {}
            frames = meta.get("animation", ["🧬 Мутация...", "✨ Мутированная карта!"])
        else:
            frames = rarity_animations.get(card.get("rarity"), rarity_animations["Обычная"])
        anim_msg = await update.message.reply_text(frames[0])
        for frame in frames[1:]:
            await asyncio.sleep(0.9)
            await anim_msg.edit_text(frame)
        await asyncio.sleep(0.8)
        try:
            await anim_msg.delete()
        except Exception:
            pass
    except Exception:
        pass

    image_path = os.path.join(CARDS_IMAGE_DIR, card.get("image", ""))
    if os.path.exists(image_path):
        photo = get_framed_card_photo(card, mutation_instance) or open(image_path, "rb")
        await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text(caption)


async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _get_card_with_mutation_core(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Получение карточки уже обрабатывается. Подождите пару секунд.")
    if '_run_locked_action' in globals():
        await _run_locked_action(context, user.id, "get_card", lambda: _get_card_with_mutation_core(update, context), "", on_busy=_busy)
    else:
        await _get_card_with_mutation_core(update, context)


def _format_market_item_name(card: dict, item: dict):
    base = f"{get_rarity_emoji(card.get('rarity', ''))} {html.escape(card.get('name', '?'))}"
    if item.get("mutation_key"):
        meta = _get_mutation_meta(item.get("mutation_key")) or {}
        return f"{base} • {meta.get('emoji', '🧬')} {html.escape(meta.get('label', 'Мутация'))} (+{meta.get('power_bonus', 0)})"
    return base


def _build_market_page(user_id: int, page: int):
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
        label = _format_market_item_name(card, item)
        lines.append(f"#{item['id']} <b>{label}</b> — 💰 {_fmt_coins(item['price'])} (продавец: {item['seller_id']})")
        if item["seller_id"] != user_id:
            keyboard.append([InlineKeyboardButton(f"Купить #{item['id']} за {_fmt_coins(item['price'])}", callback_data=f"market_buy_{item['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"market_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"market_page_{page + 1}"))
    if nav:
        keyboard.append(nav)
    lines.append("\nℹ️ Обычный лот: <code>/sell card_id цена</code> | мутированный: <code>/sell mINSTANCE_ID цена</code>")
    return "\n".join(lines), InlineKeyboardMarkup(keyboard) if keyboard else None


def _parse_sell_target(raw: str):
    token = str(raw or '').strip()
    low = token.lower()
    if low.startswith(('m', 'mut_')) or low.startswith('m-id:') or low.startswith('m_id:'):
        return 'mutated', _normalize_mutation_token(token)
    return 'normal', int(token)


def _rating_team_refs(user_id: int) -> list:
    team = get_rating_team(user_id) or {}
    refs = []
    if team.get("gk") is not None:
        refs.append(team.get("gk"))
    refs.extend(list(team.get("field", []) or []))
    if team.get("coach") is not None:
        refs.append(team.get("coach"))
    return refs


def _normal_rating_usage_count(user_id: int, card_id: int) -> int:
    count = 0
    for ref in _rating_team_refs(user_id):
        if not _is_team_mutation_ref(ref):
            try:
                if int(ref) == int(card_id):
                    count += 1
            except Exception:
                pass
    return count


def _mutation_used_in_rating_team(user_id: int, instance_id: str) -> bool:
    wanted = str(_normalize_mutation_token(instance_id))
    for ref in _rating_team_refs(user_id):
        if _is_team_mutation_ref(ref):
            current = str(ref)[len(TEAM_MUTATION_PREFIX):]
            if str(current) == wanted:
                return True
    return False


def _can_sell_normal_card(user_id: int, card_id: int) -> tuple[bool, str]:
    """Можно продавать обычную карту только если после продажи останутся копии, нужные рейтинговому составу."""
    users = load_data(USERS_FILE, {})
    normal_cards = list(users.get(str(user_id), {}).get("cards", []))
    owned = normal_cards.count(int(card_id))
    if owned <= 0:
        return False, "❌ У вас нет обычной копии этой карточки. Если хотите продать мутированную — используйте её M-ID."
    used = _normal_rating_usage_count(user_id, int(card_id))
    if used > 0 and owned - 1 < used:
        return False, (
            "❌ Эта карточка сейчас стоит в рейтинговом составе.\n"
            "Сначала замените её через /rating_team или продайте другую копию/мутированную карту."
        )
    return True, ""


def _can_sell_mutated_card(user_id: int, instance_id: str) -> tuple[bool, str]:
    """Мутированная карта — отдельный экземпляр; нельзя продавать именно тот M-ID, который стоит в составе."""
    if _mutation_used_in_rating_team(user_id, instance_id):
        return False, (
            "❌ Эта мутированная карточка сейчас стоит в рейтинговом составе.\n"
            "Сначала замените её через /rating_team, потом выставляйте на продажу."
        )
    return True, ""


def remove_one_normal_card(user_id: int, card_id: int) -> bool:
    """Списывает только обычную копию, не трогая мутированные экземпляры с тем же base card_id."""
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    cards = list(user_data.get("cards", []))
    if int(card_id) not in cards:
        return False
    buff = user_data.get("buff_card")
    if buff and buff.get("card_id") == int(card_id) and cards.count(int(card_id)) <= 1:
        return False
    cards.remove(int(card_id))
    user_data["cards"] = cards
    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)
    return True


async def sell_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        return
    if not await is_subscribed(user.id, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("ℹ️ Использование: /sell <card_id или mINSTANCE_ID> <цена>")
        return
    try:
        target_kind, target_value = _parse_sell_target(context.args[0])
        price = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Неверный формат.")
        return
    if price <= 0:
        await update.message.reply_text("❌ Цена должна быть положительной.")
        return
    if price > MARKET_MAX_PRICE:
        await update.message.reply_text(f"❌ Лимит цены одного лота: {_fmt_coins(MARKET_MAX_PRICE)} монет.")
        return
    market = load_data(MARKET_FILE, [])
    if len([m for m in market if m["seller_id"] == user.id]) >= 3:
        await update.message.reply_text("❌ У вас уже 3 активных лота. Снимите один через /my_listings.")
        return
    cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in cards}
    listing_id = max((m["id"] for m in market), default=0) + 1
    if target_kind == "mutated":
        instance = _get_mutation_instance(user.id, str(target_value))
        if not instance:
            await update.message.reply_text("❌ Мутированная карточка не найдена.")
            return
        ok, reason = _can_sell_mutated_card(user.id, str(target_value))
        if not ok:
            await update.message.reply_text(reason)
            return
        card = card_map.get(int(instance.get("card_id", -1)))
        if not card:
            await update.message.reply_text("❌ Базовая карточка не найдена.")
            return
        meta = _get_mutation_meta(instance.get("mutation")) or {}
        min_price = _get_mutated_market_min_price(card, instance.get("mutation"))
        if price < min_price:
            await update.message.reply_text(f"❌ Минимальная цена для мутированной карты на маркете: {_fmt_coins(min_price)} монет. Для личного предложения используйте /offer_sell.")
            return
        removed, mutated_cards = remove_mutated_card_instance(user.id, str(target_value))
        if not removed:
            await update.message.reply_text("❌ Не удалось снять мутированную карту из коллекции.")
            return
        _save_user_mutated_cards(user.id, mutated_cards)
        market.append({
            "id": listing_id,
            "seller_id": user.id,
            "card_id": int(instance.get("card_id")),
            "price": price,
            "listed_at": time.time(),
            "mutation_key": instance.get("mutation"),
            "mutation_instance": removed,
        })
        save_data(MARKET_FILE, market)
        await update.message.reply_text(
            f"✅ Мутированная карточка «{card['name']}» ({meta.get('label', 'Мутация')}) выставлена на маркет!\n"
            f"🆔 Объявление #{listing_id}\n💰 Цена: {_fmt_coins(price)} монет\n\n"
            f"Отменить: /unlist {listing_id}"
        )
        return
    card_id = int(target_value)
    ok, reason = _can_sell_normal_card(user.id, card_id)
    if not ok:
        await update.message.reply_text(reason)
        return
    card = card_map.get(card_id)
    if not card:
        await update.message.reply_text("❌ Карточка не найдена.")
        return
    min_price = MARKET_MIN_PRICES.get(card.get("rarity"))
    if min_price and price < min_price:
        await update.message.reply_text(f"❌ Минимальная цена для {card['rarity']} на маркете: {_fmt_coins(min_price)} монет. Для личного предложения используйте /offer_sell.")
        return
    if not remove_one_card(user.id, card_id):
        await update.message.reply_text("❌ Не удалось снять карточку с коллекции.")
        return
    market.append({
        "id": listing_id,
        "seller_id": user.id,
        "card_id": card_id,
        "price": price,
        "listed_at": time.time(),
    })
    save_data(MARKET_FILE, market)
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'market_ops', 1))
    log_action(user.id, 'market_list', str(listing_id))
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
        lines.append(f"#{item['id']} {_format_market_item_name(card, item)} — 💰 {_fmt_coins(item['price'])}")
    lines.append("\nОтменить: /unlist <ID объявления>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def unlist_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(subscription_required_text())
        return
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
    if item.get("mutation_instance"):
        add_mutated_card_instance(user.id, item.get("mutation_instance"))
    else:
        add_one_card(user.id, item["card_id"])
    await update.message.reply_text(f"✅ Объявление #{listing_id} снято, карточка возвращена в коллекцию.")


async def admin_unlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    if item.get("mutation_instance"):
        add_mutated_card_instance(item["seller_id"], item.get("mutation_instance"))
    else:
        add_one_card(item["seller_id"], item["card_id"])
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == item["card_id"]), {})
    await update.message.reply_text(f"✅ Объявление #{listing_id} снято. Карточка возвращена игроку {item['seller_id']}.")
    try:
        await context.bot.send_message(item["seller_id"], f"ℹ️ Ваше объявление #{listing_id} снято администратором. Карточка возвращена в коллекцию.")
    except Exception:
        pass



async def offer_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Личное предложение продажи: /offer_sell <user_id> <card_id|mID> <цена>. Минималки маркета тут не действуют."""
    user = update.effective_user
    if is_banned(user.id):
        return
    if not await is_subscribed(user.id, context):
        return
    if len(context.args) < 3:
        await update.message.reply_text("ℹ️ Использование: /offer_sell <user_id> <card_id или mINSTANCE_ID> <цена>\nМинимальной цены тут нет, максимум 10 000 монет.")
        return
    try:
        buyer_id = int(context.args[0])
        target_kind, target_value = _parse_sell_target(context.args[1])
        price = int(context.args[2])
    except Exception:
        await update.message.reply_text("❌ Неверный формат.")
        return
    if buyer_id == user.id:
        await update.message.reply_text("❌ Нельзя предложить продажу самому себе.")
        return
    if price <= 0 or price > MARKET_MAX_PRICE:
        await update.message.reply_text(f"❌ Цена должна быть от 1 до {_fmt_coins(MARKET_MAX_PRICE)} монет.")
        return
    users = load_data(USERS_FILE, {})
    if str(buyer_id) not in users:
        await update.message.reply_text("❌ Игрок не найден в базе бота.")
        return
    market = load_data(MARKET_FILE, [])
    if len([m for m in market if m["seller_id"] == user.id]) >= 3:
        await update.message.reply_text("❌ У вас уже 3 активных лота. Снимите один через /my_listings.")
        return
    cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in cards}
    listing_id = max((m["id"] for m in market), default=0) + 1
    mutation_instance = None
    mutation_key = None
    if target_kind == "mutated":
        mutation_instance = _get_mutation_instance(user.id, str(target_value))
        if not mutation_instance:
            await update.message.reply_text("❌ Мутированная карточка не найдена.")
            return
        ok, reason = _can_sell_mutated_card(user.id, str(target_value))
        if not ok:
            await update.message.reply_text(reason)
            return
        card_id = int(mutation_instance.get("card_id"))
        removed, mutated_cards = remove_mutated_card_instance(user.id, str(target_value))
        if not removed:
            await update.message.reply_text("❌ Не удалось снять мутированную карту из коллекции.")
            return
        _save_user_mutated_cards(user.id, mutated_cards)
        mutation_instance = removed
        mutation_key = removed.get("mutation")
    else:
        card_id = int(target_value)
        ok, reason = _can_sell_normal_card(user.id, card_id)
        if not ok:
            await update.message.reply_text(reason)
            return
        if not remove_one_normal_card(user.id, card_id):
            await update.message.reply_text("❌ Не удалось снять обычную карточку из коллекции.")
            return
    card = card_map.get(card_id, {})
    item = {
        "id": listing_id,
        "seller_id": user.id,
        "target_buyer_id": buyer_id,
        "card_id": card_id,
        "price": price,
        "listed_at": time.time(),
        "direct_offer": True,
    }
    if mutation_instance:
        item["mutation_key"] = mutation_key
        item["mutation_instance"] = mutation_instance
    market.append(item)
    save_data(MARKET_FILE, market)
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'market_ops', 1))
    log_action(user.id, 'market_offer', str(listing_id))
    label = _format_market_item_name(card, item)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"Купить за {_fmt_coins(price)}", callback_data=f"market_buy_{listing_id}")]])
    await update.message.reply_text(f"✅ Предложение продажи отправлено игроку {buyer_id}.\n#{listing_id} {label} — {_fmt_coins(price)} монет")
    try:
        await context.bot.send_message(
            buyer_id,
            f"💰 <b>Вам предложили купить карточку</b>\n\n#{listing_id} <b>{label}</b>\nЦена: {_fmt_coins(price)} монет\nПродавец: {user.id}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass


async def market_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer()
    except Exception:
        pass
    try:
        listing_id = int(str(query.data).replace("market_buy_", "", 1))
    except Exception:
        try:
            await query.edit_message_text("❌ Неверные данные покупки.")
        except Exception:
            pass
        return
    buyer_id = query.from_user.id
    if is_banned(buyer_id):
        await query.edit_message_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(buyer_id, context):
        await query.edit_message_text(subscription_required_text())
        return
    market = load_data(MARKET_FILE, [])
    item = next((m for m in market if int(m.get("id", -1)) == listing_id), None)
    if not item:
        await query.edit_message_text("❌ Объявление уже недоступно.")
        return
    if int(item.get("seller_id")) == int(buyer_id):
        await query.edit_message_text("❌ Нельзя купить свою карточку.")
        return
    if item.get("target_buyer_id") and int(item.get("target_buyer_id")) != int(buyer_id):
        await query.edit_message_text("❌ Это личное предложение продажи не для вас.")
        return
    price = int(item.get("price", 0))
    if price <= 0:
        await query.edit_message_text("❌ У лота некорректная цена. Сообщите админу.")
        log_security("bad_market_price", buyer_id, f"listing {listing_id} price {price}", "warn")
        return
    if get_coins(buyer_id) < price:
        await query.edit_message_text("❌ Недостаточно монет!")
        return
    if item.get("_processing"):
        await query.edit_message_text("⌛ Покупка уже обрабатывается, откройте маркет заново.")
        return
    # Ставим блокировку лота и сразу сохраняем, чтобы две покупки не прошли параллельно.
    for m in market:
        if int(m.get("id", -1)) == listing_id:
            m["_processing"] = buyer_id
            break
    save_data(MARKET_FILE, market)
    try:
        update_coins(buyer_id, -price)
        update_coins(item["seller_id"], price)
        if item.get("mutation_instance"):
            add_mutated_card_instance(buyer_id, dict(item.get("mutation_instance")))
        else:
            add_one_card(buyer_id, int(item["card_id"]))
        market = [m for m in load_data(MARKET_FILE, []) if int(m.get("id", -1)) != listing_id]
        save_data(MARKET_FILE, market)
    except Exception as e:
        # Денежный rollback на случай ошибки после списания.
        try:
            update_coins(buyer_id, price)
            update_coins(item["seller_id"], -price)
            market = load_data(MARKET_FILE, [])
            for m in market:
                if int(m.get("id", -1)) == listing_id:
                    m.pop("_processing", None)
                    break
            save_data(MARKET_FILE, market)
        except Exception:
            pass
        log_security("market_buy_error", buyer_id, f"listing {listing_id}: {e}", "error")
        await query.edit_message_text("❌ Покупка не прошла из-за ошибки. Деньги возвращены, попробуйте ещё раз или сообщите админу.")
        return
    # Квесты: покупатель сделал маркет-операцию, продавец сделал продажу.
    buyer_rewards = inc_stat(buyer_id, 'market_ops', 1)
    seller_rewards_1 = inc_stat(item['seller_id'], 'market_ops', 1)
    seller_rewards_2 = inc_stat(item['seller_id'], 'market_sales', 1)
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if int(c.get("id", -999)) == int(item.get("card_id", -1))), {})
    card_name = _format_market_item_name(card, item) if '_format_market_item_name' in globals() else card.get('name', str(item.get('card_id')))
    price_text = _fmt_coins(price)
    log_action(buyer_id, 'market_buy', str(listing_id))
    log_action(item['seller_id'], 'market_sale', str(listing_id))
    await query.edit_message_text(f"✅ Вы купили «{html.escape(card_name)}» за {price_text} монет!", parse_mode="HTML")
    await _notify_quest_rewards(context, buyer_id, buyer_rewards)
    await _notify_quest_rewards(context, item['seller_id'], seller_rewards_1)
    await _notify_quest_rewards(context, item['seller_id'], seller_rewards_2)
    try:
        await context.bot.send_message(item["seller_id"], f"💰 Ваша карточка «{html.escape(card_name)}» продана за {price_text} монет!", parse_mode="HTML")
    except Exception:
        pass


def _run_bot_main():
    print(f"🏒 Хоккейные карточки: запуск бота из папки {BASE_DIR}")
    try:
        main()
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception:
        _err = traceback.format_exc()
        print(_err)
        try:
            with open(os.path.join(BASE_DIR, "bot_crash.log"), "a", encoding="utf-8") as f:
                f.write("\n\n===== " + datetime.now().isoformat() + " CRASH =====\n")
                f.write(_err)
        except Exception:
            pass
        raise



# ============================ КАСТОМИЗАЦИЯ ПРОФИЛЯ ============================
PROFILE_BACKGROUNDS = {
    "ice": {"name": "Лёд", "colors": ((7, 12, 24), (22, 55, 95)), "emoji": "🧊"},
    "fire": {"name": "Огонь", "colors": ((35, 8, 8), (120, 40, 16)), "emoji": "🔥"},
    "neon": {"name": "Неон", "colors": ((8, 8, 35), (55, 18, 105)), "emoji": "🌌"},
    "gold": {"name": "Золото", "colors": ((42, 27, 4), (138, 95, 22)), "emoji": "👑"},
    "void": {"name": "Бездна", "colors": ((4, 4, 8), (45, 20, 75)), "emoji": "🕳"},
}
PROFILE_FRAMES = {
    "blue": {"name": "Синий неон", "color": (75, 155, 255), "emoji": "🔵"},
    "gold": {"name": "Золотая", "color": (255, 205, 72), "emoji": "🟡"},
    "red": {"name": "Красная", "color": (255, 90, 90), "emoji": "🔴"},
    "purple": {"name": "Фиолетовая", "color": (180, 105, 255), "emoji": "🟣"},
    "green": {"name": "Изумрудная", "color": (75, 230, 160), "emoji": "🟢"},
}
PROFILE_BADGES = {
    "none": {"name": "Без значка", "emoji": "▫️"},
    "star": {"name": "Звезда", "emoji": "⭐"},
    "crown": {"name": "Корона", "emoji": "👑"},
    "skull": {"name": "Череп", "emoji": "💀"},
    "puck": {"name": "Шайба", "emoji": "🏒"},
    "mutant": {"name": "Мутация", "emoji": "🧬"},
}

def _profile_custom(user_id:int) -> dict:
    users = load_data(USERS_FILE,{})
    u = users.setdefault(str(user_id), {})
    c = u.setdefault('profile_custom', {})
    c.setdefault('background', 'ice')
    c.setdefault('frame', 'blue')
    c.setdefault('badge', 'none')
    c.setdefault('showcase', [])
    return c

def _save_profile_custom(user_id:int, custom:dict) -> None:
    users = load_data(USERS_FILE,{})
    u = users.setdefault(str(user_id), {})
    u['profile_custom'] = custom
    users[str(user_id)] = u
    save_data(USERS_FILE, users)

def _profile_custom_names(user_id:int) -> str:
    c = _profile_custom(user_id)
    bg = PROFILE_BACKGROUNDS.get(c.get('background'), PROFILE_BACKGROUNDS['ice'])
    fr = PROFILE_FRAMES.get(c.get('frame'), PROFILE_FRAMES['blue'])
    bd = PROFILE_BADGES.get(c.get('badge'), PROFILE_BADGES['none'])
    return f"{bg['emoji']} Фон: {bg['name']}\n{fr['emoji']} Рамка: {fr['name']}\n{bd['emoji']} Значок: {bd['name']}"

async def profile_custom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    args = context.args or []
    if not args:
        lines = [
            "🎨 <b>Кастомизация профиля</b>",
            "",
            _profile_custom_names(user.id),
            "",
            "Команды:",
            "<code>/profile_bg ключ</code> — выбрать фон",
            "<code>/profile_frame ключ</code> — выбрать рамку",
            "<code>/profile_badge ключ</code> — выбрать значок",
            "<code>/profile_showcase id id id</code> — витрина до 3 карт",
            "",
            "Фоны: " + ", ".join(f"<code>{k}</code> {v['emoji']} {v['name']}" for k,v in PROFILE_BACKGROUNDS.items()),
            "Рамки: " + ", ".join(f"<code>{k}</code> {v['emoji']} {v['name']}" for k,v in PROFILE_FRAMES.items()),
            "Значки: " + ", ".join(f"<code>{k}</code> {v['emoji']} {v['name']}" for k,v in PROFILE_BADGES.items()),
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return
    await update.message.reply_text("ℹ️ Используйте /profile_custom без аргументов, либо отдельные команды /profile_bg, /profile_frame, /profile_badge, /profile_showcase", parse_mode="HTML")

async def profile_bg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    key = (context.args[0].lower() if context.args else "")
    if key not in PROFILE_BACKGROUNDS:
        await update.message.reply_text("❌ Нет такого фона. Список: /profile_custom")
        return
    if '_owns_cosmetic' in globals() and not _owns_cosmetic(user.id, 'background', key):
        await update.message.reply_text("🔒 Этот фон ещё не открыт. Проверьте /cosmetic_shop или /my_cosmetics")
        return
    c = _profile_custom(user.id); c['background'] = key; _save_profile_custom(user.id, c)
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'profile_customized', 1))
    await update.message.reply_text(f"✅ Фон профиля выбран: {PROFILE_BACKGROUNDS[key]['emoji']} {PROFILE_BACKGROUNDS[key]['name']}\nПосмотреть: /profile")

async def profile_frame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    key = (context.args[0].lower() if context.args else "")
    if key not in PROFILE_FRAMES:
        await update.message.reply_text("❌ Нет такой рамки. Список: /profile_custom")
        return
    if '_owns_cosmetic' in globals() and not _owns_cosmetic(user.id, 'frame', key):
        await update.message.reply_text("🔒 Эта рамка ещё не открыта. Проверьте /cosmetic_shop или /my_cosmetics")
        return
    c = _profile_custom(user.id); c['frame'] = key; _save_profile_custom(user.id, c)
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'profile_customized', 1))
    await update.message.reply_text(f"✅ Рамка профиля выбрана: {PROFILE_FRAMES[key]['emoji']} {PROFILE_FRAMES[key]['name']}\nПосмотреть: /profile")

async def profile_badge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    key = (context.args[0].lower() if context.args else "")
    if key not in PROFILE_BADGES:
        await update.message.reply_text("❌ Нет такого значка. Список: /profile_custom")
        return
    if '_owns_cosmetic' in globals() and not _owns_cosmetic(user.id, 'badge', key):
        await update.message.reply_text("🔒 Этот значок ещё не открыт. Проверьте /cosmetic_shop или /my_cosmetics")
        return
    c = _profile_custom(user.id); c['badge'] = key; _save_profile_custom(user.id, c)
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'profile_customized', 1))
    await update.message.reply_text(f"✅ Значок профиля выбран: {PROFILE_BADGES[key]['emoji']} {PROFILE_BADGES[key]['name']}\nПосмотреть: /profile")

async def profile_showcase_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /profile_showcase <id карты> <id карты> <id карты>\nМожно указать от 1 до 3 карт из коллекции.")
        return
    ids=[]
    try:
        for x in context.args[:3]:
            cid=int(x)
            ids.append(cid)
    except Exception:
        await update.message.reply_text("❌ Укажите обычные ID карт через пробел, например: /profile_showcase 1 5 9")
        return
    available = get_available_card_ids(user.id)
    if any(cid not in available for cid in ids):
        await update.message.reply_text("❌ Все карты витрины должны быть в вашей коллекции и не должны быть выставлены/заняты.")
        return
    c = _profile_custom(user.id); c['showcase'] = ids; _save_profile_custom(user.id, c)
    await update.message.reply_text("✅ Витрина профиля обновлена. Посмотреть: /profile")



# ============================ МАГАЗИН КОСМЕТИКИ ============================
COSMETIC_SHOP_REFRESH_SECONDS = 2 * 60 * 60
COSMETIC_SHOP_SLOTS = 5
COSMETIC_RARITIES = {
    "common": {"name": "Обычная", "emoji": "⚪", "weight": 45, "price": (350, 700)},
    "rare": {"name": "Редкая", "emoji": "🔵", "weight": 28, "price": (900, 1600)},
    "epic": {"name": "Эпическая", "emoji": "🟣", "weight": 16, "price": (2200, 3800)},
    "legendary": {"name": "Легендарная", "emoji": "🟡", "weight": 8, "price": (5000, 8500)},
    "exclusive": {"name": "Эксклюзивная", "emoji": "🔴", "weight": 3, "price": (10000, 16000)},
}
FREE_PROFILE_COSMETICS = {"background": {"ice"}, "frame": {"blue"}, "badge": {"none"}}
PROFILE_BACKGROUNDS.update({
    "storm": {"name": "Метель", "colors": ((4, 18, 32), (120, 210, 255)), "emoji": "❄️"},
    "arena": {"name": "Арена", "colors": ((10, 12, 24), (35, 95, 150)), "emoji": "🏟"},
    "lava": {"name": "Лава", "colors": ((28, 3, 3), (210, 70, 12)), "emoji": "🌋"},
    "galaxy": {"name": "Галактика", "colors": ((6, 4, 32), (110, 40, 170)), "emoji": "🌠"},
    "royal": {"name": "Royal Ice", "colors": ((28, 18, 3), (220, 170, 55)), "emoji": "🏆"},
})
PROFILE_FRAMES.update({
    "ice": {"name": "Ледяная", "color": (155, 230, 255), "emoji": "🧊"},
    "fire": {"name": "Огненная", "color": (255, 105, 45), "emoji": "🔥"},
    "void": {"name": "Бездна", "color": (120, 70, 220), "emoji": "🕳"},
    "rainbow": {"name": "Радужная", "color": (255, 120, 220), "emoji": "🌈"},
    "champion": {"name": "Чемпионская", "color": (255, 225, 90), "emoji": "🏆"},
})
PROFILE_BADGES.update({
    "diamond": {"name": "Алмаз", "emoji": "💎"},
    "fire": {"name": "Пламя", "emoji": "🔥"},
    "ice": {"name": "Лёд", "emoji": "🧊"},
    "ghost": {"name": "Призрак", "emoji": "👻"},
    "rocket": {"name": "Ракета", "emoji": "🚀"},
})
COSMETIC_CATALOG = []
def _register_cosmetic(kind, key, rarity):
    source = {"background": PROFILE_BACKGROUNDS, "frame": PROFILE_FRAMES, "badge": PROFILE_BADGES}[kind][key]
    COSMETIC_CATALOG.append({"kind": kind, "key": key, "name": source["name"], "emoji": source["emoji"], "rarity": rarity})
for k in PROFILE_BACKGROUNDS:
    if k not in FREE_PROFILE_COSMETICS["background"]:
        _register_cosmetic("background", k, {"fire":"rare","neon":"rare","gold":"epic","void":"epic","storm":"rare","arena":"common","lava":"epic","galaxy":"legendary","royal":"exclusive"}.get(k,"common"))
for k in PROFILE_FRAMES:
    if k not in FREE_PROFILE_COSMETICS["frame"]:
        _register_cosmetic("frame", k, {"gold":"epic","red":"rare","purple":"rare","green":"common","ice":"rare","fire":"epic","void":"legendary","rainbow":"exclusive","champion":"legendary"}.get(k,"common"))
for k in PROFILE_BADGES:
    if k not in FREE_PROFILE_COSMETICS["badge"]:
        _register_cosmetic("badge", k, {"star":"common","crown":"epic","skull":"rare","puck":"common","mutant":"legendary","diamond":"epic","fire":"rare","ice":"rare","ghost":"epic","rocket":"legendary"}.get(k,"common"))

def _cosmetic_id(item): return f"{item.get('kind')}:{item.get('key')}"
def _cosmetic_kind_name(kind): return {"background":"фон", "frame":"рамка", "badge":"значок"}.get(kind, kind)

def _user_cosmetics(user_id:int):
    users=load_data(USERS_FILE,{})
    u=users.setdefault(str(user_id),{})
    owned=u.setdefault('owned_cosmetics', {})
    for kind, keys in FREE_PROFILE_COSMETICS.items():
        owned[kind]=sorted(set(owned.get(kind, [])) | set(keys))
    users[str(user_id)]=u; save_data(USERS_FILE,users)
    return owned

def _owns_cosmetic(user_id:int, kind:str, key:str) -> bool:
    return key in set(_user_cosmetics(user_id).get(kind, []))

def _grant_cosmetic(user_id:int, kind:str, key:str):
    users=load_data(USERS_FILE,{})
    u=users.setdefault(str(user_id),{})
    owned=u.setdefault('owned_cosmetics', {})
    owned[kind]=sorted(set(owned.get(kind, [])) | {key})
    users[str(user_id)]=u; save_data(USERS_FILE,users)

def _roll_cosmetic_shop(force=False):
    state=load_data(COSMETIC_SHOP_FILE,{})
    now=time.time()
    if not force and state.get('items') and now < float(state.get('next_refresh',0) or 0):
        return state
    rng=random.Random(int(now//COSMETIC_SHOP_REFRESH_SECONDS))
    rarity_keys=list(COSMETIC_RARITIES.keys()); weights=[COSMETIC_RARITIES[r]['weight'] for r in rarity_keys]
    items=[]; used=set(); attempts=0
    while len(items)<COSMETIC_SHOP_SLOTS and attempts<150:
        attempts+=1
        rarity=rng.choices(rarity_keys, weights=weights, k=1)[0]
        pool=[c for c in COSMETIC_CATALOG if c['rarity']==rarity and _cosmetic_id(c) not in used] or [c for c in COSMETIC_CATALOG if _cosmetic_id(c) not in used]
        if not pool: break
        c=dict(rng.choice(pool)); used.add(_cosmetic_id(c))
        lo,hi=COSMETIC_RARITIES[c['rarity']]['price']
        c['id']=len(items)+1; c['price']=max(50, rng.randint(lo,hi)//50*50)
        items.append(c)
    state={"items":items,"last_refresh":now,"next_refresh":now+COSMETIC_SHOP_REFRESH_SECONDS}
    save_data(COSMETIC_SHOP_FILE,state)
    return state

def _cosmetic_item_text(item):
    r=COSMETIC_RARITIES.get(item.get('rarity'), COSMETIC_RARITIES['common'])
    return f"#{item['id']} {item['emoji']} <b>{html.escape(item['name'])}</b> — {_cosmetic_kind_name(item['kind'])}\n{r['emoji']} {r['name']} • 💰 {_fmt_coins(item['price'])} монет"

async def cosmetic_shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user=update.effective_user
    if is_banned(user.id): return await update.message.reply_text("❌ Вы заблокированы в этом боте.")
    state=_roll_cosmetic_shop(False)
    left=max(0,int(float(state.get('next_refresh',0))-time.time()))
    lines=["🎨 <b>Магазин косметики</b>", f"⏳ Обновление через: {left//3600}ч {(left%3600)//60}мин", "", "Купить: <code>/buy_cosmetic ID</code>", "Мои стили: <code>/my_cosmetics</code>", ""]
    owned=_user_cosmetics(user.id)
    for item in state.get('items',[]):
        mark="\n✅ Уже есть" if item['key'] in owned.get(item['kind'],[]) else ""
        lines.append(_cosmetic_item_text(item)+mark); lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def buy_cosmetic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user=update.effective_user
    if is_banned(user.id): return await update.message.reply_text("❌ Вы заблокированы в этом боте.")
    if not context.args: return await update.message.reply_text("ℹ️ Использование: /buy_cosmetic <ID из /cosmetic_shop>")
    try: item_id=int(context.args[0])
    except Exception: return await update.message.reply_text("❌ ID должен быть числом.")
    state=_roll_cosmetic_shop(False)
    item=next((i for i in state.get('items',[]) if int(i.get('id',-1))==item_id),None)
    if not item: return await update.message.reply_text("❌ Такого товара нет в текущем магазине. Откройте /cosmetic_shop")
    if _owns_cosmetic(user.id,item['kind'],item['key']): return await update.message.reply_text("✅ Эта косметика уже есть у вас.")
    price=int(item.get('price',0))
    if get_coins(user.id)<price: return await update.message.reply_text(f"❌ Недостаточно монет. Нужно {_fmt_coins(price)} монет.")
    update_coins(user.id,-price); _grant_cosmetic(user.id,item['kind'],item['key'])
    c=_profile_custom(user.id); c[item['kind']]=item['key']; _save_profile_custom(user.id,c)
    await update.message.reply_text(f"✅ Куплено и применено: {item['emoji']} <b>{html.escape(item['name'])}</b>\nПотрачено: {_fmt_coins(price)} монет\nПосмотреть профиль: /profile", parse_mode="HTML")
    await _notify_quest_rewards(update, user.id, inc_stat(user.id, 'buy_cosmetic', 1))
    log_action(user.id,'buy_cosmetic',_cosmetic_id(item))

async def my_cosmetics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user=update.effective_user; owned=_user_cosmetics(user.id)
    lines=["🎒 <b>Моя косметика</b>", "Выбрать: /profile_bg, /profile_frame, /profile_badge", ""]
    for kind,title,catalog in [('background','Фоны',PROFILE_BACKGROUNDS),('frame','Рамки',PROFILE_FRAMES),('badge','Значки',PROFILE_BADGES)]:
        keys=owned.get(kind,[]); lines.append(f"<b>{title}:</b> {len(keys)}/{len(catalog)}")
        parts=[]
        for k in keys:
            v=catalog.get(k)
            if v: parts.append(f"<code>{k}</code> {v.get('emoji','')} {html.escape(v.get('name',k))}")
        lines.append(", ".join(parts) if parts else "—"); lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cosmetic_shop_refresh_cycle(context):
    before=load_data(COSMETIC_SHOP_FILE,{})
    if time.time() >= float(before.get('next_refresh',0) or 0):
        _roll_cosmetic_shop(True)



# ============================ REPORT / ОБРАЩЕНИЕ К АДМИНУ ============================
def _next_report_id() -> int:
    reports = load_data(REPORTS_FILE, [])
    if not isinstance(reports, list): reports = []
    return max((int(r.get('id', 0)) for r in reports), default=0) + 1

def _save_report(report: dict):
    reports = load_data(REPORTS_FILE, [])
    if not isinstance(reports, list): reports = []
    reports.append(report)
    save_data(REPORTS_FILE, reports[-1000:])

def _find_open_report(report_id: int):
    reports = load_data(REPORTS_FILE, [])
    for r in reports:
        if int(r.get('id', -1)) == int(report_id) and r.get('status') == 'open':
            return r, reports
    return None, reports

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    text = " ".join(context.args or []).strip()
    if not text:
        await update.message.reply_text("ℹ️ Использование: /report <текст проблемы>\nНапример: /report не засчитался квест за дуэль")
        return
    rid = _next_report_id()
    username = f"@{user.username}" if user.username else "юзернейм не указан"
    name = html.escape(user.full_name or user.first_name or str(user.id))
    report = {"id": rid, "user_id": user.id, "username": username, "name": user.full_name or user.first_name or "", "text": text, "status": "open", "created": time.time()}
    _save_report(report)
    admin_text = (
        f"🐞 <b>Новый репорт #{rid}</b>\n\n"
        f"👤 Игрок: <b>{name}</b>\n"
        f"🔗 Юзер: <b>{html.escape(username)}</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📝 Проблема:\n{html.escape(text)}\n\n"
        f"Ответить один раз: <code>/reply_report {rid} текст ответа</code>"
    )
    try:
        await context.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text("❌ Не удалось отправить репорт админу. Попробуйте позже.")
        logger.error(f"report send error: {e}")
        return
    await update.message.reply_text(f"✅ Репорт #{rid} отправлен администратору. Ответ придёт в личные сообщения, если админ ответит.")

async def reply_report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Только главный администратор может отвечать на репорты.")
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("ℹ️ Использование: /reply_report <ID репорта> <текст ответа>")
        return
    try:
        rid = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ ID репорта должен быть числом.")
        return
    answer = " ".join(context.args[1:]).strip()
    report, reports = _find_open_report(rid)
    if not report:
        await update.message.reply_text("❌ Репорт не найден или на него уже ответили. Игрок может написать новый /report.")
        return
    uid = int(report.get('user_id'))
    try:
        await context.bot.send_message(
            uid,
            f"📩 <b>Ответ администратора на репорт #{rid}</b>\n\n{html.escape(answer)}\n\nЕсли проблема осталась — отправьте новый /report.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось отправить ответ игроку: {e}")
        return
    for r in reports:
        if int(r.get('id', -1)) == rid:
            r['status'] = 'answered'
            r['answered_at'] = time.time()
            r['answer'] = answer
            break
    save_data(REPORTS_FILE, reports[-1000:])
    await update.message.reply_text(f"✅ Ответ по репорту #{rid} отправлен. Репорт закрыт.")

# ============================ FINAL ANTI-FARM LOCKS ============================
# Эти обёртки объявлены перед финальным запуском main(), чтобы обработчики получили уже защищённые версии.
_original_casino_final = casino
async def casino(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_casino_final(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Казино уже обрабатывает вашу ставку. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "casino", lambda: _original_casino_final(update, context), "", on_busy=_busy)

_original_coin_flip_final = coin_flip
async def coin_flip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_coin_flip_final(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Монетка уже обрабатывает вашу ставку. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "coin_flip", lambda: _original_coin_flip_final(update, context), "", on_busy=_busy)

_original_slots_final = slots
async def slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_slots_final(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Слоты уже крутятся. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "slots", lambda: _original_slots_final(update, context), "", on_busy=_busy)

_original_redeem_promo_final = redeem_promo
async def redeem_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return await _original_redeem_promo_final(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Промокод уже активируется. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "redeem_promo", lambda: _original_redeem_promo_final(update, context), "", on_busy=_busy)

_original_claim_quests_cmd_final = claim_quests_cmd
async def claim_quests_cmd(update, context):
    user = update.effective_user
    if not user:
        return await _original_claim_quests_cmd_final(update, context)
    async def _busy():
        if update.message:
            await update.message.reply_text("⌛ Награды заданий уже проверяются. Подождите пару секунд.")
    await _run_locked_action(context, user.id, "claim_quests", lambda: _original_claim_quests_cmd_final(update, context), "", on_busy=_busy)

_original_duel_callback_final = duel_callback
async def duel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user if query else None
    if not user:
        return await _original_duel_callback_final(update, context)
    duel_id = str(query.data or "")
    async def _busy():
        try:
            await query.answer("Дуэль уже обрабатывается", show_alert=True)
        except Exception:
            pass
    await _run_locked_action(context, user.id, f"duel_callback:{duel_id}", lambda: _original_duel_callback_final(update, context), "", on_busy=_busy)

if __name__ == "__main__":
    _run_bot_main()

