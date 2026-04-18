import datetime as dt
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from app.auth import UserContext, normalize_client_status, require_admin_flexible, require_client
from app.config import settings
from app.services.profile_services import get_firestore_client

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
CLIENTS_COLLECTION = "clients"
APP_SETTINGS_COLLECTION = "app_settings"
APP_SETTINGS_DOC = "config"

logger = logging.getLogger(__name__)
router = APIRouter()


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


# ──────────────────────────────────────────────────────────────
# Admin — callers
# ──────────────────────────────────────────────────────────────

@router.get("/api/callers")
async def list_callers(
    intent: Optional[str] = None,
    client_id: Optional[str] = None,
    _: UserContext = Depends(require_admin_flexible),
) -> List[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return []

    if client_id and client_id != "default":
        collection = (
            db.collection("clients")
            .document(client_id)
            .collection(settings.FIRESTORE_PROFILE_COLLECTION)
        )
    else:
        collection = db.collection(settings.FIRESTORE_PROFILE_COLLECTION)

    callers = []
    docs = collection.limit(500).stream()
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
async def get_caller(
    phone_number: str,
    client_id: Optional[str] = None,
    _: UserContext = Depends(require_admin_flexible),
) -> Dict[str, Any]:
    from typing import cast
    from google.cloud.firestore_v1.base_document import DocumentSnapshot

    db = get_firestore_client()
    if db is None:
        return {}

    if client_id and client_id != "default":
        collection = (
            db.collection("clients")
            .document(client_id)
            .collection(settings.FIRESTORE_PROFILE_COLLECTION)
        )
    else:
        collection = db.collection(settings.FIRESTORE_PROFILE_COLLECTION)

    doc = cast(DocumentSnapshot, collection.document(phone_number).get())
    if not doc.exists:
        return {}
    return {"phone_number": doc.id, **(doc.to_dict() or {})}


# ──────────────────────────────────────────────────────────────
# Client-scoped /me/* routes
# ──────────────────────────────────────────────────────────────

@router.get("/me/profile")
async def me_profile(user: UserContext = Depends(require_client)) -> Dict[str, Any]:
    """Returns the client's own profile info."""
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")

    data = doc.to_dict() or {}
    # Never expose the hashed password or refresh token in the response
    return {
        "id": user.client_id,
        "name": data.get("name", ""),
        "phone_number": data.get("phone_number", ""),
        "website_url": data.get("website_url", ""),
        "gmail_email": data.get("gmail_email"),
        "gmail_connected": bool(data.get("gmail_refresh_token")),
    }


@router.get("/me/callers")
async def me_list_callers(
    intent: Optional[str] = None,
    user: UserContext = Depends(require_client),
) -> List[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return []

    collection = (
        db.collection("clients")
        .document(user.client_id)
        .collection(settings.FIRESTORE_PROFILE_COLLECTION)
    )

    callers = []
    docs = collection.limit(500).stream()
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


@router.get("/me/callers/{phone_number:path}")
async def me_get_caller(
    phone_number: str,
    user: UserContext = Depends(require_client),
) -> Dict[str, Any]:
    from typing import cast
    from google.cloud.firestore_v1.base_document import DocumentSnapshot

    db = get_firestore_client()
    if db is None:
        return {}

    collection = (
        db.collection("clients")
        .document(user.client_id)
        .collection(settings.FIRESTORE_PROFILE_COLLECTION)
    )
    doc = cast(DocumentSnapshot, collection.document(phone_number).get())
    if not doc.exists:
        return {}
    return {"phone_number": doc.id, **(doc.to_dict() or {})}


@router.get("/me/settings")
async def me_get_settings(user: UserContext = Depends(require_client)) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        return {}

    doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
    if not doc.exists:
        return {}

    data = doc.to_dict() or {}
    return {
        "sms_job_seeker": data.get("sms_job_seeker", ""),
        "sms_sales": data.get("sms_sales", ""),
    }


@router.post("/me/settings")
async def me_save_settings(
    payload: Dict[str, Any] = Body(...),
    user: UserContext = Depends(require_client),
) -> Dict[str, Any]:
    allowed = {"sms_job_seeker", "sms_sales"}
    data = {k: v for k, v in payload.items() if k in allowed}
    if not data:
        raise HTTPException(status_code=400, detail="No valid settings fields provided.")

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    db.collection(CLIENTS_COLLECTION).document(user.client_id).set(data, merge=True)
    return {"status": "saved", **data}


# ──────────────────────────────────────────────────────────────
# ElevenLabs helpers
# ──────────────────────────────────────────────────────────────

def _el_headers() -> Dict[str, str]:
    return {"xi-api-key": settings.ELEVENLABS_API_KEY}


async def _get_template_agent() -> Dict[str, Any]:
    """Fetches the template agent config to clone for new clients."""
    if not settings.ELEVENLABS_AGENT_ID:
        raise HTTPException(status_code=500, detail="ELEVENLABS_AGENT_ID is not configured.")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{ELEVENLABS_BASE}/convai/agents/{settings.ELEVENLABS_AGENT_ID}",
            headers=_el_headers(),
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"Failed to fetch template agent: {resp.text}")
        return resp.json()


async def _create_elevenlabs_agent(name: str, template: Dict[str, Any], kb_id: str) -> str:
    """Clones the template agent for a new client with their KB. Returns agent_id."""
    conversation_config = template.get("conversation_config", {})
    agent_cfg = conversation_config.get("agent", {})
    prompt_cfg = agent_cfg.get("prompt", {})
    prompt_cfg["knowledge_base"] = [{"type": "url", "name": name, "id": kb_id}]
    agent_cfg["prompt"] = prompt_cfg
    conversation_config["agent"] = agent_cfg

    payload = {
        "name": f"{name} — VoiceConnect",
        "conversation_config": conversation_config,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ELEVENLABS_BASE}/convai/agents",
            headers=_el_headers(),
            json=payload,
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"ElevenLabs agent creation failed: {resp.text}")
        return resp.json()["agent_id"]


async def _delete_elevenlabs_agent(agent_id: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{ELEVENLABS_BASE}/convai/agents/{agent_id}",
            headers=_el_headers(),
            timeout=30,
        )


async def _create_elevenlabs_kb(name: str, url: str) -> str:
    """Creates an ElevenLabs knowledge base from a URL. Returns the kb id."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ELEVENLABS_BASE}/convai/knowledge-base",
            headers=_el_headers(),
            json={"name": name, "type": "url", "url": url},
            timeout=60,
        )
        if not resp.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"ElevenLabs KB creation failed: {resp.text}",
            )
        return resp.json()["id"]


async def _delete_elevenlabs_kb(kb_id: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{ELEVENLABS_BASE}/convai/knowledge-base/{kb_id}",
            headers=_el_headers(),
            timeout=30,
        )


# ──────────────────────────────────────────────────────────────
# Twilio helpers
# ──────────────────────────────────────────────────────────────

def _twilio_client():
    from twilio.rest import Client
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="Twilio credentials are not configured.")
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def _buy_twilio_number(area_code: Optional[str], country: str) -> str:
    """Searches for and purchases a Twilio number. Returns the purchased number."""
    client = _twilio_client()
    search_kwargs: Dict[str, Any] = {"limit": 1}
    if area_code:
        search_kwargs["area_code"] = area_code

    try:
        available = (
            client.available_phone_numbers(country)
            .local.list(**search_kwargs)
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Twilio number search failed: {exc}")

    if not available:
        raise HTTPException(
            status_code=404,
            detail=f"No available numbers found for area code {area_code}." if area_code
                   else "No available numbers found.",
        )

    phone_number = available[0].phone_number
    try:
        client.incoming_phone_numbers.create(phone_number=phone_number)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Twilio number purchase failed: {exc}")

    return phone_number


def _configure_twilio_number(phone_number: str, client_id: str, base_url: str) -> None:
    """Points the Twilio number's voice webhook at our routing endpoint."""
    client = _twilio_client()
    numbers = client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)
    if not numbers:
        raise HTTPException(status_code=404, detail=f"Twilio number {phone_number} not found in account.")
    voice_url = f"{base_url}/twilio/voice/{client_id}"
    numbers[0].update(voice_url=voice_url, voice_method="GET")


def _release_twilio_number(phone_number: str) -> None:
    client = _twilio_client()
    numbers = client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)
    if numbers:
        numbers[0].delete()


# ──────────────────────────────────────────────────────────────
# Admin — clients endpoints
# ──────────────────────────────────────────────────────────────

@router.get("/api/clients")
async def list_clients(_: UserContext = Depends(require_admin_flexible)) -> List[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return []
    docs = db.collection(CLIENTS_COLLECTION).order_by("created_at", direction="DESCENDING").limit(100).stream()
    clients = []
    for doc in docs:
        data = doc.to_dict() or {}
        # Strip sensitive fields before returning
        clients.append({
            "id": doc.id,
            "name": data.get("name", ""),
            "website_url": data.get("website_url", ""),
            "phone_number": data.get("phone_number", ""),
            "country": data.get("country", ""),
            "area_code": data.get("area_code", ""),
            "email": data.get("email", ""),
            "created_at": data.get("created_at", ""),
            "status": normalize_client_status(data),
            "provisioning_error": data.get("provisioning_error"),
            "gmail_email": data.get("gmail_email"),
            "gmail_connected": bool(data.get("gmail_refresh_token")),
        })
    return clients


@router.post("/api/clients", status_code=201)
async def add_client(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    _: UserContext = Depends(require_admin_flexible),
) -> Dict[str, Any]:
    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    name = (payload.get("name") or "").strip()
    url = (payload.get("website_url") or "").strip()
    area_code = (payload.get("area_code") or "").strip() or None
    country = (payload.get("country") or "US").strip().upper()
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()

    if not name or not url:
        raise HTTPException(status_code=400, detail="name and website_url are required.")
    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required for client login.")

    # 1. Create knowledge base
    kb_id = await _create_elevenlabs_kb(name, url)

    # 2. Clone template agent with the new KB
    template = await _get_template_agent()
    agent_id = await _create_elevenlabs_agent(name, template, kb_id)

    # 3. Buy a Twilio number
    phone_number = _buy_twilio_number(area_code, country)

    # 4. Save to Firestore
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    doc_ref = db.collection(CLIENTS_COLLECTION).document()
    data = {
        "name": name,
        "website_url": url,
        "kb_id": kb_id,
        "agent_id": agent_id,
        "phone_number": phone_number,
        "country": country,
        "email": email,
        "hashed_password": _pwd.hash(password),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    doc_ref.set(data)

    # 5. Point the Twilio number at our routing endpoint
    base_url = str(request.base_url).rstrip("/")
    _configure_twilio_number(phone_number, doc_ref.id, base_url)

    return {
        "id": doc_ref.id,
        "name": name,
        "website_url": url,
        "phone_number": phone_number,
        "country": country,
        "email": email,
        "created_at": data["created_at"],
    }


@router.post("/api/clients/{client_id}/provision")
async def provision_client(
    client_id: str,
    request: Request,
    _: UserContext = Depends(require_admin_flexible),
) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    doc = db.collection(CLIENTS_COLLECTION).document(client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")

    data = doc.to_dict() or {}
    name = data.get("name", "")
    url = data.get("website_url", "")
    area_code = data.get("area_code") or None
    country = (data.get("country") or "US").upper()

    if not name or not url:
        raise HTTPException(status_code=400, detail="Client is missing name or website_url.")

    # Mark as provisioning so UI can show progress
    db.collection(CLIENTS_COLLECTION).document(client_id).update({
        "status": "provisioning",
        "provisioning_error": None,
    })

    kb_id: Optional[str] = None
    agent_id: Optional[str] = None
    phone_number: Optional[str] = None

    try:
        kb_id = await _create_elevenlabs_kb(name, url)
        template = await _get_template_agent()
        agent_id = await _create_elevenlabs_agent(name, template, kb_id)
        phone_number = _buy_twilio_number(area_code, country)

        base_url = str(request.base_url).rstrip("/")
        _configure_twilio_number(phone_number, client_id, base_url)

        db.collection(CLIENTS_COLLECTION).document(client_id).update({
            "kb_id": kb_id,
            "agent_id": agent_id,
            "phone_number": phone_number,
            "status": "active",
            "provisioning_error": None,
        })

        return {
            "id": client_id,
            "name": name,
            "website_url": url,
            "email": data.get("email", ""),
            "country": country,
            "area_code": area_code or "",
            "phone_number": phone_number,
            "kb_id": kb_id,
            "agent_id": agent_id,
            "status": "active",
            "created_at": data.get("created_at", ""),
            "gmail_email": data.get("gmail_email"),
            "gmail_connected": bool(data.get("gmail_refresh_token")),
            "provisioning_error": None,
        }

    except HTTPException as exc:
        error_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        db.collection(CLIENTS_COLLECTION).document(client_id).update({
            "status": "provisioning_failed",
            "provisioning_error": error_msg,
        })
        raise

    except Exception as exc:
        error_msg = str(exc)
        db.collection(CLIENTS_COLLECTION).document(client_id).update({
            "status": "provisioning_failed",
            "provisioning_error": error_msg,
        })
        raise HTTPException(status_code=500, detail=error_msg)


@router.delete("/api/clients/{client_id}", status_code=204)
async def delete_client(
    client_id: str,
    _: UserContext = Depends(require_admin_flexible),
) -> None:
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    doc = db.collection(CLIENTS_COLLECTION).document(client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")

    data = doc.to_dict() or {}
    if data.get("kb_id"):
        await _delete_elevenlabs_kb(data["kb_id"])
    if data.get("agent_id"):
        await _delete_elevenlabs_agent(data["agent_id"])
    if data.get("phone_number"):
        _release_twilio_number(data["phone_number"])

    db.collection(CLIENTS_COLLECTION).document(client_id).delete()


# ──────────────────────────────────────────────────────────────
# Admin — app settings endpoints
# ──────────────────────────────────────────────────────────────

@router.get("/api/settings")
async def get_settings(_: UserContext = Depends(require_admin_flexible)) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        return {}
    doc = db.collection(APP_SETTINGS_COLLECTION).document(APP_SETTINGS_DOC).get()
    return doc.to_dict() or {}


@router.post("/api/settings")
async def save_settings(
    payload: Dict[str, Any] = Body(...),
    _: UserContext = Depends(require_admin_flexible),
) -> Dict[str, Any]:
    allowed = {"sms_job_seeker", "sms_sales"}
    data = {k: v for k, v in payload.items() if k in allowed}
    if not data:
        raise HTTPException(status_code=400, detail="No valid settings fields provided.")

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    db.collection(APP_SETTINGS_COLLECTION).document(APP_SETTINGS_DOC).set(data, merge=True)
    return {"status": "saved", **data}


@router.get("/api/failed-notifications")
async def list_failed_notifications(_: UserContext = Depends(require_admin_flexible)) -> List[Dict[str, Any]]:
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
