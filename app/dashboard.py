import logging
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings
from app.services.profile_services import get_firestore_client

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()

_HTML = (Path(__file__).parent / "templates" / "dashboard.html").read_text()


def _check_auth(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    correct_username = secrets.compare_digest(credentials.username, settings.DASHBOARD_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )


def _get_name(profile: Dict[str, Any]) -> str:
    intents = profile.get("intents") or {}
    last_intent = profile.get("last_intent")
    if last_intent and last_intent in intents:
        name = intents[last_intent].get("name")
        if name:
            return name
    for intent_data in intents.values():
        if isinstance(intent_data, dict):
            name = intent_data.get("name")
            if name:
                return name
    return ""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(_: None = Depends(_check_auth)) -> str:
    return _HTML


@router.get("/api/callers")
async def list_callers(intent: Optional[str] = None, _: None = Depends(_check_auth)) -> List[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return []

    callers = []
    docs = db.collection(settings.FIRESTORE_PROFILE_COLLECTION).limit(500).stream()
    for doc in docs:
        data = doc.to_dict() or {}
        caller_intents = list((data.get("intents") or {}).keys())

        if intent and intent not in caller_intents:
            continue

        callers.append({
            "phone_number": doc.id,
            "name": _get_name(data),
            "last_intent": data.get("last_intent", ""),
            "last_interaction": data.get("last_interaction", ""),
            "created_at": data.get("created_at", ""),
            "intents": caller_intents,
        })

    callers.sort(key=lambda x: x.get("last_interaction") or "", reverse=True)
    return callers


@router.get("/api/callers/{phone_number:path}")
async def get_caller(phone_number: str, _: None = Depends(_check_auth)) -> Dict[str, Any]:
    from typing import cast
    from google.cloud.firestore_v1.base_document import DocumentSnapshot

    db = get_firestore_client()
    if db is None:
        return {}

    doc = cast(
        DocumentSnapshot,
        db.collection(settings.FIRESTORE_PROFILE_COLLECTION).document(phone_number).get(),
    )
    if not doc.exists:
        return {}
    return {"phone_number": doc.id, **(doc.to_dict() or {})}


@router.get("/api/failed-notifications")
async def list_failed_notifications(_: None = Depends(_check_auth)) -> List[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return []

    notifications = []
    try:
        docs = (
            db.collection(settings.FIRESTORE_FAILED_NOTIFICATION_COLLECTION)
            .limit(100)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict() or {}
            data["id"] = doc.id
            notifications.append(data)
    except Exception as e:
        logger.error("Failed to fetch failed notifications: %s", e)

    notifications.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return notifications
