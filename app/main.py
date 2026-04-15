# app/main.py
import datetime as dt
import json
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from app.config import settings
from app.dashboard import router as dashboard_router
from app.notifications import (
    send_email_followup,
    send_whatsapp_followup,
)
from app.schemas import (
    ElevenLabsInitiateRequest,
    ElevenLabsInitiateResponse,
    ElevenLabsPostCallWebhook,
    HealthResponse,
)
from app.services.profile_services import ProfileService, get_firestore_client

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)
app.include_router(dashboard_router)


def _clean_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _normalize_intent(value: Optional[str]) -> str:
    raw_value = _clean_string(value)
    if not raw_value:
        return "GENERAL_INQUIRY"

    normalized = raw_value.upper().replace("-", "_").replace(" ", "_")
    if normalized == "CLIENT_LEAD":
        return "US_STAFFING"
    return normalized


def _normalize_contact_preference(value: Optional[str]) -> Optional[str]:
    normalized = _clean_string(value)
    if not normalized:
        return None

    lowered = normalized.lower()
    if "mail" in lowered:
        return "email"
    if "whatsapp" in lowered or "whats app" in lowered:
        return "whatsapp"
    if lowered in {"sms", "text", "message"}:
        return "whatsapp"
    return lowered


def _unwrap_collected_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        for item in value:
            unwrapped = _unwrap_collected_value(item)
            if _clean_string(unwrapped) is not None:
                return unwrapped
        return None

    if isinstance(value, dict):
        for key in (
            "value",
            "result",
            "answer",
            "normalized_value",
            "text",
            "string",
        ):
            if key in value:
                return _unwrap_collected_value(value[key])
        if len(value) == 1:
            return _unwrap_collected_value(next(iter(value.values())))

    return None


def _first_scalar(data: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        if key not in data:
            continue
        candidate = _clean_string(_unwrap_collected_value(data.get(key)))
        if candidate is not None:
            return candidate
    return None


def _get_profile_value(profile: Dict[str, Any], key: str) -> Optional[str]:
    direct_value = _clean_string(profile.get(key))
    if direct_value:
        return direct_value

    intents = profile.get("intents")
    if isinstance(intents, dict):
        last_intent = _normalize_intent(profile.get("last_intent"))
        if last_intent in intents and isinstance(intents[last_intent], dict):
            nested_value = _clean_string(intents[last_intent].get(key))
            if nested_value:
                return nested_value

        for intent_data in intents.values():
            if isinstance(intent_data, dict):
                nested_value = _clean_string(intent_data.get(key))
                if nested_value:
                    return nested_value
    return None


def _normalize_scalar_entities(data_collection_results: Dict[str, Any]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in data_collection_results.items():
        cleaned = _clean_string(_unwrap_collected_value(value))
        if cleaned is not None:
            normalized[key] = cleaned
    return normalized


def _extract_profile_entities(
    event: ElevenLabsPostCallWebhook,
) -> tuple[str, str, Dict[str, str], Dict[str, Any]]:
    data_collection_results = event.data.analysis.data_collection_results or {}
    dynamic_variables = (
        event.data.conversation_initiation_client_data.dynamic_variables or {}
    )
    metadata = event.data.metadata or {}
    metadata_body = metadata.get("body", {}) if isinstance(metadata.get("body"), dict) else {}

    logger.info(
        "post-call data_collection_results: %s",
        json.dumps(data_collection_results, default=str),
    )

    entities = _normalize_scalar_entities(data_collection_results)

    caller_number = (
        _first_scalar(entities, "phone", "phone_number", "mobile_number")
        or _first_scalar(dynamic_variables, "caller_id", "system__caller_id")
        or _first_scalar(metadata_body, "From", "Caller")
        or _first_scalar(metadata, "from_number", "caller_id")
    )
    if not caller_number:
        raise HTTPException(
            status_code=400,
            detail="Caller phone number was not present in the ElevenLabs payload.",
        )

    intent = _normalize_intent(
        _first_scalar(
            entities,
            "branch",
            "intent",
            "call_intent",
            "job_intent",
            "conversation_intent",
        )
        or _first_scalar(dynamic_variables, "branch", "intent", "last_intent")
    )

    canonical_overrides = {
        "name": _first_scalar(
            entities,
            "name",
            "full_name",
            "candidate_name",
            "caller_name",
        ),
        "phone_number": caller_number,
        "email_address": _first_scalar(entities, "email", "email_address"),
        "role_interest": _first_scalar(
            entities,
            "job_type",
            "job_role",
            "role_interest",
            "role",
            "position",
        ),
        "experience_years": _first_scalar(
            entities,
            "experience_years",
            "years_of_experience",
        ),
        "contact_preference": _normalize_contact_preference(
            _first_scalar(
                entities,
                "contact_preference",
                "preferred_contact_method",
                "contact_method",
            )
        ),
        "caller_country": _first_scalar(
            entities,
            "caller_country",
            "country",
        )
        or _first_scalar(dynamic_variables, "caller_country"),
        "caller_state": _first_scalar(
            entities,
            "caller_state",
            "state",
            "region",
        )
        or _first_scalar(dynamic_variables, "caller_state"),
        "branch": intent,
        "transcript_summary": _clean_string(event.data.analysis.transcript_summary),
        "conversation_id": _clean_string(event.data.conversation_id),
        "call_sid": _first_scalar(dynamic_variables, "call_sid")
        or _first_scalar(metadata_body, "CallSid")
        or _first_scalar(metadata, "call_sid"),
    }

    entities.update({k: v for k, v in canonical_overrides.items() if v is not None})

    follow_up_context = {
        "caller_number": caller_number,
        "intent": intent,
        "call_sid": entities.get("call_sid") or event.data.conversation_id,
        "conversation_id": event.data.conversation_id,
    }
    return caller_number, intent, entities, follow_up_context


def _build_profile_dynamic_variables(profile: Dict[str, Any]) -> Dict[str, Any]:
    dynamic_variables: Dict[str, Any] = {}

    caller_country = _get_profile_value(profile, "caller_country") or "Unknown"
    caller_state = _get_profile_value(profile, "caller_state") or "Unknown"

    dynamic_variables["caller_country"] = caller_country
    dynamic_variables["caller_state"] = caller_state
    dynamic_variables["existing_profile_json"] = json.dumps(profile or {}, default=str)

    last_intent = _normalize_intent(profile.get("last_intent"))
    if last_intent != "GENERAL_INQUIRY" or profile.get("last_intent"):
        dynamic_variables["last_intent"] = last_intent

    latest_intent_data = {}
    intents = profile.get("intents")
    if isinstance(intents, dict) and last_intent in intents and isinstance(intents[last_intent], dict):
        latest_intent_data = intents[last_intent]

    for key, value in latest_intent_data.items():
        cleaned = _clean_string(value)
        if cleaned is not None:
            dynamic_variables[key] = cleaned

    for key, value in profile.items():
        if key == "intents":
            continue
        cleaned = _clean_string(value)
        if cleaned is not None:
            dynamic_variables.setdefault(f"profile__{key}", cleaned)

    return dynamic_variables


def _log_failed_notification(
    *,
    caller_number: str,
    call_sid: str,
    preferred_method: str,
    reason: str,
    email_address: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> None:
    db = get_firestore_client()
    if db is None:
        logger.warning("Firestore unavailable; failed notification was not persisted.")
        return

    payload: Dict[str, Any] = {
        "caller_number": caller_number,
        "call_sid": call_sid,
        "preferred_method": preferred_method,
        "reason": reason,
        "timestamp": _utc_now_iso(),
    }
    if email_address:
        payload["email_address"] = email_address
    if conversation_id:
        payload["conversation_id"] = conversation_id

    db.collection(settings.FIRESTORE_FAILED_NOTIFICATION_COLLECTION).add(payload)


def _trigger_follow_up(
    *,
    caller_number: str,
    entities: Dict[str, str],
    existing_profile: Dict[str, Any],
    call_sid: str,
    conversation_id: Optional[str],
) -> Dict[str, str]:
    contact_preference = _normalize_contact_preference(
        entities.get("contact_preference") or _get_profile_value(existing_profile, "contact_preference")
    )

    if contact_preference == "email":
        email_address = entities.get("email_address") or _get_profile_value(
            existing_profile,
            "email_address",
        )
        if not email_address:
            reason = "Email follow-up requested but no email address was available."
            _log_failed_notification(
                caller_number=caller_number,
                call_sid=call_sid,
                preferred_method="email",
                reason=reason,
                conversation_id=conversation_id,
            )
            return {"status": "failed", "channel": "email", "reason": reason}

        try:
            send_email_followup(email_address)
            return {"status": "sent", "channel": "email", "target": email_address}
        except Exception as exc:
            _log_failed_notification(
                caller_number=caller_number,
                call_sid=call_sid,
                preferred_method="email",
                reason=str(exc),
                email_address=email_address,
                conversation_id=conversation_id,
            )
            return {"status": "failed", "channel": "email", "reason": str(exc)}

    if contact_preference == "whatsapp":
        try:
            send_whatsapp_followup(caller_number)
            return {"status": "sent", "channel": "whatsapp", "target": caller_number}
        except Exception as exc:
            _log_failed_notification(
                caller_number=caller_number,
                call_sid=call_sid,
                preferred_method="whatsapp",
                reason=str(exc),
                conversation_id=conversation_id,
            )
            return {"status": "failed", "channel": "whatsapp", "reason": str(exc)}

    return {
        "status": "skipped",
        "channel": contact_preference or "unknown",
        "reason": "No supported contact preference was available.",
    }


async def _parse_request_payload(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        return dict(form)

    body = await request.body()
    if not body:
        return {}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid request payload.") from exc

    return payload if isinstance(payload, dict) else {}


@app.post("/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request) -> Dict[str, Any]:
    payload = await _parse_request_payload(request)
    try:
        event = ElevenLabsPostCallWebhook.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    caller_number, intent, entities, follow_up_context = _extract_profile_entities(event)

    profile_service = ProfileService()
    existing_profile = profile_service.get_profile(caller_number) or {}

    shared_data = {
        "last_intent": intent,
        "last_interaction": _utc_now_iso(),
    }
    if not existing_profile.get("created_at"):
        shared_data["created_at"] = _utc_now_iso()

    profile_service.update_profile_for_intent(
        caller_number,
        intent,
        entities,
        shared_data,
    )

    merged_profile = profile_service.get_profile(caller_number) or {}

    logger.info(
        "follow-up decision — intent=%s contact_preference=%s email_address=%s",
        intent,
        entities.get("contact_preference"),
        entities.get("email_address"),
    )

    follow_up_result = _trigger_follow_up(
        caller_number=caller_number,
        entities=entities,
        existing_profile=merged_profile,
        call_sid=follow_up_context["call_sid"],
        conversation_id=follow_up_context["conversation_id"],
    )

    logger.info("follow-up result: %s", follow_up_result)

    return {
        "status": "processed",
        "caller_number": caller_number,
        "intent": intent,
        "follow_up": follow_up_result,
        "conversation_id": follow_up_context["conversation_id"],
    }


@app.post(
    "/elevenlabs/initiate",
    response_model=ElevenLabsInitiateResponse,
    response_model_exclude_none=True,
)
async def elevenlabs_initiate(request: Request) -> ElevenLabsInitiateResponse:
    payload = await _parse_request_payload(request)
    try:
        initiation_request = ElevenLabsInitiateRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    # Prefer nested custom_parameters (Twilio Function path); fall back to flat fields
    cp = None
    if initiation_request.conversation_initiation_client_data:
        cp = initiation_request.conversation_initiation_client_data.custom_parameters

    caller_number = (
        _clean_string(cp.caller_number if cp else None)
        or _clean_string(cp.caller_id if cp else None)
        or _clean_string(initiation_request.caller_number)
        or _clean_string(initiation_request.caller_id)
    )
    if not caller_number:
        raise HTTPException(status_code=400, detail="caller_number is required.")

    profile = ProfileService().get_profile(caller_number) or {}
    logger.info(
        "initiate — caller=%s returning_caller=%s last_intent=%s",
        caller_number,
        bool(profile),
        profile.get("last_intent"),
    )
    dynamic_variables = _build_profile_dynamic_variables(profile)
    dynamic_variables["caller_id"] = caller_number
    dynamic_variables["caller_number"] = caller_number

    # Twilio-injected geo fields override profile defaults (authoritative at call time)
    for geo_key in ("caller_country", "caller_state", "caller_city"):
        geo_val = _clean_string(getattr(cp, geo_key, None)) if cp else None
        if geo_val:
            dynamic_variables[geo_key] = geo_val

    call_sid = (_clean_string(cp.call_sid) if cp else None) or _clean_string(initiation_request.call_sid)
    if call_sid:
        dynamic_variables["call_sid"] = call_sid
    if initiation_request.called_number:
        dynamic_variables["called_number"] = initiation_request.called_number
    if initiation_request.agent_id:
        dynamic_variables["agent_id"] = initiation_request.agent_id

    return ElevenLabsInitiateResponse(dynamic_variables=dynamic_variables)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    firestore_status = "connected" if get_firestore_client() is not None else "unavailable"
    return HealthResponse(status="ok", firestore=firestore_status)
