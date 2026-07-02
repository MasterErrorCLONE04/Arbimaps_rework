import os
import sys
import json
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from boxsdk import OAuth2

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

dotenv_path = PROJECT_DIR / ".env"
load_dotenv(dotenv_path)
load_dotenv(BACKEND_DIR / ".env")


def resolve_runtime_path(value, default):
    raw = (value or default or "").strip()
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    return str((BACKEND_DIR / path).resolve())


def write_json_atomic(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent), delete=False) as tmp:
            tmp_name = tmp.name
            json.dump(data, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


client_id = os.getenv("BOX_CLIENT_ID")
client_secret = os.getenv("BOX_CLIENT_SECRET")
tokens_file = resolve_runtime_path(os.getenv("BOX_TOKENS_FILE"), "tokens/box_oauth_tokens.json")
redirect_uri = os.getenv("BOX_REDIRECT_URI_FOR_MANUAL_RENEWAL", "http://localhost")

print("====================================================")
print("             BOX OAUTH TOKEN RENEWAL UTILITY        ")
print("====================================================")

if not client_id or not client_secret:
    print("Error: BOX_CLIENT_ID or BOX_CLIENT_SECRET is not set in your .env file.")
    print(f"Path checked: {dotenv_path}")
    sys.exit(1)

print(f"Client ID: {client_id}")
print(f"Redirect URI: {redirect_uri}")
print(f"Target Tokens File: {tokens_file}")

oauth = OAuth2(
    client_id=client_id,
    client_secret=client_secret,
)

auth_url, csrf_token = oauth.get_authorization_url(redirect_uri)

print("\nSTEP 1: Open the following URL in your browser and authorize the app:")
print("-" * 80)
print(auth_url)
print("-" * 80)

print("\nSTEP 2: Copy only the value of the 'code' parameter from the redirect URL.")

try:
    auth_code = input("\nEnter authorization code: ").strip()
except KeyboardInterrupt:
    print("\n\nOperation cancelled.")
    sys.exit(0)

if not auth_code:
    print("Error: Authorization code cannot be empty.")
    sys.exit(1)

try:
    print("\nContacting Box to exchange authorization code for fresh tokens...")
    access_token, refresh_token = oauth.authenticate(auth_code)

    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    write_json_atomic(tokens_file, data)

    print("\nSUCCESS! Tokens successfully updated and saved to:")
    print(tokens_file)
    print(f"\nNew Access Token: {access_token[:10]}...")
    print(f"New Refresh Token: {refresh_token[:10]}...")
    print("\nRestart the application process that reads this token file.")
except Exception as e:
    print(f"\nError exchanging authorization code: {e}")
    sys.exit(1)