import asyncio
import logging
import os
import asyncpg
import stripe
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
stripe.api_key = STRIPE_SECRET_KEY

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

async def get_db():
    return await asyncpg.connect(DATABASE_URL)

class RegState(StatesGroup):
    language = State()
    phone = State()
    full_name = State()

class OrderState(StatesGroup):
    choosing_date = State()
    waiting_date_input = State()

class SettingsState(StatesGroup):
    changing_name = State()
    changing_phone = State()
    changing_language = State()

def language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 Oʻzbek", callback_data="lang_uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")]
    ])

def service_buttons(services, lang):
    buttons = [[
        InlineKeyboardButton(
            text=service["title_uz"] if lang == "uz" else service["title_ru"],
            callback_data=f"order_{service['id']}"
        )
    ] for service in services]
    buttons.append([
        InlineKeyboardButton(text="⚙️ Sozlamalar" if lang == "uz" else "⚙️ Настройки", callback_data="settings")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    conn = await get_db()
    user = await conn.fetchrow("SELECT full_name, language FROM users WHERE telegram_id = $1", message.from_user.id)
    services = await conn.fetch("SELECT id, title_uz, title_ru FROM services")
    await conn.close()

    if user:
        lang = user["language"]
        name = user["full_name"]
        if not services:
            await message.answer({
                "uz": f"👋 Salom, {name}!\n✅ Ro‘yxatdan o‘tgansiz.\n⛔ Xizmatlar yo‘q.",
                "ru": f"👋 Привет, {name}!\n✅ Вы зарегистрированы.\n⛔ Услуги пока недоступны."
            }[lang])
            return
        text = {
            "uz": f"👋 Salom, {name}!\n📋 Xizmatlar ro‘yxati:",
            "ru": f"👋 Привет, {name}!\n📋 Список услуг:"
        }[lang]
        await message.answer(text, reply_markup=service_buttons(services, lang))
    else:
        await message.answer("Tilni tanlang:\nВыберите язык:", reply_markup=language_keyboard())
        await state.set_state(RegState.language)

@dp.callback_query(F.data.startswith("lang_"))
async def update_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await state.update_data(language=lang)
    btn_text = {"uz": "📱 Raqamni yuborish", "ru": "📱 Отправить номер"}[lang]
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn_text, request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    msg = {"uz": "📞 Telefon raqamingizni yuboring:", "ru": "📞 Отправьте свой номер:"}[lang]
    await callback.message.answer(msg, reply_markup=kb)
    await state.set_state(RegState.phone)
    await callback.answer()

@dp.message(F.contact)
async def handle_contact(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == RegState.phone.state:
        data = await state.get_data()
        lang = data.get("language", "uz")
        phone = message.contact.phone_number
        if phone.startswith("+1") or phone.startswith("1"):
            normalized = "+1" + phone[-10:]
            await state.update_data(phone=normalized)
            await message.answer({
                "uz": "📝 Ismingizni kiriting:",
                "ru": "📝 Введите своё имя:"
            }[lang], reply_markup=ReplyKeyboardRemove())
            await state.set_state(RegState.full_name)
        else:
            await message.answer({
                "uz": "❗ Faqat AQSH raqamlari qabul qilinadi.",
                "ru": "❗ Принимаются только номера США."
            }[lang])
@dp.message()
async def handle_text_messages(message: types.Message, state: FSMContext):
    current = await state.get_state()

    # 1. Ro‘yxatdan o‘tishda matn orqali raqam
    if current == RegState.phone.state:
        phone = message.text.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        data = await state.get_data()
        lang = data.get("language", "uz")
        if phone.startswith("+1") and len(phone) == 12 and phone[2:].isdigit():
            normalized = phone
        elif phone.isdigit() and len(phone) == 10:
            normalized = "+1" + phone
        else:
            await message.answer({
                "uz": "❗ Raqam noto‘g‘ri formatda. Masalan: <code>3479974017</code> yoki <code>+13479974017</code>",
                "ru": "❗ Неверный формат. Например: <code>3479974017</code> или <code>+13479974017</code>"
            }[lang], parse_mode="HTML")
            return
        await state.update_data(phone=normalized)
        await message.answer({
            "uz": "📝 Ismingizni kiriting:",
            "ru": "📝 Введите своё имя:"
        }[lang], reply_markup=ReplyKeyboardRemove())
        await state.set_state(RegState.full_name)
        return

    # 2. Sozlamalarda matn orqali raqamni o‘zgartirish
    if current == SettingsState.changing_phone.state:
        phone = message.text.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        conn = await get_db()
        lang = await conn.fetchval("SELECT language FROM users WHERE telegram_id = $1", message.from_user.id)
        await conn.close()
        if phone.startswith("+1") and len(phone) == 12 and phone[2:].isdigit():
            formatted = phone
        elif phone.isdigit() and len(phone) == 10:
            formatted = "+1" + phone
        else:
            await message.answer({
                "uz": "❗ Raqam noto‘g‘ri formatda.",
                "ru": "❗ Неверный формат номера."
            }[lang])
            return
        conn = await get_db()
        await conn.execute("UPDATE users SET phone_number = $1 WHERE telegram_id = $2", formatted, message.from_user.id)
        await conn.close()
        text, kb = await settings_text_and_kb(message.from_user.id)
        await message.answer({
            "uz": "✅ Raqam yangilandi.\n\n" + text,
            "ru": "✅ Номер обновлён.\n\n" + text
        }[lang], reply_markup=kb, parse_mode="HTML")
        await state.clear()
        return

    # 3. Ism kiritish (ro‘yxatdan o‘tishda)
    if current == RegState.full_name.state:
        full_name = message.text.strip()
        data = await state.get_data()
        phone = data["phone"]
        language = data["language"]
        telegram_id = message.from_user.id
        conn = await get_db()
        await conn.execute("""
            INSERT INTO users (full_name, phone_number, language, telegram_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (phone_number) DO UPDATE SET telegram_id = EXCLUDED.telegram_id
        """, full_name, phone, language, telegram_id)
        services = await conn.fetch("SELECT id, title_uz, title_ru FROM services")
        await conn.close()
        if not services:
            await message.answer({
                "uz": f"👋 Salom, {full_name}!\n✅ Ro‘yxatdan o‘tdingiz.\n⛔ Hozircha xizmatlar yo‘q.",
                "ru": f"👋 Привет, {full_name}!\n✅ Вы зарегистрированы.\n⛔ Услуги пока недоступны."
            }[language])
            return
        buttons = [[
            InlineKeyboardButton(
                text=service["title_uz"] if language == "uz" else service["title_ru"],
                callback_data=f"order_{service['id']}"
            )
        ] for service in services]
        buttons.append([
            InlineKeyboardButton(
                text="⚙️ Sozlamalar" if language == "uz" else "⚙️ Настройки",
                callback_data="settings"
            )
        ])
        await message.answer({
            "uz": f"👋 Salom, {full_name}!\n📋 Xizmatlar ro‘yxati:",
            "ru": f"👋 Привет, {full_name}!\n📋 Список услуг:"
        }[language], reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await state.clear()

@dp.callback_query(F.data.startswith("order_"))
async def handle_order(callback: types.CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split("_")[1])
    conn = await get_db()
    lang = await conn.fetchval("SELECT language FROM users WHERE telegram_id = $1", callback.from_user.id)
    await conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Bugun" if lang == "uz" else "📅 Сегодня", callback_data=f"date_today_{service_id}")],
        [InlineKeyboardButton(text="📆 Ertaga" if lang == "uz" else "📆 Завтра", callback_data=f"date_tomorrow_{service_id}")],
        [InlineKeyboardButton(text="📖 Boshqa kun" if lang == "uz" else "📖 Другая дата", callback_data=f"date_other_{service_id}")],
        [InlineKeyboardButton(text="⬅️ Ortga" if lang == "uz" else "⬅️ Назад", callback_data="back_to_services")]
    ])
    await callback.message.edit_text({
        "uz": "📅 Qachon kerak?",
        "ru": "📅 На какой день нужно?"
    }[lang], reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("date_"))
async def handle_date(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    date_type = parts[1]
    service_id = int(parts[2])

    conn = await get_db()
    user = await conn.fetchrow("SELECT id, language FROM users WHERE telegram_id = $1", callback.from_user.id)
    service = await conn.fetchrow("SELECT * FROM services WHERE id = $1", service_id)
    conn.close()

    lang = user["language"]
    user_id = user["id"]

    if date_type == "today":
        selected_date = datetime.now().date()
    elif date_type == "tomorrow":
        selected_date = datetime.now().date() + timedelta(days=1)
    else:
        await state.update_data(service_id=service_id)
        await state.set_state(OrderState.waiting_date_input)
        await callback.message.edit_text({
            "uz": "📅 Sanani kiriting (YYYY-MM-DD):",
            "ru": "📅 Введите дату (YYYY-MM-DD):"
        }[lang])
        return

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": service["title_uz"] if lang == "uz" else service["title_ru"]
                },
                "unit_amount": int(service["price_usd"] * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url="https://t.me/bztesterbot",  # o‘zgartiring
        cancel_url="https://t.me/bztesterbot",
        metadata={
            "user_id": str(user_id),
            "service_id": str(service_id),
            "date": str(selected_date)
        }
    )

    text = {
        "uz": f"🧾 Xizmat: {service['title_uz']}\n📆 Sana: {selected_date}\n💵 Narx: ${service['price_usd']}\n\n💳 To‘lov uchun tugmani bosing:",
        "ru": f"🧾 Услуга: {service['title_ru']}\n📆 Дата: {selected_date}\n💵 Цена: ${service['price_usd']}\n\n💳 Нажмите кнопку для оплаты:"
    }[lang]

    pay_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 To‘lov qilish" if lang == "uz" else "💳 Оплатить", url=session.url)],
        [InlineKeyboardButton(text="⬅️ Ortga" if lang == "uz" else "⬅️ Назад", callback_data="back_to_services")]
    ])

    await callback.message.edit_text(text, reply_markup=pay_kb)
    await state.clear()

@dp.message(OrderState.waiting_date_input)
async def handle_custom_date(message: types.Message, state: FSMContext):
    try:
        selected_date = datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except:
        await message.answer("❗ Format noto‘g‘ri. Masalan: 2025-07-01")
        return

    data = await state.get_data()
    service_id = data["service_id"]

    # bu yerda siz Stripe sessiya yaratishni takrorlasangiz bo‘ladi yoki xabar berish bilan to‘xtab tursangiz ham bo‘ladi
    await message.answer(f"✅ Sana qabul qilindi: {selected_date}")
    await state.clear()

@dp.callback_query(F.data == "back_to_services")
async def back_to_services(callback: types.CallbackQuery, state: FSMContext):
    conn = await get_db()
    user = await conn.fetchrow("SELECT full_name, language FROM users WHERE telegram_id = $1", callback.from_user.id)
    services = await conn.fetch("SELECT id, title_uz, title_ru FROM services")
    await conn.close()
    lang = user["language"]
    name = user["full_name"]
    await callback.message.edit_text({
        "uz": f"👋 Salom, {name}!\n📋 Xizmatlar ro‘yxati:",
        "ru": f"👋 Привет, {name}!\n📋 Список услуг:"
    }[lang], reply_markup=service_buttons(services, lang))
    await state.clear()

@dp.callback_query(F.data == "settings")
async def show_settings(callback: types.CallbackQuery, state: FSMContext):
    text, kb = await settings_text_and_kb(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "change_name")
async def change_name(callback: types.CallbackQuery, state: FSMContext):
    conn = await get_db()
    lang = await conn.fetchval("SELECT language FROM users WHERE telegram_id = $1", callback.from_user.id)
    await conn.close()
    await callback.message.edit_text({
        "uz": "👤 Yangi ismingizni kiriting:",
        "ru": "👤 Введите новое имя:"
    }[lang])
    await state.set_state(SettingsState.changing_name)
    await callback.answer()

@dp.message(SettingsState.changing_name)
async def save_name(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    conn = await get_db()
    await conn.execute("UPDATE users SET full_name = $1 WHERE telegram_id = $2", full_name, message.from_user.id)
    lang = await conn.fetchval("SELECT language FROM users WHERE telegram_id = $1", message.from_user.id)
    await conn.close()
    text, kb = await settings_text_and_kb(message.from_user.id)
    await message.answer({
        "uz": "✅ Ism yangilandi.\n\n" + text,
        "ru": "✅ Имя обновлено.\n\n" + text
    }[lang], reply_markup=kb, parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "change_lang")
async def change_lang(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.changing_language)
    await callback.message.edit_text("🌐 Tilni tanlang:\nВыберите язык:", reply_markup=language_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("lang_"))
async def update_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    current = await state.get_state()
    if current == SettingsState.changing_language.state:
        conn = await get_db()
        await conn.execute("UPDATE users SET language = $1 WHERE telegram_id = $2", lang, callback.from_user.id)
        await conn.close()
        text, kb = await settings_text_and_kb(callback.from_user.id)
        await callback.message.edit_text({
            "uz": "✅ Til o‘zgartirildi.\n\n" + text,
            "ru": "✅ Язык изменён.\n\n" + text
        }[lang], reply_markup=kb, parse_mode="HTML")
        await state.clear()
    else:
        # yangi foydalanuvchi ro‘yxatdan o‘tmoqda
        await state.update_data(language=lang)
        ...

@dp.callback_query(F.data == "change_phone")
async def change_phone(callback: types.CallbackQuery, state: FSMContext):
    conn = await get_db()
    lang = await conn.fetchval("SELECT language FROM users WHERE telegram_id = $1", callback.from_user.id)
    await conn.close()
    msg = {"uz": "📞 Yangi raqamingizni yuboring:", "ru": "📞 Отправьте новый номер:"}[lang]
    btn = {"uz": "📱 Raqamni yuborish", "ru": "📱 Отправить номер"}[lang]
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn, request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await callback.message.answer(msg, reply_markup=kb)
    await state.set_state(SettingsState.changing_phone)
    await callback.answer()


async def settings_text_and_kb(telegram_id: int):
    conn = await get_db()
    user = await conn.fetchrow("SELECT full_name, phone_number, language FROM users WHERE telegram_id = $1", telegram_id)
    await conn.close()
    lang = user["language"]
    text = {
        "uz": (
            f"⚙️ <b>Sozlamalar</b>\n\n"
            f"👤 Ism: {user['full_name']}\n"
            f"📞 Raqam: {user['phone_number']}\n"
            f"🌐 Til: {'O‘zbek tili' if lang == 'uz' else 'Русский язык'}\n\n"
            "Nimani o‘zgartirmoqchisiz?"
        ),
        "ru": (
            f"⚙️ <b>Настройки</b>\n\n"
            f"👤 Имя: {user['full_name']}\n"
            f"📞 Номер: {user['phone_number']}\n"
            f"🌐 Язык: {'O‘zbek tili' if lang == 'uz' else 'Русский язык'}\n\n"
            "Что вы хотите изменить?"
        )
    }[lang]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Tilni o‘zgartirish" if lang == "uz" else "🌐 Изменить язык", callback_data="change_lang")],
        [InlineKeyboardButton(text="👤 Ismni o‘zgartirish" if lang == "uz" else "👤 Изменить имя", callback_data="change_name")],
        [InlineKeyboardButton(text="📞 Raqamni o‘zgartirish" if lang == "uz" else "📞 Изменить номер", callback_data="change_phone")],
        [InlineKeyboardButton(text="⬅️ Ortga" if lang == "uz" else "⬅️ Назад", callback_data="back_to_services")]
    ])
    return text, kb

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
