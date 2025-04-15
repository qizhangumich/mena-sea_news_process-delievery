import base64
import json
import os
from pathlib import Path

def encode_firebase_credentials():
    """Encode Firebase credentials file to base64."""
    # Find the Firebase credentials file
    cred_files = list(Path('.').glob('*-firebase-adminsdk-*.json'))
    if not cred_files:
        print("Error: No Firebase credentials file found.")
        print("Please make sure the file exists and matches the pattern: *-firebase-adminsdk-*.json")
        return None
    
    cred_file = cred_files[0]
    try:
        with open(cred_file, 'rb') as f:
            content = f.read()
            return base64.b64encode(content).decode('utf-8')
    except Exception as e:
        print(f"Error reading Firebase credentials: {e}")
        return None

def check_env_file():
    """Check if .env file exists and has all required variables."""
    required_vars = [
        'OPENAI_API_KEY',
        'SMTP_USERNAME',
        'SMTP_PASSWORD',
        'EMAIL_FROM',
        'EMAIL_RECIPIENTS'
    ]
    
    if not os.path.exists('.env'):
        print("Error: .env file not found.")
        print("Please create a .env file with the following variables:")
        for var in required_vars:
            print(f"{var}=")
        return False
    
    missing_vars = []
    with open('.env', 'r') as f:
        content = f.read()
        for var in required_vars:
            if f"{var}=" not in content:
                missing_vars.append(var)
    
    if missing_vars:
        print("Error: The following variables are missing in .env:")
        for var in missing_vars:
            print(f"- {var}")
        return False
    
    return True

def main():
    print("=== GitHub Secrets Setup Helper ===")
    print("\n1. Checking .env file...")
    if not check_env_file():
        return
    
    print("\n2. Encoding Firebase credentials...")
    firebase_creds = encode_firebase_credentials()
    if not firebase_creds:
        return
    
    print("\n3. Instructions for setting up GitHub Secrets:")
    print("\nGo to your repository settings → Secrets and variables → Actions")
    print("Add the following secrets:")
    print("\nRequired Secrets:")
    print("1. OPENAI_API_KEY: Your OpenAI API key")
    print("2. GOOGLE_APPLICATION_CREDENTIALS: (Base64 encoded Firebase credentials)")
    print("3. SMTP_USERNAME: Your SMTP2Go username")
    print("4. SMTP_PASSWORD: Your SMTP2Go password")
    print("5. EMAIL_FROM: Sender email address")
    print("6. EMAIL_RECIPIENTS: Comma-separated list of recipient email addresses")
    
    print("\nThe Firebase credentials have been encoded to base64.")
    print("Copy the following value for the GOOGLE_APPLICATION_CREDENTIALS secret:")
    print("\n" + firebase_creds)

if __name__ == "__main__":
    main() 