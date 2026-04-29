import datetime as dt
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.auth import UserContext, normalize_client_status, require_admin_flexible, require_client
from app.config import settings
from app.services.profile_services import get_firestore_client

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
CLIENTS_COLLECTION = "clients"
APP_SETTINGS_COLLECTION = "app_settings"
APP_SETTINGS_DOC = "config"
CALLS_COLLECTION = "calls"

DEFAULT_CHANNELS = {"email": True, "sms": False}
DEFAULT_PLAN = "starter"
PLAN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "starter": {
        "key": "starter",
        "label": "Starter",
        "price_monthly": 49,
        "included_minutes": 100,
        "overage_rate": 0.35,
    },
    "growth": {
        "key": "growth",
        "label": "Growth",
        "price_monthly": 99,
        "included_minutes": 300,
        "overage_rate": 0.30,
    },
    "agency": {
        "key": "agency",
        "label": "Agency",
        "price_monthly": 249,
        "included_minutes": 1000,
        "overage_rate": 0.25,
    },
}

FOLLOWUP_PROMPT_ADDENDUM = (
    "\n\n[Email follow-up protocol]\n"
    "Early in the conversation, collect the caller's email address if not "
    "already known. When you have gathered enough useful information, ask: "
    "'Would you like me to send a summary to your email?' Only call the "
    "send_followup tool after the caller confirms, and call it once only.\n"
    "When you call send_followup, compose the full email_body yourself in "
    "plain text (max 5 sentences). Use only facts confirmed during the call. "
    "No placeholders like [Name] or [link]. Open with a short greeting, list "
    "next steps, and sign off with the company name.\n"
    "[End email follow-up protocol]\n"
    "\n[Transfer protocol]\n"
    "If the caller asks to speak to a human, use the transfer_to_number tool "
    "if it is available. If the tool is not available, say: 'Nobody is available "
    "to take your call right now, but I'll make a note of your details and "
    "someone will get back to you.'\n"
    "[End transfer protocol]"
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_inactivity_timeout_seconds(value: Any) -> int:
    seconds = _to_int(value, settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS)
    return max(
        settings.MIN_INACTIVITY_TIMEOUT_SECONDS,
        min(settings.MAX_INACTIVITY_TIMEOUT_SECONDS, seconds),
    )


def _normalize_max_call_duration_seconds(value: Any) -> int:
    seconds = _to_int(value, settings.DEFAULT_MAX_CALL_DURATION_SECONDS)
    return max(
        settings.MIN_MAX_CALL_DURATION_SECONDS,
        min(settings.MAX_MAX_CALL_DURATION_SECONDS, seconds),
    )


def _timeout_protocol_addendum(
    inactivity_timeout_seconds: int,
    max_call_duration_seconds: int,
) -> str:
    max_minutes = round(max_call_duration_seconds / 60, 2)
    return (
        "\n\n[Call timeout protocol]\n"
        "Goal: protect caller minutes by ending unresponsive or runaway calls safely. "
        f"If the caller is silent for {inactivity_timeout_seconds} seconds total, end the call.\n"
        "Use this exact cadence when possible: after 8 seconds of silence ask "
        "'I can't hear you. Are you still there?'; after 18 seconds total silence warn "
        "'I'll end this call in a moment to save your minutes.'; end at the inactivity limit.\n"
        f"Also enforce a hard maximum call length of {max_minutes} minutes "
        f"({max_call_duration_seconds} seconds). "
        "When the maximum is reached, politely state that the account call limit was reached and end the call.\n"
        "If the caller gives a meaningful response, continue the call and reset silence handling.\n"
        "[End call timeout protocol]"
    )


def _upsert_timeout_protocol(
    prompt_text: str,
    inactivity_timeout_seconds: int,
    max_call_duration_seconds: int,
) -> str:
    block = _timeout_protocol_addendum(
        inactivity_timeout_seconds,
        max_call_duration_seconds,
    )
    existing = (prompt_text or "").strip()
    marker_start = "[Call timeout protocol]"
    marker_end = "[End call timeout protocol]"
    pattern = re.compile(
        re.escape(marker_start) + r".*?" + re.escape(marker_end),
        flags=re.DOTALL,
    )

    if marker_start in existing and marker_end in existing:
        return pattern.sub(block.strip(), existing).strip()
    return (existing + block).strip()


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


def _normalize_plan(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in PLAN_DEFINITIONS else DEFAULT_PLAN


def _serialize_plan(value: Optional[str]) -> Dict[str, Any]:
    return dict(PLAN_DEFINITIONS[_normalize_plan(value)])


def _count_client_callers(client_id: str, db: Any) -> int:
    return sum(
        1
        for _ in db.collection(CLIENTS_COLLECTION)
        .document(client_id)
        .collection(settings.FIRESTORE_PROFILE_COLLECTION)
        .stream()
    )


def _get_email_send_method(client_data: Dict[str, Any]) -> str:
    """Returns 'oauth' if Gmail OAuth is configured, 'fallback' if using app-password, else 'none'."""
    if client_data.get("gmail_refresh_token"):
        return "oauth"
    if settings.GMAIL_SENDER_EMAIL and settings.GMAIL_APP_PASSWORD:
        return "fallback"
    return "none"


def _fetch_client_calls(client_id: str, db: Any, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent calls for a client, sorted by date descending."""
    try:
        docs = (
            db.collection(CLIENTS_COLLECTION)
            .document(client_id)
            .collection("calls")
            .order_by("occurred_at", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        calls = []
        for doc in docs:
            data = doc.to_dict() or {}
            calls.append({
                "id": doc.id,
                "caller_phone": data.get("caller_number"),
                "intent": data.get("intent"),
                "duration_seconds": data.get("duration_seconds", 0),
                "duration_minutes": data.get("duration_minutes", 0),
                "occurred_at": data.get("occurred_at"),
                "ended_reason": data.get("ended_reason"),
                "transcript_summary": data.get("transcript_summary"),
            })
        return calls
    except Exception as e:
        logger.warning(f"Failed to fetch calls for {client_id}: {e}")
        return []


def _build_usage_summary(client_id: str, data: Dict[str, Any], db: Any) -> Dict[str, Any]:
    usage = data.get("usage") or {}
    plan = _serialize_plan(data.get("plan"))
    total_seconds = int(usage.get("total_seconds") or 0)
    monthly_seconds = int(usage.get("monthly_seconds") or 0)
    total_minutes = round(total_seconds / 60, 2)
    monthly_minutes = round(monthly_seconds / 60, 2)
    included_minutes = float(plan["included_minutes"])
    minutes_used = float(data.get("minutes_used") or monthly_minutes)
    overage_minutes = round(max(minutes_used - included_minutes, 0), 2)
    remaining_minutes = round(max(included_minutes - minutes_used, 0), 2)
    percent_used = round((minutes_used / included_minutes) * 100, 2) if included_minutes > 0 else 0.0
    return {
        "caller_count": _count_client_callers(client_id, db),
        "call_count": int(usage.get("call_count") or 0),
        "total_minutes": total_minutes,
        "monthly_minutes": monthly_minutes,
        "minutes_used": minutes_used,
        "included_minutes": plan["included_minutes"],
        "plan_limit_minutes": plan["included_minutes"],
        "percent_used": percent_used,
        "remaining_minutes": remaining_minutes,
        "overage_minutes": overage_minutes,
        "overage_rate": plan["overage_rate"],
        "billing_month": usage.get("billing_month"),
        "last_call_at": usage.get("last_call_at"),
    }


def _ensure_platform_client_document() -> None:
    platform_client_id = (settings.PLATFORM_CLIENT_ID or "").strip()
    if not platform_client_id:
        return
    db = get_firestore_client()
    if db is None:
        return
    doc_ref = db.collection(CLIENTS_COLLECTION).document(platform_client_id)
    snapshot = doc_ref.get()
    if snapshot.exists:
        return
    doc_ref.set(
        {
            "name": (settings.PLATFORM_CLIENT_NAME or "Bhuvi IT").strip() or "Bhuvi IT",
            "status": "active",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "channels": DEFAULT_CHANNELS,
            "sms_10dlc_approved": False,
            "forward_to_number": None,
            "inactivity_timeout_seconds": settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
            "max_call_duration_seconds": settings.DEFAULT_MAX_CALL_DURATION_SECONDS,
            "phone_number": (settings.PLATFORM_PHONE_NUMBER or "").strip() or None,
            "agent_id": (settings.PLATFORM_AGENT_ID or "").strip() or None,
            "system_client": True,
        },
        merge=True,
    )


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
    callers = []

    if client_id and client_id != "default":
        target_client_ids = [client_id]
    else:
        target_client_ids = [doc.id for doc in db.collection(CLIENTS_COLLECTION).stream()]

    for target_client_id in target_client_ids:
        collection = (
            db.collection(CLIENTS_COLLECTION)
            .document(target_client_id)
            .collection(settings.FIRESTORE_PROFILE_COLLECTION)
        )
        docs = collection.limit(500).stream()
        for doc in docs:
            data = doc.to_dict() or {}
            caller_intents = list((data.get("intents") or {}).keys())

            if intent and intent not in caller_intents:
                continue

            callers.append({
                "client_id": target_client_id,
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

    if not client_id or client_id == "default":
        raise HTTPException(status_code=400, detail="client_id is required for this endpoint.")

    collection = (
        db.collection(CLIENTS_COLLECTION)
        .document(client_id)
        .collection(settings.FIRESTORE_PROFILE_COLLECTION)
    )

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
    channels = data.get("channels") or DEFAULT_CHANNELS
    plan = _serialize_plan(data.get("plan"))
    # Never expose the hashed password or refresh token in the response
    return {
        "id": user.client_id,
        "name": data.get("name", ""),
        "phone_number": data.get("phone_number", ""),
        "website_url": data.get("website_url", ""),
        "gmail_email": data.get("gmail_email"),
        "gmail_connected": bool(data.get("gmail_refresh_token")),
        "email_send_method": _get_email_send_method(data),
        "status": normalize_client_status(data),
        "provisioning_error": data.get("provisioning_error"),
        "plan": plan,
        "usage": _build_usage_summary(user.client_id, data, db),
        "forward_to_number": data.get("forward_to_number"),
        "channels": {**DEFAULT_CHANNELS, **channels},
        "sms_10dlc_approved": bool(data.get("sms_10dlc_approved", False)),
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


@router.get("/me/calls")
async def me_list_calls(
    limit: int = 50,
    user: UserContext = Depends(require_client),
) -> List[Dict[str, Any]]:
    db = get_firestore_client()
    if db is None:
        return []
    return _fetch_client_calls(user.client_id, db, limit=min(limit, 500))


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


@router.get("/me/agent")
async def me_get_agent(user: UserContext = Depends(require_client)) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")
    doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")
    agent_id = (doc.to_dict() or {}).get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="No agent has been provisioned yet.")

    agent = await _fetch_elevenlabs_agent(agent_id)
    prompt_cfg = (
        (agent.get("conversation_config", {}) or {})
        .get("agent", {}) or {}
    ).get("prompt", {}) or {}
    return {
        "agent_id": agent_id,
        "name": agent.get("name", ""),
        "prompt": prompt_cfg.get("prompt", ""),
    }


@router.post("/me/agent")
async def me_update_agent(
    payload: Dict[str, Any] = Body(...),
    user: UserContext = Depends(require_client),
) -> Dict[str, Any]:
    prompt_text = (payload.get("prompt") or "").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")
    doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")
    client_data = doc.to_dict() or {}
    agent_id = client_data.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="No agent has been provisioned yet.")

    prompt_with_timeouts = _upsert_timeout_protocol(
        prompt_text,
        _normalize_inactivity_timeout_seconds(client_data.get("inactivity_timeout_seconds")),
        _normalize_max_call_duration_seconds(client_data.get("max_call_duration_seconds")),
    )
    await _update_elevenlabs_agent_prompt(agent_id, prompt_with_timeouts)
    return {"status": "saved", "prompt": prompt_with_timeouts}


@router.get("/me/settings")
async def me_get_settings(user: UserContext = Depends(require_client)) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        return {}

    doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
    if not doc.exists:
        return {}

    data = doc.to_dict() or {}
    channels = data.get("channels") or DEFAULT_CHANNELS
    return {
        "sms_job_seeker": data.get("sms_job_seeker", ""),
        "sms_sales": data.get("sms_sales", ""),
        "intent_labels": data.get("intent_labels", {}),
        "forward_to_number": data.get("forward_to_number", ""),
        "inactivity_timeout_seconds": _normalize_inactivity_timeout_seconds(
            data.get("inactivity_timeout_seconds")
        ),
        "max_call_duration_seconds": _normalize_max_call_duration_seconds(
            data.get("max_call_duration_seconds")
        ),
        "channels": {**DEFAULT_CHANNELS, **channels},
        "sms_10dlc_approved": bool(data.get("sms_10dlc_approved", False)),
    }


@router.post("/me/settings")
async def me_save_settings(
    payload: Dict[str, Any] = Body(...),
    user: UserContext = Depends(require_client),
) -> Dict[str, Any]:
    allowed = {
        "sms_job_seeker",
        "sms_sales",
        "intent_labels",
        "forward_to_number",
        "channels",
        "inactivity_timeout_seconds",
        "max_call_duration_seconds",
    }
    data: Dict[str, Any] = {}
    for key in allowed:
        if key not in payload:
            continue
        value = payload[key]
        if key == "forward_to_number":
            value = (value or "").strip() or None
        elif key == "inactivity_timeout_seconds":
            raw = _to_int(value, settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS)
            if (
                raw < settings.MIN_INACTIVITY_TIMEOUT_SECONDS
                or raw > settings.MAX_INACTIVITY_TIMEOUT_SECONDS
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "inactivity_timeout_seconds must be between "
                        f"{settings.MIN_INACTIVITY_TIMEOUT_SECONDS} and "
                        f"{settings.MAX_INACTIVITY_TIMEOUT_SECONDS}."
                    ),
                )
            value = raw
        elif key == "max_call_duration_seconds":
            raw = _to_int(value, settings.DEFAULT_MAX_CALL_DURATION_SECONDS)
            if (
                raw < settings.MIN_MAX_CALL_DURATION_SECONDS
                or raw > settings.MAX_MAX_CALL_DURATION_SECONDS
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "max_call_duration_seconds must be between "
                        f"{settings.MIN_MAX_CALL_DURATION_SECONDS} and "
                        f"{settings.MAX_MAX_CALL_DURATION_SECONDS}."
                    ),
                )
            value = raw
        elif key == "channels" and isinstance(value, dict):
            value = {
                "email": bool(value.get("email", True)),
                "sms": bool(value.get("sms", False)),
            }
        data[key] = value

    if not data:
        raise HTTPException(status_code=400, detail="No valid settings fields provided.")

    # Clients cannot flip the 10DLC gate — SMS stays off until admin approves
    if isinstance(data.get("channels"), dict) and data["channels"].get("sms"):
        db_check = get_firestore_client()
        approved = False
        if db_check is not None:
            _snapshot = db_check.collection(CLIENTS_COLLECTION).document(user.client_id).get()
            approved = bool((_snapshot.to_dict() or {}).get("sms_10dlc_approved"))
        if not approved:
            data["channels"]["sms"] = False

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    db.collection(CLIENTS_COLLECTION).document(user.client_id).set(data, merge=True)

    if {
        "forward_to_number",
        "inactivity_timeout_seconds",
        "max_call_duration_seconds",
    }.intersection(data.keys()):
        client_doc = db.collection(CLIENTS_COLLECTION).document(user.client_id).get()
        client_data = client_doc.to_dict() or {}
        agent_id = client_data.get("agent_id") if client_doc.exists else None
        if agent_id:
            if "forward_to_number" in data:
                try:
                    await _patch_agent_transfer_tool(agent_id, data["forward_to_number"])
                except Exception as exc:
                    logger.warning("Transfer tool patch failed (non-fatal): %s", exc)
            try:
                await _patch_agent_timeout_protocol(
                    agent_id,
                    _normalize_inactivity_timeout_seconds(
                        client_data.get("inactivity_timeout_seconds")
                    ),
                    _normalize_max_call_duration_seconds(
                        client_data.get("max_call_duration_seconds")
                    ),
                )
            except Exception as exc:
                logger.warning("Timeout protocol patch failed (non-fatal): %s", exc)

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


def _send_followup_tool_config() -> Optional[Dict[str, Any]]:
    """ElevenLabs webhook tool definition for the in-call send_followup action."""
    if not settings.PUBLIC_BASE_URL or not settings.TOOL_SECRET:
        return None
    return {
        "type": "webhook",
        "name": "send_followup",
        "description": (
            "Send a follow-up email to the caller. The agent composes "
            "email_body itself (plain text, max 5 sentences, confirmed facts "
            "only). Only call after the caller confirms, once per call."
        ),
        "api_schema": {
            "url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/tools/send-followup",
            "method": "POST",
            "request_headers": {"X-Tool-Secret": settings.TOOL_SECRET},
            "request_body_schema": {
                "type": "object",
                "required": ["caller_email", "email_body"],
                "properties": {
                    "caller_email": {"type": "string", "description": "Caller's email address"},
                    "email_subject": {"type": "string", "description": "Optional email subject line"},
                    "email_body": {"type": "string", "description": "Email body in plain text (max 5 sentences)"},
                    "caller_number": {"type": "string", "description": "Caller's phone number"},
                    "intent": {"type": "string", "description": "Call intent or category"},
                    "client_id": {"type": "string", "description": "Client identifier"},
                    "agent_id": {"type": "string", "description": "Agent identifier"},
                    "conversation_id": {"type": "string", "description": "ElevenLabs conversation ID"},
                    "call_sid": {"type": "string", "description": "Twilio call SID"},
                },
            },
        },
    }


def _inject_send_followup_tool(prompt_cfg: Dict[str, Any]) -> None:
    """Adds the send_followup webhook tool to the agent's tool list without
    dropping any tools already present on the template (e.g. transfer_to_number)."""
    tool = _send_followup_tool_config()
    if not tool:
        logger.warning(
            "send_followup tool not injected — PUBLIC_BASE_URL or TOOL_SECRET is missing."
        )
        return

    tools = list(prompt_cfg.get("tools") or [])
    tools = [t for t in tools if (isinstance(t, dict) and t.get("name") != "send_followup")]
    tools.append(tool)
    prompt_cfg["tools"] = tools


async def _create_elevenlabs_agent(name: str, template: Dict[str, Any], kb_id: str) -> str:
    """Clones the template agent for a new client with their KB. Returns agent_id."""
    conversation_config = template.get("conversation_config", {}) or {}
    agent_cfg = conversation_config.get("agent", {}) or {}
    prompt_cfg = agent_cfg.get("prompt", {}) or {}
    prompt_cfg["knowledge_base"] = [{"type": "url", "name": name, "id": kb_id}]

    existing_prompt = (prompt_cfg.get("prompt") or "").rstrip()
    if "[Email follow-up protocol]" not in existing_prompt:
        prompt_cfg["prompt"] = existing_prompt + FOLLOWUP_PROMPT_ADDENDUM
    prompt_cfg["prompt"] = _upsert_timeout_protocol(
        prompt_cfg.get("prompt") or "",
        settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
        settings.DEFAULT_MAX_CALL_DURATION_SECONDS,
    )

    _inject_send_followup_tool(prompt_cfg)

    agent_cfg["prompt"] = prompt_cfg
    conversation_config["agent"] = agent_cfg

    # Carry over platform_settings (auth, widget, voice, overrides) from the
    # template. Without this, the cloned agent defaults to settings that can
    # reject the inbound Twilio stream.
    payload: Dict[str, Any] = {
        "name": f"{name} — VoiceConnect",
        "conversation_config": conversation_config,
    }
    if template.get("platform_settings"):
        payload["platform_settings"] = template["platform_settings"]
    if template.get("tags"):
        payload["tags"] = template["tags"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ELEVENLABS_BASE}/convai/agents/create",
            headers=_el_headers(),
            json=payload,
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"ElevenLabs agent creation failed: {resp.text}")
        return resp.json()["agent_id"]


async def _register_phone_with_elevenlabs(phone_number: str, label: str) -> str:
    """Imports a Twilio number into ElevenLabs' native integration. Returns phone_number_id."""
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="Twilio credentials are not configured.")
    payload = {
        "phone_number": phone_number,
        "label": label,
        "sid": settings.TWILIO_ACCOUNT_SID,
        "token": settings.TWILIO_AUTH_TOKEN,
        "provider": "twilio",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ELEVENLABS_BASE}/convai/phone-numbers",
            headers=_el_headers(),
            json=payload,
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"ElevenLabs phone-number import failed: {resp.text}",
            )
        body = resp.json() or {}
        return body.get("phone_number_id") or body.get("id") or ""


async def _attach_agent_to_phone(phone_number_id: str, agent_id: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{ELEVENLABS_BASE}/convai/phone-numbers/{phone_number_id}",
            headers=_el_headers(),
            json={"agent_id": agent_id},
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"Assigning agent to phone failed: {resp.text}",
            )


async def _delete_elevenlabs_phone_number(phone_number_id: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{ELEVENLABS_BASE}/convai/phone-numbers/{phone_number_id}",
            headers=_el_headers(),
            timeout=30,
        )


async def _fetch_elevenlabs_agent(agent_id: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{ELEVENLABS_BASE}/convai/agents/{agent_id}",
            headers=_el_headers(),
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"Failed to fetch agent: {resp.text}")
        return resp.json()


async def _update_elevenlabs_agent_prompt(agent_id: str, prompt_text: str) -> None:
    """Updates only the prompt text of an existing agent, leaving other config alone."""
    current = await _fetch_elevenlabs_agent(agent_id)
    conversation_config = current.get("conversation_config", {}) or {}
    agent_cfg = conversation_config.get("agent", {}) or {}
    prompt_cfg = agent_cfg.get("prompt", {}) or {}
    prompt_cfg["prompt"] = prompt_text
    agent_cfg["prompt"] = prompt_cfg
    conversation_config["agent"] = agent_cfg

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{ELEVENLABS_BASE}/convai/agents/{agent_id}",
            headers=_el_headers(),
            json={"conversation_config": conversation_config},
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"Agent update failed: {resp.text}")


async def _patch_agent_transfer_tool(agent_id: str, forward_to_number: Optional[str]) -> None:
    """Set or remove the transfer_to_number system tool on an existing agent.
    forward_to_number=None removes the tool; a literal E.164 number adds/replaces it."""
    current = await _fetch_elevenlabs_agent(agent_id)
    conversation_config = current.get("conversation_config", {}) or {}
    agent_cfg = conversation_config.get("agent", {}) or {}
    prompt_cfg = agent_cfg.get("prompt", {}) or {}

    tools = [
        t for t in (prompt_cfg.get("tools") or [])
        if not (isinstance(t, dict) and t.get("name") == "transfer_to_number")
    ]
    if forward_to_number:
        tools.append({
            "type": "system",
            "name": "transfer_to_number",
            "description": "Transfer the call to a human agent when the caller explicitly requests it.",
            "params": {
                "system_tool_type": "phone_transfer",
                "phone_number": forward_to_number,
            },
        })
    prompt_cfg["tools"] = tools
    agent_cfg["prompt"] = prompt_cfg
    conversation_config["agent"] = agent_cfg

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{ELEVENLABS_BASE}/convai/agents/{agent_id}",
            headers=_el_headers(),
            json={"conversation_config": conversation_config},
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=502, detail=f"Agent transfer tool update failed: {resp.text}")


async def _patch_agent_timeout_protocol(
    agent_id: str,
    inactivity_timeout_seconds: int,
    max_call_duration_seconds: int,
) -> None:
    """Inject/update timeout prompt text and apply native timeout config fields."""
    current = await _fetch_elevenlabs_agent(agent_id)
    conversation_config = current.get("conversation_config", {}) or {}
    agent_cfg = conversation_config.get("agent", {}) or {}
    prompt_cfg = agent_cfg.get("prompt", {}) or {}
    turn_cfg = conversation_config.get("turn", {}) or {}
    conversation_limits_cfg = conversation_config.get("conversation", {}) or {}

    normalized_inactivity_seconds = _normalize_inactivity_timeout_seconds(inactivity_timeout_seconds)
    normalized_max_duration_seconds = _normalize_max_call_duration_seconds(max_call_duration_seconds)

    prompt_cfg["prompt"] = _upsert_timeout_protocol(
        prompt_cfg.get("prompt") or "",
        normalized_inactivity_seconds,
        normalized_max_duration_seconds,
    )

    turn_cfg["silence_end_call_timeout"] = normalized_inactivity_seconds
    soft_timeout_cfg = turn_cfg.get("soft_timeout_config", {}) or {}
    soft_timeout_cfg["timeout_seconds"] = 8
    soft_timeout_cfg["message"] = "I can't hear you. Are you still there?"
    turn_cfg["soft_timeout_config"] = soft_timeout_cfg

    conversation_limits_cfg["max_duration_seconds"] = normalized_max_duration_seconds

    agent_cfg["prompt"] = prompt_cfg
    conversation_config["agent"] = agent_cfg
    conversation_config["turn"] = turn_cfg
    conversation_config["conversation"] = conversation_limits_cfg

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{ELEVENLABS_BASE}/convai/agents/{agent_id}",
            headers=_el_headers(),
            json={"conversation_config": conversation_config},
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(
                status_code=502,
                detail=f"Agent timeout protocol update failed: {resp.text}",
            )


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
            f"{ELEVENLABS_BASE}/convai/knowledge-base/url",
            headers=_el_headers(),
            json={"name": name, "url": url},
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
    """Searches for and purchases a Twilio number. Accepts area code or ZIP/postal code."""
    client = _twilio_client()
    hint = (area_code or "").strip()

    # Build attempts: prefer what the user typed, fall back to the other form.
    attempts: list[Dict[str, Any]] = []
    if hint.isdigit() and len(hint) == 5:
        attempts.append({"in_postal_code": hint})
    elif hint.isdigit() and len(hint) == 3:
        attempts.append({"area_code": hint})
    elif hint:
        attempts.append({"in_postal_code": hint})
        attempts.append({"area_code": hint})
    attempts.append({})  # any number

    available = []
    last_error: Optional[Exception] = None
    for extra in attempts:
        try:
            available = (
                client.available_phone_numbers(country)
                .local.list(limit=1, **extra)
            )
        except Exception as exc:
            last_error = exc
            continue
        if available:
            break

    if not available:
        if last_error and not hint:
            raise HTTPException(status_code=502, detail=f"Twilio number search failed: {last_error}")
        raise HTTPException(
            status_code=404,
            detail=f"No available numbers found for '{hint}'." if hint
                   else "No available numbers found.",
        )

    phone_number = available[0].phone_number
    try:
        client.incoming_phone_numbers.create(phone_number=phone_number)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Twilio number purchase failed: {exc}")

    return phone_number


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
    _ensure_platform_client_document()
    db = get_firestore_client()
    if db is None:
        return []
    docs = db.collection(CLIENTS_COLLECTION).order_by("created_at", direction="DESCENDING").limit(100).stream()
    clients = []
    for doc in docs:
        data = doc.to_dict() or {}
        channels = data.get("channels") or DEFAULT_CHANNELS
        plan = _serialize_plan(data.get("plan"))
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
            "plan": plan,
            "usage": _build_usage_summary(doc.id, data, db),
            "minutes_used": float(data.get("minutes_used") or 0),
            "gmail_email": data.get("gmail_email"),
            "gmail_connected": bool(data.get("gmail_refresh_token")),
            "forward_to_number": data.get("forward_to_number"),
            "channels": {**DEFAULT_CHANNELS, **channels},
            "sms_10dlc_approved": bool(data.get("sms_10dlc_approved", False)),
        })
    return clients


@router.post("/api/clients", status_code=201)
async def add_client(
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
        "plan": _normalize_plan(payload.get("plan")),
        "channels": DEFAULT_CHANNELS,
        "sms_10dlc_approved": False,
        "forward_to_number": None,
        "minutes_used": 0,
        "inactivity_timeout_seconds": settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
        "max_call_duration_seconds": settings.DEFAULT_MAX_CALL_DURATION_SECONDS,
    }
    doc_ref.set(data)

    # 5. Hand the Twilio number to ElevenLabs native integration and bind the agent
    el_phone_number_id = await _register_phone_with_elevenlabs(
        phone_number, f"{name} — VoiceConnect"
    )
    doc_ref.update({"el_phone_number_id": el_phone_number_id})
    await _attach_agent_to_phone(el_phone_number_id, agent_id)

    return {
        "id": doc_ref.id,
        "name": name,
        "website_url": url,
        "phone_number": phone_number,
        "country": country,
        "email": email,
        "created_at": data["created_at"],
    }


def _serialize_client(client_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    channels = data.get("channels") or DEFAULT_CHANNELS
    db = get_firestore_client()
    plan = _serialize_plan(data.get("plan"))
    return {
        "id": client_id,
        "name": data.get("name", ""),
        "website_url": data.get("website_url", ""),
        "email": data.get("email", ""),
        "phone_number": data.get("phone_number", ""),
        "country": data.get("country", ""),
        "area_code": data.get("area_code", ""),
        "created_at": data.get("created_at", ""),
        "status": normalize_client_status(data),
        "provisioning_error": data.get("provisioning_error"),
        "plan": plan,
        "usage": _build_usage_summary(client_id, data, db) if db is not None else {
            "caller_count": 0,
            "call_count": 0,
            "total_minutes": 0,
            "monthly_minutes": 0,
            "included_minutes": plan["included_minutes"],
            "remaining_minutes": plan["included_minutes"],
            "overage_minutes": 0,
            "overage_rate": plan["overage_rate"],
            "billing_month": None,
            "last_call_at": None,
        },
        "gmail_email": data.get("gmail_email"),
        "gmail_connected": bool(data.get("gmail_refresh_token")),
        "minutes_used": float(data.get("minutes_used") or 0),
        "forward_to_number": data.get("forward_to_number"),
        "inactivity_timeout_seconds": _normalize_inactivity_timeout_seconds(
            data.get("inactivity_timeout_seconds")
        ),
        "max_call_duration_seconds": _normalize_max_call_duration_seconds(
            data.get("max_call_duration_seconds")
        ),
        "channels": {**DEFAULT_CHANNELS, **channels},
        "sms_10dlc_approved": bool(data.get("sms_10dlc_approved", False)),
    }


@router.get("/api/clients/{client_id}")
async def get_client(
    client_id: str,
    _: UserContext = Depends(require_admin_flexible),
) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")
    doc = db.collection(CLIENTS_COLLECTION).document(client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")
    return _serialize_client(client_id, doc.to_dict() or {})


@router.get("/api/clients/{client_id}/calls")
async def get_client_calls(
    client_id: str,
    limit: int = 50,
    _: UserContext = Depends(require_admin_flexible),
) -> List[Dict[str, Any]]:
    """Fetch recent calls for a client (admin only)."""
    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")
    doc = db.collection(CLIENTS_COLLECTION).document(client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")
    return _fetch_client_calls(client_id, db, limit=min(limit, 500))


@router.patch("/api/clients/{client_id}")
async def update_client(
    client_id: str,
    payload: Dict[str, Any] = Body(...),
    _: UserContext = Depends(require_admin_flexible),
) -> Dict[str, Any]:
    allowed = {
        "name",
        "website_url",
        "area_code",
        "country",
        "plan",
        "forward_to_number",
        "inactivity_timeout_seconds",
        "max_call_duration_seconds",
        "channels",
        "sms_10dlc_approved",
    }
    update_data: Dict[str, Any] = {}
    for key in allowed:
        if key not in payload:
            continue
        value = payload.get(key)
        if key == "sms_10dlc_approved":
            update_data[key] = bool(value)
            continue
        if key == "inactivity_timeout_seconds":
            raw = _to_int(value, settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS)
            if (
                raw < settings.MIN_INACTIVITY_TIMEOUT_SECONDS
                or raw > settings.MAX_INACTIVITY_TIMEOUT_SECONDS
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "inactivity_timeout_seconds must be between "
                        f"{settings.MIN_INACTIVITY_TIMEOUT_SECONDS} and "
                        f"{settings.MAX_INACTIVITY_TIMEOUT_SECONDS}."
                    ),
                )
            update_data[key] = raw
            continue
        if key == "max_call_duration_seconds":
            raw = _to_int(value, settings.DEFAULT_MAX_CALL_DURATION_SECONDS)
            if (
                raw < settings.MIN_MAX_CALL_DURATION_SECONDS
                or raw > settings.MAX_MAX_CALL_DURATION_SECONDS
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "max_call_duration_seconds must be between "
                        f"{settings.MIN_MAX_CALL_DURATION_SECONDS} and "
                        f"{settings.MAX_MAX_CALL_DURATION_SECONDS}."
                    ),
                )
            update_data[key] = raw
            continue
        if key == "plan":
            update_data[key] = _normalize_plan(str(value or ""))
            continue
        if key == "channels" and isinstance(value, dict):
            update_data[key] = {
                "email": bool(value.get("email", True)),
                "sms": bool(value.get("sms", False)),
            }
            continue
        if isinstance(value, str):
            value = value.strip()
            if key == "country":
                value = value.upper()
        update_data[key] = value or None
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update.")

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")
    doc_ref = db.collection(CLIENTS_COLLECTION).document(client_id)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Client not found.")
    doc_ref.update(update_data)

    if {
        "forward_to_number",
        "inactivity_timeout_seconds",
        "max_call_duration_seconds",
    }.intersection(update_data.keys()):
        updated_data = doc_ref.get().to_dict() or {}
        agent_id = updated_data.get("agent_id")
        if agent_id:
            if "forward_to_number" in update_data:
                try:
                    await _patch_agent_transfer_tool(agent_id, update_data["forward_to_number"])
                except Exception as exc:
                    logger.warning("Transfer tool patch failed (non-fatal): %s", exc)
            try:
                await _patch_agent_timeout_protocol(
                    agent_id,
                    _normalize_inactivity_timeout_seconds(
                        updated_data.get("inactivity_timeout_seconds")
                    ),
                    _normalize_max_call_duration_seconds(
                        updated_data.get("max_call_duration_seconds")
                    ),
                )
            except Exception as exc:
                logger.warning("Timeout protocol patch failed (non-fatal): %s", exc)

    return _serialize_client(client_id, doc_ref.get().to_dict() or {})


@router.post("/api/clients/{client_id}/provision")
async def provision_client(
    client_id: str,
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

    doc_ref = db.collection(CLIENTS_COLLECTION).document(client_id)

    # Reuse any resources already created for this client — retries after a
    # partial failure must not create duplicates on ElevenLabs/Twilio.
    kb_id: Optional[str] = data.get("kb_id") or None
    agent_id: Optional[str] = data.get("agent_id") or None
    phone_number: Optional[str] = data.get("phone_number") or None
    el_phone_number_id: Optional[str] = data.get("el_phone_number_id") or None

    try:
        if not kb_id:
            kb_id = await _create_elevenlabs_kb(name, url)
            doc_ref.update({"kb_id": kb_id})
        if not agent_id:
            template = await _get_template_agent()
            agent_id = await _create_elevenlabs_agent(name, template, kb_id)
            doc_ref.update({"agent_id": agent_id})
        if not phone_number:
            phone_number = _buy_twilio_number(area_code, country)
            doc_ref.update({"phone_number": phone_number})
        if not el_phone_number_id:
            el_phone_number_id = await _register_phone_with_elevenlabs(
                phone_number, f"{name} — VoiceConnect"
            )
            doc_ref.update({"el_phone_number_id": el_phone_number_id})

        await _attach_agent_to_phone(el_phone_number_id, agent_id)

        await _patch_agent_timeout_protocol(
            agent_id,
            _normalize_inactivity_timeout_seconds(data.get("inactivity_timeout_seconds")),
            _normalize_max_call_duration_seconds(data.get("max_call_duration_seconds")),
        )

        doc_ref.update({
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
            "plan": _serialize_plan(data.get("plan")),
            "usage": _build_usage_summary(client_id, doc_ref.get().to_dict() or {}, db),
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
    if data.get("el_phone_number_id"):
        await _delete_elevenlabs_phone_number(data["el_phone_number_id"])
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
    allowed = {"sms_job_seeker", "sms_sales", "intent_labels"}
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
