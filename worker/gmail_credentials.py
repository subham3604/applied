"""
worker/gmail_credentials.py
===========================
Headless OAuth2 authentication provider for Google Gmail API.

Builds Google OAuth2 credentials strictly from environment variables or offline
token storage, guaranteeing zero browser re-authentication in containerized
and server environments.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("gmail_credentials")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailAuthError(Exception):
    """Raised when Gmail OAuth credentials cannot be loaded or refreshed."""
    pass


def build_credentials_from_env(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_json_path: Optional[str] = None,
):
    """
    Builds Google OAuth2 Credentials object from environment variables or token.json.
    
    Args:
        client_id: Optional explicit client ID (defaults to GMAIL_CLIENT_ID env var).
        client_secret: Optional explicit client secret (defaults to GMAIL_CLIENT_SECRET env var).
        refresh_token: Optional explicit refresh token (defaults to GMAIL_REFRESH_TOKEN env var).
        token_json_path: Optional path to token.json backup.
        
    Returns:
        google.oauth2.credentials.Credentials if credentials are valid, None if not configured.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import json

    cid = client_id or os.getenv("GMAIL_CLIENT_ID", "").strip().strip('"\'')
    csecret = client_secret or os.getenv("GMAIL_CLIENT_SECRET", "").strip().strip('"\'')
    rtoken = refresh_token or os.getenv("GMAIL_REFRESH_TOKEN", "").strip().strip('"\'')

    # If env variables are placeholders or empty, attempt fallback to token.json
    if not (cid and csecret and rtoken) or "placeholder" in cid or "placeholder" in rtoken:
        default_token_path = Path(token_json_path or "token.json")
        if default_token_path.exists():
            try:
                with open(default_token_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cid = data.get("client_id", cid)
                    csecret = data.get("client_secret", csecret)
                    rtoken = data.get("refresh_token", rtoken)
            except Exception as e:
                logger.warning("Could not read token.json fallback: %s", e)

    # Check if credentials are valid non-placeholders
    if not cid or not csecret or not rtoken:
        logger.info("Gmail credentials not fully provided in environment.")
        return None

    if "placeholder" in cid or "placeholder" in csecret or "placeholder" in rtoken:
        logger.info("Gmail credentials contain placeholder values; skipping live Gmail auth.")
        return None

    try:
        credentials = Credentials(
            token=None,
            refresh_token=rtoken,
            token_uri=TOKEN_URI,
            client_id=cid,
            client_secret=csecret,
            scopes=GMAIL_SCOPES,
        )

        # Refresh token to verify validity
        if not credentials.valid:
            request = Request()
            credentials.refresh(request)
            logger.info("Successfully refreshed Gmail OAuth2 access token.")

        return credentials
    except Exception as exc:
        logger.error("Failed to build or refresh Gmail credentials: %s", exc)
        raise GmailAuthError(f"OAuth token refresh failed: {exc}") from exc


def get_gmail_service(credentials=None):
    """
    Instantiates and returns a Google Gmail API resource service.
    
    Args:
        credentials: Optional Google Credentials object. If None, loaded via build_credentials_from_env().
        
    Returns:
        googleapiclient.discovery.Resource or None if unconfigured.
    """
    from googleapiclient.discovery import build

    creds = credentials or build_credentials_from_env()
    if not creds:
        return None

    return build("gmail", "v1", credentials=creds, cache_discovery=False)
