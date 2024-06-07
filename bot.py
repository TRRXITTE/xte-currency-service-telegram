import os
import logging
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.exc import IntegrityError
from cryptography.fernet import Fernet
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Constants
TELEGRAM_BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
XTE_API_BASE_URL = 'http://your-xte-wallet-api-url'
DATABASE_URL = 'sqlite:///tip_bot.db'
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', Fernet.generate_key().decode())

# Set up encryption
fernet = Fernet(ENCRYPTION_KEY.encode())

# Set up database
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    wallet_address = Column(String, nullable=False)
    encrypted_spend_key = Column(String, nullable=False)

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    recipient_address = Column(String, nullable=False)
    status = Column(String, default='pending')

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Helper functions
def create_wallet():
    response = requests.post(f"{XTE_API_BASE_URL}/wallet/create")
    return response.json()

def get_balance(wallet_address):
    response = requests.get(f"{XTE_API_BASE_URL}/balance/{wallet_address}")
    return response.json()

def send_transaction(sender_spend_key, recipient_address, amount):
    payload = {
        'destinations': [
            {
                'address': recipient_address,
                'amount': amount
            }
        ],
        'spendKey': sender_spend_key
    }
    response = requests.post(f"{XTE_API_BASE_URL}/transactions/send/basic", json=payload)
    return response.json()

# Command handlers
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    update.message.reply_html(
        rf'Hi {user.mention_html()}! I am your XTE tip bot. Use /createwallet to get started.'
    )

def create_wallet_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    existing_user = session.query(User).filter_by(telegram_id=user_id).first()

    if existing_user:
        update.message.reply_text(f'You already have a wallet. Address: {existing_user.wallet_address}')
        return

    wallet = create_wallet()
    wallet_address = wallet['address']
    encrypted_spend_key = fernet.encrypt(wallet['spendKey'].encode()).decode()

    new_user = User(telegram_id=user_id, wallet_address=wallet_address, encrypted_spend_key=encrypted_spend_key)
    session.add(new_user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        update.message.reply_text('Error creating your wallet. Please try again.')
        return

    update.message.reply_text(f'Your new wallet has been created. Address: {wallet_address}')

def balance_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()

    if not user:
        update.message.reply_text('You do not have a wallet. Use /createwallet to create one.')
        return

    balance = get_balance(user.wallet_address)
    update.message.reply_text(f'Your wallet balance is: {balance["available_balance"]} XTE')

def tip_command(update: Update, context: CallbackContext) -> None:
    args = context.args
    if len(args) != 2:
        update.message.reply_text('Usage: /tip <amount> <recipient_username>')
        return

    amount = float(args[0])
    recipient_username = args[1]

    sender_user_id = update.message.from_user.id
    sender = session.query(User).filter_by(telegram_id=sender_user_id).first()

    if not sender:
        update.message.reply_text('You do not have a wallet. Use /createwallet to create one.')
        return

    recipient_user = session.query(User).filter(User.telegram_id == recipient_username).first()

    if not recipient_user:
        update.message.reply_text('Recipient user not found.')
        return

    sender_spend_key = fernet.decrypt(sender.encrypted_spend_key.encode()).decode()

    transaction_response = send_transaction(sender_spend_key, recipient_user.wallet_address, amount)

    if transaction_response['status'] == 'success':
        new_transaction = Transaction(user_id=sender.id, amount=amount, recipient_address=recipient_user.wallet_address, status='completed')
        session.add(new_transaction)
        session.commit()
        update.message.reply_text(f'Successfully tipped {amount} XTE to {recipient_username}')
    else:
        update.message.reply_text('Failed to send the tip. Please try again.')

def main() -> None:
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("createwallet", create_wallet_command))
    dispatcher.add_handler(CommandHandler("balance", balance_command))
    dispatcher.add_handler(CommandHandler("tip", tip_command, pass_args=True))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
