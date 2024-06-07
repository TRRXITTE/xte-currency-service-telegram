from cryptography.fernet import Fernet

# Generate a key
encryption_key = Fernet.generate_key()

# Print the key
print(encryption_key.decode())
