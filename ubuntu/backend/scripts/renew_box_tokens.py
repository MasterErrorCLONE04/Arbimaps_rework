import os
import sys
import json
from dotenv import load_dotenv
from boxsdk import OAuth2

# Load environment variables from the root .env file
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env"))
load_dotenv(dotenv_path)

client_id = os.getenv("BOX_CLIENT_ID")
client_secret = os.getenv("BOX_CLIENT_SECRET")
tokens_file = os.getenv("BOX_TOKENS_FILE", "tokens/box_oauth_tokens.json")

# Ensure tokens_file path is absolute (relative to backend directory)
if not os.path.isabs(tokens_file):
    tokens_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../", tokens_file))

print("====================================================")
print("             BOX OAUTH TOKEN RENEWAL UTILITY        ")
print("====================================================")

if not client_id or not client_secret:
    print(f"❌ Error: BOX_CLIENT_ID or BOX_CLIENT_SECRET is not set in your .env file.")
    print(f"Path checked: {dotenv_path}")
    sys.exit(1)

print(f"🔹 Client ID: {client_id}")
print(f"🔹 Target Tokens File: {tokens_file}")

# Note: The Redirect URI must match what is configured in your Box App Console under 'OAuth 2.0 Redirect URI'
# Usually, a default of http://localhost is excellent for local token generation.
redirect_uri = "http://localhost"

oauth = OAuth2(
    client_id=client_id,
    client_secret=client_secret,
)

auth_url, csrf_token = oauth.get_authorization_url(redirect_uri)

print("\n👉 STEP 1: Open the following URL in your web browser and authorize the app:")
print("-" * 80)
print(auth_url)
print("-" * 80)

print("\n👉 STEP 2: After logging in and clicking 'Grant access to Box', you will be redirected.")
print("The browser will attempt to load a page at your redirect URI (e.g. http://localhost/?state=...&code=XYZ).")
print("Copy the value of the 'code' parameter from the URL in your browser's address bar.")

try:
    auth_code = input("\nEnter the authorization code (the value of 'code='): ").strip()
except KeyboardInterrupt:
    print("\n\nOperation cancelled.")
    sys.exit(0)

if not auth_code:
    print("❌ Error: Authorization code cannot be empty.")
    sys.exit(1)

try:
    print("\n🔄 Contacting Box to exchange authorization code for fresh tokens...")
    access_token, refresh_token = oauth.authenticate(auth_code)
    
    # Save the new tokens
    os.makedirs(os.path.dirname(tokens_file), exist_ok=True)
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }
    with open(tokens_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    print(f"\n✅ SUCCESS! Tokens successfully updated and saved to:")
    print(f"👉 {tokens_file}")
    print(f"\nNew Access Token: {access_token[:10]}...")
    print(f"New Refresh Token: {refresh_token[:10]}...")
    print("\nYou can now safely restart your application, and the Box API error should be resolved!")
except Exception as e:
    print(f"\n❌ Error exchanging authorization code: {e}")
    sys.exit(1)
