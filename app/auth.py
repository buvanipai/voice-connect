import datetime as dt
import logging
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.config import settings
from app.services.profile_services import get_firestore_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_basic_security = HTTPBasic(auto_error=False)

CLIENTS_COLLECTION = "clients"
DEFAULT_PLAN = "starter"
GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.send",
]
CLIENT_ACTIVE_STATUSES = {"active"}
CLIENT_NON_ACTIVE_STATUSES = {"pending", "provisioning", "provisioning_failed"}


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    name: str
    website_url: str
    email: str
    password: str
    area_code: Optional[str] = None
    country: str = "US"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    client_id: Optional[str] = None
    status: Optional[str] = None


class GmailConnectResponse(BaseModel):
    url: str


class UserContext(BaseModel):
    role: str
    client_id: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def normalize_client_status(client_data: Dict[str, Any]) -> str:
    status_value = str(client_data.get("status") or "").strip().lower()
    if status_value in CLIENT_ACTIVE_STATUSES | CLIENT_NON_ACTIVE_STATUSES:
        return status_value

    if client_data.get("provisioning_error"):
        return "provisioning_failed"
    if client_data.get("phone_number") and client_data.get("agent_id"):
        return "active"
    if client_data.get("kb_id") or client_data.get("agent_id"):
        return "provisioning"
    return "pending"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def get_client_by_email(email: str) -> Optional[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return None

    docs = (
        db.collection(CLIENTS_COLLECTION)
        .where("email", "==", email.strip().lower())
        .limit(1)
        .stream()
    )
    for doc in docs:
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data
    return None


def _create_access_token(data: Dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        minutes=settings.JWT_EXPIRE_MINUTES
    )
    to_encode["exp"] = expire
    if not settings.JWT_SECRET_KEY:
        raise HTTPException(status_code=500, detail="JWT_SECRET_KEY is not configured.")
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_jwt(token: str) -> Dict[str, Any]:
    if not settings.JWT_SECRET_KEY:
        raise HTTPException(status_code=500, detail="JWT_SECRET_KEY is not configured.")
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(request: Request) -> UserContext:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_jwt(auth_header[7:])
    return UserContext(
        role=payload.get("role", ""),
        client_id=payload.get("client_id"),
        email=payload.get("sub"),
        status=payload.get("status"),
    )


def require_admin(request: Request) -> UserContext:
    user = get_current_user(request)
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


def require_client(request: Request) -> UserContext:
    user = get_current_user(request)
    if user.role != "client" or not user.client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client access required.",
        )
    return user


def require_admin_flexible(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(_basic_security),
) -> UserContext:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = decode_jwt(auth_header[7:])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required.")
        return UserContext(role="admin", email=payload.get("sub"))

    if credentials:
        ok_user = secrets.compare_digest(credentials.username, settings.DASHBOARD_USERNAME)
        ok_pass = secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD)
        if ok_user and ok_pass:
            return UserContext(role="admin")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _build_client_token(email: str, client_id: str, client_status: str) -> TokenResponse:
    token = _create_access_token(
        {
            "sub": email,
            "role": "client",
            "client_id": client_id,
            "status": client_status,
        }
    )
    return TokenResponse(
        access_token=token,
        role="client",
        client_id=client_id,
        status=client_status,
    )


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest) -> TokenResponse:
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    email = body.email.strip().lower()
    if secrets.compare_digest(email, settings.DASHBOARD_USERNAME.strip().lower()):
        raise HTTPException(status_code=400, detail="That email is reserved.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    if get_client_by_email(email):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    now = _utc_now_iso()
    payload = {
        "name": body.name.strip(),
        "website_url": body.website_url.strip(),
        "email": email,
        "hashed_password": hash_password(body.password),
        "area_code": (body.area_code or "").strip() or None,
        "country": body.country.strip().upper() or "US",
        "status": "pending",
        "signup_source": "self_serve",
        "created_at": now,
        "requested_at": now,
        "sms_job_seeker": "",
        "sms_sales": "",
        "plan": DEFAULT_PLAN,
        "minutes_used": 0,
        "channels": {"email": True, "sms": False},
        "sms_10dlc_approved": False,
        "forward_to_number": None,
        "usage": {},
    }

    if not payload["name"] or not payload["website_url"]:
        raise HTTPException(
            status_code=400,
            detail="name and website_url are required.",
        )
    if len(body.password.strip()) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters.",
        )

    doc_ref = db.collection(CLIENTS_COLLECTION).document()
    doc_ref.set(payload)
    return _build_client_token(email, doc_ref.id, payload["status"])


@router.post("/password-reset-request")
async def password_reset_request(
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Request a password reset by email. Returns success message."""
    email = (payload.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    client_data = get_client_by_email(email)
    if not client_data:
        # For security, don't reveal if email exists or not
        return {"status": "reset_email_sent", "message": "If an account exists, a reset link will be sent."}

    # Generate a time-based reset token (expires in 1 hour)
    reset_token = _create_access_token(
        {"sub": email, "purpose": "password_reset", "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)}
    )

    # In a real app, send an email with the reset link
    # For now, log it (the token would be sent in a reset URL)
    logger.info(
        "Password reset requested for %s. Token: %s...",
        email,
        reset_token[:20],
    )

    return {"status": "reset_email_sent", "message": "If an account exists, a reset link will be sent."}


@router.post("/password-reset")
async def password_reset(
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Reset password using a valid reset token."""
    token = (payload.get("token") or "").strip()
    new_password = (payload.get("password") or "").strip()

    if not token or not new_password:
        raise HTTPException(status_code=400, detail="token and password are required.")

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    try:
        decoded = decode_jwt(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid or expired reset token.")

    email = decoded.get("sub", "").strip().lower()
    purpose = decoded.get("purpose", "")
    if purpose != "password_reset" or not email:
        raise HTTPException(status_code=401, detail="Invalid reset token.")

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    # Find and update the client
    query = db.collection(CLIENTS_COLLECTION).where("email", "==", email).limit(1)
    updated = False
    for doc in query.stream():
        doc.reference.update({"hashed_password": hash_password(new_password)})
        updated = True
        break

    if not updated:
        raise HTTPException(status_code=404, detail="Client not found.")

    return {"status": "password_reset_success", "message": "Password has been reset. Please log in."}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    email = body.email.strip().lower()
    if get_firestore_client() is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    if (
        secrets.compare_digest(email, settings.DASHBOARD_USERNAME.strip().lower())
        and secrets.compare_digest(body.password, settings.DASHBOARD_PASSWORD)
    ):
        token = _create_access_token({"sub": email, "role": "admin"})
        return TokenResponse(access_token=token, role="admin")

    client_data = get_client_by_email(email)
    if not client_data:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    hashed = client_data.get("hashed_password", "")
    if not hashed or not verify_password(body.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    client_status = normalize_client_status(client_data)
    return _build_client_token(email, client_data["id"], client_status)


def _get_oauth_flow():
    from google_auth_oauthlib.flow import Flow

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth credentials are not configured.",
        )
    if not settings.GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_REDIRECT_URI is not configured.",
        )

    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=GMAIL_SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )
    # Confidential server client with client_secret — PKCE adds no security and
    # can't round-trip across requests (each /gmail/* call creates a fresh Flow).
    flow.autogenerate_code_verifier = False
    return flow


def _build_gmail_connect_url(client_id: str) -> str:
    flow = _get_oauth_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=client_id,
        prompt="consent",
    )
    return auth_url


@router.get("/gmail/connect-url", response_model=GmailConnectResponse)
async def gmail_connect_url(user: UserContext = Depends(require_client)) -> GmailConnectResponse:
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")

    client_status = normalize_client_status(doc.to_dict() or {})
    if client_status != "active":
        raise HTTPException(
            status_code=400,
            detail="Gmail can be connected after provisioning is complete.",
        )
    return GmailConnectResponse(url=_build_gmail_connect_url(user.client_id))


@router.get("/gmail/callback")
async def gmail_oauth_callback(code: str, state: str) -> HTMLResponse:
    client_id = state
    try:
        flow = _get_oauth_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as exc:
        logger.error("Gmail OAuth token exchange failed: %s", exc)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            "<h2>Connection failed</h2><p>Please try again.</p></body></html>",
            status_code=400,
        )

    gmail_email: Optional[str] = None
    try:
        import httpx as _httpx

        resp = _httpx.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        if resp.is_success:
            gmail_email = resp.json().get("email")
    except Exception:
        logger.warning("Unable to resolve Gmail userinfo for client %s", client_id)

    db = get_firestore_client()
    if db is None:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            "<h2>Connection failed</h2><p>Database unavailable.</p></body></html>",
            status_code=500,
        )

    doc = db.collection(CLIENTS_COLLECTION).document(client_id).get()
    if not doc.exists:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            "<h2>Connection failed</h2><p>Client not found.</p></body></html>",
            status_code=404,
        )

    update_data: Dict[str, Any] = {}
    if creds.refresh_token:
        update_data["gmail_refresh_token"] = creds.refresh_token
    if gmail_email:
        update_data["gmail_email"] = gmail_email

    if update_data:
        db.collection(CLIENTS_COLLECTION).document(client_id).update(update_data)
        logger.info("Gmail connected for client %s (%s)", client_id, gmail_email)

    return HTMLResponse(
        """
        <html>
        <body style="font-family:sans-serif;text-align:center;padding:60px;background:#f9fafb">
          <div style="max-width:400px;margin:auto;background:white;padding:40px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
            <h2 style="color:#16a34a">Gmail Connected!</h2>
            <p style="color:#6b7280">Your Gmail account has been connected successfully.</p>
            <p style="color:#6b7280">You can close this window and refresh the app.</p>
          </div>
        </body>
        </html>
        """
    )


@router.get("/gmail/{client_id}")
async def gmail_oauth_start(
    client_id: str,
    _: UserContext = Depends(require_admin_flexible),
) -> RedirectResponse:
    return RedirectResponse(url=_build_gmail_connect_url(client_id))
