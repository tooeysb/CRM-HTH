"""
Email drafting API router.

Provides endpoints for generating voice-matched email drafts.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.database import get_sync_db
from src.services.voice.draft_service import EmailDraftService

router = APIRouter()


class DraftRequest(BaseModel):
    """Request body for composing an email draft."""

    user_id: str
    recipient_email: str
    context: str
    tone: str | None = None
    reply_to_subject: str | None = None


class DraftResponse(BaseModel):
    """Response body with the generated email draft."""

    subject: str
    body: str
    similar_emails_used: int
    voice_profile_used: str
    model: str


@router.post("/compose", response_model=DraftResponse)
def compose_draft(request: DraftRequest, db: Session = Depends(get_sync_db)):
    """
    Generate a voice-matched email draft.

    Uses the user's voice profile and similar sent emails to draft
    an email that matches their natural writing style.
    """
    try:
        service = EmailDraftService(db)
        result = service.draft_email(
            user_id=request.user_id,
            recipient_email=request.recipient_email,
            context=request.context,
            tone=request.tone,
            reply_to_subject=request.reply_to_subject,
        )

        return DraftResponse(
            subject=result.subject,
            body=result.body,
            similar_emails_used=result.similar_emails_used,
            voice_profile_used=result.voice_profile_used,
            model=result.model,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Draft generation failed: {e}")
