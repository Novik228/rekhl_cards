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

# Pillow нужен для картинки рейтингового состава (/rating).
# Если не установлен (pip install Pillow) — бот работает, состав показывается текстом.
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
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
REFERRALS_FILE = "referrals.json"
MARKET_MAX_PRICE = 100_000
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
    "Блещет умом": (55, 85),
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
    rarity = card.get("rarity")
    if rarity in RARITY_POWER:
        return RARITY_POWER[rarity]
    # Кастомные редкости: сила вычисляется по шансу выпадения: чем реже - тем сильнее.
    try:
        chance = get_rarity_drop_chance(rarity)
    except Exception:
        chance = 0.0
    if chance <= 0:
        return 105  # невыпадающие (эксклюзивного уровня)
    if chance <= 0.02:
        return 105
    if chance <= 0.05:
        return 100
    if chance <= 0.08:
        return 95   # Мифическая (6%)
    if chance <= 0.12:
        return 85
    if chance <= 0.20:
        return 70
    if chance <= 0.30:
        return 55   # Сверхредкая (25%)
    if chance <= 0.40:
        return 45
    return 35

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
# Категории REKHL: Prospect → Average → Elite → Franchise.
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
    "🎴 Карточки:\n"
    "/get_card - получить карточку\n"
    "/my_cards - моя коллекция\n"
    "/card_info <card_id> - информация о карточке\n"
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
    "/redeem <код> - активировать промокод\n"
    "/ref - реферальная ссылка (приглашай друзей — получай монеты)\n\n"
    "🏪 Маркет и обмен:\n"
    "/market - маркет карточек\n"
    "/sell <card_id> <цена> - выставить карточку на продажу\n"
    "/my_listings - мои объявления на маркете\n"
    "/trade <user_id> <card_id> - предложить обмен карточкой\n\n"
    "🎲 Игры и ставки:\n"
    "/casino <сумма> - сыграть в казино\n"
    "/coin <орел|решка> <сумма> - подбросить монетку (макс. 300, рискованно!)\n"
    "/slots <сумма> - игровые автоматы \U0001F3B0\n"
    "/duel <ставка> - дуэль карточек 1 на 1 на монеты\n"
    "/bet - сделать ставку на матч (инлайн-меню)\n"
    "/my_bets - мои ставки\n\n"
    "⚔️ Рейтинговый режим:\n"
    "/rating_team - собрать состав для рейтингового режима\n"
    "/find_match - найти соперника (рейтинговый режим)\n"
    "/rating - мой рейтинг и текущий состав\n\n"
    "👤 Профиль и прочее:\n"
    "/profile - ваш профиль\n"
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
            "✨ 🎇 ЛЕГЕНДА! Открываем!",
        ],
        "Блещет умом": [
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
    frames = RARITY_ANIMATIONS.get(card["rarity"])
    if frames is None:
        # Кастомная редкость без своей анимации:
        # собираем её автоматически по шансу выпадения и её смайлику.
        emoji = get_rarity_emoji(card["rarity"])
        chance = get_rarity_drop_chance(card["rarity"])
        if 0 < chance <= 0.08:
            frames = [
                "🃏 Тянем карточку из колоды...",
                f"{emoji} ✨ Карта светится...",
                f"{emoji} 💫 Она ОЧЕНЬ редкая...",
                f"{emoji} 🎆 Невероятно! Открываем!",
            ]
        elif 0 < chance <= 0.2:
            frames = [
                "🃏 Тянем карточку из колоды...",
                f"{emoji} ✨ Отличный улов! Открываем!",
            ]
        else:
            frames = RARITY_ANIMATIONS["Обычная"]
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
    # Сила с учётом прокачки (/upgrade_card)
    card_map = {c["id"]: c for c in cards}
    lvl = int(user_data.get("card_upgrades", {}).get(str(card_id), 0))
    caption += f"💪 <b>Сила</b>: {get_player_card_power(user.id, card_id, card_map)}"
    if lvl > 0:
        caption += f" (⭐ прокачана до ур. {lvl}, потолок {RARITY_RATING_CAPS.get(card.get('rarity'), '?')})"
    caption += "\n"
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
        "🏪 <b>МАГАЗИН REKHL CARDS</b>\n"
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
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на канал: {CHANNEL_LINK}")
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
    await post_to_channel(context, f"🛒 <b>Новинка в магазине!</b>\n\n<b>{html.escape(new_item['name'])}</b>\n💰 Цена: {_fmt_coins(new_item['price'])} монет\n📦 Тип: {'Сброс таймера' if new_item['type'] == 'reset' else 'Набор карточек'}\n\nОткрыть магазин: /shop")
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
    if len(selected_cards) != len(set(card_ids)):
        await update.message.reply_text("❌ Одна или несколько карточек больше не существуют в базе. Карты не были списаны.")
        return CRAFT_SELECT_CARDS
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
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
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
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на канал: {CHANNEL_LINK}")
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
        await query.edit_message_text(f"❌ Для покупки необходимо подписаться на канал: {CHANNEL_LINK}")
        return
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
        return WORK_REWARDS["Блещет умом"]
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
    now_ts = time.time()
    for uid, udata in list(users.items()):
        # Оптимизация против лагов: не вызываем тяжёлую функцию для тех,
        # у кого нет завершившейся работы (меньше лишних чтений файлов).
        work = (udata or {}).get("working_card")
        if not work or now_ts < work.get("finish_at", 0):
            continue
        try:
            await _complete_work_if_ready(int(uid), context)
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
    season["active"] = False
    season["ended_at"] = time.time()
    save_data(SEASON_FILE, season)
    await post_to_channel(context, "\n".join(result_lines))
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
        cond_text = f"⏰ Итоги — {time.strftime('%d.%m.%Y %H:%M', time.localtime(end_at))}."
    announce = (
        "🎉 <b>РОЗЫГРЫШ ОТ REKHL CARDS!</b>\n\n"
        "🏆 <b>Призы:</b>\n" + "\n".join(prize_lines) + "\n\n"
        f"{cond_text}\n\n"
        "Нажмите кнопку ниже, чтобы участвовать!"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 Участвовать (0)", callback_data=f"gw_join_{gid}")]])
    try:
        msg = await context.bot.send_message(CHANNEL_ID, announce, parse_mode="HTML", reply_markup=keyboard)
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
            await post_to_channel(context, f"🎭 Розыгрыш #{gw['id']} завершён: участников не было, призы не разыграны.")
        except Exception:
            pass
        try:
            await context.bot.send_message(ADMIN_ID, f"🎁 Розыгрыш #{gw['id']} завершён без участников.")
        except Exception:
            pass
        return
    count = min(gw.get("winners_count", 1), len(participants))
    winners = random.sample(participants, count)
    result_lines = [f"🎉 <b>ИТОГИ РОЗЫГРЫША #{gw['id']} • REKHL CARDS</b>\n"]
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
        await post_to_channel(context, "\n".join(result_lines))
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
    active = [g for g in load_data(GIVEAWAYS_FILE, []) if g.get("status") == "active"]
    if not active:
        await update.message.reply_text("📭 Активных розыгрышей нет. Создать: /giveaway")
        return
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    lines = []
    for g in active:
        if g.get("end_type") == "participants":
            cond = f"итоги при {g.get('end_value')} участниках"
        else:
            cond = f"итоги {time.strftime('%d.%m %H:%M', time.localtime(g.get('end_at') or 0))}"
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
        await post_to_channel(context, "🔄 ОБНОВЛЕНИЕ REKHL CARDS!\nБот перезапускается с новой версией и вернётся через минуту. Спасибо за ожидание! 🏒")
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
    # тем же интерпретатором (виртуальная среда сохраняется) из папки бота.
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
    await post_to_channel(context, f"🏒 <b>Новый матч для ставок!</b>\n\n<b>{html.escape(team1)} — {html.escape(team2)}</b>\n⏳ Приём ставок до: <b>{deadline.strftime('%d.%m.%Y %H:%M')}</b> ({hours:g} ч.)\n🎯 Сделать ставку: /bet")
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
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для ставки необходимо подписаться на канал: {CHANNEL_LINK}")
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

    context.user_data["rating_field"] = field_ids
    await update.message.reply_text(
        "🧠 Теперь введите ID карточки-ТРЕНЕРА (любая ваша карта, не из состава).\n"
        "Чем РЕЖЕ выпадает карта тренера, тем сильнее бафф его тактики!\n\n"
        "Или напишите «пропустить», чтобы играть без тренера и тактики."
    )
    return RATING_TEAM_COACH

async def rating_team_coach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    raw_text = update.message.text.strip()
    if raw_text.lower() in ("пропустить", "скип", "skip", "нет"):
        context.user_data["rating_coach"] = None
        context.user_data["rating_tactic"] = "balanced"
        await update.message.reply_text(
            "🧠 Играем без тренера — тактика будет недоступна.\n\n"
            "🏒 Придумайте НАЗВАНИЕ вашей команды (от 2 до 20 символов):"
        )
        return RATING_TEAM_NAME
    try:
        coach_id = int(raw_text)
    except ValueError:
        await update.message.reply_text("❌ Введите числовой ID карточки-тренера или «пропустить».")
        return RATING_TEAM_COACH
    available = get_available_card_ids(user.id)
    if coach_id not in available:
        await update.message.reply_text("❌ У вас нет такой карточки или она недоступна. Проверьте ID и попробуйте снова.")
        return RATING_TEAM_COACH
    used = [context.user_data.get("rating_gk")] + list(context.user_data.get("rating_field", []))
    if coach_id in used:
        await update.message.reply_text("❌ Тренер не может совпадать с игроками состава. Выберите другую карту.")
        return RATING_TEAM_COACH
    context.user_data["rating_coach"] = coach_id
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    card = card_map.get(coach_id, {})
    bonus = round(get_coach_bonus(card.get("rarity", "")) * 100)
    await update.message.reply_text(
        f"🧠 Тренер: {card.get('name', coach_id)} ({card.get('rarity', '—')})\n"
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
    if len(team_name) < 2 or len(team_name) > 20:
        await update.message.reply_text("❌ Название должно быть от 2 до 20 символов. Попробуйте снова.")
        return RATING_TEAM_NAME
    gk_id = context.user_data.get("rating_gk")
    field_ids = context.user_data.get("rating_field", [])
    coach_id = context.user_data.get("rating_coach")
    tactic = context.user_data.get("rating_tactic", "balanced")
    set_rating_team(user.id, gk_id, field_ids, coach_id, tactic, team_name)
    card_map = {c["id"]: c for c in load_data(CARDS_FILE, [])}
    gk_card = card_map.get(gk_id)
    lines = [f"🥅 Вратарь: {gk_card['name'] if gk_card else gk_id}"]
    for fid in field_ids:
        fc = card_map.get(fid)
        lines.append(f"⚔️ Полевой: {fc['name'] if fc else fid}")
    if coach_id:
        ccard = card_map.get(coach_id)
        bonus = round(get_coach_bonus(ccard.get("rarity", "")) * 100) if ccard else 3
        lines.append(f"🧠 Тренер: {ccard['name'] if ccard else coach_id} — {TACTIC_LABELS.get(tactic)} (бафф {bonus}%)")
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

def _draw_vertical_gradient(img, top_color, bottom_color):
    """Вертикальный градиент фона (1px колонка, растянутая на всю ширину)."""
    w, h = img.size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top_color, bottom_color)))
    img.paste(col.resize((w, h)))

def build_rating_team_image(user_id: int):
    """Красивая картинка рейтингового состава: градиентный фон,
    рамки в цвет редкости карт, бейджи ролей, центрированные подписи.

    Возвращает BytesIO или None (нет Pillow / нет состава) — тогда показываем текст."""
    if not PIL_AVAILABLE:
        return None
    team = get_rating_team(user_id)
    if not team:
        return None
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    members = [("ВРАТАРЬ", team["gk"], card_map.get(team["gk"]))]
    for fid in team["field"]:
        members.append(("ПОЛЕВОЙ", fid, card_map.get(fid)))
    coach_id = team.get("coach")
    if coach_id:
        members.append(("ТРЕНЕР", coach_id, card_map.get(coach_id)))
    upgrades = load_data(USERS_FILE, {}).get(str(user_id), {}).get("card_upgrades", {})

    CARD_W, CARD_H, GAP, PAD, TOP = 240, 336, 30, 48, 172
    width = PAD * 2 + len(members) * CARD_W + (len(members) - 1) * GAP
    height = TOP + CARD_H + 150
    img = Image.new("RGB", (width, height))
    _draw_vertical_gradient(img, (26, 36, 66), (7, 9, 18))
    draw = ImageDraw.Draw(img)
    font_title = _load_team_font(52)
    font_sub = _load_team_font(26)
    font_role = _load_team_font(20)
    font_name = _load_team_font(26)
    font_small = _load_team_font(22)

    gold = (255, 212, 84)
    # Мини-шапка бренда + название команды по центру + декоративные линии по бокам
    font_mini = _load_team_font(20)
    mini = "REKHL CARDS  •  РЕЙТИНГОВЫЙ СОСТАВ"
    try:
        mw = draw.textlength(mini, font=font_mini)
    except Exception:
        mw = 0
    draw.text((max(PAD, (width - mw) / 2), 6), mini, font=font_mini, fill=(140, 165, 210))
    title = (team.get("name") or "МОЯ КОМАНДА").upper()[:24]
    try:
        tw = draw.textlength(title, font=font_title)
    except Exception:
        tw = 0
    tx = max(PAD, (width - tw) / 2)
    draw.text((tx, 32), title, font=font_title, fill=gold)
    for x1, x2 in ((PAD, tx - 28), (tx + tw + 28, width - PAD)):
        if x2 > x1:
            draw.line([x1, 60, x2, 60], fill=(150, 125, 55), width=3)
            draw.line([x1, 67, x2, 67], fill=(80, 68, 38), width=1)
    elo = get_rating_elo(user_id)
    strength = int(_team_strength(team, card_map, user_id))  # с учётом прокачки карт
    sub = f"Рейтинг: {elo}      Сила состава: {strength}"
    if coach_id:
        coach_card = card_map.get(coach_id)
        coach_bonus = round(get_coach_bonus(coach_card.get("rarity", "")) * 100) if coach_card else 3
        sub += f"      Тактика: {TACTIC_PLAIN.get(team.get('tactic', 'balanced'), 'Баланс')} (+{coach_bonus}%)"
    try:
        sw = draw.textlength(sub, font=font_sub)
    except Exception:
        sw = 0
    draw.text((max(PAD, (width - sw) / 2), 96), sub, font=font_sub, fill=(165, 205, 255))

    for i, (role, member_id, card) in enumerate(members):
        x = PAD + i * (CARD_W + GAP)
        rarity = card.get("rarity", "") if card else ""
        if rarity:
            main, light = _rarity_frame_colors(rarity)
        else:
            main, light = (110, 125, 150), (170, 185, 210)
        role_color = (255, 200, 60) if role == "ВРАТАРЬ" else ((205, 130, 255) if role == "ТРЕНЕР" else (110, 165, 255))
        # Свечение для топ-редкостей
        if rarity and _is_premium_rarity(rarity):
            for g, col in enumerate((tuple(c // 3 for c in main), tuple(c // 2 for c in main))):
                off = 13 - g * 4
                draw.rectangle([x - off, TOP - off, x + CARD_W + off, TOP + CARD_H + off], outline=col, width=4)
        # Рамка в цвет редкости карты + светлая линия
        draw.rectangle([x - 5, TOP - 5, x + CARD_W + 5, TOP + CARD_H + 5], outline=main, width=5)
        draw.rectangle([x - 1, TOP - 1, x + CARD_W + 1, TOP + CARD_H + 1], outline=light, width=1)
        card_img = None
        if card:
            path = os.path.join(CARDS_IMAGE_DIR, card.get("image", ""))
            if os.path.exists(path):
                try:
                    # Центр-кроп без искажения пропорций (раньше картинки плющило)
                    card_img = ImageOps.fit(Image.open(path).convert("RGB"), (CARD_W, CARD_H))
                except Exception:
                    card_img = None
        if card_img:
            img.paste(card_img, (x, TOP))
        else:
            draw.rectangle([x, TOP, x + CARD_W, TOP + CARD_H], fill=(30, 45, 70))
            nf = "НЕТ ФОТО"
            try:
                nfw = draw.textlength(nf, font=font_role)
            except Exception:
                nfw = 0
            draw.text((x + max(0, (CARD_W - nfw) / 2), TOP + CARD_H // 2 - 12), nf, font=font_role, fill=(120, 140, 170))
        # Бейдж роли над карточкой
        try:
            rw = draw.textlength(role, font=font_role)
        except Exception:
            rw = 60
        bw = rw + 30
        bx = x + (CARD_W - bw) / 2
        by = TOP - 36
        try:
            draw.rounded_rectangle([bx, by, bx + bw, by + 27], radius=13, fill=(5, 8, 16), outline=role_color, width=2)
        except Exception:
            draw.rectangle([bx, by, bx + bw, by + 27], fill=(5, 8, 16), outline=role_color)
        draw.text((bx + 15, by + 4), role, font=font_role, fill=role_color)
        # Имя, сила и редкость — по центру под карточкой
        name = card.get("name", "?") if card else "?"
        if len(name) > 16:
            name = name[:15] + "..."
        try:
            nw = draw.textlength(name, font=font_name)
        except Exception:
            nw = 0
        draw.text((x + max(0, (CARD_W - nw) / 2), TOP + CARD_H + 16), name, font=font_name, fill=(238, 242, 250))
        lvl = int(upgrades.get(str(member_id), 0))
        if role == "ТРЕНЕР":
            power_text = f"Бафф тактики: +{round(get_coach_bonus(card.get('rarity', '')) * 100) if card else 3}%"
        else:
            power_text = f"Сила: {get_player_card_power(user_id, member_id, card_map)}"
            if lvl > 0:
                power_text += f" (ур. {lvl})"
        try:
            pw = draw.textlength(power_text, font=font_small)
        except Exception:
            pw = 0
        draw.text((x + max(0, (CARD_W - pw) / 2), TOP + CARD_H + 52), power_text, font=font_small, fill=main)
        if rarity:
            rtext = str(rarity).upper()
            try:
                rtw = draw.textlength(rtext, font=font_role)
            except Exception:
                rtw = 0
            draw.text((x + max(0, (CARD_W - rtw) / 2), TOP + CARD_H + 86), rtext, font=font_role, fill=(145, 155, 175))

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
            f"⭐ Ваш рейтинг: {elo}\n{get_rating_rank(elo)[1]} Ранг: {get_rating_rank(elo)[2]}\n\n❌ У вас ещё нет состава. Используйте /rating_team, чтобы его создать."
        )
        return
    all_cards = load_data(CARDS_FILE, [])
    card_map = {c["id"]: c for c in all_cards}
    upgrades = load_data(USERS_FILE, {}).get(str(user.id), {}).get("card_upgrades", {})
    def _member_line(icon, role, cid):
        card = card_map.get(cid)
        name = card["name"] if card else cid
        lvl = int(upgrades.get(str(cid), 0))
        lvl_text = f" ⭐ур.{lvl}" if lvl > 0 else ""
        return f"{icon} {role}: {name} — сила {get_player_card_power(user.id, cid, card_map)}{lvl_text}"
    lines = [_member_line("🥅", "Вратарь", team["gk"])]
    for fid in team["field"]:
        lines.append(_member_line("⚔️", "Полевой", fid))
    coach_id = team.get("coach")
    if coach_id:
        ccard = card_map.get(coach_id)
        cname = ccard["name"] if ccard else coach_id
        cbonus = round(get_coach_bonus(ccard.get("rarity", "")) * 100) if ccard else 3
        ctactic = TACTIC_LABELS.get(team.get("tactic", "balanced"), "⚖️ Сбалансировано")
        lines.append(f"🧠 Тренер: {cname} — {ctactic} (бафф {cbonus}%)")
    strength = int(_team_strength(team, card_map, user.id))
    team_name = team.get("name")
    header = f"🏒 Команда: «{team_name}»\n" if team_name else ""
    rank_num, rank_emoji, rank_name = get_rating_rank(elo)
    caption = header + f"⭐ Ваш рейтинг: {elo}\n{rank_emoji} Ранг: {rank_name}\n💪 Сила состава: {strength}\n\n" + "\n".join(lines)
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

def _team_strength(team: dict, card_map: dict, owner_id=None) -> float:
    """Сила состава. Если передан owner_id — учитывается прокачка карт (/upgrade_card)."""
    def _power(cid):
        if owner_id is not None:
            return get_player_card_power(owner_id, cid, card_map)
        return get_card_power(card_map.get(cid, {}))
    return _power(team["gk"]) * 1.5 + sum(_power(fid) for fid in team["field"])

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
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not get_rating_team(user.id):
        await update.message.reply_text("❌ У вас нет состава. Сначала используйте /rating_team.")
        return

    queue = context.bot_data.setdefault("rating_queue", [])

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
        asyncio.create_task(_simulate_match(context, user.id, opponent_entry["user_id"]))
    else:
        queue.append({"user_id": user.id, "joined": now, "rank": my_rank})
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
    """Сила игрока в дуэли: суммарная сила его топ-3 карточек.
    Возвращает (power, [подписи карточек])."""
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
    labels = [f"{html.escape(c['name'])} - сила {_p(c)}" for c in top]
    return power, labels

async def duel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Использование: /duel <ставка>\n"
            "⚔️ Дуэль: оба игрока ставят монеты, победитель выбирается честным рандомом 50/50.\n"
            f"💰 Ставка: от {DUEL_MIN_BET} до {DUEL_MAX_BET} монет. Комиссия с банка: {int(DUEL_COMMISSION * 100)}%."
        )
        return
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
        "created": time.time(),
    }
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Принять дуэль", callback_data=f"duel_accept_{duel_id}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"duel_cancel_{duel_id}")],
    ])
    await update.message.reply_text(
        f"⚔️ <b>{html.escape(user.first_name or 'Игрок')} бросает вызов на дуэль карточек!</b>\n\n"
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
            f"⚔️ <b>{name_a} 🆚 {name_b}</b>\n\n🃏 Карточки сходятся в бою...",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await asyncio.sleep(2)

    # Дуэль намеренно не зависит от карточек: строго 50/50.
    challenger_wins = random.random() < 0.5
    winner_id = challenger_id if challenger_wins else acceptor.id
    winner_name = name_a if challenger_wins else name_b

    pot = bet * 2
    commission = int(pot * DUEL_COMMISSION)
    win_amount = pot - commission
    update_coins(winner_id, win_amount)

    cards_a_text = "\n".join(f"  • {c}" for c in cards_a)
    cards_b_text = "\n".join(f"  • {c}" for c in cards_b)
    result_text = (
        f"⚔️ <b>Дуэль: {name_a} 🆚 {name_b}</b>\n\n"
        f"🃏 <b>{name_a}</b> (сила {power_a}):\n{cards_a_text}\n\n"
        f"🃏 <b>{name_b}</b> (сила {power_b}):\n{cards_b_text}\n\n"
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
            {"id": 1, "name": "Тумба", "rarity": "Легендарная", "image": "tumba.png", "description": "x2 Чемпион РЕКХЛ"},
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
    application.add_handler(CommandHandler("view_matches", view_matches))
    application.add_handler(CommandHandler("ref", referral_info))
    application.add_handler(CommandHandler("upgrade_card", upgrade_card))
    application.add_handler(CommandHandler("find_match", find_match))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("duel", duel_start))
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
    application.add_handler(MessageHandler(filters.Text(ALL_KEYBOARD_BUTTONS), keyboard_button_handler))

    # MessageHandler для текстового ввода (ставки, обмен, события)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    # Проверка подписки (обрабатывает оставшиеся сообщения)
    application.add_handler(MessageHandler(filters.ALL, check_subscription))

    # Явно запрашиваем все типы апдейтов, чтобы гарантированно получать Poll-апдейты.
    application.run_polling(allowed_updates=Update.ALL_TYPES)


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
        await update.message.reply_text(f"❌ Подпишитесь на канал: {CHANNEL_LINK}, затем повторите /start."); return
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
            "🛠 Полный список админских команд: /admin\n\n"
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
            "🎮 Добро пожаловать в REKHL CARDS!\n\n" + USER_COMMANDS_TEXT,
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
        f"🤝 <b>Реферальная программа</b>\n\nВаша ссылка:\n<code>{html.escape(link)}</code>\n\n"
        f"👥 Приглашено: {len(mine)}\n✅ Подтверждено: {rewarded}\n⏳ На проверке: {pending}\n💰 Получено: {rewarded * REFERRAL_REWARD} монет\n\n"
        "Бонус 50 монет начисляется только один раз после: новый ID отсутствовал во всех игровых JSON, приглашение не от себя, аккаунт не бот, есть профиль, игрок подписан на канал и получил первую карту. Повторные выплаты блокируются журналом рефералов.", parse_mode='HTML')

async def view_matches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text('❌ Только для администратора и модераторов.'); return
    events=load_data(EVENTS_FILE,[]); now=time.time()
    if not events: await update.message.reply_text('📭 Матчей для ставок нет.'); return
    lines=['🏒 <b>Матчи для ставок</b>\n']
    for e in sorted(events,key=lambda x:x.get('id',0),reverse=True)[:30]:
        state='🟢 открыт' if e.get('status')=='active' and e.get('deadline',0)>now else ('⌛ приём закрыт' if e.get('status')=='active' else '🏁 завершён')
        deadline=datetime.fromtimestamp(e.get('deadline',0)).strftime('%d.%m %H:%M')
        lines.append(f"#{e['id']} {html.escape(e['team1'])} — {html.escape(e['team2'])}: {state}; до {deadline}; счёт: {e.get('score') or '—'}")
    await update.message.reply_text('\n'.join(lines),parse_mode='HTML')

RARITY_RATING_CAPS={"Обычная":39,"Редкая":59,"Эпическая":79,"Блещет умом":94,"Легендарная":104,"Эксклюзивная":110}
def get_player_card_power(user_id:int, card_id:int, card_map:dict)->int:
    card=card_map.get(card_id,{})
    base=get_card_power(card); cap=RARITY_RATING_CAPS.get(card.get('rarity'), base)
    level=load_data(USERS_FILE,{}).get(str(user_id),{}).get('card_upgrades',{}).get(str(card_id),0)
    return min(cap, base+max(0,int(level))*2)

async def upgrade_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user=update.effective_user
    if is_banned(user.id):
        await update.message.reply_text('❌ Вы заблокированы в этом боте.'); return
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f'❌ Для использования бота необходимо подписаться на канал: {CHANNEL_LINK}'); return
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
    level=int(data.get('card_upgrades',{}).get(str(cid),0)); base=get_card_power(card); cap=RARITY_RATING_CAPS.get(card.get('rarity'),base)
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

def build_match_result_image(name_a, name_b, goals_a, goals_b, periods, scorers=None, coaches=None, stats=None):
    """Финальная картинка матча: брендинг REKHL CARDS, крупный счёт, тренеры с тактиками,
    счёт по периодам, авторы голов с минутами и статистика как в реальном хоккее."""
    if not PIL_AVAILABLE:
        return None
    scorers = scorers or []
    stats = stats or []
    w = 1100
    h = 700 + (58 + 36 * len(scorers) if scorers else 0) + (78 + 34 * len(stats) if stats else 0)
    img = Image.new('RGB', (w, h), (8, 14, 30))
    _draw_vertical_gradient(img, (18, 46, 92), (5, 9, 20))
    d = ImageDraw.Draw(img)
    brand = _load_team_font(66)
    title = _load_team_font(30)
    big = _load_team_font(150)
    teamfont = _load_team_font(32)
    small = _load_team_font(25)
    tiny = _load_team_font(23)
    gold = (255, 208, 64)
    def center(text, x, y, font, fill):
        d.text((x - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill)
    # Шапка с названием бота
    d.rectangle([0, 0, w, 122], fill=(9, 20, 44))
    center('REKHL CARDS', w / 2, 26, brand, gold)
    d.line((60, 122, w - 60, 122), fill=gold, width=3)
    d.line((60, 128, w - 60, 128), fill=(120, 100, 45), width=1)
    center('РЕЙТИНГОВЫЙ МАТЧ • ФИНАЛЬНЫЙ СЧЁТ', w / 2, 146, title, (150, 190, 235))
    # Команды и крупный счёт
    center(name_a[:24], 265, 218, teamfont, (238, 245, 255))
    center(name_b[:24], 835, 218, teamfont, (238, 245, 255))
    center(str(goals_a), 265, 270, big, (94, 180, 255))
    center(':', 550, 287, big, gold)
    center(str(goals_b), 835, 270, big, (94, 180, 255))
    center('МАТЧ ОКОНЧЕН', 550, 455, title, (255, 215, 100))
    center('Периоды: ' + '  •  '.join(periods), 550, 500, small, (180, 205, 230))
    y = 540
    # Тренеры и тактики
    if coaches:
        center(f'Тренеры:  {str(coaches[0])[:36]}  —  {str(coaches[1])[:36]}', 550, y, tiny, (170, 195, 225))
        y += 34
    # Авторы голов с минутами
    if scorers:
        d.line((220, y, w - 220, y), fill=(70, 110, 160), width=2)
        center('АВТОРЫ ГОЛОВ', 550, y + 14, small, gold)
        y += 58
        for minute, scorer, team_name, score_text in scorers:
            center(f"{minute:02d}'  {scorer[:20]} ({team_name[:18]})  —  {score_text}", 550, y, tiny, (215, 230, 245))
            y += 36
    # Статистика матча (как в реальном хоккее)
    if stats:
        y += 6
        d.line((220, y, w - 220, y), fill=(70, 110, 160), width=2)
        center('СТАТИСТИКА МАТЧА', 550, y + 14, small, gold)
        y += 58
        for label, va, vb in stats:
            d.text((300, y), label, font=tiny, fill=(170, 195, 225))
            center(str(va), 690, y, tiny, (235, 242, 252))
            center('—', 760, y, tiny, (120, 145, 175))
            center(str(vb), 830, y, tiny, (235, 242, 252))
            y += 34
    out = io.BytesIO()
    img.save(out, 'PNG')
    out.seek(0)
    return out

async def _simulate_match(context: ContextTypes.DEFAULT_TYPE, user_a: int, user_b):
    """Симуляция рейтингового матча. Вместо «глухой заглушки» со счётом периода
    игрокам отправляются важные события периода (голы с минутами, сэйвы, удаления).
    Прокачка карт (/upgrade_card) учитывается в силе составов."""
    team_a = get_rating_team(user_a)
    team_b = get_rating_team(user_b) if user_b else _generate_bot_team()
    card_map = {c['id']: c for c in load_data(CARDS_FILE, [])}
    sa = _team_strength(team_a, card_map, user_a)
    sb = _team_strength(team_b, card_map, user_b)
    # РЕБАЛАНС: разница сил влияет мягче (слабый состав реально может
    # победить: минимум 40% шанса), а случайная «форма дня» делает каждый
    # матч уникальным — одна и та же пара команд играет по-разному.
    form = random.uniform(-0.07, 0.07)
    p_a = max(.40, min(.60, .50 + (sa - sb) / 1400 + form))
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

    def raw_name(cid):
        card = card_map.get(cid)
        return card['name'] if card else f'Игрок {cid}'

    def _coach_info(team, plain=False):
        """Строка «Тренер — тактика (бафф N%)». plain=True — без эмодзи (для картинки)."""
        coach_id = (team or {}).get('coach')
        if not coach_id:
            return 'без тренера'
        card = card_map.get(coach_id)
        cname = card['name'] if card else f'Тренер {coach_id}'
        bonus = round(get_coach_bonus(card.get('rarity', '')) * 100) if card else 3
        tactic = (team or {}).get('tactic', 'balanced')
        if plain:
            return f"{cname} ({TACTIC_PLAIN.get(tactic, 'Баланс')}, +{bonus}%)"
        return f"{cname} — {TACTIC_LABELS.get(tactic, '⚖️ Сбалансировано')} (бафф {bonus}%)"

    coach_a_text, coach_b_text = _coach_info(team_a), _coach_info(team_b)
    for uid in recipients:
        await send(
            uid,
            f'🏒 <b>Матч начался:</b> {na} 🆚 {nb}\n💪 Сила составов: {int(sa)} 🆚 {int(sb)}\n\n'
            f'🧠 <b>Тренеры:</b>\n▪️ {na}: {html.escape(coach_a_text)}\n▪️ {nb}: {html.escape(coach_b_text)}'
        )

    ga = gb = 0
    period_scores = []
    scorers = []  # (минута, имя игрока, команда, счёт после гола) — без HTML-экранирования

    def _goal_event(minute, side):
        """Оформляет гол: обновляет счёт, запоминает автора, возвращает строку события."""
        nonlocal ga, gb
        att_team, def_team = (team_a, team_b) if side == 'a' else (team_b, team_a)
        att_name = na if side == 'a' else nb
        pid = _pick_field_player(att_team, card_map)
        if side == 'a':
            ga += 1
        else:
            gb += 1
        scorers.append((minute, raw_name(pid), (name_a_raw if side == 'a' else name_b_raw).lstrip('@'), f'{ga}:{gb}'))
        text = random.choice(GOAL_EVENTS).format(team=att_name, player=_card_name(pid, card_map), gk=_card_name(def_team['gk'], card_map))
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
                text = random.choice(pool).format(
                    team=att_name,
                    player=_card_name(_pick_field_player(att_team, card_map), card_map),
                    gk=_card_name(def_team['gk'], card_map),
                )
                lines.append(f"⏱ {minute:02d}' — {text}")
        period_scores.append(f'{pa}:{pb}')
        for uid in recipients:
            await send(uid, f'🏒 <b>Период {period}</b>\n' + '\n'.join(lines) + f'\n\n📊 Счёт после периода: <b>{ga}:{gb}</b>')
        await asyncio.sleep(1.5)

    if ga == gb:
        # Овертайм — почти монетка: сила даёт лишь минимальный перевес.
        ot_minute = 60 + random.randint(1, 5)
        ot_pa = max(.44, min(.56, p_a))
        line = _goal_event(ot_minute, 'a' if random.random() < ot_pa else 'b')
        period_scores.append('ОТ')
        for uid in recipients:
            await send(uid, f'🚨 <b>ОВЕРТАЙМ!</b>\n{line}')
        await asyncio.sleep(1.0)

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
    if user_b:
        add_rating_result(user_b, 'win' if gb > ga else 'loss')
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
    ot_mark = ' (ОТ)' if len(period_scores) > 3 else ''
    image = None
    try:
        image = build_match_result_image(
            name_a_raw.lstrip('@'), name_b_raw.lstrip('@'), ga, gb, period_scores, scorers,
            coaches=(_coach_info(team_a, plain=True), _coach_info(team_b, plain=True)),
            stats=stats_rows,
        )
    except Exception as e:
        logger.warning(f'Не удалось построить картинку результата матча: {e}')
    for uid, old, new, won in [(user_a, ea, newa, ga > gb)] + ([(user_b, eb, newb, gb > ga)] if user_b else []):
        cap = (
            f"🚨🔔 <b>ФИНАЛЬНАЯ СИРЕНА!</b>\n"
            f"🏟 {na} <b>{ga}:{gb}</b>{ot_mark} {nb}\n"
            f"📊 Периоды: {' | '.join(period_scores)}\n\n"
            f"🧠 <b>Тренеры:</b>\n▪️ {na}: {html.escape(coach_a_text)}\n▪️ {nb}: {html.escape(coach_b_text)}\n\n"
            f"🚨 <b>Голы:</b>\n{goals_text}\n\n"
            f"📈 <b>Статистика матча ({na} — {nb}):</b>\n{stats_text}\n\n"
            f"{'🏆🎉 ПОБЕДА! Красивая игра!' if won else '😤 Поражение... Реванш не за горами!'}\n⭐ Рейтинг: {old} → <b>{new}</b>"
            + (f'\n💰 Рейтинговая награда: +{reward}' if uid == winner and reward else '')
        )
        short_cap = (
            f"🚨🔔 <b>ФИНАЛЬНАЯ СИРЕНА!</b> {na} <b>{ga}:{gb}</b>{ot_mark} {nb}\n"
            f"{'🏆🎉 ПОБЕДА!' if won else '😤 Поражение.'} ⭐ Рейтинг: {old} → <b>{new}</b>"
            + (f' 💰 +{reward}' if uid == winner and reward else '')
        )
        try:
            if image:
                image.seek(0)
                if len(cap) <= 1024:
                    await context.bot.send_photo(uid, photo=image, caption=cap, parse_mode='HTML')
                else:
                    # Подпись к фото ограничена 1024 символами — шлём фото с коротким итогом и детали отдельным сообщением.
                    await context.bot.send_photo(uid, photo=image, caption=short_cap, parse_mode='HTML')
                    await context.bot.send_message(uid, cap, parse_mode='HTML')
            else:
                await context.bot.send_message(uid, cap, parse_mode='HTML')
        except Exception:
            # Запасной вариант: если фото не отправилось (например, длинная подпись) — шлём текст.
            try:
                await context.bot.send_message(uid, cap, parse_mode='HTML')
            except Exception:
                pass


if __name__ == "__main__":
    print(f"🏒 REKHL CARDS: запуск бота из папки {BASE_DIR}")
    try:
        main()
    except Exception:
        import traceback
        _err = traceback.format_exc()
        print(_err)
        try:
            with open(os.path.join(BASE_DIR, "bot_crash.log"), "w", encoding="utf-8") as f:
                f.write(_err)
        except Exception:
            pass
        raise
