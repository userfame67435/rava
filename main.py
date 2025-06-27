import logging
import sys
import uuid
import psycopg2
import hashlib
import requests
import asyncio
import os
import qrcode
import base64
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from urllib.parse import urlencode
from config import fetch_bot_settings
import time
import random
import string

# Настройка логирования с уникальным ID
def generate_log_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(log_id)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)
log_id = generate_log_id()
log.info(f"Инициализация приложения [{log_id}]")

# Пути и конфигурации
PAYMENT_STORE = "/store_payment"
YOOMONEY_HOOK = "/yoomoney_hook"
HEALTH_CHECK = "/health"
WEBHOOK_BASE = "/hook"
DB_URL = os.getenv("DB_URL", "postgresql://postgres.iylthyqzwovudjcyfubg:Alex4382!@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")
HOST_URL = os.getenv("HOST_URL", "https://new-project.up.railway.app")
TON_ADDRESS = "UQBLNUOpN5B0q_M2xukAB5MsfSCUsdE6BkXHO6ndogQDi5_6"
BTC_ADDRESS = "bc1q5xq9m473r8nnkx799ztcrwfqs0555fs3ulw9vr"
USDT_ADDRESS = "TQzs3V6QHdXb3CtNPYK9iPWuvvrYCPt6vE"
PAYPAL_EMAIL = "nemillingsuppay@gmail.com"

# Окружение
ENV = os.getenv("ENV", "railway")
log.info(f"Запуск на платформе: {ENV} [{log_id}]")

# Кэш для курсов криптовалют
crypto_cache = {"prices": None, "timestamp": 0}
CACHE_TIMEOUT = 300  # 5 минут

def get_usd_from_rub(rub_amount):
    try:
        usd_rate = random.uniform(95.0, 105.0)
        return rub_amount / usd_rate
    except Exception as e:
        log.error(f"Ошибка конвертации RUB в USD [{log_id}]: {e}")
        return rub_amount / 100.0

def get_crypto_prices():
    global crypto_cache
    current_time = time.time()
    if crypto_cache["prices"] and (current_time - crypto_cache["timestamp"]) < CACHE_TIMEOUT:
        log.info(f"Использование кэша курсов [{log_id}]")
        return crypto_cache["prices"]
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network,bitcoin,tether&vs_currencies=usd",
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        crypto_cache["prices"] = (
            data["the-open-network"]["usd"],
            data["bitcoin"]["usd"],
            data["tether"]["usd"]
        )
        crypto_cache["timestamp"] = current_time
        log.info(f"Курсы криптовалют обновлены [{log_id}]")
        return crypto_cache["prices"]
    except Exception as e:
        log.error(f"Ошибка получения курса [{log_id}]: {e}")
        return 5.0, 60000.0, 1.0

def generate_qr_code(data):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        log.error(f"Ошибка генерации QR-кода [{log_id}]: {e}")
        return None

# Загрузка ботов
SETTINGS = fetch_bot_settings()
log.info(f"Инициализация {len(SETTINGS)} ботов [{log_id}]")
bot_instances = {}
dispatchers = {}

for bot_key, cfg in SETTINGS.items():
    try:
        bot_instances[bot_key] = Bot(token=cfg["TOKEN"])
        dispatchers[bot_key] = Dispatcher(bot_instances[bot_key])
        log.info(f"Бот {bot_key} готов [{log_id}]")
    except Exception as e:
        log.error(f"Ошибка инициализации бота {bot_key} [{log_id}]: {e}")
        sys.exit(1)

def setup_database():
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        for bot_key in SETTINGS:
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS payments_{bot_key} "
                "(label TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL, payment_type TEXT)"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_payments_{bot_key}_label ON payments_{bot_key} (label)"
            )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS user_languages "
            "(user_id TEXT PRIMARY KEY, language TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()
        log.info(f"База данных инициализирована [{log_id}]")
    except Exception as e:
        log.error(f"Ошибка настройки базы данных [{log_id}]: {e}")
        sys.exit(1)

setup_database()

def create_language_buttons():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("English", callback_data="lang_en"),
        InlineKeyboardButton("Русский", callback_data="lang_ru"),
        InlineKeyboardButton("Українська", callback_data="lang_uk"),
        InlineKeyboardButton("Türkçe", callback_data="lang_tr"),
        InlineKeyboardButton("हिन्दी", callback_data="lang_hi")
    )
    return keyboard

def create_payment_buttons(user_id, language):
    keyboard = InlineKeyboardMarkup()
    buttons = {
        "ru": [
            ("ЮMoney", f"yoomoney_{user_id}"),
            ("TON", f"ton_{user_id}"),
            ("BTC", f"btc_{user_id}"),
            ("USDT TRC20", f"usdt_{user_id}"),
            ("PayPal", f"paypal_{user_id}")
        ],
        "en": [
            ("TON", f"ton_{user_id}"),
            ("BTC", f"btc_{user_id}"),
            ("USDT TRC20", f"usdt_{user_id}"),
            ("PayPal", f"paypal_{user_id}")
        ],
        "uk": [
            ("TON", f"ton_{user_id}"),
            ("BTC", f"btc_{user_id}"),
            ("USDT TRC20", f"usdt_{user_id}"),
            ("PayPal", f"paypal_{user_id}")
        ],
        "tr": [
            ("TON", f"ton_{user_id}"),
            ("BTC", f"btc_{user_id}"),
            ("USDT TRC20", f"usdt_{user_id}"),
            ("PayPal", f"paypal_{user_id}")
        ],
        "hi": [
            ("TON", f"ton_{user_id}"),
            ("BTC", f"btc_{user_id}"),
            ("USDT TRC20", f"usdt_{user_id}"),
            ("PayPal", f"paypal_{user_id}")
        ]
    }
    for text, callback in buttons.get(language, buttons["en"]):
        keyboard.add(InlineKeyboardButton(text, callback_data=callback))
    return keyboard

def get_user_language(user_id):
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM user_languages WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else "en"
    except Exception as e:
        log.error(f"Ошибка получения языка для {user_id} [{log_id}]: {e}")
        return "en"

def save_user_language(user_id, language):
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_languages (user_id, language) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET language = %s",
            (user_id, language, language)
        )
        conn.commit()
        conn.close()
        log.info(f"Язык {language} сохранен для {user_id} [{log_id}]")
    except Exception as e:
        log.error(f"Ошибка сохранения языка для {user_id} [{log_id}]: {e}")

async def handle_crypto_or_paypal_payment(cb, bot_key, payment_type, address=None, price_index=None, decimals=2):
    try:
        user_id = cb.data.split("_")[1]
        chat_id = cb.message.chat.id
        bot = bot_instances[bot_key]
        cfg = SETTINGS[bot_key]
        language = get_user_language(user_id)
        await bot.answer_callback_query(cb.id)
        log.info(f"[{bot_key}] Платеж {payment_type} выбран пользователем {user_id} [{log_id}]")

        payment_id = str(uuid.uuid4())
        price = cfg["PRICE"]["ru"] if language == "ru" else cfg["PRICE"][language]
        usd_amount = get_usd_from_rub(price) if language == "ru" else price

        if payment_type in ["ton", "btc", "usdt"]:
            ton_price, btc_price, usdt_price = get_crypto_prices()
            prices = {"ton": ton_price, "btc": btc_price, "usdt": usdt_price}
            amount = usd_amount / prices[payment_type]
            amount = round(amount, 4 if payment_type == "ton" else 8 if payment_type == "btc" else 2)
            addresses = {"ton": TON_ADDRESS, "btc": BTC_ADDRESS, "usdt": USDT_ADDRESS}
            address = addresses[payment_type]
            qr_data = f"{payment_type}://{address}?amount={amount}" if payment_type != "usdt" else address
            qr_base64 = generate_qr_code(qr_data)
            if qr_base64:
                qr_bytes = base64.b64decode(qr_base64)
                await bot.send_photo(
                    chat_id,
                    photo=qr_bytes,
                    caption=f"{address}",
                    protect_content=True,
                    has_spoiler=True
                )
            else:
                await bot.send_message(chat_id, f"{address}", protect_content=True)
        else:  # PayPal
            amount = price
            currency = "RUB" if language == "ru" else "USD"

        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
            "VALUES (%s, %s, %s, %s)",
            (payment_id, user_id, "pending", payment_type)
        )
        conn.commit()
        conn.close()
        log.info(f"[{bot_key}] Платеж {payment_id} ({payment_type}) сохранен для {user_id} [{log_id}]")

        prompt = {
            "en": f"Send {amount:.{decimals}f} {payment_type.upper()} to {address or PAYPAL_EMAIL}" + 
                  (f". Include Telegram ID ({user_id}) in note." if payment_type == "paypal" else ""),
            "ru": f"Отправьте {amount:.{decimals}f} {payment_type.upper()} на {address or PAYPAL_EMAIL}" + 
                  (f". Укажите Telegram ID ({user_id}) в заметке." if payment_type == "paypal" else ""),
            "uk": f"Надішліть {amount:.{decimals}f} {payment_type.upper()} на {address or PAYPAL_EMAIL}" + 
                  (f". Вкажіть Telegram ID ({user_id}) у примітці." if payment_type == "paypal" else ""),
            "tr": f"{amount:.{decimals}f} {payment_type.upper()} adresine {address or PAYPAL_EMAIL} gönderin" + 
                  (f". Notta Telegram ID ({user_id}) belirtin." if payment_type == "paypal" else ""),
            "hi": f"{amount:.{decimals}f} {payment_type.upper()} को {address or PAYPAL_EMAIL} पर भेजें" + 
                  (f". नोट में Telegram ID ({user_id}) शामिल करें।" if payment_type == "paypal" else "")
        }
        await bot.send_message(chat_id, prompt[language], protect_content=True)
        log.info(f"[{bot_key}] Инструкции {payment_type} отправлены {user_id} (protect_content=True) [{log_id}]")
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка обработки {payment_type} для {user_id} [{log_id}]: {e}")
        await bot_instances[bot_key].send_message(chat_id, "Payment error. Contact support.", protect_content=True)

for bot_key, dp in dispatchers.items():
    @dp.message_handler(commands=["start"])
    async def initiate_language_selection(msg: types.Message, bot_key=bot_key):
        try:
            user_id = str(msg.from_user.id)
            chat_id = msg.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            log.info(f"[{bot_key}] Старт для {user_id} [{log_id}]")

            keyboard = create_language_buttons()
            welcome_text = random.choice([
                "Please select your language:\nВыберите язык:\nОберіть мову:\nLütfen dilinizi seçin:\nकृपया अपनी भाषा चुनें:",
                "Choose your language:\nВыберите ваш язык:\nВиберіть мову:\nDilinizi seçin:\nअपनी भाषा चुनें:"
            ])
            if "START_PHOTO" in cfg:
                await bot.send_photo(
                    chat_id,
                    photo=cfg["START_PHOTO"],
                    caption=welcome_text,
                    reply_markup=keyboard,
                    protect_content=True,
                    has_spoiler=True
                )
                log.info(f"[{bot_key}] Фото и выбор языка отправлены для {user_id} (protect_content=True) [{log_id}]")
            else:
                await bot.send_message(
                    chat_id,
                    welcome_text,
                    reply_markup=keyboard,
                    protect_content=True
                )
                log.info(f"[{bot_key}] Выбор языка отправлен для {user_id} (protect_content=True) [{log_id}]")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка /start для {user_id} [{log_id}]: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Error. Contact support.", protect_content=True)

    @dp.callback_query_handler(lambda c: c.data.startswith("lang_"))
    async def handle_language_choice(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = str(cb.from_user.id)
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            language = cb.data.split("_")[1]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] Язык {language} выбран {user_id} [{log_id}]")

            save_user_language(user_id, language)
            keyboard = create_payment_buttons(user_id, language)
            price = cfg["PRICE"][language]
            original_price = price * 2
            welcome_msg = cfg["DESCRIPTION"][language].format(price=price, original_price=original_price)
            currency = "RUB" if language == "ru" else "USD"
            payment_prompt = {
                "en": f"{welcome_msg}\n\nChoose payment method for {price} {currency}:",
                "ru": f"{welcome_msg}\n\nВыберите способ оплаты для {price} {currency}:",
                "uk": f"{welcome_msg}\n\nОберіть спосіб оплати для {price} {currency}:",
                "tr": f"{welcome_msg}\n\n{price} {currency} için ödeme yöntemi seçin:",
                "hi": f"{welcome_msg}\n\n{price} {currency} के लिए भुगतान विधि चुनें:"
            }
            await bot.send_message(chat_id, payment_prompt[language], reply_markup=keyboard, protect_content=True)
            log.info(f"[{bot_key}] Варианты оплаты отправлены {user_id} на {language} (protect_content=True) [{log_id}]")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка выбора языка для {user_id} [{log_id}]: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Error selecting language. Contact support.", protect_content=True)

    @dp.callback_query_handler(lambda c: c.data.startswith("yoomoney_"))
    async def handle_yoomoney_choice(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = cb.data.split("_")[1]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            language = get_user_language(user_id)
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] ЮMoney выбран {user_id} [{log_id}]")

            payment_id = str(uuid.uuid4())
            price = cfg["PRICE"]["ru"]
            payment_data = {
                "quickpay-form": "shop",
                "paymentType": "AC",
                "targets": f"Subscription {user_id} ({bot_key})",
                "sum": price,
                "label": payment_id,
                "receiver": cfg["YOOMONEY_WALLET"],
                "successURL": f"https://t.me/{(await bot.get_me()).username}"
            }
            payment_link = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(payment_data)}"

            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
                "VALUES (%s, %s, %s, %s)",
                (payment_id, user_id, "pending", "yoomoney")
            )
            conn.commit()
            conn.close()
            log.info(f"[{bot_key}] Платеж {payment_id} (yoomoney) сохранен для {user_id} [{log_id}]")

            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("Оплатить сейчас", url=payment_link))
            await bot.send_message(chat_id, "Перейдите для оплаты через ЮMoney:", reply_markup=keyboard, protect_content=True)
            log.info(f"[{bot_key}] Ссылка ЮMoney отправлена {user_id} (protect_content=True) [{log_id}]")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка ЮMoney для {user_id} [{log_id}]: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Payment error. Contact support.", protect_content=True)

    @dp.callback_query_handler(lambda c: c.data.startswith(("ton_", "btc_", "usdt_", "paypal_")))
    async def handle_payment_choice(cb: types.CallbackQuery, bot_key=bot_key):
        payment_type = cb.data.split("_")[0]
        params = {
            "ton": (TON_ADDRESS, 0, 4),
            "btc": (BTC_ADDRESS, 1, 8),
            "usdt": (USDT_ADDRESS, 2, 2),
            "paypal": (None, None, 2)
        }
        address, price_index, decimals = params[payment_type]
        await handle_crypto_or_paypal_payment(cb, bot_key, payment_type, address, price_index, decimals)

def check_yoomoney_webhook(data, bot_key):
    try:
        cfg = SETTINGS[bot_key]
        params = [
            data.get("notification_type", ""),
            data.get("operation_id", ""),
            data.get("amount", ""),
            data.get("currency", ""),
            data.get("datetime", ""),
            data.get("sender", ""),
            data.get("codepro", ""),
            cfg["NOTIFICATION_SECRET"],
            data.get("label", "")
        ]
        computed_hash = hashlib.sha1("&".join(str(p) for p in params).encode()).hexdigest()
        return computed_hash == data.get("sha1_hash")
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка проверки ЮMoney webhook [{log_id}]: {e}")
        return False

async def handle_payment_confirmation(data, bot_key):
    try:
        if not check_yoomoney_webhook(data, bot_key):
            log.error(f"[{bot_key}] Неверный хэш ЮMoney webhook [{log_id}]")
            return web.json_response({"status": "error", "message": "Invalid hash"}, status=400)

        label = data.get("label")
        user_id = data.get("user_id")
        if not label or not user_id:
            log.error(f"[{bot_key}] Отсутствует label или user_id в webhook [{log_id}]")
            return web.json_response({"status": "error", "message": "Missing label or user_id"}, status=400)

        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT status FROM payments_{bot_key} WHERE label = %s AND user_id = %s",
            (label, user_id)
        )
        result = cursor.fetchone()
        if not result:
            conn.close()
            log.error(f"[{bot_key}] Платеж {label} не найден для {user_id} [{log_id}]")
            return web.json_response({"status": "error", "message": "Payment not found"}, status=404)

        if result[0] == "completed":
            conn.close()
            log.info(f"[{bot_key}] Платеж {label} уже обработан для {user_id} [{log_id}]")
            return web.json_response({"status": "success", "message": "Already processed"})

        cursor.execute(
            f"UPDATE payments_{bot_key} SET status = %s WHERE label = %s",
            ("completed", label)
        )
        conn.commit()
        conn.close()

        bot = bot_instances[bot_key]
        cfg = SETTINGS[bot_key]
        language = get_user_language(user_id)
        invite_link = await bot.create_chat_invite_link(
            chat_id=cfg["PRIVATE_CHANNEL_ID"],
            member_limit=1,
            expire_date=int(time.time()) + 86400
        )
        success_msg = {
            "en": f"Payment successful! Join the private channel: {invite_link.invite_link}",
            "ru": f"Оплата прошла успешно! Присоединяйтесь к приватному каналу: {invite_link.invite_link}",
            "uk": f"Оплата успішна! Долучайтесь до приватного каналу: {invite_link.invite_link}",
            "tr": f"Ödeme başarılı! Özel kanala katıl: {invite_link.invite_link}",
            "hi": f"भुगतान सफल! निजी चैनल में शामिल हों: {invite_link.invite_link}"
        }
        await bot.send_message(user_id, success_msg[language], protect_content=True)
        log.info(f"[{bot_key}] Платеж {label} подтвержден, ссылка отправлена {user_id} [{log_id}]")
        return web.json_response({"status": "success"})
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка обработки webhook для {user_id} [{log_id}]: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def store_payment(request):
    try:
        data = await request.json()
        bot_key = data.get("bot_key")
        user_id = data.get("user_id")
        payment_type = data.get("payment_type")
        label = data.get("label")

        if not all([bot_key, user_id, payment_type, label]):
            log.error(f"Недостаточно данных в /store_payment [{log_id}]")
            return web.json_response({"status": "error", "message": "Missing parameters"}, status=400)

        if bot_key not in SETTINGS:
            log.error(f"Неверный bot_key {bot_key} в /store_payment [{log_id}]")
            return web.json_response({"status": "error", "message": "Invalid bot_key"}, status=400)

        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (label) DO NOTHING",
            (label, user_id, "pending", payment_type)
        )
        conn.commit()
        conn.close()
        log.info(f"[{bot_key}] Платеж {label} ({payment_type}) сохранен для {user_id} [{log_id}]")
        return web.json_response({"status": "success"})
    except Exception as e:
        log.error(f"Ошибка /store_payment [{log_id}]: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def yoomoney_webhook(request):
    try:
        data = await request.post()
        bot_key = data.get("bot_key")
        if not bot_key or bot_key not in SETTINGS:
            log.error(f"Неверный bot_key в /yoomoney_hook [{log_id}]")
            return web.json_response({"status": "error", "message": "Invalid bot_key"}, status=400)
        return await handle_payment_confirmation(data, bot_key)
    except Exception as e:
        log.error(f"Ошибка /yoomoney_hook [{log_id}]: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def health_check(request):
    return web.json_response({"status": "ok"})

async def webhook_handler(request):
    bot_key = request.match_info["bot_key"]
    if bot_key not in dispatchers:
        log.error(f"Неверный bot_key {bot_key} в /hook [{log_id}]")
        return web.json_response({"status": "error", "message": "Invalid bot_key"}, status=400)
    update = await request.json()
    await dispatchers[bot_key].handle_update(types.Update(**update))
    return web.json_response({"status": "ok"})

async def on_startup(app):
    for bot_key, bot in bot_instances.items():
        webhook_url = f"{HOST_URL}{WEBHOOK_BASE}/{bot_key}"
        try:
            await bot.set_webhook(webhook_url)
            log.info(f"[{bot_key}] Webhook установлен: {webhook_url} [{log_id}]")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка установки webhook [{log_id}]: {e}")

async def on_shutdown(app):
    for bot_key, bot in bot_instances.items():
        try:
            await bot.delete_webhook()
            await bot.get_session().close()
            log.info(f"[{bot_key}] Webhook удален, сессия закрыта [{log_id}]")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка при остановке [{log_id}]: {e}")

def create_app():
    app = web.Application()
    app.router.add_post(PAYMENT_STORE, store_payment)
    app.router.add_post(YOOMONEY_HOOK, yoomoney_webhook)
    app.router.add_get(HEALTH_CHECK, health_check)
    app.router.add_post(f"{WEBHOOK_BASE}/{{bot_key}}", webhook_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
