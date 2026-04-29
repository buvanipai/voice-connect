# app/main.py
import datetime as dt
import hmac
import json
import logging
import re
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from google.cloud import firestore
from pydantic import ValidationError

from app.config import settings
from app.auth import router as auth_router
from app.dashboard import router as dashboard_router
from app.notifications import send_email
from app.schemas import (
    ElevenLabsInitiateRequest,
    ElevenLabsInitiateResponse,
    ElevenLabsPostCallWebhook,
    HealthResponse,
    SendFollowupRequest,
)
from app.services.profile_services import ProfileService, get_firestore_client

logger = logging.getLogger(__name__)

PLAN_INCLUDED_MINUTES = {
    "starter": 100,
    "growth": 300,
    "agency": 1000,
}

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(dashboard_router)


def _clean_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def _normalize_phone_digits(value: Optional[str]) -> Optional[str]:
    """Returns only digits from a phone string; 11-digit NANP values collapse to 10 digits.
    This helps match numbers stored in different human-readable formats.
    """
    cleaned = _clean_string(value)
    if not cleaned:
        return None
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _billing_month_key(occurred_at: str) -> str:
    return occurred_at[:7]


def _normalize_plan_key(value: Any) -> str:
    key = (_clean_string(value) or "starter").strip().lower()
    return key if key in PLAN_INCLUDED_MINUTES else "starter"


def _included_minutes_for_client(client_data: Dict[str, Any]) -> float:
    return float(PLAN_INCLUDED_MINUTES[_normalize_plan_key(client_data.get("plan"))])


def _ensure_platform_client_document() -> None:
    """Creates a minimal platform client document so it appears in admin lists
    and can be used as a stable fallback client_id for internal calls.
    Bhuvi IT is set to 'agency' plan (unlimited-like 1000 min).
    """
    platform_client_id = (settings.PLATFORM_CLIENT_ID or "").strip()
    if not platform_client_id:
        return
    db = get_firestore_client()
    if db is None:
        return
    doc_ref = db.collection("clients").document(platform_client_id)
    snapshot = doc_ref.get()
    if snapshot.exists:
        return
    doc_ref.set(
        {
            "name": (settings.PLATFORM_CLIENT_NAME or "Bhuvi IT").strip() or "Bhuvi IT",
            "status": "active",
            "created_at": _utc_now_iso(),
            "plan": "agency",
            "minutes_used": 0,
            "channels": {"email": True, "sms": False},
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


def _resolve_client_id_from_called_number(called_number: Optional[str]) -> Optional[str]:
    """Look up which client owns the inbound number. Returns client_id (doc id) or None."""
    cleaned = _clean_string(called_number)
    if not cleaned:
        return None
    db = get_firestore_client()
    if db is None:
        return None
    try:
        # Fast path: exact match if Firestore stores the number exactly as received.
        query = db.collection("clients").where("phone_number", "==", cleaned).limit(1)
        for doc in query.stream():
            return doc.id

        # Fallback path: normalize to digits and scan client docs in case stored value
        # includes formatting differences (spaces, dashes, parentheses, etc.).
        target_digits = _normalize_phone_digits(cleaned)
        if target_digits:
            for doc in db.collection("clients").stream():
                data = doc.to_dict() or {}
                stored_digits = _normalize_phone_digits(data.get("phone_number"))
                if stored_digits and stored_digits == target_digits:
                    logger.info(
                        "client lookup matched by normalized phone digits (called=%s, client_id=%s)",
                        cleaned,
                        doc.id,
                    )
                    return doc.id

            platform_digits = _normalize_phone_digits(settings.PLATFORM_PHONE_NUMBER)
            if platform_digits and platform_digits == target_digits:
                _ensure_platform_client_document()
                logger.info(
                    "client lookup fell back to platform client (called=%s, client_id=%s)",
                    cleaned,
                    settings.PLATFORM_CLIENT_ID,
                )
                return settings.PLATFORM_CLIENT_ID
    except Exception as exc:
        logger.error("client lookup by phone_number failed: %s", exc)
    return None


def _resolve_client_id_from_agent_id(agent_id: Optional[str]) -> Optional[str]:
    cleaned = _clean_string(agent_id)
    if not cleaned:
        return None
    db = get_firestore_client()
    if db is None:
        return None
    try:
        query = db.collection("clients").where("agent_id", "==", cleaned).limit(1)
        for doc in query.stream():
            return doc.id

        platform_agent_id = (settings.PLATFORM_AGENT_ID or "").strip()
        if platform_agent_id and cleaned == platform_agent_id:
            _ensure_platform_client_document()
            logger.info(
                "client lookup fell back to platform client by agent_id (agent_id=%s, client_id=%s)",
                cleaned,
                settings.PLATFORM_CLIENT_ID,
            )
            return settings.PLATFORM_CLIENT_ID
    except Exception as exc:
        logger.error("client lookup by agent_id failed: %s", exc)
    return None


def _normalize_intent(value: Optional[str]) -> str:
    raw_value = _clean_string(value)
    if not raw_value:
        return "GENERAL_INQUIRY"

    normalized = raw_value.upper().replace("-", "_").replace(" ", "_")
    if normalized == "CLIENT_LEAD":
        return "US_STAFFING"
    return normalized


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


def _render_email_html(body_text: str) -> str:
    return "<p>" + body_text.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"


def _intent_label(intent: str) -> str:
    labels = {
        "JOB_SEEKER": "Job Seeker",
        "US_STAFFING": "US Staffing",
        "SALES": "Sales",
        "GENERAL_INQUIRY": "General Inquiry",
    }
    return labels.get(intent, intent.replace("_", " ").title())


def _build_post_call_email_body_fallback(
    company_name: str,
    intent: str,
    entities: Dict[str, Any],
    website_url: Optional[str],
) -> str:
    """Fallback email copy when LLM generation is unavailable."""
    caller_name = _clean_string(entities.get("name")) or "there"
    role_interest = _clean_string(
        entities.get("role_interest")
        or entities.get("job_type")
        or entities.get("position")
    )
    experience = _clean_string(entities.get("experience_years") or entities.get("years_of_experience"))
    location = _clean_string(entities.get("location") or entities.get("city"))
    availability = _clean_string(entities.get("availability") or entities.get("available_from"))

    if intent == "JOB_SEEKER":
        lines = [
            f"Hi {caller_name},",
            "",
            f"Thanks for speaking with {company_name}. Based on your interest"
            + (f" in {role_interest}" if role_interest else "")
            + ", our team can guide you on the best-fit openings and submission path.",
            "",
            "Next steps:",
            "1) Share your latest resume and preferred role type.",
            "2) We will review fit and send matching opportunities.",
            "3) If shortlisted, we will help coordinate interviews.",
        ]
    elif intent in {"US_STAFFING", "SALES"}:
        lines = [
            f"Hi {caller_name},",
            "",
            f"Thanks for contacting {company_name}. We can support your hiring needs"
            + (f" around {role_interest}" if role_interest else "")
            + " with a tailored staffing approach.",
            "",
            "Next steps:",
            "1) Reply with your current hiring priorities and team goals.",
            "2) We will suggest a recommended engagement model and timeline.",
            "3) We can set up a short discovery call to finalize scope.",
        ]
    else:
        lines = [
            f"Hi {caller_name},",
            "",
            f"Thanks for calling {company_name}. We appreciate your interest and can help based on the details you shared.",
            "",
            "Next steps:",
            "1) Reply with your top priority and desired outcome.",
            "2) We will send a focused recommendation.",
            "3) We can schedule a follow-up call if needed.",
        ]

    optional_details = []
    if experience:
        optional_details.append(f"Experience noted: {experience}")
    if location:
        optional_details.append(f"Location: {location}")
    if availability:
        optional_details.append(f"Availability: {availability}")
    if optional_details:
        lines.extend(["", *optional_details])

    if website_url:
        lines.extend(["", f"You can also review our services here: {website_url}"])

    lines.extend(["", f"Best,", company_name])
    return "\n".join(lines)


def _sanitize_generated_email_body(body_text: str, company_name: str) -> str:
    """Apply deterministic safety rules to LLM output before sending."""
    text = (body_text or "").strip()
    if not text:
        return text

    # Remove obvious placeholders and template artifacts.
    text = re.sub(r"\[\s*your name\s*\]", company_name, text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*company\s*\]", company_name, text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*tbd\s*\]", "", text, flags=re.IGNORECASE)

    # Remove unsupported commitments that the system did not execute.
    blocked_patterns = [
        r"(?im)^.*i\s*(?:will|'ll)\s*send\s*(?:you\s*)?(?:a\s*)?calendar\s*link.*$",
        r"(?im)^.*i\s*(?:will|'ll)\s*share\s*(?:you\s*)?(?:a\s*)?calendar\s*link.*$",
        r"(?im)^.*booking\s*link.*$",
        r"(?im)^.*\"i\s*am\s*flexible.*\".*$",
        r"(?im)^.*\"i'm\s*flexible.*\".*$",
    ]
    for pattern in blocked_patterns:
        text = re.sub(pattern, "", text)

    # Remove fabricated sample-response quote lines.
    text = re.sub(r'(?im)^.*"[^"]{8,}".*$', "", text)

    # Avoid implying the AI itself will run meetings.
    text = re.sub(r"\bI(?:\s*'d|\s+would)?\s+like\s+to\s+schedule\b", "Our team can schedule", text)
    text = re.sub(r"\bI\s+can\s+schedule\b", "Our team can schedule", text)
    text = re.sub(r"\bI\s+will\s+schedule\b", "Our team will schedule", text)

    # Normalize excessive blank lines created by removals.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Ensure sign-off is concrete and not placeholder-like.
    lowered = text.lower()
    if "best regards" in lowered and company_name.lower() not in lowered:
        text = text.replace("Best regards,", "Best,")
    if company_name.lower() not in text.lower().splitlines()[-1].lower():
        text = f"{text}\n\nBest,\n{company_name}"

    return text


async def _build_post_call_email_body(
    *,
    company_name: str,
    intent: str,
    entities: Dict[str, Any],
    client_data: Dict[str, Any],
) -> str:
    """Generate intent-aware follow-up copy with LLM when configured, else fallback."""
    website_url = _clean_string(client_data.get("website_url"))

    if not settings.ANTHROPIC_API_KEY:
        logger.info("post-call email body source=fallback reason=missing_anthropic_key")
        return _build_post_call_email_body_fallback(company_name, intent, entities, website_url)

    prompt_payload = {
        "company_name": company_name,
        "company_website": website_url,
        "intent": intent,
        "intent_label": _intent_label(intent),
        "captured_entities": entities,
    }

    system_prompt = (
        "You write concise follow-up emails for inbound business calls. "
        "Write like a human account manager, not a bot. "
        "Do NOT output a raw field dump of captured details. "
        "Instead, provide useful, intent-specific guidance based on caller needs. "
        "For JOB_SEEKER: mention matching roles and candidate next steps. "
        "For US_STAFFING/SALES: mention staffing/service support and discovery next steps. "
        "If conversation suggests product/help request, respond with what help can be offered and a concrete next action. "
        "Use only provided facts. If data is missing, avoid hallucinating and ask for it politely. "
        "Do not invent caller quotes or sample replies. "
        "Do not imply the AI voice agent will personally conduct meetings; refer to the company team or a specialist. "
        "Do not hardcode services for one company. Keep wording adaptable to the provided company_name, website, and captured context. "
        "Never use placeholders such as [Your name], [Company], or TBD text. "
        "Never promise actions the system did not perform (for example: do not claim a calendar link was sent unless explicitly provided in context). "
        "Use a truthful CTA that can be completed by email reply (for example: ask for preferred time windows). "
        "End with a real sign-off using the company_name from context. "
        "Output plain text only, max 170 words, with a short greeting and sign-off."
    )

    user_prompt = (
        "Draft the follow-up email body from this JSON context:\n"
        f"{json.dumps(prompt_payload, default=str)}"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.MODEL_NAME,
                    "max_tokens": 350,
                    "temperature": 0.3,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()
            parts = payload.get("content") or []
            text_chunks = []
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = _clean_string(part.get("text"))
                    if text:
                        text_chunks.append(text)
            generated = "\n".join(text_chunks).strip()
            if generated:
                generated = _sanitize_generated_email_body(generated, company_name)
                logger.info("post-call email body source=llm model=%s", settings.MODEL_NAME)
                return generated
    except Exception as exc:
        logger.warning("LLM email generation failed, using fallback template: %s", exc)

    logger.info("post-call email body source=fallback reason=llm_empty_or_failed")
    return _build_post_call_email_body_fallback(company_name, intent, entities, website_url)


def _parse_duration_seconds(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = int(round(float(value)))
        return seconds if seconds >= 0 else None

    text = _clean_string(value)
    if not text:
        return None

    if ":" in text:
        parts = [part.strip() for part in text.split(":") if part.strip()]
        if all(part.isdigit() for part in parts):
            total = 0
            for part in parts:
                total = (total * 60) + int(part)
            return total

    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None

    amount = float(match.group(1))
    lowered = text.lower()
    if "min" in lowered:
        amount *= 60
    seconds = int(round(amount))
    return seconds if seconds >= 0 else None


def _find_duration_value(payload: Any) -> Optional[int]:
    duration_keys = {
        "duration",
        "duration_sec",
        "duration_secs",
        "duration_second",
        "duration_seconds",
        "call_duration",
        "call_duration_sec",
        "call_duration_secs",
        "call_duration_seconds",
        "conversation_duration",
        "conversation_duration_sec",
        "conversation_duration_secs",
        "conversation_duration_seconds",
    }

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in duration_keys:
                parsed = _parse_duration_seconds(value)
                if parsed is not None:
                    return parsed
        for value in payload.values():
            parsed = _find_duration_value(value)
            if parsed is not None:
                return parsed
    elif isinstance(payload, list):
        for item in payload:
            parsed = _find_duration_value(item)
            if parsed is not None:
                return parsed
    return None


def _extract_duration_seconds(event: ElevenLabsPostCallWebhook) -> int:
    payloads = [
        event.data.model_dump(mode="python"),
        event.data.metadata or {},
        (event.data.metadata or {}).get("body") or {},
    ]
    for payload in payloads:
        parsed = _find_duration_value(payload)
        if parsed is not None:
            return parsed

    latest_transcript_offset = None
    for item in event.data.transcript or []:
        if not isinstance(item, dict):
            continue
        for key in ("time_in_call_secs", "time_in_call_seconds", "offset_secs", "offset_seconds"):
            parsed = _parse_duration_seconds(item.get(key))
            if parsed is not None:
                latest_transcript_offset = max(latest_transcript_offset or 0, parsed)
    return latest_transcript_offset or 0


def _normalize_inactivity_timeout_seconds(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = settings.DEFAULT_INACTIVITY_TIMEOUT_SECONDS
    return max(
        settings.MIN_INACTIVITY_TIMEOUT_SECONDS,
        min(settings.MAX_INACTIVITY_TIMEOUT_SECONDS, seconds),
    )


def _normalize_max_call_duration_seconds(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = settings.DEFAULT_MAX_CALL_DURATION_SECONDS
    return max(
        settings.MIN_MAX_CALL_DURATION_SECONDS,
        min(settings.MAX_MAX_CALL_DURATION_SECONDS, seconds),
    )


def _extract_transcript_text(entry: Dict[str, Any]) -> str:
    for key in ("text", "message", "transcript", "content", "utterance"):
        value = _clean_string(entry.get(key))
        if value:
            return value
    return ""


def _has_meaningful_caller_response(transcript: Any) -> bool:
    if not isinstance(transcript, list):
        return False

    for item in transcript:
        if not isinstance(item, dict):
            continue
        speaker = (
            _clean_string(
                item.get("speaker")
                or item.get("role")
                or item.get("source")
                or item.get("participant")
            )
            or ""
        ).lower()
        is_caller_turn = any(token in speaker for token in ("caller", "user", "human", "customer", "client"))
        is_caller_turn = is_caller_turn or bool(item.get("is_user") is True)
        if not is_caller_turn:
            continue

        text = _extract_transcript_text(item)
        compact = re.sub(r"[^a-z0-9]+", "", text.lower())
        if len(compact) >= 2:
            return True
    return False


def _derive_ended_reason(
    event: ElevenLabsPostCallWebhook,
    duration_seconds: int,
    inactivity_timeout_seconds: int,
    max_call_duration_seconds: int,
) -> Optional[str]:
    if duration_seconds >= max_call_duration_seconds:
        return "max_duration_exceeded"

    if duration_seconds < inactivity_timeout_seconds:
        return None

    if _has_meaningful_caller_response(event.data.transcript):
        return None
    return "inactivity_timeout"


def _record_call_usage(
    *,
    client_id: str,
    caller_number: str,
    called_number: Optional[str],
    agent_id: Optional[str],
    intent: str,
    transcript_summary: Optional[str],
    call_sid: Optional[str],
    conversation_id: Optional[str],
    duration_seconds: int,
    ended_reason: Optional[str],
    occurred_at: str,
) -> Dict[str, Any]:
    db = get_firestore_client()
    if db is None:
        return {}

    call_doc_id = call_sid or conversation_id
    if not call_doc_id:
        return {}

    call_ref = (
        db.collection("clients")
        .document(client_id)
        .collection("calls")
        .document(call_doc_id)
    )
    snapshot = call_ref.get()
    existing = snapshot.to_dict() or {}
    previous_duration = int(existing.get("duration_seconds") or 0)
    is_new_call = not snapshot.exists
    delta_seconds = max(duration_seconds - previous_duration, 0)

    call_ref.set(
        {
            "caller_number": caller_number,
            "called_number": called_number,
            "agent_id": agent_id,
            "intent": intent,
            "transcript_summary": transcript_summary,
            "conversation_id": conversation_id,
            "call_sid": call_sid,
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_seconds / 60, 2),
            "ended_reason": ended_reason,
            "occurred_at": occurred_at,
            "updated_at": _utc_now_iso(),
        },
        merge=True,
    )

    client_ref = db.collection("clients").document(client_id)
    client_data = client_ref.get().to_dict() or {}
    usage = client_data.get("usage") or {}
    billing_month = _billing_month_key(occurred_at)
    current_billing_month = usage.get("billing_month")

    total_seconds = int(usage.get("total_seconds") or 0) + delta_seconds
    total_calls = int(usage.get("call_count") or 0) + (1 if is_new_call else 0)

    if current_billing_month == billing_month:
        monthly_seconds = int(usage.get("monthly_seconds") or 0) + delta_seconds
        monthly_calls = int(usage.get("monthly_call_count") or 0) + (1 if is_new_call else 0)
    else:
        monthly_seconds = duration_seconds
        monthly_calls = 1 if is_new_call else int(usage.get("monthly_call_count") or 0)

    minutes_used = round(monthly_seconds / 60, 2)

    client_ref.set(
        {
            "minutes_used": minutes_used,
            "usage": {
                "total_seconds": total_seconds,
                "call_count": total_calls,
                "monthly_seconds": monthly_seconds,
                "monthly_call_count": monthly_calls,
                "billing_month": billing_month,
                "last_call_at": occurred_at,
            }
        },
        merge=True,
    )

    return {
        "billing_month": billing_month,
        "monthly_seconds": monthly_seconds,
        "monthly_minutes": round(monthly_seconds / 60, 2),
        "minutes_used": minutes_used,
        "total_seconds": total_seconds,
        "total_minutes": round(total_seconds / 60, 2),
    }


def _mark_usage_warning_sent(client_id: str, billing_month: str) -> None:
    db = get_firestore_client()
    if db is None:
        return
    db.collection("clients").document(client_id).set(
        {
            "usage": {
                "warning_90_sent_month": billing_month,
                "warning_90_sent_at": _utc_now_iso(),
            }
        },
        merge=True,
    )


def _send_usage_warning_email_if_needed(
    *,
    client_id: str,
    client_data: Dict[str, Any],
    usage_stats: Dict[str, Any],
) -> None:
    usage = client_data.get("usage") or {}
    billing_month = _clean_string(usage_stats.get("billing_month"))
    if not billing_month:
        return

    if _clean_string(usage.get("warning_90_sent_month")) == billing_month:
        return

    included_minutes = _included_minutes_for_client(client_data)
    monthly_minutes = float(usage_stats.get("minutes_used") or usage_stats.get("monthly_minutes") or 0)
    threshold = included_minutes * 0.9
    if monthly_minutes < threshold:
        return
    if monthly_minutes >= included_minutes:
        return

    target_email = _clean_string(client_data.get("email"))
    if not target_email:
        return

    company_name = _clean_string(client_data.get("name")) or "VoiceConnect"
    percent = int(round((monthly_minutes / included_minutes) * 100))
    remaining = max(round(included_minutes - monthly_minutes, 2), 0)

    subject = f"Usage warning: {percent}% of your monthly call minutes used"
    body_text = (
        f"Hi {company_name},\n\n"
        f"You have used {monthly_minutes:.2f} of {included_minutes:.0f} included minutes this month "
        f"({percent}%).\n"
        f"Remaining included minutes: {remaining:.2f}.\n\n"
        "If you expect more call volume, please consider upgrading your plan to avoid interruptions.\n\n"
        "- VoiceConnect"
    )
    body_html = _render_email_html(body_text)

    try:
        send_email(
            target_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            gmail_refresh_token=client_data.get("gmail_refresh_token"),
            gmail_from_email=client_data.get("gmail_email"),
        )
        _mark_usage_warning_sent(client_id, billing_month)
        logger.info("usage warning email sent to %s for client %s", target_email, client_id)
    except Exception as exc:
        logger.warning("Failed to send usage warning email for client %s: %s", client_id, exc)


def _log_followup_sent(
    *,
    client_id: str,
    call_sid: Optional[str],
    conversation_id: Optional[str],
    caller_email: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    db = get_firestore_client()
    if db is None:
        return
    doc_id = call_sid or conversation_id
    if not doc_id:
        return
    payload: Dict[str, Any] = {
        "followup_sent": status == "sent",
        "followup_status": status,
        "caller_email": caller_email,
        "timestamp": _utc_now_iso(),
    }
    if error:
        payload["error"] = error
    try:
        (
            db.collection("clients")
            .document(client_id)
            .collection("calls")
            .document(doc_id)
            .set(payload, merge=True)
        )
    except Exception as exc:
        logger.error("Failed to log followup status: %s", exc)


@app.post("/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request) -> Dict[str, Any]:
    payload = await _parse_request_payload(request)
    try:
        event = ElevenLabsPostCallWebhook.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    caller_number, intent, entities, follow_up_context = _extract_profile_entities(event)

    # Identify which client this call belongs to
    dynamic_variables = (
        event.data.conversation_initiation_client_data.dynamic_variables or {}
    )
    metadata = event.data.metadata or {}
    metadata_body = metadata.get("body", {}) if isinstance(metadata.get("body"), dict) else {}
    called_number = (
        _first_scalar(dynamic_variables, "called_number", "system__called_number")
        or _first_scalar(metadata_body, "To", "Called")
        or _first_scalar(metadata, "to_number", "called_number")
    )
    client_id = (
        _clean_string(dynamic_variables.get("client_id"))
        or _resolve_client_id_from_called_number(called_number)
        or _resolve_client_id_from_agent_id(event.data.agent_id)
    )
    if not client_id:
        logger.warning(
            "post-call — could not resolve client_id (caller=%s called=%s)",
            caller_number,
            called_number,
        )
        raise HTTPException(
            status_code=400,
            detail="Unable to resolve client_id from dynamic_variables or called_number.",
        )

    db = get_firestore_client()
    client_data: Dict[str, Any] = {}
    if db is not None:
        client_doc = db.collection("clients").document(client_id).get()
        if client_doc.exists:
            client_data = client_doc.to_dict() or {}

    profile_service = ProfileService(client_id=client_id)
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

    occurred_at = _utc_now_iso()
    duration_seconds = _extract_duration_seconds(event)
    inactivity_timeout_seconds = _normalize_inactivity_timeout_seconds(
        client_data.get("inactivity_timeout_seconds")
    )
    max_call_duration_seconds = _normalize_max_call_duration_seconds(
        client_data.get("max_call_duration_seconds")
    )
    ended_reason = _derive_ended_reason(
        event,
        duration_seconds,
        inactivity_timeout_seconds,
        max_call_duration_seconds,
    )
    usage_stats = _record_call_usage(
        client_id=client_id,
        caller_number=caller_number,
        called_number=called_number,
        agent_id=event.data.agent_id,
        intent=intent,
        transcript_summary=entities.get("transcript_summary"),
        call_sid=follow_up_context.get("call_sid"),
        conversation_id=follow_up_context.get("conversation_id"),
        duration_seconds=duration_seconds,
        ended_reason=ended_reason,
        occurred_at=occurred_at,
    )
    if usage_stats:
        _send_usage_warning_email_if_needed(
            client_id=client_id,
            client_data=client_data,
            usage_stats=usage_stats,
        )

    # Send post-call follow-up email if caller provided an email address
    caller_email = entities.get("email_address", "").strip()
    if caller_email and "@" in caller_email:
        channels = client_data.get("channels") or {}
        email_channel_enabled = channels.get("email", True)

        if email_channel_enabled:
            company_name = _clean_string(client_data.get("name")) or settings.FOLLOW_UP_COMPANY_NAME
            call_sid = follow_up_context.get("call_sid")
            conversation_id = follow_up_context.get("conversation_id")

            body_text = await _build_post_call_email_body(
                company_name=company_name,
                intent=intent,
                entities=entities,
                client_data=client_data,
            )

            subject = f"Following up on your call with {company_name}"
            body_html = _render_email_html(body_text)

            try:
                send_email(
                    caller_email,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                    gmail_refresh_token=client_data.get("gmail_refresh_token"),
                    gmail_from_email=client_data.get("gmail_email"),
                )
                _log_followup_sent(
                    client_id=client_id,
                    call_sid=call_sid,
                    conversation_id=conversation_id,
                    caller_email=caller_email,
                    status="sent",
                )
                logger.info("post-call follow-up email sent to %s", caller_email)
            except Exception as exc:
                logger.error("post-call follow-up email failed: %s", exc)
                _log_followup_sent(
                    client_id=client_id,
                    call_sid=call_sid,
                    conversation_id=conversation_id,
                    caller_email=caller_email,
                    status="send_failed",
                    error=str(exc),
                )

    return {
        "status": "processed",
        "caller_number": caller_number,
        "intent": intent,
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

    called_number = (
        _clean_string(cp.called_number if cp else None)
        or _clean_string(initiation_request.called_number)
    )
    client_id = (
        _clean_string(cp.client_id if cp and hasattr(cp, "client_id") else None)
        or _clean_string(initiation_request.client_id if hasattr(initiation_request, "client_id") else None)
        or _resolve_client_id_from_called_number(called_number)
        or _resolve_client_id_from_agent_id(initiation_request.agent_id)
    )
    if not client_id:
        logger.warning(
            "initiate — no client_id resolved (caller=%s called=%s) — returning empty vars",
            caller_number,
            called_number,
        )
        dynamic_variables: Dict[str, Any] = {
            "caller_id": caller_number,
            "caller_number": caller_number,
            "existing_profile_json": "{}",
        }
        if called_number:
            dynamic_variables["called_number"] = called_number
        if initiation_request.agent_id:
            dynamic_variables["agent_id"] = initiation_request.agent_id
        return ElevenLabsInitiateResponse(dynamic_variables=dynamic_variables)

    # Pull client-level settings for dynamic variables
    client_name: Optional[str] = None
    client_data: Dict[str, Any] = {}
    db = get_firestore_client()
    if db is not None:
        client_doc = db.collection("clients").document(client_id).get()
        if client_doc.exists:
            client_data = client_doc.to_dict() or {}
            client_name = _clean_string(client_data.get("name"))

    profile = ProfileService(client_id=client_id).get_profile(caller_number) or {}
    logger.info(
        "initiate — client=%s caller=%s returning_caller=%s last_intent=%s",
        client_id,
        caller_number,
        bool(profile),
        profile.get("last_intent"),
    )
    dynamic_variables = _build_profile_dynamic_variables(profile)
    dynamic_variables["caller_id"] = caller_number
    dynamic_variables["caller_number"] = caller_number
    dynamic_variables["client_id"] = client_id
    if client_name:
        dynamic_variables["client_name"] = client_name

    call_sid = (_clean_string(cp.call_sid) if cp else None) or _clean_string(initiation_request.call_sid)
    if call_sid:
        dynamic_variables["call_sid"] = call_sid
    if called_number:
        dynamic_variables["called_number"] = called_number
    if initiation_request.agent_id:
        dynamic_variables["agent_id"] = initiation_request.agent_id

    usage = client_data.get("usage") or {}
    monthly_seconds = int(usage.get("monthly_seconds") or 0)
    tracked_minutes_used = float(client_data.get("minutes_used") or round(monthly_seconds / 60, 2))
    included_minutes = _included_minutes_for_client(client_data)
    if tracked_minutes_used >= included_minutes:
        dynamic_variables["account_limit_reached"] = True
        dynamic_variables["account_limit_monthly_minutes"] = round(tracked_minutes_used, 2)
        dynamic_variables["account_limit_included_minutes"] = included_minutes
        return ElevenLabsInitiateResponse(
            dynamic_variables=dynamic_variables,
            conversation_config_override={
                "agent": {
                    "first_message": "Account limit reached, please upgrade."
                },
                "conversation": {"max_duration_seconds": 10},
                "turn": {
                    "silence_end_call_timeout": 3,
                    "soft_timeout_config": {
                        "timeout_seconds": 3,
                        "message": "Ending the call now."
                    },
                },
            },
        )

    return ElevenLabsInitiateResponse(dynamic_variables=dynamic_variables)


@app.post("/tools/send-followup")
async def tools_send_followup(
    request: Request,
    x_tool_secret: Optional[str] = Header(default=None, alias="X-Tool-Secret"),
) -> Dict[str, Any]:
    """ElevenLabs agent webhook tool. Agent calls this once the caller confirms
    they want a follow-up email."""
    if not settings.TOOL_SECRET:
        raise HTTPException(status_code=500, detail="TOOL_SECRET is not configured.")
    if not x_tool_secret or not hmac.compare_digest(x_tool_secret, settings.TOOL_SECRET):
        raise HTTPException(status_code=401, detail="Invalid tool secret.")

    payload = await _parse_request_payload(request)
    try:
        body = SendFollowupRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    client_id = _clean_string(body.client_id) or _resolve_client_id_from_agent_id(body.agent_id)
    if not client_id:
        raise HTTPException(status_code=400, detail="Unable to resolve client_id.")

    db = get_firestore_client()
    if db is None:
        raise HTTPException(status_code=500, detail="Firestore unavailable.")

    client_doc = db.collection("clients").document(client_id).get()
    if not client_doc.exists:
        raise HTTPException(status_code=404, detail="Client not found.")
    client_data = client_doc.to_dict() or {}

    caller_email = (body.caller_email or "").strip()
    if not caller_email or "@" not in caller_email:
        raise HTTPException(status_code=400, detail="A valid caller_email is required.")

    call_sid = _clean_string(body.call_sid) or _clean_string(body.conversation_id)
    company_name = _clean_string(client_data.get("name")) or settings.FOLLOW_UP_COMPANY_NAME

    body_text = (body.email_body or "").strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="email_body is required.")

    subject = _clean_string(body.email_subject) or f"Following up on your call with {company_name}"
    body_html = _render_email_html(body_text)

    try:
        send_email(
            caller_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            gmail_refresh_token=client_data.get("gmail_refresh_token"),
            gmail_from_email=client_data.get("gmail_email"),
        )
    except Exception as exc:
        logger.error("Follow-up email send failed: %s", exc)
        _log_followup_sent(
            client_id=client_id,
            call_sid=call_sid,
            conversation_id=body.conversation_id,
            caller_email=caller_email,
            status="send_failed",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=f"Email send failed: {exc}")

    _log_followup_sent(
        client_id=client_id,
        call_sid=call_sid,
        conversation_id=body.conversation_id,
        caller_email=caller_email,
        status="sent",
    )

    return {"status": "sent", "channel": "email", "target": caller_email}


@app.get("/twilio/voice/{client_id}")
async def twilio_voice(client_id: str) -> Response:
    """Returns TwiML that routes an inbound call to the client's ElevenLabs agent."""
    from app.services.profile_services import get_firestore_client as _get_db
    db = _get_db()
    agent_id = settings.ELEVENLABS_AGENT_ID  # fallback to template agent

    if db is not None:
        doc = db.collection("clients").document(client_id).get()
        if doc.exists:
            agent_id = (doc.to_dict() or {}).get("agent_id") or agent_id

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://api.elevenlabs.io/v1/convai/twilio?agent_id={agent_id}">
      <Parameter name="caller_id" value="{{{{From}}}}"/>
      <Parameter name="client_id" value="{client_id}"/>
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    firestore_status = "connected" if get_firestore_client() is not None else "unavailable"
    return HealthResponse(status="ok", firestore=firestore_status)
