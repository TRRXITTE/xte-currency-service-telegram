import logging
import requests
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Constants
DATABASE_URL = os.getenv('DATABASE_URL')
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

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
    username = Column(String, unique=True, nullable=False)
    wallet = relationship("Wallet", uselist=False, back_populates="user")

class Wallet(Base):
    __tablename__ = 'wallets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    address = Column(String, nullable=False)
    encrypted_private_spend_key = Column(String, nullable=False)
    public_spend_key = Column(String, nullable=False)
    user = relationship("User", back_populates="wallet")

# Create engine and session
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Helper function to create wallet
def create_wallet():
    headers = {'X-API-KEY': XTE_API_RPC_PASSWORD}
    response = requests.post('http://localhost:8441/addresses/create', headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception('Failed to create wallet')

def create_wallet_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    existing_user = session.query(User).filter_by(telegram_id=user_id).first()

    if existing_user:
        update.message.reply_text('You already have a wallet. Address: {}'.format(existing_user.wallet_address))
        return

    try:
        # Create wallet
        wallet_data = create_wallet()
        wallet_address = wallet_data['address']
        encrypted_spend_key = fernet.encrypt(wallet_data['privateSpendKey'].encode()).decode()  # Use privateSpendKey for encryption

        new_user = User(telegram_id=user_id, wallet_address=wallet_address, encrypted_spend_key=encrypted_spend_key)
        session.add(new_user)
        session.commit()

        # Prepare response message
        response_message = 'Your new wallet has been created. Address: {}\n'.format(wallet_address)
        response_message += 'Private Spend Key: {}\n'.format(wallet_data['privateSpendKey'])
        response_message += 'Public Spend Key: {}'.format(wallet_data['publicSpendKey'])

        update.message.reply_text(response_message)
    except Exception as e:
        logger.error("Error creating wallet or address: {}".format(e))
        update.message.reply_text('Error creating your wallet or address. Please try again.')



def export_keys_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()

    if not user:
        update.message.reply_text('You do not have a wallet. Use /createwallet to create one.')
        return

    # Check if the message is from a direct chat
    if update.message.chat.type == 'private':
        decrypted_spend_key = fernet.decrypt(user.encrypted_spend_key.encode()).decode()
        update.message.reply_text('Your private spend key: {}\nYour public spend key: {}'.format(decrypted_spend_key, user.wallet_address))
    else:
        update.message.reply_text('You can only export keys in a direct chat.')



# Helper functions
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


def autosave():
    global wallet_opened
    if wallet_opened:
        # Save the opened wallet
        print("Autosaving the opened wallet...")
        # Your saving logic goes here
        # For example: save_wallet()
    # Schedule the next autosave after 1 minute
    Timer(60, autosave).start()

def close_and_save_wallet(update: Update, context: CallbackContext) -> None:
    global wallet_opened
    if wallet_opened:
        # Close and save the opened wallet
        print("Closing and saving the opened wallet...")
        # Your closing and saving logic goes here
        # For example: close_and_save_wallet()
        wallet_opened = False
        update.message.reply_text('Wallet closed and saved successfully.')
    else:
        update.message.reply_text('No wallet is currently opened.')

def main() -> None:
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("createwallet", create_wallet_command))
    dispatcher.add_handler(CommandHandler("balance", balance_command))
    dispatcher.add_handler(CommandHandler("tip", tip_command, pass_args=True))
    dispatcher.add_handler(CommandHandler("history", history_command))
    dispatcher.add_handler(CommandHandler("exportkeys", export_keys_command))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
