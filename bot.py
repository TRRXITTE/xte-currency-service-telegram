import os
import logging
import requests
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from cryptography.fernet import Fernet
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, CallbackContext
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
XTE_API_BASE_URL = os.getenv('XTE_API_BASE_URL')
DATABASE_URL = os.getenv('DATABASE_URL')
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
XTE_API_RPC_PASSWORD = os.getenv('XTE_API_RPC_PASSWORD')

# Set up encryption
fernet = Fernet(ENCRYPTION_KEY.encode())

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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
    user = relationship("User")

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Helper functions
def create_wallet():
    headers = {'Authorization': 'Basic {}'.format(XTE_API_RPC_PASSWORD)}
    response = requests.post("{}/wallet/create".format(XTE_API_BASE_URL), headers=headers)
    response.raise_for_status()
    return response.json()

def get_balance(wallet_address):
    headers = {'Authorization': 'Basic {}'.format(XTE_API_RPC_PASSWORD)}
    response = requests.get("{}/balance/{}".format(XTE_API_BASE_URL, wallet_address), headers=headers)
    response.raise_for_status()
    return response.json()

def send_transaction(sender_spend_key, recipient_address, amount):
    headers = {'Authorization': 'Basic {}'.format(XTE_API_RPC_PASSWORD)}
    payload = {
        'destinations': [
            {
                'address': recipient_address,
                'amount': amount
            }
        ],
        'spendKey': sender_spend_key
    }
    response = requests.post("{}/transactions/send/basic".format(XTE_API_BASE_URL), json=payload, headers=headers)
    response.raise_for_status()
    return response.json()

def validate_address(address):
    headers = {'Authorization': 'Basic {}'.format(XTE_API_RPC_PASSWORD)}
    payload = {'address': address}
    response = requests.post("{}/addresses/validate".format(XTE_API_BASE_URL), json=payload, headers=headers)
    return response.status_code == 200

# Command handlers
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    update.message.reply_html(
        'Hi {}! I am your XTE tip bot. Use /createwallet to get started.'.format(user.mention_html())
    )

def create_wallet_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    existing_user = session.query(User).filter_by(telegram_id=user_id).first()

    if existing_user:
        update.message.reply_text('You already have a wallet. Address: {}'.format(existing_user.wallet_address))
        return

    try:
        wallet = create_wallet()
        wallet_address = wallet['address']
        encrypted_spend_key = fernet.encrypt(wallet['spendKey'].encode()).decode()

        new_user = User(telegram_id=user_id, wallet_address=wallet_address, encrypted_spend_key=encrypted_spend_key)
        session.add(new_user)
        session.commit()

        update.message.reply_text('Your new wallet has been created. Address: {}'.format(wallet_address))
    except Exception as e:
        logger.error("Error creating wallet: {}".format(e))
        update.message.reply_text('Error creating your wallet. Please try again.')

def balance_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()

    if not user:
        update.message.reply_text('You do not have a wallet. Use /createwallet to create one.')
        return

    try:
        balance = get_balance(user.wallet_address)
        update.message.reply_text('Your wallet balance is: {} XTE'.format(balance["available_balance"]))
    except Exception as e:
        logger.error("Error fetching balance: {}".format(e))
        update.message.reply_text('Error fetching balance. Please try again.')

def tip_command(update: Update, context: CallbackContext) -> None:
    args = context.args
    if len(args) != 2:
        update.message.reply_text('Usage: /tip <amount> <recipient_username>')
        return

    try:
        amount = float(args[0])
        recipient_username = args[1]
    except ValueError:
        update.message.reply_text('Invalid amount.')
        return

    sender_user_id = update.message.from_user.id
    sender = session.query(User).filter_by(telegram_id=sender_user_id).first()

    if not sender:
        update.message.reply_text('You do not have a wallet. Use /createwallet to create one.')
        return

    recipient = session.query(User).filter(User.telegram_id == recipient_username).first()

    if not recipient:
        update.message.reply_text('Recipient user not found.')
        return

    if not validate_address(recipient.wallet_address):
        update.message.reply_text('Recipient wallet address is invalid.')
        return

    sender_spend_key = fernet.decrypt(sender.encrypted_spend_key.encode()).decode()

    try:
        transaction_response = send_transaction(sender_spend_key, recipient.wallet_address, amount)
        if transaction_response['status'] == 'success':
            new_transaction = Transaction(user_id=sender.id, amount=amount, recipient_address=recipient.wallet_address, status='completed')
            session.add(new_transaction)
            session.commit()
            update.message.reply_text('Successfully tipped {} XTE to {}'.format(amount, recipient_username))
        else:
            update.message.reply_text('Failed to send the tip. Please try again.')
    except Exception as e:
        logger.error("Error sending tip: {}".format(e))
        update.message.reply_text('Error sending tip. Please try again.')

def history_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()

    if not user:
        update.message.reply_text('You do not have a wallet. Use /createwallet to create one.')
        return

    transactions = session.query(Transaction).filter_by(user_id=user.id).all()
    if not transactions:
        update.message.reply_text('No transaction history found.')
        return

    message = 'Transaction History:\n'
    for tx in transactions:
        message += "Amount: {} XTE, Recipient: {}, Status: {}\n".format(tx.amount, tx.recipient_address, tx.status)
    update.message.reply_text(message)

def main() -> None:
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("createwallet", create_wallet_command))
    dispatcher.add_handler(CommandHandler("balance", balance_command))
    dispatcher.add_handler(CommandHandler("tip", tip_command, pass_args=True))
    dispatcher.add_handler(CommandHandler("history", history_command))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
