import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.auth.jwt import create_gmail_oauth_state, decode_gmail_oauth_state
from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.gmail_client import SCOPES, gmail_oauth_configured

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gmail", tags=["Gmail"])


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


@router.post("/oauth/start")
def gmail_oauth_start(current_user: User = Depends(get_current_user)):
    if not gmail_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail OAuth is not configured on the server.",
        )
    state = create_gmail_oauth_state(current_user.id)
    # PKCE verifier is tied to the Flow instance; callback builds a new Flow, so PKCE must be off
    # for web clients that use a client secret (confidential client).
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
        autogenerate_code_verifier=False,
    )
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return {"authorization_url": authorization_url}


@router.get("/oauth/callback")
def gmail_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
):
    if not gmail_oauth_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gmail OAuth not configured")
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google sign-in was cancelled or failed ({error}).",
        )
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    try:
        user_id = decode_gmail_oauth_state(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from None

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
        autogenerate_code_verifier=False,
    )
    try:
        # Web clients: pass the full callback URL (google-auth-oauthlib matches redirect_uri to this).
        flow.fetch_token(authorization_response=str(request.url))
    except Exception as exc:
        _log.warning("Gmail OAuth token exchange failed: %s", exc)
        hint = (
            "OAuth token exchange failed. If redirect URIs already match in Google Cloud Console, "
            "restart the backend and try Connect Gmail again (auth codes are single-use). "
            f"Server log: {exc!s}"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=hint) from None

    creds = flow.credentials
    refresh = creds.refresh_token
    if not refresh:
        raise HTTPException(status_code=400, detail="No refresh token returned; try revoking app access and reconnect.")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.google_refresh_token = refresh
    db.add(user)
    db.commit()

    return RedirectResponse(url=f"{settings.frontend_url.rstrip('/')}/settings?gmail=connected", status_code=302)


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def gmail_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.google_refresh_token = None
    db.add(current_user)
    db.commit()
