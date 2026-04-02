"""
Authentication routes for Gmail OAuth2 flow.
"""

import hashlib
import hmac
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_sync_db
from src.core.logging import get_logger
from src.integrations.gmail.auth import GmailAuthService
from src.models import GmailAccount, User

logger = get_logger(__name__)

router = APIRouter()


def _sign_state(payload: str) -> str:
    """Create HMAC-signed state token: payload.signature."""
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_state(state: str) -> str:
    """Verify HMAC signature and return the payload portion, or raise ValueError."""
    parts = state.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError("Invalid state token format")
    payload, signature = parts
    expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("State token CSRF validation failed")
    return payload


# OAuth2 scopes
GMAIL_SCOPES = [
    "openid",  # Required to get id_token with email
    "https://www.googleapis.com/auth/userinfo.email",  # Explicit email scope
    "https://www.googleapis.com/auth/gmail.readonly",
    # Note: Contacts scope removed for now - can add back later if needed
    # "https://www.googleapis.com/auth/contacts.readonly",
]


# Response models
class AuthUrlResponse(BaseModel):
    """Response for auth URL generation."""

    auth_url: str
    account_label: str
    message: str


class AuthCallbackResponse(BaseModel):
    """Response for OAuth callback."""

    status: str
    message: str
    account_label: str | None = None
    account_email: str | None = None


class AccountStatus(BaseModel):
    """Account authentication status."""

    label: str
    email: str
    is_active: bool
    last_synced_at: str | None


class AuthStatusResponse(BaseModel):
    """Response for authentication status check."""

    user_id: str
    authenticated_accounts: list[AccountStatus]
    total_accounts: int


@router.get("/login/{account_label}", response_model=AuthUrlResponse)
async def initiate_oauth(
    account_label: str,
    user_id: str = Query(..., description="User ID"),
    db: Session = Depends(get_sync_db),
) -> AuthUrlResponse:
    """
    Initiate OAuth2 flow for a specific Gmail account.

    Args:
        account_label: Account identifier (procore-main, procore-private, personal)
        user_id: User ID
        db: Database session

    Returns:
        Authorization URL for user to click
    """
    logger.info("Initiating OAuth for user %s, account %s", user_id, account_label)

    # Validate account label
    valid_labels = ["procore-main", "procore-private", "personal"]
    if account_label not in valid_labels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid account label. Must be one of: {', '.join(valid_labels)}",
        )

    # Ensure user exists
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    # Generate OAuth URL
    try:
        # Create OAuth2 flow
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.google_redirect_uri],
                }
            },
            scopes=GMAIL_SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )

        # Generate HMAC-signed state token with user_id, account_label, and CSRF nonce
        state_payload = f"{user_id}:{account_label}:{secrets.token_urlsafe(32)}"
        state_data = _sign_state(state_payload)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            state=state_data,
            prompt="consent",
        )

        logger.info("Generated auth URL for %s", account_label)
    except Exception as e:
        logger.error("Error generating auth URL: %s", str(e))
        raise HTTPException(
            status_code=500, detail="Failed to generate authorization URL"
        ) from None

    return AuthUrlResponse(
        auth_url=auth_url,
        account_label=account_label,
        message=f"Click the URL to authorize {account_label} account",
    )


@router.get("/callback", response_model=AuthCallbackResponse)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State token (contains user_id and account_label)"),
    db: Session = Depends(get_sync_db),
) -> AuthCallbackResponse:
    """
    Handle OAuth2 callback from Google.

    Args:
        code: Authorization code
        state: State token
        db: Database session

    Returns:
        Success/failure status
    """
    logger.info("Received OAuth callback")

    try:
        # Verify HMAC signature on state token to prevent CSRF
        state_payload = _verify_state(state)

        # Parse the verified payload
        state_parts = state_payload.split(":")
        if len(state_parts) < 2:
            raise ValueError("Invalid state token")

        user_id = state_parts[0]
        account_label = state_parts[1]

        logger.info("Processing callback for user %s, account %s", user_id, account_label)

        # Exchange code for credentials
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.google_redirect_uri],
                }
            },
            scopes=GMAIL_SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )

        # Disable strict scope validation (Google may grant additional scopes)
        flow.oauth2session.scope = None

        # Fetch token
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user info to extract email
        # Try to get email from id_token first (most reliable)
        account_email = None

        if hasattr(credentials, "id_token") and credentials.id_token:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            id_token_claims = google_id_token.verify_oauth2_token(
                credentials.id_token,
                google_requests.Request(),
                audience=settings.google_client_id,
            )
            account_email = id_token_claims.get("email")
            logger.info("Extracted email from id_token: %s", account_email)

        # Fallback to userinfo endpoint if needed
        if not account_email:
            import requests as http_requests

            logger.info("Falling back to userinfo endpoint")
            userinfo_response = http_requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
            userinfo = userinfo_response.json()
            logger.info("Userinfo response: %s", userinfo)
            account_email = userinfo.get("email")

        if not account_email:
            logger.error("Could not retrieve email address from any source")
            raise ValueError("Could not retrieve email address from Google account")

        # Store credentials in database
        import json
        from datetime import datetime

        # Check if account already exists
        existing_account = (
            db.query(GmailAccount)
            .filter(
                GmailAccount.user_id == uuid.UUID(user_id),
                GmailAccount.account_label == account_label,
            )
            .first()
        )

        credentials_dict = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
        }

        # Encrypt credentials using pgcrypto before storing
        from sqlalchemy import text

        encrypted_row = db.execute(
            text(
                "SELECT encode("
                "pgp_sym_encrypt(:creds_json::text, :secret_key), 'base64'"
                ") as encrypted"
            ),
            {
                "creds_json": json.dumps(credentials_dict),
                "secret_key": settings.secret_key,
            },
        ).fetchone()

        if not encrypted_row:
            raise ValueError("Failed to encrypt credentials")

        encrypted_creds = json.dumps({"encrypted": encrypted_row[0]})

        if existing_account:
            # Update existing account
            existing_account.account_email = account_email
            existing_account.credentials = encrypted_creds
            existing_account.is_active = True
            existing_account.updated_at = datetime.utcnow()
        else:
            # Create new account
            new_account = GmailAccount(
                id=str(uuid.uuid4()),
                user_id=uuid.UUID(user_id),
                account_email=account_email,
                account_label=account_label,
                credentials=encrypted_creds,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(new_account)

        db.commit()

        logger.info("OAuth callback successful for %s (%s)", account_label, account_email)

        return AuthCallbackResponse(
            status="success",
            message=f"Successfully authenticated {account_label} account",
            account_label=account_label,
            account_email=account_email,
        )

    except ValueError as e:
        logger.error("OAuth callback validation error: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e)) from None

    except Exception as e:
        logger.error("OAuth callback error: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Authentication failed") from None


@router.get("/status", response_model=AuthStatusResponse)
async def check_auth_status(
    user_id: str = Query(..., description="User ID"), db: Session = Depends(get_sync_db)
) -> AuthStatusResponse:
    """
    Check authentication status for all Gmail accounts.

    Args:
        user_id: User ID
        db: Database session

    Returns:
        List of authenticated accounts with status
    """
    logger.info("Checking auth status for user %s", user_id)

    # Get user
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    # Get all accounts for user
    accounts = db.query(GmailAccount).filter(GmailAccount.user_id == uuid.UUID(user_id)).all()

    account_statuses = [
        AccountStatus(
            label=account.account_label,
            email=account.account_email,
            is_active=account.is_active,
            last_synced_at=account.last_synced_at.isoformat() if account.last_synced_at else None,
        )
        for account in accounts
    ]

    logger.info("Found %s accounts for user %s", len(accounts), user_id)

    return AuthStatusResponse(
        user_id=user_id,
        authenticated_accounts=account_statuses,
        total_accounts=len(accounts),
    )


@router.post("/revoke/{account_id}")
async def revoke_account(
    account_id: str,
    user_id: str = Query(..., description="User ID"),
    db: Session = Depends(get_sync_db),
) -> dict[str, Any]:
    """
    Revoke OAuth credentials for a Gmail account.

    Args:
        account_id: Account ID
        user_id: User ID
        db: Database session

    Returns:
        Success status
    """
    logger.info("Revoking credentials for account %s", account_id)

    # Verify account belongs to user
    account = (
        db.query(GmailAccount)
        .filter(
            GmailAccount.id == uuid.UUID(account_id),
            GmailAccount.user_id == uuid.UUID(user_id),
        )
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Revoke credentials
    auth_service = GmailAuthService()
    try:
        auth_service.revoke_credentials(account_id, db)
        logger.info("Successfully revoked credentials for %s", account.account_label)

        return {
            "status": "success",
            "message": f"Revoked credentials for {account.account_label}",
        }

    except Exception as e:
        logger.error("Error revoking credentials: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to revoke credentials") from None
