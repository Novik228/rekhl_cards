import json
import os
import random
import time
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
CARDS_IMAGE_DIR = "cards_images"

# Состояния для добавления карточек
ADMIN_CARD_NAME, ADMIN_CARD_RARITY, ADMIN_CARD_DESCRIPTION, ADMIN_CARD_IMAGE = range(4)

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Шансы выпадения карточек (без эксклюзивных)
RARITY_CHANCES = {
    "Легендарная": 0.05,
    "Блещет умом": 0.07,
    "Эпическая": 0.15,
    "Редкая": 0.3,
    "Обычная": 0.5
}

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

# Показать коллекцию пользователя с ID карточек
async def show_collection_with_ids(user_id: int) -> str:
    users = load_data(USERS_FILE, {})
    user_data = users.get(str(user_id), {})
    cards = user_data.get("cards", [])
    
    if not cards:
        return "📭 Ваша коллекция пуста!"
    
    all_cards = load_data(CARDS_FILE, [])
    
    # Считаем количество каждой карточки
    card_counts = {}
    for card_id in cards:
        card_counts[card_id] = card_counts.get(card_id, 0) + 1
    
    # Группируем по редкости
    rarity_order = ["Легендарная", "Блещет умом", "Эпическая", "Редкая", "Обычная", "Эксклюзивная"]
    grouped = {rarity: [] for rarity in rarity_order}
    
    for card_id, count in card_counts.items():
        card = next((c for c in all_cards if c["id"] == card_id), None)
        if card:
            count_text = f" (x{count})" if count > 1 else ""
            grouped[card["rarity"]].append(f"{card['name']}{count_text} [ID: {card_id}]")
    
    # Формируем сообщение
    message = "🃏 <b>Ваша коллекция карточек</b>:\n\n"
    total_count = 0
    
    for rarity in rarity_order:
        if grouped[rarity]:
            count = sum(card_counts.get(card["id"], 0) for card in all_cards if card["rarity"] == rarity)
            total_count += count
            
            emoji = ""
            if rarity == "Легендарная": emoji = "🔥"
            elif rarity == "Эксклюзивная": emoji = "😎"
            elif rarity == "Блещет умом": emoji = "🧠"
            elif rarity == "Эпическая": emoji = "💎"
            elif rarity == "Редкая": emoji = "✨"
            else: emoji = "🃏"
            
            message += f"{emoji} <b>{rarity}</b> ({count}):\n"
            message += "\n".join(f"   • {name}" for name in sorted(grouped[rarity]))
            message += "\n\n"
    
    message += f"📚 <b>Всего карточек: {total_count}</b>"
    return message

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
        
        if is_admin(user.id):
            await update.message.reply_text(
                "👑 Вы администратор. Доступные команды:\n"
                "/admin_addcard - добавить карточку\n"
                "/admin_listcards - список всех карточек\n"
                "/admin_resettimer <user_id> - сбросить таймер\n"
                "/admin_givecard <user_id> <card_id> - выдать карточку\n"
                "/admin_broadcast <message> - сделать рассылку\n"
                "/ban <user_id> - заблокировать пользователя\n"
                "/unban <user_id> - разблокировать пользователя\n\n"
                "Обычные команды:\n"
                "/get_card - получить карточку\n"
                "/my_cards - моя коллекция\n"
                "/trade - обмен"
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
                "/trade - Обмен карточками\n\n"
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
                "/unban <user_id> - разблокировать пользователя\n\n"
                "Обычные команды:\n"
                "/get_card - получить карточку\n"
                "/my_cards - моя коллекция\n"
                "/trade - обмен"
            )
        else:
            await update.message.reply_text(
                "🎮 Добро пожаловать в REKHL CARDS!\n\n"
                "📋 Основные команды:\n"
                "/get_card - Получить случайную карточку\n"
                "/my_cards - Показать вашу коллекцию\n"
                "/trade - Обмен карточками\n\n"
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
        # Рассчитываем оставшееся время в часах и минутах
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        
        # Формируем сообщение в зависимости от оставшегося времени
        if hours > 0:
            time_text = f"{hours} час(ов) и {minutes} минут(ы)"
        else:
            time_text = f"{minutes} минут(ы)"
            
        await update.message.reply_text(
            f"⏳ Следующую карточку можно получить через: {time_text}"
        )
        return

    # Выбор карточки (исключая эксклюзивные)
    cards = [c for c in load_data(CARDS_FILE, []) if c["rarity"] != "Эксклюзивная"]
    if not cards:
        await update.message.reply_text("⚠️ Карточки не найдены! Обратитесь к администратору.")
        return

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

    # Получаем количество этой карточки у пользователя
    card_count = user_data["cards"].count(card["id"])
    count_text = f" (x{card_count})" if card_count > 1 else ""

    # Отправка карточки с описанием
    caption = f"🎉 Вы получили карточку!\n\n🏷 Название: {card['name']}{count_text}\n⭐ Редкость: {card['rarity']}\n"
    
    # Добавляем описание
    if "description" in card:
        caption += f"📝 Описание: {card['description']}\n"
    
    caption += f"📚 Теперь в вашей коллекции: {len(user_data['cards'])}"
    
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

# ====================== АДМИН КОМАНДЫ ====================== #

# Добавление карточки - начало процесса
async def admin_addcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
        return ConversationHandler.END
        
    await update.message.reply_text("Введите название новой карточки:")
    return ADMIN_CARD_NAME

# Добавление карточки - шаг 1: название
async def admin_card_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_card"] = {"name": update.message.text}
    await update.message.reply_text("Введите редкость карточки (Легендарная/Блещет умом/Эпическая/Редкая/Обычная/Эксклюзивная):")
    return ADMIN_CARD_RARITY

# Добавление карточки - шаг 2: редкость
async def admin_card_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    rarity = update.message.text.strip()
    valid_rarities = ["Легендарная", "Блещет умом", "Эпическая", "Редкая", "Обычная", "Эксклюзивная"]
    
    if rarity not in valid_rarities:
        await update.message.reply_text("❌ Некорректная редкость! Используйте: Легендарная/Блещет умом/Эпическая/Редкая/Обычная/Эксклюзивная")
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
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда доступна только администратору!")
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
        message += f"🆔 ID: {card['id']}\n🏷 Название: {card['name']}\n⭐ Редкость: {card['rarity']}\n\n"
    
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
        await update.message.reply_text("❌ Неверный формат ID! Используйте только цифры.")

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

    # Создание приложения
    application = Application.builder().token(TOKEN).build()

    # Сначала создаем ConversationHandler для добавления карточек
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
    
    # Добавляем обработчики в правильном порядке
    application.add_handler(addcard_conv_handler)  # Первым!
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_card", get_card))
    application.add_handler(CommandHandler("my_cards", show_collection))
    application.add_handler(CommandHandler("trade", start_trade))
    application.add_handler(CommandHandler("admin_listcards", admin_listcards))
    application.add_handler(CommandHandler("admin_resettimer", admin_resettimer))
    application.add_handler(CommandHandler("admin_givecard", admin_givecard))
    application.add_handler(CommandHandler("admin_broadcast", admin_broadcast))
    application.add_handler(CommandHandler("ban", admin_ban))
    application.add_handler(CommandHandler("unban", admin_unban))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(trade_button, pattern=r"^(confirm_trade_|accept_trade_|reject_trade_|cancel_trade)"))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trade))
    application.add_handler(MessageHandler(filters.ALL, check_subscription))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()