#!/usr/bin/env python3
"""
scripts/local_auth.py
======================
Interactive local OAuth2 authorization utility for the JobTracker background worker.

Run this script locally on your development machine to generate Gmail API OAuth2
refresh tokens for headless background worker execution.

Usage:
    python scripts/local_auth.py [--credentials-file PATH] [--update-env]

Prerequisites in Google Cloud Console:
1. Enable Gmail API:
   API & Services -> Library -> Search "Gmail API" -> Enable.
2. Configure OAuth Consent Screen:
   - User Type: External.
   - App Name: JobTracker.
   - Test Users (CRITICAL): Add your primary Gmail address.
     Without adding your email as a test user, authentication will fail with access_denied.
3. Create Credentials:
   - APIs & Services -> Credentials -> Create Credentials -> OAuth Client ID.
   - Application type: Desktop app.
   - Name: JobTracker Desktop.
   - Download JSON file and save as 'credentials.json' in project root.
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: google-auth-oauthlib is not installed.")
    print("Please install requirements: pip install google-auth-oauthlib")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_credentials_from_file(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_oauth_flow(credentials_path: Path):
    print("=" * 70)
    print("  JobTracker Autonomous Email Worker — Gmail OAuth2 Setup")
    print("=" * 70)
    print(f"Loading OAuth configuration from: {credentials_path}")

    if not credentials_path.exists():
        # Auto-detect any client_secret*.json file in current directory
        secret_files = list(Path(".").glob("client_secret*.json"))
        if secret_files:
            credentials_path = secret_files[0]
            print(f"[+] Auto-detected OAuth client secret file: {credentials_path}")
        else:
            print(f"\n[!] Credentials file not found at: {credentials_path}")
            print("\nPlease follow these setup steps in Google Cloud Console:")
            print("  1. Visit: https://console.cloud.google.com/")
            print("  2. Enable the Gmail API.")
            print("  3. Set OAuth Consent Screen to External and add your Gmail as a Test User.")
            print("  4. Create an 'OAuth client ID' with Application Type: 'Desktop app'.")
            print("  5. Download the JSON and save it as 'credentials.json' in the project root.\n")
            
            choice = input("Would you like to manually enter Client ID and Client Secret? (y/N): ").strip().lower()
            if choice != "y":
                print("Aborting. Please place 'credentials.json' and re-run.")
                sys.exit(1)
            
            client_id = input("Enter Google Client ID: ").strip()
            client_secret = input("Enter Google Client Secret: ").strip()
            
            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            credentials_path = None

    if credentials_path is not None:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)

    print("\nStarting local HTTP authorization server...")
    print("Your browser should open automatically to prompt Google account sign-in.\n")
    
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    client_id = creds.client_id
    client_secret = creds.client_secret
    refresh_token = creds.refresh_token

    if not refresh_token:
        print("\n[WARNING] No refresh token returned by Google.")
        print("This typically happens if access was already granted without prompt=consent.")
        print("Please visit: https://myaccount.google.com/permissions to revoke JobTracker access, then re-run.")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  OAuth2 Authorization Succeeded!")
    print("=" * 70)
    print("\nAdd the following lines to your .env file:\n")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}")
    print("-" * 70)

    # Optionally save token.json
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": SCOPES,
    }
    token_file = Path("token.json")
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    print(f"[OK] Saved offline token backup to: {token_file.resolve()}")

    return client_id, client_secret, refresh_token


def update_env_file(client_id: str, client_secret: str, refresh_token: str, env_path: Path = Path(".env")):
    if not env_path.exists():
        print(f"[!] {env_path} does not exist. Creating new .env file.")
        env_content = ""
    else:
        with open(env_path, "r", encoding="utf-8") as f:
            env_content = f.read()

    lines = env_content.splitlines()
    updates = {
        "GMAIL_CLIENT_ID": client_id,
        "GMAIL_CLIENT_SECRET": client_secret,
        "GMAIL_REFRESH_TOKEN": refresh_token,
    }
    
    new_lines = []
    found_keys = set()
    for line in lines:
        matched = False
        for k, v in updates.items():
            if line.startswith(f"{k}="):
                new_lines.append(f"{k}={v}")
                found_keys.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in found_keys:
            new_lines.append(f"{k}={v}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    
    print(f"[OK] Successfully updated Gmail credentials in {env_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="JobTracker Gmail OAuth2 Desktop Setup Utility")
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=Path("credentials.json"),
        help="Path to Google Cloud OAuth client credentials JSON (default: credentials.json)"
    )
    parser.add_argument(
        "--update-env",
        action="store_true",
        help="Automatically write credentials to .env file"
    )
    args = parser.parse_args()

    client_id, client_secret, refresh_token = run_oauth_flow(args.credentials_file)

    if args.update_env or input("\nUpdate .env file automatically? (y/N): ").strip().lower() == "y":
        update_env_file(client_id, client_secret, refresh_token)


if __name__ == "__main__":
    main()
