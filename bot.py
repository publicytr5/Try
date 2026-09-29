import logging
import random
import string
import asyncio
import os
import qrcode
from io import BytesIO
from datetime import datetime, time, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import threading

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set!")
PORT = int(os.environ.get("PORT", 8080))

BOT_USERNAME = "Vanilla_cards_bot"
ADMIN_ID = 8508012498

CAD_TO_USD_RATE = 0.71352
AUD_TO_USD_RATE = 0.6983

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "running", "message": "Bot is running!"})

@app.route('/health')
def health():
    return "OK", 200

CARD_BINS = {
    "USD": [
        "435880xx", "491277xx", "511332xx", "520356xx", "409758xx",
        "525362xx", "451129xx", "434340xx", "426370xx", "411810xx",
        "403446xx", "533621xx", "446317xx", "545660xx", "516612xx",
        "484718xx", "485246xx", "402372xx", "457851xx",
        "373778xx", "377935xx", "375163xx"
    ],
    "CAD": ["533985xx", "461126xx"],
    "AUD": ["428313xx", "457824xx", "432465xx"]
}

CAD_BINS = ["533985xx", "461126xx"]
AUD_BINS = ["428313xx", "457824xx", "432465xx"]

FILTER_BIN_MAP = {
    "vanilla": ["411810xx", "409758xx", "520356xx", "525362xx", "484718xx", "545660xx"],
    "cardbalance": ["428313xx", "432465xx", "457824xx"],
    "walmart": ["485246xx"],
    "giftcardmall": ["451129xx", "403446xx", "435880xx", "511332xx"],
    "joker": ["533985xx", "461126xx"],
    "amex": ["373778xx", "377935xx", "375163xx"]
}

class StickerType(Enum):
    NONE = ""
    RELISTED = "🔄"
    GOOGLE = "🅶"
    PAYPAL = "🅿"

# Updated GRAM addresses
TON_ADDRESSES = [
    "UQCCTTF03CCeyNKov1azQty5iNcNMnwH72J7pcb7MUaDKXsd",
    "UQAZjMCIT6MEMUgvKmweTySPrGqxnUrgvG5JQVUfnR-d_tke",
    "UQBwwD_2VekRaM-7_6wwltzkboxbTiYDqif40G9Tbnq76Td1",
    "UQAMBt7k1FZHvewkpB1IHMLiOMLZR63rO_NKv-fiQ0n5EGW_",
    "UQC9OvldFlHMbxKRq-6yRTm9uWv-YWFcsywHQAZz6p9dtonc",
    "UQAG4IdlmwUiVB5Svz91RaJOVL6EnLKWq0tonb4q408yOjIo",
    "UQCekPKzhJKHME00xTIGfgUr4BMI80QvHymBXmExxJVC3XXK",
    "UQAt6yloEtY3IQhvY7tZCPFfty6V12XJNbP9tsajRFDYn3dr",
    "UQBrqCRNNP6bnpCGaWRYGONLo3TIR0ToFtqC5LuyjGws6lRV",
    "UQAkIjD9O5IoQaAj6BV2haF5CQ5tqKW2TP0_JtrVQNvMlPnH"
]

# Updated USDT (BEP20) addresses
USDT_ADDRESSES = [
    "0xe8725d6a779fc008284f8df9e63173ce58d67366",
    "0x0dfd565d45e4c0b78f77ae81dbadfd759e03e1a7",
    "0x0e887c0e24a5347afb140abfd53aed254cdeca82",
    "0xe62977795248f8c1b775424381abfb25c986e094",
    "0x4c6ab1bc7a0de8dcf4698d2f49215ead34ea8485",
    "0x98a821294224c0e6a202ee9fad2c89e0cf097133",
    "0xe00e826fb0480d653b98024d3397f9306699df35",
    "0x0fa53f15289fe38907cc13ecc7f40f3c314d271",
    "0x3d28f6a7cbd499b018561780a422e60bab8508e8",
    "0xa09adc5ce6767e983542dd1624844a60fa0611f2"
]

user_deposit_data = {}

@dataclass
class Card:
    card_number: str
    currency: str
    amount: float
    sticker: StickerType = StickerType.NONE
    is_registered: bool = True
    is_out_of_stock: bool = False

    def display(self) -> str:
        sticker_str = f" {self.sticker.value}" if self.sticker != StickerType.NONE else ""
        return f"{self.card_number} {self.currency}${self.amount:.2f} at 33%{sticker_str}"

@dataclass
class UserData:
    user_id: int
    username: str
    first_name: str
    chat_id: int = 0
    ton_balance: float = 0.0
    usdt_balance: float = 0.0
    usd_balance: float = 0.0
    total_deposits_ton: float = 0.0
    total_deposits_usd: float = 0.0
    last_deposit: str = "Never"
    purchase_count: int = 0
    usd_spent: float = 0.0
    purchased_cards: List[str] = field(default_factory=list)
    referrals_count: int = 0
    referred_by: str = ""
    referral_link: str = ""
    pending_deposit: Optional[Dict] = None

class CardGenerator:
    def __init__(self):
        self.cards: List[Card] = []
        self._last_update_time = None
        self._is_updating = False

    def _generate_unique_number(self, existing_numbers: set) -> str:
        while True:
            bin_list = []
            for currency, bins in CARD_BINS.items():
                bin_list.extend(bins)
            selected_bin = random.choice(bin_list)
            random_suffix = ''.join(random.choices(string.digits, k=2))
            card_num = selected_bin.replace('xx', random_suffix)
            if card_num not in existing_numbers:
                return card_num

    def _get_max_amount_for_bin(self, card_number: str) -> float:
        bin_prefix = card_number[:6] + 'xx'
        if bin_prefix in CAD_BINS:
            return 150.0
        elif bin_prefix in AUD_BINS:
            return 50.0
        else:
            return 500.0

    def _get_sticker_for_amount(self, amount: float) -> StickerType:
        if amount >= 300:
            return StickerType.NONE
        rand = random.random()
        if rand < 0.65:
            return StickerType.NONE
        elif rand < 0.75:
            return StickerType.RELISTED
        elif rand < 0.83:
            return StickerType.GOOGLE
        elif rand < 0.87:
            return StickerType.PAYPAL
        else:
            return StickerType.GOOGLE

    def _get_currency_for_bin(self, card_number: str) -> str:
        bin_prefix = card_number[:6] + 'xx'
        for currency, bins in CARD_BINS.items():
            if bin_prefix in bins:
                return currency
        return "USD"

    def generate_cards(self) -> List[Card]:
        total_cards = random.randint(200, 250)
        cards = []
        existing_numbers = set()
        existing_pairs = set()
        low_amount_count = random.randint(15, 20)
        high_amount_count = random.randint(10, min(12, total_cards // 10))
        medium_amount_count = random.randint(20, 30)
        remaining = total_cards - (low_amount_count + high_amount_count + medium_amount_count)
        aud_count = 0
        max_aud_cards = 20

        for _ in range(low_amount_count):
            amount = round(random.uniform(0.01, 0.98), 2)
            while True:
                card_num = self._generate_unique_number(existing_numbers)
                if (card_num, amount) not in existing_pairs:
                    max_amt = self._get_max_amount_for_bin(card_num)
                    if amount <= max_amt:
                        break
            existing_numbers.add(card_num)
            existing_pairs.add((card_num, amount))
            currency = self._get_currency_for_bin(card_num)
            sticker = self._get_sticker_for_amount(amount)
            cards.append(Card(card_num, currency, amount, sticker))

        for _ in range(high_amount_count):
            amount = round(random.uniform(300, 500), 2)
            while True:
                card_num = self._generate_unique_number(existing_numbers)
                if (card_num, amount) not in existing_pairs:
                    max_amt = self._get_max_amount_for_bin(card_num)
                    if amount <= max_amt:
                        break
            existing_numbers.add(card_num)
            existing_pairs.add((card_num, amount))
            currency = self._get_currency_for_bin(card_num)
            cards.append(Card(card_num, currency, amount, StickerType.NONE))

        for _ in range(medium_amount_count):
            amount = round(random.uniform(5, 40), 2)
            while True:
                card_num = self._generate_unique_number(existing_numbers)
                if (card_num, amount) not in existing_pairs:
                    max_amt = self._get_max_amount_for_bin(card_num)
                    if amount <= max_amt:
                        if card_num[:6] + 'xx' in AUD_BINS:
                            if aud_count >= max_aud_cards:
                                continue
                        break
            existing_numbers.add(card_num)
            existing_pairs.add((card_num, amount))
            if card_num[:6] + 'xx' in AUD_BINS:
                aud_count += 1
            currency = self._get_currency_for_bin(card_num)
            sticker = self._get_sticker_for_amount(amount)
            cards.append(Card(card_num, currency, amount, sticker))

        for _ in range(remaining):
            amount = round(random.uniform(5, 40), 2)
            while True:
                card_num = self._generate_unique_number(existing_numbers)
                if (card_num, amount) not in existing_pairs:
                    max_amt = self._get_max_amount_for_bin(card_num)
                    if amount <= max_amt:
                        if card_num[:6] + 'xx' in AUD_BINS:
                            if aud_count >= max_aud_cards:
                                continue
                        break
            existing_numbers.add(card_num)
            existing_pairs.add((card_num, amount))
            if card_num[:6] + 'xx' in AUD_BINS:
                aud_count += 1
            currency = self._get_currency_for_bin(card_num)
            sticker = self._get_sticker_for_amount(amount)
            cards.append(Card(card_num, currency, amount, sticker))

        cards.sort(key=lambda x: x.amount, reverse=True)
        unregistered_count = int(len(cards) * 0.2)
        cards_by_amount_desc = sorted(cards, key=lambda x: x.amount, reverse=True)
        for i in range(unregistered_count):
            cards_by_amount_desc[len(cards_by_amount_desc) - 1 - i].is_registered = False
        return cards

    async def update_cards(self):
        self._is_updating = True
        self.cards = self.generate_cards()
        self._last_update_time = datetime.now()
        self._is_updating = False
        print(f"Cards generated: {len(self.cards)} cards")

    def mark_random_cards_out_of_stock(self, percentage: float = 1.0):
        available_cards = [c for c in self.cards if not c.is_out_of_stock]
        if not available_cards:
            return 0
        count = max(1, int(len(self.cards) * percentage / 100))
        count = min(count, len(available_cards))
        selected = random.sample(available_cards, count)
        for card in selected:
            card.is_out_of_stock = True
        print(f"Marked {count} cards as OUT OF STOCK ({percentage}%) (Total OUT OF STOCK: {len([c for c in self.cards if c.is_out_of_stock])})")
        return count

    def get_cards_paginated(self, page: int, per_page: int = 10, filter_type: str = None) -> Tuple[List[Card], int]:
        if not self.cards:
            return [], 0
        filtered_cards = self.cards.copy()
        if filter_type:
            if filter_type == "unregistered":
                filtered_cards = [c for c in filtered_cards if not c.is_registered]
            elif filter_type == "registered":
                filtered_cards = [c for c in filtered_cards if c.is_registered]
            elif filter_type in FILTER_BIN_MAP:
                allowed_bins = FILTER_BIN_MAP[filter_type]
                filtered_cards = [c for c in filtered_cards if any(c.card_number.startswith(bin_prefix.replace('xx', '')) for bin_prefix in allowed_bins)]
        total_pages = max(1, (len(filtered_cards) + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        return filtered_cards[start:end], total_pages

    def get_low_amount_cards_page(self, per_page: int = 10) -> Tuple[List[Card], int]:
        if not self.cards:
            return [], 0
        low_cards = [c for c in self.cards if c.amount < 0.99]
        total_pages = max(1, (len(low_cards) + per_page - 1) // per_page)
        return low_cards, total_pages


class UserManager:
    def __init__(self):
        self.users: Dict[int, UserData] = {}
        self.order_counter = 20990

    def get_or_create_user(self, update: Update) -> UserData:
        user = update.effective_user
        chat = update.effective_chat
        if user.id not in self.users:
            referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
            self.users[user.id] = UserData(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name,
                chat_id=chat.id if chat else 0,
                referral_link=referral_link
            )
        else:
            if chat and self.users[user.id].chat_id != chat.id:
                self.users[user.id].chat_id = chat.id
        return self.users[user.id]

    def get_next_order_number(self) -> int:
        self.order_counter += 1
        if self.order_counter > 1000060:
            self.order_counter = 20990
        return self.order_counter


class KeyboardBuilder:
    @staticmethod
    def get_main_menu_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("💳 Stock", callback_data="stock"),
                InlineKeyboardButton("📞 Contact Admin", url="https://t.me/cardsellr")
            ],
            [
                InlineKeyboardButton("👥 Profile", callback_data="profile"),
                InlineKeyboardButton("🔗 Refer", callback_data="refer")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_filters_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("🔐 Unregistered", callback_data="filter_unregistered"), InlineKeyboardButton("🔓 Registered", callback_data="filter_registered")],
            [InlineKeyboardButton("⚪ Vanilla", callback_data="filter_vanilla"), InlineKeyboardButton("💠 CardBalance", callback_data="filter_cardbalance")],
            [InlineKeyboardButton("☀️ Walmart", callback_data="filter_walmart"), InlineKeyboardButton("🛍️ GiftCardMall", callback_data="filter_giftcardmall")],
            [InlineKeyboardButton("🎭 Joker", callback_data="filter_joker"), InlineKeyboardButton("🟦 AMEX", callback_data="filter_amex")],
            [InlineKeyboardButton("🏠 Clear Filters", callback_data="clear_filters")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_deposit_choice_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("💵 USDT", callback_data="deposit_usdt")],
            [InlineKeyboardButton("🔷 GRAM", callback_data="deposit_ton")]
        ]
        return InlineKeyboardMarkup(keyboard)


card_generator = CardGenerator()
user_manager = UserManager()
keyboard_builder = KeyboardBuilder()


async def is_update_time() -> bool:
    now = datetime.now()
    return now.hour == 3 and now.minute < 10

async def delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    try:
        await context.bot.delete_message(chat_id=job_data['chat_id'], message_id=job_data['message_id'])
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")


# ---------- ADMIN BROADCAST ----------
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text
    sent = 0
    failed = 0
    for user_id, user_data in user_manager.users.items():
        if user_data.chat_id and user_data.chat_id != update.effective_chat.id:
            try:
                await context.bot.send_message(chat_id=user_data.chat_id, text=text)
                sent += 1
            except Exception as e:
                logger.error(f"Broadcast failed to {user_id}: {e}")
                failed += 1
    report = f"✅ Broadcast Done!\nSent: {sent}\nFailed: {failed}"
    await update.message.reply_text(report)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_or_create_user(update)
    if user.user_id != ADMIN_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    current = context.user_data.get('broadcast_mode', False)
    context.user_data['broadcast_mode'] = not current
    if context.user_data['broadcast_mode']:
        await update.message.reply_text("Broadcast mode ON ✅")
    else:
        await update.message.reply_text("Broadcast mode OFF ❌")


# ---------- COMMANDS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_or_create_user(update)
    welcome_text = (
        f"Welcome {user.first_name} to Vanila Exchange!\n\n"
        "Sell, Buy, and strike deals in seconds!!\n"
        "All transactions are secure and transparent.\n"
        "All types of cards are available here at best rates. Current rate is 33%"
    )
    await update.message.reply_text(welcome_text, reply_markup=keyboard_builder.get_main_menu_keyboard())

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_update_time():
        if update.callback_query:
            await update.callback_query.answer("The bot is currently updating, please wait", show_alert=True)
        else:
            await update.message.reply_text("The bot is currently updating, please wait")
        return
    if not card_generator.cards:
        await card_generator.update_cards()
    cards, total_pages = card_generator.get_cards_paginated(1)
    if not cards:
        await update.message.reply_text("No cards available at the moment. Please try again later.")
        return
    await send_listing_page(update, context, cards, 1, total_pages)

async def send_listing_page(update: Update, context: ContextTypes.DEFAULT_TYPE, cards: List[Card], page: int, total_pages: int, filter_type: str = None):
    if not cards:
        if update.callback_query:
            await update.callback_query.edit_message_text("No cards available at the moment.")
        else:
            await update.message.reply_text("No cards available at the moment.")
        return
    user = user_manager.get_or_create_user(update)
    message_text = "Vanila Exchange - Main Listings V2\n\n"
    message_text += "Your Balance:\n"
    message_text += f"💵 USDT: ${user.usdt_balance:.2f}\n"
    message_text += f"• GRAM : {user.ton_balance:.6f} (${user.ton_balance * 2:.2f})\n\n"

    for i, card in enumerate(cards, 1):
        message_text += f"{i}. {card.card_number} {card.currency}${card.amount:.2f} at 33%"
        if card.sticker != StickerType.NONE:
            message_text += f" {card.sticker.value}"
        message_text += "\n"

    total_balance = sum(c.amount for c in cards)
    message_text += f"\nTotal Cards: {len(cards)} | Total Cards Balance: ${total_balance:.2f}\n"
    message_text += "Legend:\n🔄 = Re-listed\n🅶 = Used on Google\n🅿 = Used on PayPal\n\n"
    message_text += f"Filters: {filter_type or 'None'} \n"
    message_text += f"Page: {page}/{total_pages} | Updated: {datetime.now().strftime('%H:%M:%S')}"

    keyboard = []
    for i, card in enumerate(cards, 1):
        if card.is_out_of_stock:
            purchase_text = "⚠️ OUT OF STOCK"
            callback_data = f"outofstock_{card.card_number}"
        else:
            purchase_text = "🛒Purchase"
            callback_data = f"purchase_{card.card_number}"
        keyboard.append([
            InlineKeyboardButton(f"{i}. {card.card_number[:6]}xx", callback_data=f"card_{card.card_number}"),
            InlineKeyboardButton(purchase_text, callback_data=callback_data)
        ])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("First↩️", callback_data=f"page_1_{filter_type or ''}"))
        nav_buttons.append(InlineKeyboardButton("Back⬅️", callback_data=f"page_{page-1}_{filter_type or ''}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next➡️", callback_data=f"page_{page+1}_{filter_type or ''}"))
        nav_buttons.append(InlineKeyboardButton("Last↪️", callback_data=f"page_{total_pages}_{filter_type or ''}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("💰 Deposit", callback_data="deposit"),
        InlineKeyboardButton("Refresh🔂", callback_data=f"refresh_{page}_{filter_type or ''}"),
        InlineKeyboardButton("🔍 Filters", callback_data="show_filters")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)


# ---------- Function to send stock listing as a NEW message (for callback) ----------
async def send_stock_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_update_time():
        await update.callback_query.answer("The bot is currently updating, please wait", show_alert=True)
        return
    if not card_generator.cards:
        await card_generator.update_cards()
    cards, total_pages = card_generator.get_cards_paginated(1)
    if not cards:
        await update.callback_query.message.reply_text("No cards available at the moment.")
        return
    user = user_manager.get_or_create_user(update)
    message_text = "Vanila Exchange - Main Listings V2\n\n"
    message_text += "Your Balance:\n"
    message_text += f"💵 USDT: ${user.usdt_balance:.2f}\n"
    message_text += f"• GRAM : {user.ton_balance:.6f} (${user.ton_balance * 2:.2f})\n\n"

    for i, card in enumerate(cards, 1):
        message_text += f"{i}. {card.card_number} {card.currency}${card.amount:.2f} at 33%"
        if card.sticker != StickerType.NONE:
            message_text += f" {card.sticker.value}"
        message_text += "\n"

    total_balance = sum(c.amount for c in cards)
    message_text += f"\nTotal Cards: {len(cards)} | Total Cards Balance: ${total_balance:.2f}\n"
    message_text += "Legend:\n🔄 = Re-listed\n🅶 = Used on Google\n🅿 = Used on PayPal\n\n"
    message_text += f"Filters: None \n"
    message_text += f"Page: 1/{total_pages} | Updated: {datetime.now().strftime('%H:%M:%S')}"

    keyboard = []
    for i, card in enumerate(cards, 1):
        if card.is_out_of_stock:
            purchase_text = "⚠️ OUT OF STOCK"
            callback_data = f"outofstock_{card.card_number}"
        else:
            purchase_text = "🛒Purchase"
            callback_data = f"purchase_{card.card_number}"
        keyboard.append([
            InlineKeyboardButton(f"{i}. {card.card_number[:6]}xx", callback_data=f"card_{card.card_number}"),
            InlineKeyboardButton(purchase_text, callback_data=callback_data)
        ])

    nav_buttons = []
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton("Next➡️", callback_data=f"page_2_"))
        nav_buttons.append(InlineKeyboardButton("Last↪️", callback_data=f"page_{total_pages}_"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("💰 Deposit", callback_data="deposit"),
        InlineKeyboardButton("Refresh🔂", callback_data="refresh_1_"),
        InlineKeyboardButton("🔍 Filters", callback_data="show_filters")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text(message_text, reply_markup=reply_markup)


# ---------- DEPOSIT FLOW ----------
async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🏦 Vanila Exchange Deposit\n\nChoose your deposit amount and the coin type:\nUSDT | GRAM | More being added soon",
            reply_markup=keyboard_builder.get_deposit_choice_keyboard()
        )
    else:
        await update.message.reply_text(
            "🏦 Vanila Exchange Deposit\n\nChoose your deposit amount and the coin type:\nUSDT | GRAM | More being added soon",
            reply_markup=keyboard_builder.get_deposit_choice_keyboard()
        )

async def deposit_coin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    coin = query.data.split("_")[1]
    context.user_data['deposit_coin'] = coin.upper()
    context.user_data['awaiting_deposit_amount'] = True
    display_coin = "GRAM" if coin.upper() == "TON" else coin.upper()
    await query.edit_message_text(f"Enter your amount in {display_coin}:")

async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_deposit_amount'):
        return
    try:
        amount = float(update.message.text.strip())
        coin = context.user_data.get('deposit_coin', 'TON')
        display_coin = "GRAM" if coin == "TON" else coin
        min_amount = 10.0
        if amount < min_amount:
            await update.message.reply_text(f"Minimum deposit {min_amount} {display_coin}. Please enter a valid amount.")
            return

        order_number = str(random.randint(10000000, 99999999))
        user = user_manager.get_or_create_user(update)
        user_id = user.user_id
        user_name = user.first_name

        if coin == "TON":
            addresses = TON_ADDRESSES
            network = "TON Network"
            currency = "GRAM"
        else:
            addresses = USDT_ADDRESSES
            network = "USDT-BSC(BEP20)"
            currency = "USDT"

        selected_address = random.choice(addresses)
        valid_until = datetime.now() + timedelta(hours=1)
        valid_until_str = valid_until.strftime("%Y-%m-%d %H:%M:%S")

        qr = qrcode.make(selected_address)
        qr_bytes = BytesIO()
        qr.save(qr_bytes, format='PNG')
        qr_bytes.seek(0)

        invoice_caption = (
            f"Here are the details:\n"
            f"Send crypto to the address shown below:\n\n"
            f"📸 Scan the QR code or copy the address to proceed with payment.\n\n"
            f"🌐 NETWORK: {network} ✅\n"
            f"💎 Currency : {currency}\n\n"
            f"🏦 Address: `{selected_address}`\n"
            f"💸 Deposit Amount: `{amount:.2f}` {currency}\n"
            f"Charge ID: `{user_id}`\n"
            f"Valid till: `{valid_until_str}`\n"
            f"More details:\n"
            f"Payment ID: `{user_id}`\n"
            f"Order number: `{order_number}`\n\n"
            f"1. Make sure you deposit the exact value to get the funds. If the value is lower than the invoice value, your funds may not be deposited.\n"
            f"Any issue, contact @cardsellr with your charge ID.\n"
            f"2. Do not deposit two times to this same address. Only deposit once.\n"
            f"3. Deposit to this address within 1 hour. After 1 hour this address is not valid anymore. You will need to create a new deposit by typing /deposit.\n"
            f"4. If you sent money and are waiting for confirmations, do not create another invoice. Wait for the money to get confirmed.\n"
            f"5. Your balance will be automatically credited to your account within 2 minutes of your deposit."
        )

        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("✆ Contact", url="https://t.me/cardsellr")]])

        sent_invoice = await update.message.reply_photo(
            photo=qr_bytes,
            caption=invoice_caption,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        waiting_msg = await update.message.reply_text("🕓 Waiting for payment confirmation.....")
        context.user_data['awaiting_deposit_amount'] = False
        context.user_data.pop('deposit_coin', None)

        job_queue = context.application.job_queue
        if job_queue:
            job_queue.run_once(
                send_deposit_failure,
                when=3660,
                data={
                    'chat_id': update.effective_chat.id,
                    'user_id': user_id,
                    'user_name': user_name,
                    'order_number': order_number
                },
                name=f"deposit_failure_{user_id}"
            )
            job_queue.run_once(
                delete_message_job,
                when=3720,
                data={'chat_id': sent_invoice.chat_id, 'message_id': sent_invoice.message_id},
                name=f"deposit_delete_invoice_{user_id}"
            )
            job_queue.run_once(
                delete_message_job,
                when=3600,
                data={'chat_id': update.effective_chat.id, 'message_id': waiting_msg.message_id},
                name=f"deposit_delete_waiting_{user_id}"
            )
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

async def send_deposit_failure(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    failure_text = (
        f"NAME: {job_data['user_name']}\n"
        f"ID: `{job_data['user_id']}`\n"
        f"Order ID: `{job_data['order_number']}`\n"
        f"Status: Failed ⚠️"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✆ Contract", url="https://t.me/cardsellr")]])
    await context.bot.send_message(chat_id=job_data['chat_id'], text=failure_text, parse_mode='Markdown', reply_markup=keyboard)


# ---------- BALANCE, WITHDRAW, PROFILE ----------
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_or_create_user(update)
    text = (
        f"Name : {user.first_name}\n"
        f"ID : {user.user_id}\n"
        f"Your balance USDT : {user.usdt_balance:.4f}\n"
        f"Your balance GRAM : {user.ton_balance:.4f}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Balance", callback_data="deposit"),
         InlineKeyboardButton("📥 Withdraw", callback_data="withdraw")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_or_create_user(update)
    text = (
        f"Name : {user.first_name}\n"
        f"ID : {user.user_id}\n"
        f"Your balance USDT : {user.usdt_balance:.4f}\n"
        f"Your balance GRAM : {user.ton_balance:.4f}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Balance", callback_data="deposit"),
         InlineKeyboardButton("💰 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("✅ Confirm", callback_data="withdraw_confirm")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

async def withdraw_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = await query.message.reply_text("⚙️⏳ Checking USDT Balance")
    await asyncio.sleep(1)
    await msg.edit_text("⚙️⏳ Checking GRAM Balance")
    await asyncio.sleep(1)
    await msg.edit_text("Sorry, insufficient balance. Please /deposit first.")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_or_create_user(update)
    last_cards_text = '\n  '.join(['• No cards purchased yet.'] if not user.purchased_cards else [f'• {c}' for c in user.purchased_cards[-3:]])
    profile_text = (
        f"Vanila Exchange PROFILE\n\n"
        f"👤 {user.first_name}\n"
        f"🧠 It is impossible to love and to be wise.\n"
        f"💬 By: Francis Bacon\n\n"
        f"🆔 User ID: {user.user_id}\n"
        f"🔹 Username: @{user.username}\n"
        f"💰 GRAM Balance: {user.ton_balance:.10f}\n"
        f"💵 USDT Balance: ${user.usdt_balance:.2f}\n\n"
        f"📥 Deposits\n"
        f"• Total GRAM: {user.total_deposits_ton:.4f} Gram\n"
        f"• Total USDT: ${user.total_deposits_usd:.2f}\n"
        f"• Last: {user.last_deposit}\n\n"
        f"🛒 Purchases\n"
        f"• Count: {user.purchase_count}\n"
        f"• USD Spent: ${user.usd_spent:.2f}\n"
        f"• Last Cards:\n  {last_cards_text}\n\n"
        f"👥 Referrals\n"
        f"• Invited: {user.referrals_count}\n"
        f"• Referred By: {user.referral_link}\n\n"
        f"🛠 Permissions\n"
        f"• Vendor: ❌\n"
        f"• Re-list: ❌\n\n"
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(profile_text)

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_or_create_user(update)
    if not user.referral_link or BOT_USERNAME not in user.referral_link:
        user.referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.user_id}"
    text = (
        f"🎉 REFERRAL PROGRAM\n\n"
        f"Invite friends and earn 5% every deposit each active referral!\n\n"
        f"🔗 Your unique link: {user.referral_link}\n\n"
        f"📊 Stats\n"
        f"• Total referrals: {user.referrals_count}\n"
        f"• Earned: $0.00\n\n"
        f"❗ Rules\n"
        f"- Bonus awarded when referral completes first transaction\n"
        f"- No self-referrals\n"
        f"- Fraudulent referrals will be banned"
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("If you need help, please contact @cardsellr")

async def refund_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = (
        "⚡️⚡️⚡️ VERY IMPORTANT ⚡️⚡️⚡️\n"
        "💳 Vanila Exchange – Refund Policy 💳\n\n"
        "✅✅✅ CARD REFUND REQUIREMENTS ✅✅✅\n"
        "1️⃣ Refund requests must be submitted within 25 minutes of purchase.\n"
        "2️⃣ Refunds are accepted ONLY if the card is stolen or partially used.\n"
        "3️⃣ You must have a valid Telegram username set.\n\n"
        "💬 Official Refund Support: https://t.me/cardsellr\n\n"
        "❌❌❌ AUTOMATIC REFUND REJECTIONS ❌❌❌\n"
        "🚫 No refund for ReListed cards\n"
        "🚫 No refund for cards used with Google / Google Pay\n"
        "🚫 No Telegram username = Auto rejection\n\n"
        "⚠️ IMPORTANT NOTICE: All cards are checked immediately before delivery\n"
        "📩 Need help? Contact support: https://t.me/cardsellr"
    )
    await update.message.reply_text(rules)

async def cents_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_update_time():
        await update.message.reply_text("The bot is currently updating, please wait")
        return
    if not card_generator.cards:
        await card_generator.update_cards()
    cards, total_pages = card_generator.get_low_amount_cards_page()
    await send_listing_page(update, context, cards, 1, total_pages, "Low Amount (<$0.99)")

async def scheduled_update(context: ContextTypes.DEFAULT_TYPE):
    await card_generator.update_cards()

# প্রতি ১ ঘণ্টায় ১% কার্ড আউট-অফ-স্টক হবে (পুরনো ৩% সরিয়ে ১% করা হয়েছে)
async def auto_mark_out_of_stock(context: ContextTypes.DEFAULT_TYPE):
    if not card_generator.cards:
        return
    count = card_generator.mark_random_cards_out_of_stock(1.0)  # 1% each hour
    if count and count > 0:
        print(f"Auto OUT OF STOCK: {count} cards marked (1%) at {datetime.now()}")


# ---------- MAIN CALLBACK HANDLER ----------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("purchase_"):
        card_number = data.split("_", 1)[1]
        target_card = None
        for card in card_generator.cards:
            if card.card_number == card_number:
                target_card = card
                break
        if not target_card:
            await query.answer("Card not found.", show_alert=True)
            return

        if target_card.currency == "CAD":
            total_cost_usd = target_card.amount * 0.33 * CAD_TO_USD_RATE
        elif target_card.currency == "AUD":
            total_cost_usd = target_card.amount * 0.33 * AUD_TO_USD_RATE
        else:
            total_cost_usd = target_card.amount * 0.33

        info_text = (
            "❗Vanilla cards prepaid - Listing Information\n\n"
            f"Card information: {target_card.card_number[:6]}xx\n"
            f"Purchase Rate: 33%\n"
            f"Balance: {target_card.currency}${target_card.amount:.2f}\n"
            f"Total Cost: USD${total_cost_usd:.2f}\n"
            f"Registration Status: {'Registered' if target_card.is_registered else 'Unregistered'}\n"
            "Card Status: Fresh\n"
            "Click Confirm to proceed with purchase"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{card_number}"),
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{card_number}")
            ]
        ])
        await query.answer()
        await query.message.reply_text(info_text, reply_markup=keyboard)
        return

    if data.startswith("cancel_"):
        await query.answer()
        await query.edit_message_text("❌ Purchase cancelled.")
        return

    if data.startswith("confirm_"):
        await query.answer()
        await query.edit_message_text("🔄 Your purchase is being prepared...")
        await asyncio.sleep(1)
        await query.edit_message_text("💰 Verifying your balance...")
        await asyncio.sleep(1)
        await query.edit_message_text(
            "❌ Insufficient balance. Please deposit funds and try again. OR Please contact with Admin: @cardsellr"
        )
        return

    if data.startswith("outofstock_"):
        await query.answer("Sorry, the card is out of stock ⚠", show_alert=True)
        return

    await query.answer()

    if await is_update_time():
        await query.edit_message_text("The bot is currently updating, please wait")
        return

    if data == "stock":
        await send_stock_reply(update, context)
    elif data == "profile":
        await profile_command(update, context)
    elif data == "refer":
        await ref_command(update, context)
    elif data == "deposit":
        await deposit_command(update, context)
    elif data == "withdraw":
        await withdraw_command(update, context)
    elif data == "withdraw_confirm":
        await withdraw_confirm_callback(update, context)
    elif data in ("deposit_ton", "deposit_usdt"):
        await deposit_coin_selected(update, context)
    elif data.startswith("card_"):
        card_num = data.replace("card_", "")
        await query.answer(f"✅ Copied: {card_num}", show_alert=False)
    elif data.startswith("page_"):
        parts = data.split("_")
        page = int(parts[1])
        filter_type = parts[2] if len(parts) > 2 and parts[2] else None
        cards, total_pages = card_generator.get_cards_paginated(page, filter_type=filter_type if filter_type else None)
        await send_listing_page(update, context, cards, page, total_pages, filter_type)
    elif data.startswith("refresh_"):
        parts = data.split("_")
        page = int(parts[1])
        filter_type = parts[2] if len(parts) > 2 and parts[2] else None
        cards, total_pages = card_generator.get_cards_paginated(page, filter_type=filter_type if filter_type else None)
        await send_listing_page(update, context, cards, page, total_pages, filter_type)
    elif data == "show_filters":
        await query.edit_message_reply_markup(reply_markup=keyboard_builder.get_filters_keyboard())
    elif data.startswith("filter_"):
        filter_type = data.replace("filter_", "")
        cards, total_pages = card_generator.get_cards_paginated(1, filter_type=filter_type)
        await send_listing_page(update, context, cards, 1, total_pages, filter_type)
    elif data == "clear_filters":
        cards, total_pages = card_generator.get_cards_paginated(1)
        await send_listing_page(update, context, cards, 1, total_pages)


# ---------- GENERAL MESSAGE HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_deposit_amount'):
        await handle_deposit_amount(update, context)
        return
    user = user_manager.get_or_create_user(update)
    if user.user_id == ADMIN_ID and context.user_data.get('broadcast_mode', False):
        await admin_broadcast(update, context)
        return
    await update.message.reply_text("Use /help for assistance.")


async def main():
    print("Starting bot...")
    await card_generator.update_cards()
    print(f"Bot started with {len(card_generator.cards)} cards")

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("listings", stock_command))
    application.add_handler(CommandHandler("cents_listing", cents_listing))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("withdraw", withdraw_command))
    application.add_handler(CommandHandler("deposit", deposit_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("refund_rules", refund_rules_command))
    application.add_handler(CommandHandler("ref", ref_command))
    application.add_handler(CommandHandler("admin", admin_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    if application.job_queue:
        # প্রতি ১ ঘণ্টায় ১% কার্ড আউট-অফ-স্টক হবে (৩৬০০ সেকেন্ড)
        application.job_queue.run_repeating(auto_mark_out_of_stock, interval=3600, first=3600)
        print("Auto OUT OF STOCK scheduled every 1 hour (1% each time)")
        # রাত ৩টায় কার্ড রিফ্রেশ (পূর্বের মতো)
        application.job_queue.run_daily(scheduled_update, time=time(hour=3, minute=0, second=0))

    print("Starting polling...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    while True:
        await asyncio.sleep(3600)

def start_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
