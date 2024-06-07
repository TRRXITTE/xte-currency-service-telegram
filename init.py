import os
import requests

# Constants
XTE_API_BASE_URL = os.getenv('XTE_API_BASE_URL')
XTE_API_RPC_PASSWORD = os.getenv('XTE_API_RPC_PASSWORD')
WALLET_INIT_FILE = 'wallet_init.json'

def create_wallet_init_file():
    # Check if the initialization file already exists
    if os.path.exists(WALLET_INIT_FILE):
        print("Initialization file already exists.")
        return

    # Create payload
    payload = {
        "daemonHost": "127.0.0.1",
        "daemonPort": 14485,
        "filename": "mywallet.wallet",
        "password": "supersecretpassword"
    }

    # Set headers
    headers = {'X-API-KEY': XTE_API_RPC_PASSWORD}

    try:
        # Send POST request to create wallet
        response = requests.post(f"{XTE_API_BASE_URL}/wallet/create", json=payload, headers=headers)
        response.raise_for_status()
        wallet_data = response.json()

        # Write wallet data to initialization file
        with open(WALLET_INIT_FILE, 'w') as file:
            file.write(json.dumps(wallet_data))
        
        print("Initialization file created successfully.")
    except Exception as e:
        print(f"Error creating initialization file: {e}")

if __name__ == "__main__":
    create_wallet_init_file()
