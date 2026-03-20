# app/main.py
import os
import datetime
import select
import asyncio
import time
from dotenv import load_dotenv
from requests import get, post
import twilio
load_dotenv()
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
from pydoc import text
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from app.schemas import CallPayload, AIResponse
from app.config import settings
from app.services.llm_service import LLMService
from app.services.stt_service import DeepgramSTT
from app.services.drive_service import DriveService
from app.services.profile_services import ProfileService, get_firestore_client
from app.services.metrics_service import MetricsService
from app.services.cloud_logging_service import CloudLoggingService
from twilio.rest import Client
from contextlib import asynccontextmanager
from fastapi.responses import HTMLResponse
from xml.sax.saxutils import escape as xml_escape

app = FastAPI(title="VoiceConnect API", version="0.1.0")

_llm_service_instance = None
_stt_instance = None
_drive_service_instance = None
_metrics_instance = None
_cloud_logging_instance = None
# Store per-call state (conversation memory + active branch)
call_sessions: Dict[str, Dict[str, Any]] = {}
RESUME_UPLOAD_LINK = "https://athena-natatory-dawn.ngrok-free.dev/upload"


def _get_or_init_session(call_sid: str) -> Dict[str, Any]:
    if call_sid not in call_sessions:
        call_sessions[call_sid] = {
            "memory": [],
            "branch": None,
        }
    return call_sessions[call_sid]


def _build_record_response(message: str) -> Response:
    safe_message = xml_escape(message)
    xml_response = f"""
        <Response>
            <Say voice="Polly.Joanna-Neural">{safe_message}</Say>
            <Record maxLength="30" timeout="2" trim="trim-silence" action="/transcribe" playBeep="true"/>
        </Response>
        """
    return Response(content=xml_response, media_type="application/xml")


def _non_empty_str(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _get_profile_value(profile_data: Dict[str, Any], key: str) -> Optional[str]:
    direct_value = _non_empty_str(profile_data.get(key))
    if direct_value:
        return direct_value

    intents = profile_data.get("intents") if isinstance(profile_data, dict) else None
    if isinstance(intents, dict):
        for intent_data in intents.values():
            if isinstance(intent_data, dict):
                nested_value = _non_empty_str(intent_data.get(key))
                if nested_value:
                    return nested_value
    return None


def _merge_session_profile_entities(session: Dict[str, Any], *sources: Dict[str, Any]) -> Dict[str, Any]:
    merged = session.get("profile_entities", {}).copy()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            cleaned = _non_empty_str(value)
            if cleaned:
                merged[key] = cleaned
    session["profile_entities"] = merged
    return merged


def _send_whatsapp_followup(caller_number: str) -> None:
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    wa_message = (
        "Thanks for speaking with Bhuvi IT Solutions! To complete your profile, please upload your "
        f"resume and documents here: {RESUME_UPLOAD_LINK}. Our team will review your information "
        "and get back to you shortly!"
    )

    client.messages.create(
        body=wa_message,
        from_="whatsapp:+14155238886",
        to=f"whatsapp:{caller_number}"
    )


def _send_email_followup(email_address: str) -> None:
    if not settings.SENDGRID_API_KEY or not settings.SENDGRID_FROM_EMAIL:
        raise ValueError("Missing SENDGRID_API_KEY or SENDGRID_FROM_EMAIL in settings")

    payload = {
        "personalizations": [{"to": [{"email": email_address}]}],
        "from": {"email": settings.SENDGRID_FROM_EMAIL},
        "subject": "Bhuvi IT Solutions - Resume Upload Link",
        "content": [{
            "type": "text/html",
            "value": (
                "Thanks for speaking with Bhuvi IT Solutions! "
                "Please upload your resume and supporting documents using this secure link: "
                f"<a href=\"{RESUME_UPLOAD_LINK}\">{RESUME_UPLOAD_LINK}</a>. "
                "Our team will review your profile and follow up shortly."
            )
        }],
    }
    response = post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    if response.status_code not in {200, 202}:
        raise RuntimeError(f"SendGrid API error: {response.status_code} {response.text[:300]}")


def _log_failed_notification(
    caller_number: str,
    call_sid: str,
    preferred_method: str,
    reason: str,
    email_address: Optional[str] = None,
) -> None:
    try:
        db = get_firestore_client()
        if db is None:
            print(f"[{call_sid}] Firestore unavailable. Could not log failed notification.")
            return

        payload: Dict[str, Any] = {
            "caller_number": caller_number,
            "call_sid": call_sid,
            "preferred_method": preferred_method,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "reason": reason,
        }
        if email_address:
            payload["email_address"] = email_address

        db.collection("failed_notifications").add(payload)
        print(f"[{call_sid}] Logged failed notification for method={preferred_method}")
    except Exception as firestore_error:
        print(f"[{call_sid}] Failed to log failed_notification: {firestore_error}")


async def _build_forward_response(
    call_sid: str,
    intent: str,
    spoken_text: str,
    selected_voice: str,
    profile_data: Optional[Dict[str, Any]] = None,
) -> Response:
    session = call_sessions.get(call_sid, {})
    call_memory = session.get("memory", [])

    service = get_llm_service()
    call_whisper = await service.generate_call_summary(
        intent=intent,
        call_memory=call_memory,
        profile_data=profile_data or session.get("profile_entities", {}),
    )

    safe_text = xml_escape(spoken_text)
    safe_whisper = xml_escape(call_whisper)
    print(f"[{call_sid}] Call Whisper: {safe_whisper}")

    if call_sid in call_sessions:
        del call_sessions[call_sid]

    xml_response = f"""
        <Response>
            <Say voice="{selected_voice}">{safe_text}</Say>
            <Pause length="1"/>
            <Say voice="Polly.Joanna-Neural">[RECRUITER BRIEF: {safe_whisper}]</Say>
            <Hangup/>
        </Response>
        """
    return Response(content=xml_response, media_type="application/xml")

# Initialize Service
def get_llm_service():
    global _llm_service_instance
    if _llm_service_instance is None:
        print("[INFO] Initializing LLMService for the first time.")
        _llm_service_instance = LLMService()
    return _llm_service_instance

def get_stt_service():
    global _stt_instance
    if _stt_instance is None:
        print("[INFO] Initializing DeepgramSTT for the first time.")
        _stt_instance = DeepgramSTT()
    return _stt_instance

def get_drive_service():
    global _drive_service_instance
    if _drive_service_instance is None:
        print("[INFO] Initializing DriveService for the first time.")
        _drive_service_instance = DriveService()
    return _drive_service_instance

def get_metrics_service():
    global _metrics_instance
    if _metrics_instance is None:
        print("[INFO] Initializing MetricsService for the first time.")
        _metrics_instance = MetricsService()
    return _metrics_instance

def get_cloud_logging_service():
    global _cloud_logging_instance
    if _cloud_logging_instance is None:
        print("[INFO] Initializing CloudLoggingService for the first time.")
        _cloud_logging_instance = CloudLoggingService()
    return _cloud_logging_instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[INFO] Pre-loading AI models...")
    get_llm_service()
    get_stt_service()
    get_drive_service()
    print("[INFO] AI models loaded successfully.")
    yield

app = FastAPI(title="VoiceConnect API", version="0.1.0", lifespan=lifespan)


def _main_menu_response() -> Response:
    xml_response = """
        <Response>
            <Gather input="dtmf" action="/menu-select" numDigits="1" timeout="7">
                <Say voice="Polly.Joanna-Neural">Hi, thank you for calling Bhuvi IT Solutions! Press 1 if you are a Job Seeker. Press 2 for Staffing Services. Press 0 to hear these options again.</Say>
            </Gather>
            <Redirect method="POST">/voice</Redirect>
        </Response>
        """
    return Response(content=xml_response, media_type="application/xml")


def _staffing_submenu_response() -> Response:
    xml_response = """
        <Response>
            <Gather input="dtmf" action="/submenu-select" numDigits="1" timeout="7">
                <Say voice="Polly.Joanna-Neural">Press 1 for US Staffing. Press 2 for AI Career Development. Press 3 for AI for Small Business. Press 4 for AI Product Development. Press 0 to hear these options again.</Say>
            </Gather>
            <Redirect method="POST">/submenu-select</Redirect>
        </Response>
        """
    return Response(content=xml_response, media_type="application/xml")

@app.get("/")
def home():
    return {"message": "Welcome to the VoiceConnect API!",
            "status": "online"}

@app.post("/process-speech", response_model=AIResponse)
async def process_speech(payload: CallPayload):
    """
    Endpoint exposed to the Telephony Service (Twilio/Rockscar).
    """
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Input text cannot be empty")
        
    service = get_llm_service()
    result = await service.analyze_call(payload.text)
    return result

# Phone endpoint for Twilio
@app.post("/voice")
async def voice_webhook(request: Request):
    """
    Step 1: Answer and ask the user to speak
    Twilio hits this endpoint when the phone rings.
    We return XML instructions telling it to speak.
    """
    # Get CallSid to track this conversation
    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "unknown"))
    caller_number = str(form_data.get("From", "unknown"))
    
    session = _get_or_init_session(call_sid)
    call_memory = session["memory"]
    print(f"[NEW/ACTIVE CALL] CallSid: {call_sid}")
    
    # Check if this is a returning caller
    profile_service = ProfileService()
    profile_data = profile_service.get_profile(caller_number)
    print(f"[PROFILE DEBUG] Caller: {caller_number}, Profile data: {profile_data}")
    
    known_branch = profile_data.get("last_intent") if profile_data else None
    if known_branch == "CLIENT_LEAD":
        known_branch = "US_STAFFING"
    if known_branch:
        session["branch"] = known_branch
        personalized = "Welcome back! Thanks for calling Bhuvi IT Solutions again. Please share any updates after the beep."
        call_memory.append({
            "user": "[SYSTEM: Returning caller]",
            "ai": personalized,
            "intent": known_branch,
            "branch": known_branch,
            "entities": profile_data or {}
        })
        print(f"[RETURNING CALLER] {caller_number} -> branch={known_branch}")
        return _build_record_response(personalized)

    print(f"[NEW CALLER] {caller_number}")
    return _main_menu_response()


@app.post("/menu-select")
async def menu_select(request: Request):
    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "unknown"))
    digit = str(form_data.get("Digits", "")).strip()
    session = _get_or_init_session(call_sid)

    if digit == "1":
        session["branch"] = "JOB_SEEKER"
        message = "Great! Please tell us about the role you're looking for after the beep."
        return _build_record_response(message)

    if digit == "0":
        return _main_menu_response()

    if digit == "2":
        return _staffing_submenu_response()

    return _main_menu_response()


@app.post("/submenu-select")
async def submenu_select(request: Request):
    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "unknown"))
    digit = str(form_data.get("Digits", "")).strip()
    session = _get_or_init_session(call_sid)

    branch_map = {
        "1": "US_STAFFING",
        "2": "AI_CAREER_DEV",
        "3": "AI_SMALL_BIZ",
        "4": "AI_PROD_DEV",
    }
    opening_lines = {
        "US_STAFFING": "Please describe the role or talent you're looking for.",
        "AI_CAREER_DEV": "Tell us about your background and what you're hoping to achieve with AI.",
        "AI_SMALL_BIZ": "Tell us about your business and what problem you'd like AI to solve.",
        "AI_PROD_DEV": "Tell us about the AI product you want to build.",
    }

    selected_branch = branch_map.get(digit)
    if not selected_branch:
        return _staffing_submenu_response()

    session["branch"] = selected_branch
    return _build_record_response(opening_lines[selected_branch])

@app.post("/transcribe")
async def transcribe_webhook(request: Request):
    """
    Step 2: Recieve recording -> Transcribe -> Echo back
    Twilio hits this endpoint after the call ends, sending the recording URL.
    We will process the recording and return a response.
    """
    form_data = await request.form()
    recording_url = str(form_data.get("RecordingUrl"))
    speech_result = str(form_data.get("SpeechResult", "")).strip()
    call_sid = str(form_data.get("CallSid", "unknown"))
    caller_country = str(form_data.get("CallerCountry", "unknown"))
    caller_state = str(form_data.get("CallerState", "unknown"))
    print(f"[{call_sid}] DEBUG: Twilio reports CallerState as: '{caller_state}'")
    caller_number = str(form_data.get("From", "unknown"))
    session_exists = call_sid in call_sessions
    session = _get_or_init_session(call_sid)
    
    # Initialize metrics and cloud logging for this call
    metrics = get_metrics_service()
    cloud_logger = get_cloud_logging_service()
    if not session_exists:
        metrics.start_call(call_sid, caller_number)
        cloud_logger.log_call_event({
            "call_sid": call_sid,
            "phone_number": caller_number,
            "caller_country": caller_country,
            "caller_state": caller_state,
            "status": "started"
        })
    
    if not recording_url and not speech_result:
        metrics.record_stt_attempt(call_sid, success=False, text="")
        return Response(content="<Response><Say>I didn't hear anything.</Say></Response>", media_type="application/xml")
    
    # Twilio times out webhook fetches at ~15s. Keep a safety buffer.
    endpoint_start = time.monotonic()
    endpoint_deadline = endpoint_start + 13.5

    # Deepgram to convert audio to text unless Gather already provided speech text
    if speech_result:
        text = speech_result
        print(f"[{call_sid}] Using Gather speech text: '{text}'")
        metrics.record_stt_attempt(call_sid, success=True, text=text)
    else:
        stt = get_stt_service()

        print(f"[{call_sid}] Sending URL to Deepgram: {recording_url}")

        stt_start = time.time()
        try:
            stt_timeout_s = max(2.0, min(6.0, endpoint_deadline - time.monotonic() - 6.0))
            text = await asyncio.wait_for(stt.transcribe(recording_url), timeout=stt_timeout_s)
            stt_duration_ms = (time.time() - stt_start) * 1000
            print(f"[{call_sid}] RAW DEEPGRAM TEXT: '{text}'")
            metrics.record_stt_attempt(call_sid, success=True, text=text)
            metrics.record_latency("stt_transcribe", stt_duration_ms)
            cloud_logger.log_stt_metric(call_sid, success=True, text=text, duration_ms=stt_duration_ms)
        except asyncio.TimeoutError:
            stt_duration_ms = (time.time() - stt_start) * 1000
            print(f"[{call_sid}] STT timeout at {stt_duration_ms:.0f}ms. Returning fast retry prompt.")
            metrics.record_error(call_sid, "STT_TIMEOUT", f"Timed out after {stt_duration_ms:.0f}ms")
            metrics.record_stt_attempt(call_sid, success=False)
            metrics.record_latency("stt_transcribe", stt_duration_ms)
            cloud_logger.log_error_event(call_sid, "STT_TIMEOUT", "Deepgram transcription timed out", {"duration_ms": stt_duration_ms})
            return _build_record_response("I had trouble hearing that in time. Please repeat after the beep.")
        except Exception as e:
            stt_duration_ms = (time.time() - stt_start) * 1000
            print(f"[{call_sid}] DEEPGRAM CRASHED: {str(e)}")
            metrics.record_error(call_sid, "STT_EXCEPTION", str(e))
            metrics.record_stt_attempt(call_sid, success=False)
            metrics.record_latency("stt_transcribe", stt_duration_ms)
            cloud_logger.log_error_event(call_sid, "STT_EXCEPTION", str(e), {"duration_ms": stt_duration_ms})
            text = ""
    
    print(f"[{call_sid}] User said: {text}")
    
    if not text or not text.strip():
        print("User was silent. Asking them to repeat.")
        return Response(
            content="<Response><Say>I didn't catch that. Could you please repeat?</Say><Record maxLength='10' timeout='3' action='/transcribe' playBeep='false'/></Response>", 
            media_type="application/xml"
        )
    
    # Get conversation history for this call
    call_memory = session["memory"]
    active_branch: Optional[str] = session.get("branch")
    profile_service = ProfileService()
    profile_data = profile_service.get_profile(caller_number) or {}
    
    print(f"[{call_sid}] Processing: '{text}' (Transcription confidence may vary)")
    
    service = get_llm_service()
    llm_start = time.time()
    llm_timeout_s = max(2.0, endpoint_deadline - time.monotonic() - 1.0)
    try:
        ai_response_obj = await asyncio.wait_for(
            service.analyze_call(
                text,
                call_memory=call_memory,
                caller_country=caller_country,
                caller_state=caller_state,
                user_profile=profile_data,
                branch=active_branch
            ),
            timeout=llm_timeout_s
        )
    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - endpoint_start) * 1000
        print(f"[{call_sid}] LLM timeout after {elapsed_ms:.0f}ms. Returning fast retry prompt before Twilio limit.")
        metrics.record_error(call_sid, "LLM_TIMEOUT", f"Timed out after {elapsed_ms:.0f}ms")
        cloud_logger.log_error_event(call_sid, "LLM_TIMEOUT", "LLM analysis timed out", {"elapsed_ms": elapsed_ms})
        return _build_record_response("Thanks. One moment please. Could you repeat that after the beep?")

    llm_duration_ms = (time.time() - llm_start) * 1000
    metrics.record_latency("llm_analyze", llm_duration_ms)
    
    # Track intent classification and entity extraction
    metrics.record_turn(
        call_sid, 
        text, 
        ai_response_obj.intent, 
        ai_response_obj.confidence,
        ai_response_obj.entities
    )
    
    # Log to cloud
    cloud_logger.log_turn_event(call_sid, len(call_memory) + 1, {
        "user_text": text,
        "intent": ai_response_obj.intent,
        "confidence": ai_response_obj.confidence,
        "entities": ai_response_obj.entities,
        "llm_latency_ms": llm_duration_ms
    })
    
    # GUARDRAIL: Do NOT save profile data if the LLM returned an ERROR intent
    # This prevents corrupting good profile data when the system has a technical issue
    updated_data = profile_data.copy() if profile_data else {}
    
    if ai_response_obj.intent != "ERROR":
        try:
            # Prepare shared metadata (intent-agnostic)
            shared_metadata = {
                "last_intent": ai_response_obj.intent,
                "last_interaction": datetime.datetime.now().isoformat()
            }
            
            # Filter entities: only save non-empty string values
            filtered_entities = {}
            if ai_response_obj.entities:
                for key, value in ai_response_obj.entities.items():
                    if value is not None and isinstance(value, str) and value.strip():
                        filtered_entities[key] = value.strip()
                    elif value is None:
                        print(f"[{call_sid}] Skipping null entity: {key}")
            
            # Save intent-scoped entities + shared metadata
            profile_service.update_profile_for_intent(
                caller_number, 
                ai_response_obj.intent, 
                filtered_entities,
                shared_metadata
            )
            
            # For logging, show the updated profile merged view
            updated_data = profile_data.copy() if profile_data else {}
            updated_data.update(shared_metadata)
            updated_data.update(filtered_entities)
            
            # Track profile completion
            profile_completion = metrics.check_profile_completion(ai_response_obj.intent, updated_data)
            cloud_logger.log_profile_completion(caller_number, ai_response_obj.intent, profile_completion)
            
            print(f"[{call_sid}] Profile updated for intent '{ai_response_obj.intent}'. New entities: {filtered_entities}")
            print(f"[{call_sid}] Profile completion: {profile_completion['completion_pct']}% ({profile_completion['filled']}/{profile_completion['required']} fields)")
            print(f"[{call_sid}] Full merged profile view: {updated_data}")
        except Exception as e:
            print(f"Error updating profile: {e}")
            metrics.record_error(call_sid, "PROFILE_UPDATE_ERROR", str(e))
            cloud_logger.log_error_event(call_sid, "PROFILE_UPDATE_ERROR", str(e))
    else:
        print(f"[{call_sid}] GUARDRAIL: Skipping profile update due to ERROR intent")
        metrics.record_error(call_sid, "LLM_ERROR_INTENT", "LLM returned ERROR intent")
        cloud_logger.log_error_event(call_sid, "LLM_ERROR_INTENT", "LLM returned ERROR intent")
    
    ai_text = ai_response_obj.reply_text
    action = ai_response_obj.action
    
    # Record metrics: action and completion
    metrics.record_action(call_sid, action)
    resolved_branch = ai_response_obj.branch or active_branch or ai_response_obj.intent
    session["branch"] = resolved_branch

    call_memory.append({
        "user": text,
        "ai": ai_text,
        "intent": ai_response_obj.intent,
        "branch": resolved_branch,
        "entities": ai_response_obj.entities
    })
    session_profile = _merge_session_profile_entities(session, profile_data, ai_response_obj.entities, updated_data)
    
    elapsed_ms = (time.monotonic() - endpoint_start) * 1000
    print(f"[{call_sid}] AI response: {ai_text}")
    print(f"[{call_sid}] Action decision: {action}, Intent: {ai_response_obj.intent}, /transcribe elapsed: {elapsed_ms:.0f}ms")
    print(f"[{call_sid}] Conversation history length: {len(call_memory)}")
    
    VOICE_MAP = {
        "[EN]": {"voice": "Polly.Joanna-Neural", "language": "en-US"},
        "[ES]": {"voice": "Polly.Mia", "language": "es-MX"},
        "[HI]": {"voice": "Polly.Aditi", "language": "hi-IN"},
    }
    
    selected_voice = "Polly.Joanna-Neural"
    selected_language = "en-US"
    clean_text = ai_text
    
    for tag, settings in VOICE_MAP.items():
        if tag in ai_text:
            selected_voice = settings["voice"]
            selected_language = settings["language"]
            clean_text = ai_text.replace(tag, "").strip()
            break

    spoken_clean_text = clean_text
    
    # Check if we should forward the call
    if action == "forward" or ai_response_obj.intent == "ERROR":
        print(f"[{call_sid}] Ready to forward. Intent: {ai_response_obj.intent}")
        
        caller_number = str(form_data.get("From", ""))
        contact_preference = _non_empty_str(ai_response_obj.entities.get("contact_preference") if ai_response_obj.entities else None)
        if not contact_preference:
            contact_preference = _non_empty_str(session_profile.get("contact_preference"))
        if not contact_preference:
            contact_preference = _get_profile_value(profile_data, "contact_preference")
        contact_preference = (contact_preference or "whatsapp").lower()

        email_address = _non_empty_str(ai_response_obj.entities.get("email_address") if ai_response_obj.entities else None)
        if not email_address:
            email_address = _non_empty_str(session_profile.get("email_address"))
        if not email_address:
            email_address = _get_profile_value(profile_data, "email_address")
        
        # WhatsApp Logic for JOB_SEEKER - send resume upload link
        if ai_response_obj.intent == "JOB_SEEKER":
            if contact_preference == "email":
                confirm_url = (
                    f"/confirm-email?call_sid={quote_plus(call_sid)}"
                    f"&caller_number={quote_plus(caller_number)}"
                )
                xml_response = f"""
                    <Response>
                        <Redirect method="POST">{confirm_url}</Redirect>
                    </Response>
                    """
                return Response(content=xml_response, media_type="application/xml")

            try:
                _send_whatsapp_followup(caller_number)
                print(f"[{call_sid}] Success: WhatsApp message sent to {caller_number}")
            except Exception as e:
                print(f"[{call_sid}] Error sending WhatsApp message: {e}")
                _log_failed_notification(
                    caller_number=caller_number,
                    call_sid=call_sid,
                    preferred_method="whatsapp",
                    reason=str(e),
                )

        return await _build_forward_response(
            call_sid=call_sid,
            intent=ai_response_obj.intent,
            spoken_text=spoken_clean_text,
            selected_voice=selected_voice,
            profile_data=session_profile,
        )
    
    # Continue conversation
    xml_response = f"""
        <Response>
            <Say voice="Polly.Joanna-Neural">{xml_escape(spoken_clean_text)}</Say>
            <Pause length="2"/>
            <Record maxLength="30" timeout="2" trim="trim-silence" action="/transcribe" playBeep="true"/>
        </Response>
        """
    
    return Response(content=xml_response, media_type="application/xml")


@app.api_route("/confirm-email", methods=["GET", "POST"])
async def confirm_email(request: Request):
    call_sid = str(request.query_params.get("call_sid", "unknown"))
    caller_number = str(request.query_params.get("caller_number", "unknown"))

    session = call_sessions.get(call_sid, {})
    session_entities = session.get("profile_entities", {}) if isinstance(session, dict) else {}
    email_address = _non_empty_str(session_entities.get("email_address") if isinstance(session_entities, dict) else None)

    if not email_address and caller_number and caller_number != "unknown":
        profile = ProfileService().get_profile(caller_number) or {}
        email_address = _get_profile_value(profile, "email_address")
        if email_address and isinstance(session, dict):
            _merge_session_profile_entities(session, {"email_address": email_address})

    if not email_address:
        confirm_url = (
            f"/confirm-email?call_sid={quote_plus(call_sid)}"
            f"&caller_number={quote_plus(caller_number)}"
        )
        xml_response = """
            <Response>
                <Gather input="speech" action="/transcribe" timeout="7">
                    <Say voice="Polly.Joanna-Neural">Please say your email address slowly and clearly.</Say>
                </Gather>
                <Redirect method="POST">{confirm_url}</Redirect>
            </Response>
            """
        xml_response = xml_response.replace("{confirm_url}", confirm_url)
        return Response(content=xml_response, media_type="application/xml")

    action_url = (
        f"/email-confirmed?call_sid={quote_plus(call_sid)}"
        f"&caller_number={quote_plus(caller_number)}"
    )
    safe_email = xml_escape(email_address)
    xml_response = f"""
        <Response>
            <Gather input="dtmf" numDigits="1" action="{action_url}" timeout="7">
                <Say voice="Polly.Joanna-Neural">I have your email as {safe_email}. Press 1 to confirm or Press 2 to re-enter.</Say>
            </Gather>
            <Redirect method="POST">{action_url}</Redirect>
        </Response>
        """
    return Response(content=xml_response, media_type="application/xml")


@app.api_route("/email-confirmed", methods=["GET", "POST"])
async def email_confirmed(request: Request):
    form_data = await request.form()
    digit = str(form_data.get("Digits", "")).strip()
    call_sid = str(request.query_params.get("call_sid", "unknown"))
    caller_number = str(request.query_params.get("caller_number", "unknown"))

    session = call_sessions.get(call_sid, {})
    session_entities = session.get("profile_entities", {}) if isinstance(session, dict) else {}
    email_address = _non_empty_str(session_entities.get("email_address") if isinstance(session_entities, dict) else None)
    if not email_address and caller_number and caller_number != "unknown":
        profile = ProfileService().get_profile(caller_number) or {}
        email_address = _get_profile_value(profile, "email_address")

    if digit == "1":
        if email_address:
            try:
                _send_email_followup(email_address)
                print(f"[{call_sid}] Email follow-up sent to {email_address}")
            except Exception as email_error:
                print(f"[{call_sid}] Error sending email follow-up: {email_error}")
                _log_failed_notification(
                    caller_number=caller_number,
                    call_sid=call_sid,
                    preferred_method="email",
                    email_address=email_address,
                    reason=str(email_error),
                )

        forward_intent = session.get("branch") if isinstance(session, dict) else None
        return await _build_forward_response(
            call_sid=call_sid,
            intent=forward_intent or "JOB_SEEKER",
            spoken_text="Thanks. I am connecting you with our recruiter now.",
            selected_voice="Polly.Joanna-Neural",
            profile_data=session_entities if isinstance(session_entities, dict) else None,
        )

    if digit == "2":
        confirm_url = (
            f"/confirm-email?call_sid={quote_plus(call_sid)}"
            f"&caller_number={quote_plus(caller_number)}"
        )
        xml_response = """
            <Response>
                <Gather input="dtmf speech" action="/transcribe" timeout="7">
                    <Say voice="Polly.Joanna-Neural">Please say your email address again slowly.</Say>
                </Gather>
                <Redirect method="POST">{confirm_url}</Redirect>
            </Response>
            """
        xml_response = xml_response.replace("{confirm_url}", confirm_url)
        return Response(content=xml_response, media_type="application/xml")

    action_url = (
        f"/email-confirmed?call_sid={quote_plus(call_sid)}"
        f"&caller_number={quote_plus(caller_number)}"
    )
    safe_email = xml_escape(email_address or "the email you shared")
    xml_response = f"""
        <Response>
            <Gather input="dtmf" numDigits="1" action="{action_url}" timeout="7">
                <Say voice="Polly.Joanna-Neural">I have your email as {safe_email}. Press 1 to confirm or Press 2 to re-enter.</Say>
            </Gather>
            <Redirect method="POST">{action_url}</Redirect>
        </Response>
        """
    return Response(content=xml_response, media_type="application/xml")


@app.post("/call-status")
async def call_status_webhook(request: Request):
    """
    Twilio calls this endpoint when call status changes (completed, failed, etc.)
    We use it to clean up conversation memory.
    """
    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "unknown"))
    call_status = str(form_data.get("CallStatus", "unknown"))
    
    print(f"[{call_sid}] Call status: {call_status}")
    
    # Clean up session when call ends
    if call_status in ["completed", "failed", "busy", "no-answer"]:
        if call_sid in call_sessions:
            conversation_length = len(call_sessions[call_sid].get("memory", []))
            print(f"[{call_sid}] Cleaning up session. Had {conversation_length} exchanges.")
            del call_sessions[call_sid]
    
    return Response(content="<Response></Response>", media_type="application/xml")

@app.get("/upload", response_class=HTMLResponse)
async def get_upload_page():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "upload.html")
    try:
        with open(file_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="Upload page not found.", status_code=404)

@app.post("/upload-resume")
async def upload_file(file: UploadFile = File(...)):
    """
    Endpoint to receive file uploads (e.g. resumes) from the user.
    We will save the file to Google Drive and return the link.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    try:
        content = await file.read()
        drive_service = get_drive_service()
        file_link = await drive_service.upload_file(file.filename, content, file.content_type)
        return {"file_link": file_link}
    except Exception as e:
        print(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")

@app.get("/metrics")
async def get_metrics():
    """
    Endpoint to retrieve system metrics dashboard.
    Includes call funnel, intent distribution, STT success, errors, user behavior, and latencies.
    """
    metrics = get_metrics_service()
    return metrics.get_aggregated_metrics()

@app.get("/metrics/summary")
async def get_metrics_summary():
    """
    Endpoint to log and return a human-readable summary of metrics.
    Also publishes to Cloud Logging for persistence.
    """
    metrics = get_metrics_service()
    cloud_logger = get_cloud_logging_service()
    
    # Get metrics and log to cloud
    aggregated = metrics.get_aggregated_metrics()
    cloud_logger.log_aggregated_metrics(aggregated)
    
    # Log to console
    metrics.log_metrics_summary()
    
    return {"status": "Metrics logged to console and Cloud Logging", "summary": aggregated}

@app.get("/metrics/call/{call_sid}")
async def get_call_metrics(call_sid: str):
    """
    Get metrics for a specific call.
    """
    metrics = get_metrics_service()
    call_summary = metrics.get_call_summary(call_sid)
    if not call_summary:
        raise HTTPException(status_code=404, detail=f"Call {call_sid} not found")
    return call_summary
