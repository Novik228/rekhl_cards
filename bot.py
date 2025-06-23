import json
import os
import random
import time
import html
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

# Конфигурация
TOKEN = input("Введите токен бота: ")
CHANNEL_ID = "-1002899939309"
CHANNEL_LINK = "https://t.me/cabakoff"
ADMIN_ID = 1106828306

# Пути к файлам
CARDS_FILE = "cards.json"
USERS_FILE = "users.json"
TRADES_FILE = "trades.json"
BLACKLIST_FILE = "blacklist.json"
MODERATORS_FILE = "moderators.json"
COINS_FILE = "coins.json"
RARITIES_FILE = "rarities.json"
SHOP_FILE = "shop.json"
CARDS_IMAGE_DIR = "cards_images"

# Состояния для добавления карточек
ADMIN_CARD_NAME, ADMIN_CARD_RARITY, ADMIN_CARD_DESCRIPTION, ADMIN_CARD_IMAGE = range(4)
ADMIN_SHOP_NAME, ADMIN_SHOP_TYPE, ADMIN_SHOP_PRICE, ADMIN_SHOP_CARDS, ADMIN_SHOP_DURATION = range(5)
ADMIN_RARITY_NAME, ADMIN_RARITY_EMOJI, ADMIN_RARITY_DROPPABLE = range(3)

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка данных
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

# Проверка блокировки
def is_banned(user_id: int) -> bool:
    blacklist = load_data(BLACKLIST_FILE, [])
    return user_id in blacklist

# Проверка подписки на канал
async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# Проверка администратора
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# Проверка модератора
def is_moderator(user_id: int) -> bool:
    moderators = load_data(MODERATORS_FILE, [])
    return user_id in moderators

# Проверка доступа (админ или модератор)
def has_admin_access(user_id: int) -> bool:
    return is_admin(user_id) or is_moderator(user_id)

# Получить эмодзи для редкости
def get_rarity_emoji(rarity_name: str) -> str:
    rarities = load_data(RARITIES_FILE, [])
    for rarity in rarities:
        if rarity["name"] == rarity_name:
            return rarity["emoji"]
    
    # Стандартные эмодзи
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
    
    # Считаем количество каждой карточки
    card_counts = {}
    for card_id in user_cards:
        card_counts[card_id] = card_counts.get(card_id, 0) + 1
    
    # Группируем по редкости
    grouped = {}
    for card in all_cards:
        card_id = card["id"]
        if card_id in card_counts:
            if card["rarity"] not in grouped:
                grouped[card["rarity"]] = []
            grouped[card["rarity"]].append((card, card_counts[card_id]))
    
    # Сортируем редкости
    rarity_order = [r["name"] for r in rarities] + ["Легендарная", "Блещет умом", "Эпическая", "Редкая", "Обычная", "Эксклюзивная"]
    unique_rarities = list(set(grouped.keys()))
    sorted_rarities = sorted(unique_rarities, key=lambda r: rarity_order.index(r) if r in rarity_order else len(rarity_order))
    
    # Формируем сообщение
    message = "🃏 <b>Ваша коллекция карточек</b>:\n\n"
    total_count = 0
    
    for rarity in sorted_rarities:
        cards_in_rarity = grouped[rarity]
        count_in_rarity = sum(count for _, count in cards_in_rarity)
        total_count += count_in_rarity
        
        emoji = get_rarity_emoji(rarity)
        message += f"{emoji} <b>{rarity}</b> ({count_in_rarity}):\n"
        
        # Сортируем карточки по ID
        sorted_cards = sorted(cards_in_rarity, key=lambda x: x[0]['id'])
        
        for card, count in sorted_cards:
            count_text = f" (x{count})" if count > 1 else ""
            message += f"   • {html.escape(card['name'])}{count_text} [ID: {card['id']}]\n"
        
        message += "\n"
    
    message += f"📚 <b>Всего карточек: {total_count}</b>"
    return message

# Получить баланс пользователя
def get_coins(user_id: int) -> int:
    coins_data = load_data(COINS_FILE, {})
    return coins_data.get(str(user_id), 0)

# Изменить баланс пользователя
def update_coins(user_id: int, amount: int) -> int:
    coins_data = load_data(COINS_FILE, {})
    current = coins_data.get(str(user_id), 0)
    new_amount = max(0, current + amount)
    coins_data[str(user_id)] = new_amount
    save_data(COINS_FILE, coins_data)
    return new_amount

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Проверка блокировки
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
    if str(user.id) not in users:
        users[str(user.id)] = {
            "cards": [],
            "last_drop": 0,
            "username": user.username
        }
        save_data(USERS_FILE, users)
        
        # Инициализация монет
        coins_data = load_data(COINS_FILE, {})
        if str(user.id) not in coins_data:
            coins_data[str(user.id)] = 0
            save_data(COINS_FILE, coins_data)
        
        if is_admin(user.id):
            await update.message.reply_text(
                "👑 Вы администратор. Доступные команды:\n"
                "/admin_addcard - добавить карточку\n"
                "/admin_listcards - список всех карточек\n"
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
                "/admin_listshop - список товаров\n\n"
                "Обычные команды:\n"
                "/get_card - получить карточку\n"
                "/my_cards - моя коллекция\n"
                "/trade - обмен\n"
                "/shop - магазин\n"
                "/balance - баланс монет\n"
                "/card_info <card_id> - информация о карточке"
            )
        elif is_moderator(user.id):
            await update.message.reply_text(
                "🛡 Вы модератор. Доступные команды:\n"
                "/admin_addcard - добавить карточку\n"
                "/admin_listcards - список всех карточек\n"
                "/admin_addrarity - добавить редкость\n"
                "/admin_listrarities - список редкостей\n"
                "/admin_addshopitem - добавить товар в магазин\n"
                "/admin_listshop - список товаров\n\n"
                "Обычные команды:\n"
                "/get_card - получить карточку\n"
                "/my_cards - моя коллекция\n"
                "/trade - обмен\n"
                "/shop - магазин\n"
                "/balance - баланс монет\n"
                "/card_info <card_id> - информация о карточке"
            )
        else:
            await context.bot.send_message(
                ADMIN_ID,
                f"Новый пользователь: @{user.username} | ID: {user.id}"
            )
            await update.message.reply_text(
                "🎮 Добро пожаловать в REKHL CARDS!\n\n"
                "📋 Основные команды:\n"
                "/get_card - Получить случайную карточку\n"
                "/my_cards - Показать вашу коллекцию\n"
                "/trade - Обмен карточками\n"
                "/shop - Магазин\n"
                "/balance - Баланс монет\n"
                "/card_info <card_id> - Информация о карточке\n\n"
                "⏳ Карточку можно получать каждые 6 часов!"
            )
    else:
        if is_admin(user.id):
            await update.message.reply_text(
                "👑 Вы администратор. Доступные команды:\n"
                "/admin_addcard - добавить карточку\n"
                "/admin_listcards - список всех карточек\n"
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
                "/admin_listshop - список товаров\n\n"
                "Обычные команды:\n"
                "/get_card - получить карточку\n"
                "/my_cards - моя коллекция\n"
                "/trade - обмен\n"
                "/shop - магазин\n"
                "/balance - баланс монет\n"
                "/card_info <card_id> - информация о карточке"
            )
        elif is_moderator(user.id):
            await update.message.reply_text(
                "🛡 Вы модератор. Доступные команды:\n"
                "/admin_addcard - добавить карточку\n"
                "/admin_listcards - список всех карточек\n"
                "/admin_addrarity - добавить редкость\n"
                "/admin_listrarities - список редкостей\n"
                "/admin_addshopitem - добавить товар в магазин\n"
                "/admin_listshop - список товаров\n\n"
                "Обычные команды:\n"
                "/get_card - получить карточку\n"
                "/my_cards - моя коллекция\n"
                "/trade - обмен\n"
                "/shop - магазин\n"
                "/balance - баланс монет\n"
                "/card_info <card_id> - информация о карточке"
            )
        else:
            await update.message.reply_text(
                "🎮 Добро пожаловать в REKHL CARDS!\n\n"
                "📋 Основные команды:\n"
                "/get_card - Получить случайную карточку\n"
                "/my_cards - Показать вашу коллекцию\n"
                "/trade - Обмен карточками\n"
                "/shop - Магазин\n"
                "/balance - Баланс монет\n"
                "/card_info <card_id> - Информация о карточке\n\n"
                "⏳ Карточку можно получать каждые 6 часов!"
            )

# Выдача карточки пользователю
async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Проверка блокировки
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
        
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return

    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    
    # Проверка времени
    current_time = time.time()
    last_drop = user_data.get("last_drop", 0)
    cooldown = 6 * 3600  # 6 часов в секундах
    
    time_left = cooldown - (current_time - last_drop)
    
    if time_left > 0:
        # Рассчитываем оставшееся время
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        
        # Формируем сообщение
        if hours > 0:
            time_text = f"{hours} час(ов) и {minutes} минут(ы)"
        else:
            time_text = f"{minutes} минут(ы)"
            
        await update.message.reply_text(
            f"⏳ Следующую карточку можно получить через: {time_text}"
        )
        return

    # Выбор карточки (только droppable редкости)
    rarities = load_data(RARITIES_FILE, [])
    droppable_rarities = [r["name"] for r in rarities if r.get("droppable", True)]
    cards = [c for c in load_data(CARDS_FILE, []) if c["rarity"] in droppable_rarities]
    
    if not cards:
        await update.message.reply_text("⚠️ Карточки не найдены! Обратитесь к администратору.")
        return

    # Шансы выпадения карточек
    RARITY_CHANCES = {
        "Легендарная": 0.05,
        "Блещет умом": 0.07,
        "Эпическая": 0.15,
        "Редкая": 0.3,
        "Обычная": 0.5
    }
    
    # Выбор редкости
    rarities = list(RARITY_CHANCES.keys())
    weights = [RARITY_CHANCES[r] for r in rarities]
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
    
    # Фильтрация по редкости
    rarity_cards = [c for c in cards if c["rarity"] == chosen_rarity]
    
    # Если для выбранной редкости нет карточек, попробуем другие редкости
    if not rarity_cards:
        logger.warning(f"Для редкости '{chosen_rarity}' нет карточек! Пробуем другие редкости.")
        for rarity in rarities:
            rarity_cards = [c for c in cards if c["rarity"] == rarity]
            if rarity_cards:
                logger.info(f"Нашли карточки для редкости: {rarity}")
                break
    
    # Если всё равно нет карточек, сообщаем об ошибке
    if not rarity_cards:
        logger.error("В базе нет карточек ни для одной редкости!")
        await update.message.reply_text("⚠️ Ошибка в базе карточек! Обратитесь к администратору.")
        return
    
    card = random.choice(rarity_cards)
    
    # Обновление данных пользователя
    if "cards" not in user_data:
        user_data["cards"] = []
    
    # Добавляем карточку
    user_data["cards"].append(card["id"])
    user_data["last_drop"] = current_time
    users[str(user.id)] = user_data
    save_data(USERS_FILE, users)

    # Начисление монет
    coins_earned = random.randint(10, 50)
    new_balance = update_coins(user.id, coins_earned)
    
    # Получаем количество этой карточки у пользователя
    card_count = user_data["cards"].count(card["id"])
    count_text = f" (x{card_count})" if card_count > 1 else ""

    # Отправка карточки с описанием
    caption = (
        f"🎉 Вы получили карточку!\n\n"
        f"🏷 Название: {card['name']}{count_text}\n"
        f"⭐ Редкость: {card['rarity']}\n"
    )
    
    # Добавляем описание
    if "description" in card:
        caption += f"📝 Описание: {card['description']}\n"
    
    caption += (
        f"💰 Получено монет: +{coins_earned}\n"
        f"💰 Ваш баланс: {new_balance}\n\n"
        f"📚 Теперь в вашей коллекции: {len(user_data['cards'])}"
    )
    
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        await update.message.reply_photo(
            photo=open(image_path, "rb"),
            caption=caption
        )
    else:
        logger.warning(f"Изображение карточки не найдено: {image_path}")
        await update.message.reply_text(caption)

# Показ коллекции пользователя
async def show_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Проверка блокировки
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
        
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Для использования бота необходимо подписаться на наш канал: {CHANNEL_LINK}")
        return

    message = await show_collection_with_ids(user.id)
    
    # Разбиваем сообщение если слишком длинное
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

# Просмотр информации о карточке
async def card_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Проверка блокировки
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
    
    # Проверяем, есть ли карточка у пользователя
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    if card_id not in user_data.get("cards", []):
        await update.message.reply_text("❌ У вас нет этой карточки в коллекции!")
        return
    
    # Ищем карточку в базе
    cards = load_data(CARDS_FILE, [])
    card = next((c for c in cards if c["id"] == card_id), None)
    
    if not card:
        await update.message.reply_text("❌ Карточка не найдена в базе данных!")
        return
    
    # Формируем сообщение
    emoji = get_rarity_emoji(card["rarity"])
    caption = (
        f"🃏 <b>Информация о карточке</b>\n\n"
        f"🏷 <b>Название</b>: {card['name']}\n"
        f"{emoji} <b>Редкость</b>: {card['rarity']}\n"
    )
    
    if "description" in card:
        caption += f"📝 <b>Описание</b>: {card['description']}\n"
    
    # Получаем количество этой карточки у пользователя
    card_count = user_data["cards"].count(card_id)
    caption += f"📊 <b>В вашей коллекции</b>: {card_count} шт.\n"
    
    # Отправляем изображение
    image_path = os.path.join(CARDS_IMAGE_DIR, card["image"])
    if os.path.exists(image_path):
        await update.message.reply_photo(
            photo=open(image_path, "rb"),
            caption=caption,
            parse_mode="HTML"
        )
    else:
        logger.warning(f"Изображение карточки не найдено: {image_path}")
        await update.message.reply_text(caption, parse_mode="HTML")

# Показать баланс монет
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    balance = get_coins(user.id)
    await update.message.reply_text(f"💰 Ваш баланс: {balance} монет")

async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    shop_items = load_data(SHOP_FILE, [])
    
    # Удаляем просроченные товары
    current_time = time.time()
    active_items = [
        item for item in shop_items 
        if item.get("expire_time", 0) == 0 or item["expire_time"] > current_time
    ]
    
    # Обновляем файл магазина
    save_data(SHOP_FILE, active_items)
    
    if not active_items:
        await update.message.reply_text("🛒 Магазин пуст! Загляните позже.")
        return
    
    message = "🛒 Товары в магазине\n\n"
    for item in active_items:
        message += f"🆔 ID: {item['id']}\n"
        message += f"🏷 Название: {item['name']}\n"
        message += f"💵 Цена: {item['price']} монет\n"
        
        # Отображаем время до истечения
        if item.get("expire_time", 0) > 0:
            time_left = item["expire_time"] - current_time
            if time_left > 0:
                hours = int(time_left // 3600)
                minutes = int((time_left % 3600) // 60)
                message += f"⏳ Осталось: {hours}ч {minutes}мин\n"
        
        if item["type"] == "reset":
            message += "📝 Тип: Сброс таймера получения карточки\n\n"
        elif item["type"] == "pack":
            # Исправлено: добавлена закрывающая скобка для len()
            message += "📝 Тип: Набор карточек\n"
            message += f"🃏 Карточек в наборе: {len(item['cards'])}\n\n"
    
    message += "ℹ️ Для покупки используйте /buy <ID товара>"
    
    # Разбиваем сообщение если слишком длинное
    if len(message) > 4000:
        parts = []
        while message:
            if len(message) <= 4000:
                parts.append(message)
                break
                
            # Находим последний перенос строки в пределах 4000 символов
            last_newline = message[:4000].rfind('\n')
            
            if last_newline == -1:
                # Если нет переносов, разбиваем по символам
                parts.append(message[:4000])
                message = message[4000:]
            else:
                parts.append(message[:last_newline])
                message = message[last_newline+1:]
        
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(message)

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
    
    # Проверяем срок действия
    current_time = time.time()
    if item.get("expire_time", 0) > 0 and item["expire_time"] < current_time:
        await update.message.reply_text("❌ Срок действия этого товара истек!")
        return
    
    # Проверяем баланс
    balance = get_coins(user.id)
    if balance < item["price"]:
        await update.message.reply_text("❌ Недостаточно монет для покупки!")
        return
    
    # Выполняем покупку
    new_balance = update_coins(user.id, -item["price"])
    
    if item["type"] == "reset":
        # Сбрасываем таймер
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
        # Выдаем ОДНУ случайную карточку из набора
        users = load_data(USERS_FILE, {})
        user_data = users.get(str(user.id), {})
        
        if "cards" not in user_data:
            user_data["cards"] = []
        
        # Выбираем случайную карточку из набора
        card_id = random.choice(item["cards"])
        user_data["cards"].append(card_id)
        
        users[str(user.id)] = user_data
        save_data(USERS_FILE, users)
        
        # Получаем информацию о карточке
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
        
        # Получаем количество этой карточки у пользователя
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

# Система обмена
async def start_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Проверка блокировки
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
        
    if not await is_subscribed(user.id, context):
        return

    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    
    if not user_data.get("cards"):
        await update.message.reply_text("📭 У вас нет карточек для обмена!")
        return

    # Показываем коллекцию с ID карточек
    message = await show_collection_with_ids(user.id)
    message += "\n\n🔄 Введите ID карточки, которую хотите обменять:"
    
    await update.message.reply_text(message, parse_mode="HTML")
    context.user_data["trade_state"] = "select_your_card"

async def handle_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Проверка блокировки
    if is_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы в этом боте.")
        return
        
    text = update.message.text
    state = context.user_data.get("trade_state")
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user.id), {})
    
    if state == "select_your_card":
        try:
            card_id = int(text)
            # Проверяем, есть ли такая карточка
            if card_id not in user_data.get("cards", []):
                await update.message.reply_text("❌ У вас нет такой карточки!")
                return
                
            context.user_data["your_card"] = card_id
            context.user_data["trade_state"] = "select_partner"
            await update.message.reply_text(
                "👤 Введите ID пользователя для обмена:\n"
                "(Пользователь должен отправить /start боту)"
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

    elif state == "select_partner":
        try:
            partner_id = int(text)
            if partner_id == user.id:
                await update.message.reply_text("❌ Нельзя обмениваться с самим собой!")
                return
                
            # Проверка блокировки партнера
            if is_banned(partner_id):
                await update.message.reply_text("❌ Этот пользователь заблокирован!")
                return
                
            partner_data = users.get(str(partner_id))
            if not partner_data:
                await update.message.reply_text("❌ Пользователь не найден!")
                return
                
            if not partner_data.get("cards"):
                await update.message.reply_text("❌ У пользователя нет карточек для обмена!")
                return
                
            context.user_data["partner_id"] = partner_id
            context.user_data["trade_state"] = "select_their_card"
            
            # Показываем коллекцию партнера
            partner_collection = await show_collection_with_ids(partner_id)
            await update.message.reply_text(
                f"🃏 Коллекция пользователя {partner_id}:\n\n{partner_collection}\n\n"
                "Введите ID карточки, которую хотите получить:",
                parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

    elif state == "select_their_card":
        try:
            card_id = int(text)
            partner_id = context.user_data["partner_id"]
            partner_data = users.get(str(partner_id), {})
            
            # Проверяем, есть ли карточка у партнера
            if card_id not in partner_data.get("cards", []):
                await update.message.reply_text("❌ Этой карточки нет у пользователя!")
                return
                
            context.user_data["their_card"] = card_id
            
            # Получение информации о карточках
            all_cards = load_data(CARDS_FILE, [])
            your_card = next((c for c in all_cards if c["id"] == context.user_data["your_card"]), None)
            their_card = next((c for c in all_cards if c["id"] == card_id), None)
            
            if not your_card or not their_card:
                await update.message.reply_text("❌ Ошибка данных карточек!")
                return
            
            # Сохраняем обмен в файл
            trades = load_data(TRADES_FILE, {})
            trade_id = f"{user.id}_{int(time.time())}"
            trades[trade_id] = {
                "from_user": user.id,
                "from_card": your_card["id"],
                "to_user": partner_id,
                "to_card": their_card["id"],
                "status": "pending"
            }
            save_data(TRADES_FILE, trades)
            
            # Клавиатура подтверждения
            keyboard = [
                [InlineKeyboardButton("✅ Подтвердить обмен", callback_data=f"confirm_trade_{trade_id}")],
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_trade")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "🔄 Подтвердите обмен:\n\n"
                f"Вы отдаете: {your_card['name']} (ID: {your_card['id']})\n"
                f"Вы получаете: {their_card['name']} (ID: {their_card['id']})",
                reply_markup=reply_markup
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID!")

# Обработка кнопок обмена
async def trade_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Проверка блокировки
    if is_banned(user_id):
        await query.edit_message_text("❌ Вы заблокированы в этом боте.")
        return
        
    data = query.data
    
    if data == "cancel_trade":
        await query.edit_message_text("❌ Обмен отменен")
        return
    
    if data.startswith("confirm_trade_"):
        trade_id = data[len("confirm_trade_"):]
        trades = load_data(TRADES_FILE, {})
        trade = trades.get(trade_id)
        
        if not trade or trade["status"] != "pending":
            await query.edit_message_text("❌ Предложение об обмене не найдено или устарело!")
            return
            
        # Отправляем запрос на подтверждение ПАРТНЕРУ
        all_cards = load_data(CARDS_FILE, [])
        your_card = next((c for c in all_cards if c["id"] == trade["from_card"]), None)
        their_card = next((c for c in all_cards if c["id"] == trade["to_card"]), None)
        
        if not your_card or not their_card:
            await query.edit_message_text("❌ Ошибка данных карточек!")
            return
        
        keyboard = [
            [InlineKeyboardButton("✅ Принять обмен", callback_data=f"accept_trade_{trade_id}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_trade_{trade_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # Отправляем запрос ПАРТНЕРУ
            await context.bot.send_message(
                chat_id=trade["to_user"],
                text=f"🔄 Пользователь @{query.from_user.username} предлагает обмен:\n\n"
                     f"Вы отдаете: {their_card['name']} (ID: {their_card['id']})\n"
                     f"Вы получаете: {your_card['name']} (ID: {your_card['id']})\n\n"
                     "Подтвердите обмен:",
                reply_markup=reply_markup
            )
            await query.edit_message_text("✅ Запрос на обмен отправлен! Ожидайте подтверждения.")
        except Exception as e:
            logger.error(f"Не удалось отправить запрос на обмен: {e}")
            await query.edit_message_text("❌ Не удалось отправить запрос на обмен второму игроку!")
    
    elif data.startswith("accept_trade_") or data.startswith("reject_trade_"):
        action = "accept" if data.startswith("accept_trade_") else "reject"
        trade_id = data[len("accept_trade_"):] if action == "accept" else data[len("reject_trade_"):]
        trades = load_data(TRADES_FILE, {})
        trade = trades.get(trade_id)
        
        if not trade or trade["status"] != "pending":
            await query.edit_message_text("❌ Предложение об обмене не найдено или устарело!")
            return
            
        if action == "reject":
            trades[trade_id]["status"] = "rejected"
            save_data(TRADES_FILE, trades)
            
            await query.edit_message_text("❌ Вы отклонили предложение об обмене.")
            
            # Уведомляем первого игрока
            try:
                await context.bot.send_message(
                    trade["from_user"],
                    f"❌ Пользователь @{query.from_user.username} отклонил ваш запрос на обмен."
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить первого игрока: {e}")
            return
        
        # Выполняем обмен
        users = load_data(USERS_FILE, {})
        from_user_data = users.get(str(trade["from_user"]), {})
        to_user_data = users.get(str(trade["to_user"]), {})
        
        # Проверяем наличие карточек
        if (trade["from_card"] not in from_user_data.get("cards", []) or 
            trade["to_card"] not in to_user_data.get("cards", [])):
            await query.edit_message_text("❌ Обмен невозможен: карточки больше недоступны!")
            return
            
        # Обмен карточками
        from_user_data["cards"].remove(trade["from_card"])
        from_user_data["cards"].append(trade["to_card"])
        
        to_user_data["cards"].remove(trade["to_card"])
        to_user_data["cards"].append(trade["from_card"])
        
        # Сохраняем данные
        users[str(trade["from_user"])] = from_user_data
        users[str(trade["to_user"])] = to_user_data
        save_data(USERS_FILE, users)
        
        # Обновляем статус обмена
        trades[trade_id]["status"] = "completed"
        save_data(TRADES_FILE, trades)
        
        # Уведомления
        await query.edit_message_text("✅ Обмен успешно завершен!")
        
        # Уведомляем первого игрока
        try:
            await context.bot.send_message(
                trade["from_user"],
                f"✅ Пользователь @{query.from_user.username} подтвердил обмен! Обмен успешно завершен."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить первого игрока: {e}")

# Проверка подписки перед любым сообщением
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    
    # Проверка блокировки
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

# ====================== АДМИН И МОДЕРАТОР КОМАНДЫ ====================== #

# Добавление карточки - начало процесса
async def admin_addcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
        
    await update.message.reply_text("Введите название новой карточки:")
    return ADMIN_CARD_NAME

# Добавление карточки - шаг 1: название
async def admin_card_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_card"] = {"name": update.message.text}
    
    # Получаем список редкостей
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

# Добавление карточки - шаг 2: редкость
async def admin_card_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    rarity = update.message.text.strip()
    rarities = load_data(RARITIES_FILE, [])
    
    # Проверяем существование редкости
    if rarity not in [r["name"] for r in rarities]:
        await update.message.reply_text("❌ Редкость не найдена! Введите существующую редкость.")
        return ADMIN_CARD_RARITY
    
    context.user_data["new_card"]["rarity"] = rarity
    await update.message.reply_text("Введите описание карточки:")
    return ADMIN_CARD_DESCRIPTION

# Добавление карточки - шаг 3: описание
async def admin_card_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_card"]["description"] = update.message.text
    await update.message.reply_text("Отправьте изображение карточки (фото):")
    return ADMIN_CARD_IMAGE

# Добавление карточки - шаг 4: изображение
async def admin_card_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Сохраняем изображение
    if not update.message.photo:
        await update.message.reply_text("❌ Пожалуйста, отправьте изображение карточки!")
        return ADMIN_CARD_IMAGE
        
    photo = update.message.photo[-1]
    file = await photo.get_file()
    
    # Создаем папку для изображений, если её нет
    os.makedirs(CARDS_IMAGE_DIR, exist_ok=True)
    
    filename = f"{int(time.time())}.jpg"
    image_path = os.path.join(CARDS_IMAGE_DIR, filename)
    
    await file.download_to_drive(image_path)
    
    # Создаем новую карточку
    new_card = context.user_data["new_card"]
    cards = load_data(CARDS_FILE, [])
    
    # Генерируем ID
    new_id = max(card["id"] for card in cards) + 1 if cards else 1
    new_card["id"] = new_id
    new_card["image"] = filename
    
    cards.append(new_card)
    save_data(CARDS_FILE, cards)
    
    await update.message.reply_text(f"✅ Карточка '{new_card['name']}' успешно добавлена!")
    context.user_data.clear()
    return ConversationHandler.END

# Отмена добавления карточки
async def cancel_addcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление карточки отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# Список всех карточек
async def admin_listcards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
        
    cards = load_data(CARDS_FILE, [])
    if not cards:
        await update.message.reply_text("ℹ️ Карточек нет в базе данных.")
        return
    
    # Сортируем по ID
    sorted_cards = sorted(cards, key=lambda x: x["id"])
    
    # Формируем сообщение
    message = "<b>Список всех карточек:</b>\n\n"
    for card in sorted_cards:
        emoji = get_rarity_emoji(card["rarity"])
        message += (
            f"🆔 ID: {card['id']}\n"
            f"🏷 Название: {html.escape(card['name'])}\n"
            f"{emoji} Редкость: {card['rarity']}\n\n"
        )
    
    await update.message.reply_text(message, parse_mode="HTML")

# Сброс таймера пользователя
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
        
        # Уведомляем пользователя
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

# Выдача карточки пользователю
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
        
        # Проверяем существование карточки
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await update.message.reply_text("❌ Карточка не найдена!")
            return
        
        # Добавляем карточку пользователю
        if str(user_id) not in users:
            users[str(user_id)] = {"cards": [], "last_drop": 0}
        
        users[str(user_id)]["cards"].append(card_id)
        save_data(USERS_FILE, users)
        
        # Получаем количество этой карточки у пользователя
        card_count = users[str(user_id)]["cards"].count(card_id)
        count_text = f" (x{card_count})" if card_count > 1 else ""
        
        await update.message.reply_text(
            f"✅ Карточка '{card['name']}{count_text}' выдана пользователю {user_id}!"
        )
        
        # Уведомляем пользователя
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

# Рассылка сообщений
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
            continue  # Пропускаем заблокированных
            
        try:
            await context.bot.send_message(
                chat_id=uid, 
                text=f"📢 Рассылка от администратора:\n\n{message}"
            )
            count += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки для {user_id}: {e}")
            errors += 1
    
    await update.message.reply_text(
        f"✅ Рассылка завершена!\n"
        f"Отправлено: {count} пользователям\n"
        f"Ошибок: {errors}"
    )

# Блокировка пользователя
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /ban <user_id>")
        return
        
    try:
        user_id = int(context.args[0])
        
        # Нельзя заблокировать администратора
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
        
        # Уведомляем пользователя
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

# Разблокировка пользователя
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
        
        # Уведомляем пользователя
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

# Добавление модератора
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
        
        # Уведомляем пользователя
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

# Удаление модератора
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
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                user_id,
                "ℹ️ У вас были отозваны права модератора."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

# Выдача монет пользователю
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
        
        # Уведомляем пользователя
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

# Изъятие монет у пользователя
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
        
        # Уведомляем пользователя
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

# Добавление редкости - начало процесса
async def admin_addrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
        
    await update.message.reply_text("Введите название новой редкости:")
    return ADMIN_RARITY_NAME

# Добавление редкости - шаг 1: название
async def admin_rarity_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_rarity"] = {"name": update.message.text}
    await update.message.reply_text("Введите смайлик для этой редкости:")
    return ADMIN_RARITY_EMOJI

# Добавление редкости - шаг 2: смайлик
async def admin_rarity_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_rarity"]["emoji"] = update.message.text
    await update.message.reply_text(
        "Могут ли карточки этой редкости выпадать через /get_card?\n"
        "1 - Да, 0 - Нет:"
    )
    return ADMIN_RARITY_DROPPABLE

# Добавление редкости - шаг 3: droppable флаг
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

# Отмена добавления редкости
async def cancel_addrarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление редкости отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# Список всех редкостей
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

# Добавление товара в магазин - начало процесса
async def admin_addshopitem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return ConversationHandler.END
        
    await update.message.reply_text("Введите название товара:")
    return ADMIN_SHOP_NAME

# Добавление товара - шаг 1: название
async def admin_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_shop_item"] = {"name": update.message.text}
    
    keyboard = [
        [InlineKeyboardButton("Сброс таймера", callback_data="reset")],
        [InlineKeyboardButton("Набор карточек", callback_data="pack")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите тип товара:",
        reply_markup=reply_markup
    )
    return ADMIN_SHOP_TYPE

# Обработка типа товара
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

# Добавление товара - шаг 2: цена
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
        # Для сброса таймера не нужны карточки
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

# Добавление товара - шаг 3: карточки (для набора)
async def admin_shop_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        card_ids = [int(id_str) for id_str in update.message.text.split()]
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID! Используйте цифры, разделенные пробелами.")
        return ADMIN_SHOP_CARDS
    
    # Проверяем существование карточек
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

# Добавление товара - шаг 4: продолжительность
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
    
    # Устанавливаем время истечения
    if duration > 0:
        new_item["expire_time"] = time.time() + duration * 3600
    else:
        new_item["expire_time"] = 0
    
    # Генерируем ID
    new_id = max(item["id"] for item in shop_items) + 1 if shop_items else 1
    new_item["id"] = new_id
    
    shop_items.append(new_item)
    save_data(SHOP_FILE, shop_items)
    
    # Формируем сообщение
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

# Отмена добавления товара
async def cancel_addshopitem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Добавление товара отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# Список товаров в магазине (для админа)
async def admin_listshop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору и модераторам!")
        return
        
    shop_items = load_data(SHOP_FILE, [])
    current_time = time.time()
    
    # Удаляем просроченные товары
    active_items = [
        item for item in shop_items 
        if item.get("expire_time", 0) == 0 or item["expire_time"] > current_time
    ]
    
    # Обновляем файл магазина
    save_data(SHOP_FILE, active_items)
    
    if not active_items:
        await update.message.reply_text("🛒 Магазин пуст!")
        return
    
    message = "🛒 <b>Товары в магазине</b>\n\n"
    for item in active_items:
        message += f"🆔 <b>ID</b>: {item['id']}\n"
        message += f"🏷 <b>Название</b>: {html.escape(item['name'])}\n"
        message += f"💵 <b>Цена</b>: {item['price']} монет\n"
        
        # Отображаем время до истечения
        if item.get("expire_time", 0) > 0:
            time_left = item["expire_time"] - current_time
            if time_left > 0:
                hours = int(time_left // 3600)
                minutes = int((time_left % 3600) // 60)
                message += f"⏳ <b>Осталось</b>: {hours}ч {minutes}мин\n"
            else:
                continue  # Пропускаем просроченные
        
        if item["type"] == "reset":
            message += "📝 <b>Тип</b>: Сброс таймера получения карточки\n\n"
        elif item["type"] == "pack":
            message += "📝 <b>Тип</b>: Набор карточек\n"
            card_names = ", ".join([str(card_id) for card_id in item["cards"]])
            message += f"🃏 <b>Карточки</b>: {card_names}\n\n"
    
    await update.message.reply_text(message, parse_mode="HTML")

# ====================== ОСНОВНАЯ ФУНКЦИЯ ====================== #

def main() -> None:
    # Создание необходимых файлов и папок
    os.makedirs(CARDS_IMAGE_DIR, exist_ok=True)
    
    # Инициализация файлов
    if not os.path.exists(CARDS_FILE):
        save_data(CARDS_FILE, [
            {
                "id": 1,
                "name": "Тумба",
                "rarity": "Легендарная",
                "image": "tumba.png",
                "description": "x2 Чемпион РЕКХЛ"
            },
            {
                "id": 2,
                "name": "Тимахез",
                "rarity": "Редкая",
                "image": "tima.png",
                "description": "Тимакез дота 2"
            },
            {
                "id": 3,
                "name": "Казума",
                "rarity": "Эпическая",
                "image": "kazuma.png",
                "description": "Алкаш"
            },
            {
                "id": 4,
                "name": "Китаец",
                "rarity": "Обычная",
                "image": "kitaec.png",
                "description": "Узкоглазый"
            }
        ])
    
    if not os.path.exists(USERS_FILE):
        save_data(USERS_FILE, {})
        
    if not os.path.exists(TRADES_FILE):
        save_data(TRADES_FILE, {})
        
    if not os.path.exists(BLACKLIST_FILE):
        save_data(BLACKLIST_FILE, [])
    
    if not os.path.exists(MODERATORS_FILE):
        save_data(MODERATORS_FILE, [])
    
    if not os.path.exists(COINS_FILE):
        save_data(COINS_FILE, {})
    
    if not os.path.exists(RARITIES_FILE):
        # Стандартные редкости
        save_data(RARITIES_FILE, [
            {"name": "Легендарная", "emoji": "🔥", "droppable": True},
            {"name": "Блещет умом", "emoji": "🧠", "droppable": True},
            {"name": "Эпическая", "emoji": "💎", "droppable": True},
            {"name": "Редкая", "emoji": "✨", "droppable": True},
            {"name": "Обычная", "emoji": "🃏", "droppable": True},
            {"name": "Эксклюзивная", "emoji": "😎", "droppable": False}
        ])
    
    if not os.path.exists(SHOP_FILE):
        save_data(SHOP_FILE, [])

    # Создание приложения
    application = Application.builder().token(TOKEN).build()

    # ConversationHandler для добавления карточек
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
    
    # ConversationHandler для добавления редкостей
    addrarity_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin_addrarity", admin_addrarity)],
        states={
            ADMIN_RARITY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_name)],
            ADMIN_RARITY_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_emoji)],
            ADMIN_RARITY_DROPPABLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rarity_droppable)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addrarity)],
    )
    
    # ConversationHandler для добавления товаров в магазин
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

    # Добавляем обработчики
    application.add_handler(addcard_conv_handler)
    application.add_handler(addrarity_conv_handler)
    application.add_handler(addshopitem_conv_handler)
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_card", get_card))
    application.add_handler(CommandHandler("my_cards", show_collection))
    application.add_handler(CommandHandler("trade", start_trade))
    application.add_handler(CommandHandler("card_info", card_info))
    application.add_handler(CommandHandler("balance", show_balance))
    application.add_handler(CommandHandler("shop", show_shop))
    application.add_handler(CommandHandler("buy", buy_item))
    
    application.add_handler(CommandHandler("admin_listcards", admin_listcards))
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
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(trade_button, pattern=r"^(confirm_trade_|accept_trade_|reject_trade_|cancel_trade)"))
    application.add_handler(CallbackQueryHandler(admin_shop_type, pattern=r"^(reset|pack)"))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trade))
    application.add_handler(MessageHandler(filters.ALL, check_subscription))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()